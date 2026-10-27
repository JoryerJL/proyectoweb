"""EC2 bootstrap script (cloud-init user data). Idempotent and logged."""

from string import Template

COMPOSE_VERSION = "v2.40.3"

_SCRIPT = Template(r"""#!/bin/bash
# Canaco bootstrap. Runs once at first boot as root; safe to re-run by hand.
set -euo pipefail
export HOME=/root
exec > >(tee -a /var/log/canaco-bootstrap.log) 2>&1
echo "=== canaco bootstrap started $$(date -u +%FT%TZ) ==="

APP_DIR=/opt/canaco
DOMAIN='${domain}'
REPO_URL='${repo_url}'
COMPOSE_VERSION='${compose_version}'

# 1. Swap (t3.micro has 1 GiB RAM) -------------------------------------------
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
fi
swapon --show | grep -q /swapfile || swapon /swapfile
grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab

# 2. Docker, git and the compose v2 plugin -----------------------------------
dnf install -y docker git
systemctl enable --now docker

PLUGIN_DIR=/usr/local/lib/docker/cli-plugins
if ! docker compose version >/dev/null 2>&1; then
  mkdir -p "$$PLUGIN_DIR"
  BASE="https://github.com/docker/compose/releases/download/$${COMPOSE_VERSION}"
  curl -fsSL "$$BASE/docker-compose-linux-x86_64" -o "$$PLUGIN_DIR/docker-compose"
  curl -fsSL "$$BASE/docker-compose-linux-x86_64.sha256" -o /tmp/compose.sha256
  (cd "$$PLUGIN_DIR" && echo "$$(cut -d' ' -f1 /tmp/compose.sha256)  docker-compose" | sha256sum -c -)
  chmod +x "$$PLUGIN_DIR/docker-compose"
fi
docker compose version

# 3. Application code --------------------------------------------------------
if [ -d "$$APP_DIR/.git" ]; then
  git -C "$$APP_DIR" pull --ff-only
else
  git clone "$$REPO_URL" "$$APP_DIR"
fi
cd "$$APP_DIR"

# 4. .env (only if absent: secrets are generated once and never overwritten) --
set_kv() {
  if grep -q "^$$1=" .env; then
    sed -i "s|^$$1=.*|$$1=$$2|" .env
  else
    echo "$$1=$$2" >> .env
  fi
}
if [ ! -f .env ]; then
  umask 077
  cp deploy/env.example .env
  set_kv DJANGO_SECRET_KEY "$$(openssl rand -base64 48 | tr -d '\n/+=')"
  set_kv DB_PASSWORD "$$(openssl rand -hex 24)"
  set_kv DJANGO_DEBUG false
  set_kv DJANGO_ALLOWED_HOSTS "$$DOMAIN"
  set_kv DJANGO_CSRF_TRUSTED_ORIGINS "https://$$DOMAIN"
  set_kv DJANGO_USE_PROXY_SSL_HEADER true
  set_kv DJANGO_SECURE_SSL_REDIRECT true
  set_kv DJANGO_SESSION_COOKIE_SECURE true
  set_kv DJANGO_CSRF_COOKIE_SECURE true
  chmod 600 .env
  echo ".env generated."
else
  echo ".env already exists, left untouched."
fi

# 5. Start the stack ---------------------------------------------------------
# Never build on the instance (1 GiB RAM, no buildx): pull or give up cleanly.
if docker compose -f docker-compose.prod.yml pull; then
  docker compose -f docker-compose.prod.yml up -d --no-build
else
  echo "WARNING: could not pull the images. Is the GHCR package published and public?"
  echo "Fix it, then run: cd $$APP_DIR && docker compose -f docker-compose.prod.yml up -d --no-build"
fi
echo "=== canaco bootstrap finished $$(date -u +%FT%TZ) ==="
""")


def render_user_data(domain: str, repo_url: str) -> str:
    return _SCRIPT.substitute(
        domain=domain, repo_url=repo_url, compose_version=COMPOSE_VERSION
    )
