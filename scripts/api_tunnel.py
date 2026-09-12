"""Loopback-only CONNECT relay and reconnecting SSH reverse tunnel.

TLS stays end-to-end between the server SDK and www.dmxapi.cn. No API
credentials or HTTP bodies are read, stored or logged by this process.
"""
import argparse
import logging
import os
from pathlib import Path
import select
import signal
import socket
import socketserver
import subprocess
import threading

DESTINATION = ('www.dmxapi.cn', 443)


def read_connect(sock):
    data = bytearray()
    # Do not buffer bytes beyond the CONNECT header (TLS follows the 200).
    while not data.endswith(b'\r\n\r\n'):
        chunk = sock.recv(1)
        if not chunk or len(data) >= 8192:
            raise ValueError('invalid header')
        data.extend(chunk)
    first = bytes(data).split(b'\r\n', 1)[0]
    if first not in (b'CONNECT www.dmxapi.cn:443 HTTP/1.1',
                     b'CONNECT www.dmxapi.cn:443 HTTP/1.0'):
        raise ValueError('destination or method not allowed')


def transfer(left, right):
    while True:
        readable, _, _ = select.select([left, right], [], [], 180)
        if not readable:
            return
        for source in readable:
            data = source.recv(65536)
            if not data:
                return
            (right if source is left else left).sendall(data)


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        if not self.server.slots.acquire(blocking=False):
            self.request.sendall(b'HTTP/1.1 503 Service Unavailable\r\n\r\n')
            return
        established = False
        try:
            self.request.settimeout(10)
            try:
                read_connect(self.request)
            except ValueError:
                self.request.sendall(b'HTTP/1.1 403 Forbidden\r\n\r\n')
                return
            with socket.create_connection(DESTINATION, timeout=8) as upstream:
                self.request.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                established = True
                self.request.settimeout(30)
                upstream.settimeout(30)
                transfer(self.request, upstream)
        except (OSError, ValueError) as exc:
            logging.warning('relay connection failed: %s', type(exc).__name__)
            if not established:
                try:
                    self.request.sendall(b'HTTP/1.1 502 Bad Gateway\r\n\r\n')
                except OSError:
                    pass
        finally:
            self.server.slots.release()


class Relay(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 128

    def __init__(self, port, max_connections=64):
        if not isinstance(max_connections, int) or not 1 <= max_connections <= 256:
            raise ValueError('max_connections must be between 1 and 256')
        self.max_connections = max_connections
        # CONNECT slots count open TCP connections, including SDK keepalives;
        # they are separate from the compute service's active API request slots.
        self.slots = threading.BoundedSemaphore(max_connections)
        super().__init__(('127.0.0.1', port), Handler)


def connection_limit(value):
    try:
        result = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError('must be an integer between 1 and 256') from None
    if not 1 <= result <= 256:
        raise argparse.ArgumentTypeError('must be between 1 and 256')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', required=True)
    p.add_argument('--identity', type=Path, required=True)
    p.add_argument('--known-hosts', type=Path, required=True)
    p.add_argument('--pid-file', type=Path, required=True)
    p.add_argument('--local-port', type=int, default=18081)
    p.add_argument('--remote-port', type=int, default=18080)
    p.add_argument('--max-connections', type=connection_limit, default=64,
                   help='Maximum open CONNECT TCP connections, including idle keepalives (1–256; default: 64)')
    args = p.parse_args()
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    command = ['ssh', '-N', '-T', '-i', str(args.identity),
        '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'UserKnownHostsFile=' + str(args.known_hosts),
        '-o', 'ConnectTimeout=8', '-o', 'ExitOnForwardFailure=yes',
        '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
        '-R', f'127.0.0.1:{args.remote_port}:127.0.0.1:{args.local_port}', args.host]
    child = None
    with Relay(args.local_port, max_connections=args.max_connections) as server:
        args.pid_file.write_text(str(os.getpid()) + '\n')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logging.info('relay listening on loopback:%d; destination restricted to %s; connection limit=%d',
                     args.local_port, DESTINATION[0], args.max_connections)
        try:
            while not stop.is_set():
                logging.info('starting SSH reverse tunnel on remote loopback:%d', args.remote_port)
                child = subprocess.Popen(command)
                while child.poll() is None and not stop.wait(1):
                    pass
                if not stop.is_set():
                    logging.warning('SSH exited (%s); retrying in 5 seconds', child.returncode)
                    stop.wait(5)
        finally:
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            server.shutdown()
            args.pid_file.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
