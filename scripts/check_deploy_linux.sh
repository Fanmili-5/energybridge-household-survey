#!/usr/bin/env bash
# Run with sudo: Nginx validates production ports and reads root-owned defaults.
# Validate templates using native Linux tools without installing a service.
set -euo pipefail
project_root=$(cd "$(dirname "$0")/.." && pwd)
check_dir=$(mktemp -d)
trap 'rm -rf "$check_dir"' EXIT
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=survey.example.org \
  -keyout "$check_dir/privkey.pem" -out "$check_dir/fullchain.pem" >/dev/null 2>&1
sed "s|/etc/letsencrypt/live/survey.example.org|$check_dir|g" "$project_root/deploy/nginx.conf.example" > "$check_dir/site.conf"
cat > "$check_dir/nginx.conf" <<CONF
pid $check_dir/nginx.pid;
error_log $check_dir/error.log;
events {}
http {
    access_log off;
    client_body_temp_path $check_dir/body;
    proxy_temp_path $check_dir/proxy;
    fastcgi_temp_path $check_dir/fastcgi;
    uwsgi_temp_path $check_dir/uwsgi;
    scgi_temp_path $check_dir/scgi;
    include $check_dir/site.conf;
}
CONF
nginx -t -c "$check_dir/nginx.conf" -p "$check_dir"
systemd-analyze verify "$project_root/deploy/energybridge.service"
bash -n "$project_root/deploy/start.sh"
