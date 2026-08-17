#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
set -a
. ./.env
set +a

if [ "$DOMAIN" = "license.example.com" ] || [ -z "$DOMAIN" ]; then
  echo "Set DOMAIN in .env before enabling HTTPS." >&2
  exit 1
fi

docker compose run --rm --entrypoint certbot certbot certonly \
  --webroot -w /var/www/certbot \
  --email "$TLS_EMAIL" --agree-tos --no-eff-email \
  -d "$DOMAIN"

docker compose -f docker-compose.yml -f docker-compose.https.yml up -d nginx
echo "HTTPS enabled: https://$DOMAIN/api/health"
