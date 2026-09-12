import argparse
import socket
import threading
import unittest
from unittest.mock import patch
from api_tunnel import Relay, connection_limit


class TunnelTest(unittest.TestCase):
    def setUp(self):
        self.server = Relay(0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def connect(self):
        # Use a real local socket even while the upstream connector is mocked.
        client = socket.socket()
        client.settimeout(2)
        client.connect(self.server.server_address)
        return client

    def configure_capacity(self, limit):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.server = Relay(0, max_connections=limit)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def test_capacity_configuration_bounds(self):
        self.assertEqual(self.server.max_connections, 64)
        self.assertEqual(self.server.request_queue_size, 128)
        self.assertEqual(self.server.server_address[0], '127.0.0.1')
        for value in ('1', '64', '256'):
            self.assertEqual(connection_limit(value), int(value))
        for value in ('0', '-1', '257', '1.5', 'invalid'):
            with self.assertRaises(argparse.ArgumentTypeError):
                connection_limit(value)
        for value in (0, -1, 257, '8', None, 1.5):
            with self.assertRaises(ValueError):
                Relay(0, max_connections=value)

    def test_sixteen_default_connections_remain_open_and_transfer(self):
        clients, peers = [], []

        def upstream_connection(*args, **kwargs):
            upstream, peer = socket.socketpair()
            peer.settimeout(2)
            peers.append(peer)
            return upstream

        try:
            with patch('api_tunnel.socket.create_connection', side_effect=upstream_connection) as connect:
                for _ in range(16):
                    client = self.connect()
                    clients.append(client)
                    client.sendall(b'CONNECT www.dmxapi.cn:443 HTTP/1.1\r\n\r\n')
                    self.assertIn(b'200 Connection Established', client.recv(1024))
                self.assertEqual(connect.call_count, 16)
                # Check after all handshakes: earlier keepalive connections must
                # still work, rather than being evicted to admit new ones.
                for i, (client, peer) in enumerate(zip(clients, peers)):
                    message = b'\x16\x03\x01opaque-' + bytes([i])
                    client.sendall(message)
                    self.assertEqual(peer.recv(1024), message)
                    peer.sendall(message[::-1])
                    self.assertEqual(client.recv(1024), message[::-1])
        finally:
            for client in clients:
                client.close()
            for peer in peers:
                peer.close()

    def test_exhausted_capacity_returns_503_and_close_releases_slots(self):
        self.configure_capacity(2)
        clients, peers = [], []

        def upstream_connection(*args, **kwargs):
            upstream, peer = socket.socketpair()
            peer.settimeout(2)
            peers.append(peer)
            return upstream

        def establish():
            client = self.connect()
            clients.append(client)
            client.sendall(b'CONNECT www.dmxapi.cn:443 HTTP/1.1\r\n\r\n')
            self.assertIn(b'200 Connection Established', client.recv(1024))
            return client

        try:
            with patch('api_tunnel.socket.create_connection', side_effect=upstream_connection) as connect:
                first, second = establish(), establish()
                with self.connect() as rejected:
                    self.assertIn(b'503 Service Unavailable', rejected.recv(1024))
                self.assertEqual(connect.call_count, 2)
                first.close()
                self.assertTrue(self.server.slots.acquire(timeout=2), 'closed connection did not release its slot')
                self.server.slots.release()
                third = establish()
                self.assertEqual(connect.call_count, 3)
                third.sendall(b'reused-slot')
                self.assertEqual(peers[2].recv(1024), b'reused-slot')
                second.close()
                third.close()
                # Both remaining connections must release exactly one slot.
                self.assertTrue(self.server.slots.acquire(timeout=2))
                self.assertTrue(self.server.slots.acquire(timeout=2))
                self.assertFalse(self.server.slots.acquire(blocking=False))
                self.server.slots.release()
                self.server.slots.release()
        finally:
            for client in clients:
                client.close()
            for peer in peers:
                peer.close()

    def test_forbids_other_hosts_and_plain_http(self):
        for request in [b'CONNECT example.com:443 HTTP/1.1\r\n\r\n',
                        b'GET http://www.dmxapi.cn/ HTTP/1.1\r\n\r\n',
                        b'CONNECT www.dmxapi.cn:80 HTTP/1.1\r\n\r\n']:
            with self.connect() as client:
                client.sendall(request)
                self.assertIn(b'403 Forbidden', client.recv(1024))

    def test_connect_transfers_bytes_both_directions_without_inspection(self):
        upstream, peer = socket.socketpair()
        peer.settimeout(2)
        client = self.connect()
        try:
            with patch('api_tunnel.socket.create_connection', return_value=upstream) as connect:
                client.sendall(b'CONNECT www.dmxapi.cn:443 HTTP/1.1\r\nHost: www.dmxapi.cn:443\r\n\r\n')
                self.assertIn(b'200 Connection Established', client.recv(1024))
                connect.assert_called_once_with(('www.dmxapi.cn', 443), timeout=8)
                client.sendall(b'\x16\x03\x01opaque-client-bytes')
                self.assertEqual(peer.recv(100), b'\x16\x03\x01opaque-client-bytes')
                peer.sendall(b'opaque-server-bytes')
                self.assertEqual(client.recv(100), b'opaque-server-bytes')
        finally:
            client.close()
            peer.close()

    def test_upstream_failure_returns_502(self):
        client = self.connect()
        try:
            with patch('api_tunnel.socket.create_connection', side_effect=TimeoutError):
                client.sendall(b'CONNECT www.dmxapi.cn:443 HTTP/1.1\r\n\r\n')
                self.assertIn(b'502 Bad Gateway', client.recv(1024))
        finally:
            client.close()


if __name__ == '__main__':
    unittest.main()
