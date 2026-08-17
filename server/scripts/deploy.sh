#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  cp .env.example .env
  jwt_secret=$(openssl rand -hex 32)
  card_pepper=$(openssl rand -hex 32)
  db_password=$(openssl rand -hex 24)
  db_root_password=$(openssl rand -hex 24)
  admin_password=$(openssl rand -base64 18 | tr -d '/+=')
  sed -i "s/replace-with-at-least-32-random-characters/$jwt_secret/" .env
  sed -i "s/replace-with-another-32-character-random-secret/$card_pepper/" .env
  sed -i "s/replace-with-a-long-random-password/$db_password/" .env
  sed -i "s/replace-with-another-long-random-password/$db_root_password/" .env
  sed -i "s/replace-with-at-least-12-characters/$admin_password/" .env
  chmod 600 .env
  echo "Created .env. Set DOMAIN before production use."
  echo "Initial admin password: $admin_password"
fi

docker compose config >/dev/null
docker compose up -d --build
docker compose ps
