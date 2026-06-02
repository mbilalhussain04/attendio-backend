# Attendio VPS Deployment

This guide keeps three modes working:

- Local Python services: `make local`
- Local Docker: `docker compose up --build`
- Production VPS: Docker Compose behind host Nginx + Let's Encrypt

## Target domains

Use one public frontend and one public API gateway:

- Frontend: `https://attendio.technoflick.com`
- Backend gateway: `https://api.attendio.technoflick.com`

The service-specific subdomains from the hosting panel are not needed in production. Keep traffic through the single API gateway so cookies, CORS, OAuth callbacks, and routing stay predictable.

## DNS

Create these `A` records and point them to the VPS public IP:

```text
attendio.technoflick.com      A  178.105.220.187
api.attendio.technoflick.com  A  178.105.220.187
```

Optional later:

```text
www.attendio.technoflick.com  CNAME  attendio.technoflick.com
```

## VPS bootstrap

Run once on Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y ca-certificates curl git nginx certbot python3-certbot-nginx ufw
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
sudo ufw allow OpenSSH
sudo ufw allow 80
sudo ufw allow 443
sudo ufw --force enable
```

Log out and back in so the Docker group applies.

## Clone repos

```bash
sudo mkdir -p /opt/attendio
sudo chown -R $USER:$USER /opt/attendio
cd /opt/attendio
git clone git@github.com:mbilalhussain04/attendio-backend.git backend
git clone git@github.com:mbilalhussain04/attendio-frontend.git frontend
```

## Backend env

```bash
cd /opt/attendio/backend
python3 scripts/create-production-env.py --force
nano .env
```

The generator creates strong values for Postgres, RabbitMQ, MinIO, app signing, JWT, and internal service tokens. After that, fill only the external provider values you actually use: Google, Microsoft, SMTP, Stripe/Payoneer.

Never commit `.env`. Production secrets should live only on the VPS and in GitHub Actions secrets.

Important production values:

```text
APP_ENV=production
DEBUG=false
GATEWAY_BIND=127.0.0.1
GATEWAY_PORT=8080
INFRA_BIND=127.0.0.1
COOKIE_SECURE=true
COOKIE_DOMAIN=.attendio.technoflick.com
DEFAULT_ROOT_DOMAIN=attendio.technoflick.com
AUTH_BASE_DOMAIN=api.attendio.technoflick.com
BASE_DOMAIN=attendio.technoflick.com
FRONTEND_BASE_URL=https://attendio.technoflick.com
OAUTH_REDIRECT_URI=https://api.attendio.technoflick.com/api/v1/auth/sso/callback
CORS_ORIGINS=https://attendio.technoflick.com,https://api.attendio.technoflick.com
PUBLIC_STORAGE_BASE_URL=https://api.attendio.technoflick.com/api/v1/storage/files
```

If you already generated values manually with `openssl rand -hex 32`, map them like this inside VPS `.env`:

```text
POSTGRES_PASSWORD=<first generated value>
SECRET_KEY=<second generated value>
JWT_ACCESS_SECRET=<third generated value>
INTERNAL_SERVICE_TOKEN=<fourth generated value>
RABBITMQ_DEFAULT_PASS=<fifth generated value>
MINIO_SECRET_KEY=<sixth generated value>
```

Then make sure every database URL uses the same `POSTGRES_PASSWORD`, and `RABBITMQ_URL` uses the same `RABBITMQ_DEFAULT_PASS`.

## Start backend containers

The backend gateway is bound to `127.0.0.1:8080` by `.env.production.example`, so only host Nginx can reach it. Postgres, Redis, RabbitMQ, and MinIO are also bound to localhost.

```bash
cd /opt/attendio/backend
docker compose up --build -d
docker compose ps
```

Backend containers use `restart: unless-stopped`, so after the first successful `docker compose up -d` they will come back automatically after a VPS reboot or Docker daemon restart.

Install the backend systemd unit so the Docker Compose stack is also started by the host during boot:

```bash
sudo cp /opt/attendio/backend/infra/vps/attendio-backend.service /etc/systemd/system/attendio-backend.service
sudo systemctl daemon-reload
sudo systemctl enable attendio-backend
sudo systemctl start attendio-backend
sudo systemctl status attendio-backend --no-pager
```

If Postgres fails during the very first fresh setup, inspect it with:

```bash
docker compose logs --tail=100 platform-postgres
```

If the failure happened before any real production data exists, reset the broken init volume and start again:

```bash
docker compose down -v
docker compose up --build -d
```

Do not run `down -v` after real users/data exist; use backups and migrations instead.

## Start frontend container

```bash
cd /opt/attendio/frontend
docker build \
  --build-arg VITE_API_BASE_URL=https://api.attendio.technoflick.com/api/v1 \
  --build-arg VITE_ENABLE_AUTH_API_CONSOLE=false \
  -t attendio-frontend:latest .
docker rm -f attendio-frontend 2>/dev/null || true
docker run -d --name attendio-frontend --restart unless-stopped -p 127.0.0.1:5174:80 attendio-frontend:latest
```

## Host Nginx + SSL

First certificate issue needs an HTTP-only config. Do not install the final HTTPS config before certificates exist, because `nginx -t` will fail on missing `/etc/letsencrypt/live/...` files.

Install the pre-cert Nginx config:

```bash
sudo mkdir -p /var/www/certbot
sudo cp /opt/attendio/backend/infra/vps/attendio.pre-cert.nginx.conf /etc/nginx/sites-available/attendio
sudo ln -sf /etc/nginx/sites-available/attendio /etc/nginx/sites-enabled/attendio
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

Issue certificates:

```bash
sudo certbot --nginx -d attendio.technoflick.com -d api.attendio.technoflick.com
```

This creates one SAN certificate under the first domain path:

```text
/etc/letsencrypt/live/attendio.technoflick.com/
```

The final Nginx config intentionally uses that same certificate path for both the frontend and API server blocks.

After certificates exist, install the final HTTPS config:

```bash
sudo cp /opt/attendio/backend/infra/vps/attendio.nginx.conf /etc/nginx/sites-available/attendio
sudo nginx -t
sudo systemctl reload nginx
```

## OAuth provider redirects

Set these in Google/Microsoft dashboards:

```text
https://api.attendio.technoflick.com/api/v1/auth/sso/callback
https://api.attendio.technoflick.com/api/v1/auth/integrations/callback
```

## Deploy after pushing code

Backend:

```bash
cd /opt/attendio/backend
git pull
docker compose up --build -d --remove-orphans
docker compose exec nginx nginx -s reload || docker compose restart nginx
docker compose exec auth-service alembic upgrade head
docker compose exec attendance-service alembic upgrade head
docker compose exec storage-service alembic upgrade head
docker compose exec notification-service alembic upgrade head
docker compose exec leave-service alembic upgrade head
docker compose ps
```

If the backend Nginx config changed, reload the Docker gateway after the deploy:

```bash
docker compose exec nginx nginx -t
docker compose exec nginx nginx -s reload || docker compose restart nginx
```

If the host Nginx config changed, reinstall and reload it too:

```bash
sudo cp /opt/attendio/backend/infra/vps/attendio.nginx.conf /etc/nginx/sites-available/attendio
sudo nginx -t
sudo systemctl reload nginx
```

Frontend:

```bash
cd /opt/attendio/frontend
git pull
docker build \
  --build-arg VITE_API_BASE_URL=https://api.attendio.technoflick.com/api/v1 \
  --build-arg VITE_ENABLE_AUTH_API_CONSOLE=false \
  -t attendio-frontend:latest .
docker rm -f attendio-frontend
docker run -d --name attendio-frontend --restart unless-stopped -p 127.0.0.1:5174:80 attendio-frontend:latest
```

## GitHub auto deploy

Recommended simple path:

1. Create a deploy user on VPS.
2. Add the deploy user's public SSH key as a GitHub deploy key to both repos.
3. Add GitHub Actions repository secrets:
   - `VPS_HOST`
   - `VPS_USER`
   - `VPS_SSH_KEY`
4. In backend repo action: SSH to VPS, `cd /opt/attendio/backend`, update `main`, run `docker compose up --build -d --remove-orphans`, then run migrations.
5. In frontend repo action: SSH to VPS, `cd /opt/attendio/frontend`, `git pull`, rebuild the frontend container.

Use branch protection and deploy only from `main`.

### One-time CI/CD setup

On the VPS:

```bash
sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG docker deploy
sudo chown -R deploy:deploy /opt/attendio
sudo -u deploy ssh-keygen -t ed25519 -C attendio-vps-github-pull -f /home/deploy/.ssh/github_pull -N ""
sudo -u deploy cat /home/deploy/.ssh/github_pull.pub
```

Add that printed public key as a deploy key with read access in both GitHub repos.

Then add an SSH key that GitHub Actions can use to enter the VPS:

```bash
sudo -u deploy ssh-keygen -t ed25519 -C attendio-actions-to-vps -f /home/deploy/.ssh/actions_to_vps -N ""
sudo -u deploy sh -c 'cat /home/deploy/.ssh/actions_to_vps.pub >> /home/deploy/.ssh/authorized_keys'
sudo -u deploy cat /home/deploy/.ssh/actions_to_vps
```

Put the private key printed by the last command into both repos as `VPS_SSH_KEY`, and set:

```text
VPS_HOST=178.105.220.187
VPS_USER=deploy
```

Finally, make the cloned repos use the VPS GitHub pull key:

```bash
sudo -u deploy sh -c 'cat > /home/deploy/.ssh/config <<EOF
Host github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/github_pull
  IdentitiesOnly yes
EOF'
sudo -u deploy ssh -T git@github.com || true
```

Install the limited host Nginx reload helper so GitHub Actions can apply Nginx changes without broad sudo access:

```bash
sudo cp /opt/attendio/backend/infra/vps/reload-host-nginx.sh /usr/local/bin/attendio-reload-host-nginx
sudo chmod 755 /usr/local/bin/attendio-reload-host-nginx
echo 'deploy ALL=(root) NOPASSWD: /usr/local/bin/attendio-reload-host-nginx' | sudo tee /etc/sudoers.d/attendio-deploy-nginx
sudo chmod 440 /etc/sudoers.d/attendio-deploy-nginx
sudo visudo -cf /etc/sudoers.d/attendio-deploy-nginx
```

Install the backend boot service too:

```bash
sudo cp /opt/attendio/backend/infra/vps/attendio-backend.service /etc/systemd/system/attendio-backend.service
sudo systemctl daemon-reload
sudo systemctl enable attendio-backend
sudo systemctl start attendio-backend
```

After this, you do not clone manually again. Push to `main`, and GitHub Actions will SSH into the VPS, pull the latest code, rebuild containers, run migrations, and restart production.

## Smoke checks

```bash
curl -I https://attendio.technoflick.com
curl -fsS https://api.attendio.technoflick.com/nginx-health
curl -fsS https://api.attendio.technoflick.com/api/v1/health
docker compose -f /opt/attendio/backend/docker-compose.yml ps
curl -fsS http://127.0.0.1:8080/nginx-health
docker logs --tail=100 attendio-frontend
```

## SSO Header Troubleshooting

Microsoft and Google callbacks can return large response headers because the backend sets secure auth cookies and redirects in the same response. If the VPS shows `upstream sent too big header while reading response header from upstream`, pull the latest Nginx config and reload both layers:

```bash
cd /opt/attendio/backend
git pull
docker compose exec nginx nginx -t
docker compose exec nginx nginx -s reload || docker compose restart nginx
sudo cp /opt/attendio/backend/infra/vps/attendio.nginx.conf /etc/nginx/sites-available/attendio
sudo nginx -t
sudo systemctl reload nginx
```

## Backups

Minimum production backup:

```bash
docker exec attendio-platform-platform-postgres-1 pg_dumpall -U attendio > /opt/attendio/backups/postgres-$(date +%F).sql
docker run --rm -v attendio-platform_minio_data:/data -v /opt/attendio/backups:/backup alpine tar czf /backup/minio-$(date +%F).tgz /data
```

Automate this with cron before real users arrive.
