#!/bin/sh
# Picks the TLS certificate nginx serves on 443 (runs from /docker-entrypoint.d/).
#
#   1. If /etc/nginx/origin/origin.pem and origin.key exist (mounted from
#      ./deploy/certs), use them: Cloudflare Origin CA cert -> SSL mode "Full (strict)".
#   2. Otherwise generate a self-signed cert -> SSL mode "Full".
set -eu

TLS_DIR=/etc/nginx/tls
ORIGIN_DIR=/etc/nginx/origin
mkdir -p "$TLS_DIR"

if [ -s "$ORIGIN_DIR/origin.pem" ] && [ -s "$ORIGIN_DIR/origin.key" ]; then
  echo "[tls] Using mounted origin certificate."
  ln -sf "$ORIGIN_DIR/origin.pem" "$TLS_DIR/cert.pem"
  ln -sf "$ORIGIN_DIR/origin.key" "$TLS_DIR/cert.key"
  exit 0
fi

echo "[tls] No origin certificate mounted: generating a self-signed one."
# nginx:alpine does not ship the openssl CLI.
command -v openssl >/dev/null 2>&1 || apk add --no-cache openssl >/dev/null
openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
  -subj "/CN=canaco-origin" \
  -keyout "$TLS_DIR/self.key" -out "$TLS_DIR/self.pem" 2>/dev/null
ln -sf "$TLS_DIR/self.pem" "$TLS_DIR/cert.pem"
ln -sf "$TLS_DIR/self.key" "$TLS_DIR/cert.key"
