#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
set -a
. ./.env
set +a
stamp=$(date +%Y%m%d_%H%M%S)
target="backups/$stamp"
mkdir -p "$target"
chmod 700 "$target"

docker compose exec -T db mysqldump --single-transaction --routines --triggers -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" > "$target/database.sql"
docker compose cp api:/app/secrets/license_ed25519.pem "$target/license_ed25519.pem"
cp .env "$target/server.env"
chmod 600 "$target"/*
echo "Backup created: $target"
