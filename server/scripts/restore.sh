#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ] || [ ! -d "$1" ]; then
  echo "Usage: $0 backups/YYYYMMDD_HHMMSS" >&2
  exit 1
fi

backup_dir=$(cd "$1" && pwd)
cd "$(dirname "$0")/.."

test -f "$backup_dir/database.sql"
test -f "$backup_dir/license_ed25519.pem"
test -f "$backup_dir/server.env"

cp "$backup_dir/server.env" .env
set -a
. ./.env
set +a
docker compose up -d db
until docker compose exec -T db mysqladmin ping -h 127.0.0.1 -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" --silent >/dev/null 2>&1; do
  sleep 2
done
docker compose exec -T db mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "DROP DATABASE IF EXISTS \`$MYSQL_DATABASE\`; CREATE DATABASE \`$MYSQL_DATABASE\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; GRANT ALL PRIVILEGES ON \`$MYSQL_DATABASE\`.* TO '$MYSQL_USER'@'%';"
docker compose exec -T db mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" < "$backup_dir/database.sql"
docker compose up -d api
docker compose cp "$backup_dir/license_ed25519.pem" api:/tmp/license_ed25519.pem
docker compose exec -u root -T api install -o appuser -g appuser -m 600 /tmp/license_ed25519.pem /app/secrets/license_ed25519.pem
docker compose restart api
echo "Restore completed. Start the HTTP or HTTPS Nginx configuration, then verify /api/health."
