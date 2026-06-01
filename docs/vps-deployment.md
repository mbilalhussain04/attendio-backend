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
cp .env.production.example .env
nano .env
```

Change every placeholder secret. Do not reuse local secrets.

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

## Start backend containers

The backend gateway is bound to `127.0.0.1:8080` by `.env.production.example`, so only host Nginx can reach it. Postgres, Redis, RabbitMQ, and MinIO are also bound to localhost.

```bash
cd /opt/attendio/backend
docker compose up --build -d
docker compose ps
```

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

Install the Nginx config:

```bash
sudo cp /opt/attendio/backend/infra/vps/attendio.nginx.conf /etc/nginx/sites-available/attendio
sudo ln -sf /etc/nginx/sites-available/attendio /etc/nginx/sites-enabled/attendio
sudo nginx -t
sudo systemctl reload nginx
```

Issue certificates:

```bash
sudo certbot --nginx -d attendio.technoflick.com -d api.attendio.technoflick.com
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
docker compose exec auth-service alembic upgrade head
docker compose exec attendance-service alembic upgrade head
docker compose exec storage-service alembic upgrade head
docker compose exec notification-service alembic upgrade head
docker compose exec leave-service alembic upgrade head
docker compose ps
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

## Smoke checks

```bash
curl -I https://attendio.technoflick.com
curl -fsS https://api.attendio.technoflick.com/nginx-health
curl -fsS https://api.attendio.technoflick.com/api/v1/health
docker compose -f /opt/attendio/backend/docker-compose.yml ps
curl -fsS http://127.0.0.1:8080/nginx-health
docker logs --tail=100 attendio-frontend
```

## Backups

Minimum production backup:

```bash
docker exec attendio-platform-platform-postgres-1 pg_dumpall -U attendio > /opt/attendio/backups/postgres-$(date +%F).sql
docker run --rm -v attendio-platform_minio_data:/data -v /opt/attendio/backups:/backup alpine tar czf /backup/minio-$(date +%F).tgz /data
```

Automate this with cron before real users arrive.
