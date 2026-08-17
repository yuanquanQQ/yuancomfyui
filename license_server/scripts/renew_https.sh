#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
docker compose run --rm --entrypoint certbot certbot renew --webroot -w /var/www/certbot --quiet
docker compose -f docker-compose.yml -f docker-compose.https.yml exec -T nginx nginx -s reload
