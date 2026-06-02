#!/usr/bin/env sh
set -eu

BACKEND_DIR="${ATTENDIO_BACKEND_DIR:-/opt/attendio/backend}"
NGINX_SITE="/etc/nginx/sites-available/attendio"

cp "$BACKEND_DIR/infra/vps/attendio.nginx.conf" "$NGINX_SITE"
nginx -t
systemctl reload nginx
