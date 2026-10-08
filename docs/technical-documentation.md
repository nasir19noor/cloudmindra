# CloudMindra — Technical Documentation

## Company Overview

CloudMindra is a cloud and AI solution company. This document covers the technical architecture and setup for the company profile website.

## Architecture

```
                    Cloudflare (DNS + Proxy)
                           |
                    Contabo VPS (207.180.248.214)
                           |
                       Nginx Reverse Proxy
                      /                  \
        cloudmindra.com              api.cloudmindra.com
        Port 11000                   Port 11001
        Astro (Frontend)             FastAPI (Backend)
                                          |
                                     PostgreSQL

        AWS S3 (cloudmindra.com/backend/.env)
              ↓
        GitHub Actions downloads .env during deploy
```

## Stack

| Component  | Technology | Domain               | Port  |
|------------|------------|----------------------|-------|
| Frontend   | Astro      | cloudmindra.com      | 11000 |
| Backend    | FastAPI    | api.cloudmindra.com  | 11001 |
| Database   | PostgreSQL | localhost             | 5432  |
| Reverse Proxy | Nginx  | —                    | 443   |
| DNS + CDN  | Cloudflare | —                    | —     |
| CI/CD      | GitHub Actions | —                | —     |
| IaC        | Terraform  | —                    | —     |
| Cloud      | AWS (OIDC) | —                    | —     |

## Project Structure

```
cloudmindra/
├── app/
│   ├── frontend/                # Astro frontend
│   │   ├── src/
│   │   │   ├── layouts/
│   │   │   │   └── Layout.astro
│   │   │   ├── pages/
│   │   │   │   ├── index.astro
│   │   │   │   ├── about.astro
│   │   │   │   ├── services.astro
│   │   │   │   └── contact.astro
│   │   │   ├── components/
│   │   │   │   ├── Header.astro
│   │   │   │   ├── Footer.astro
│   │   │   │   ├── Hero.astro
│   │   │   │   ├── Services.astro
│   │   │   │   └── ContactForm.astro
│   │   │   └── styles/
│   │   │       └── global.css
│   │   ├── public/
│   │   │   └── favicon.svg
│   │   ├── astro.config.mjs
│   │   ├── tailwind.config.mjs
│   │   ├── package.json
│   │   └── Dockerfile
│   └── backend/                 # FastAPI backend
│       ├── main.py
│       ├── database.py
│       ├── models.py
│       ├── db_models.py
│       ├── routers/
│       │   ├── contact.py
│       │   ├── services.py
│       │   └── blog.py
│       ├── requirements.txt
│       ├── upload.sh
│       └── Dockerfile
├── cloudflare/                  # Terraform (existing)
│   ├── dns.tf
│   ├── provider.tf
│   ├── backend.tf
│   ├── data.tf
│   ├── locals.tf
│   ├── variables.tf
│   └── outputs.tf
├── .github/
│   └── workflows/
│       ├── cloudflare-apply.yml
│       └── deploy.yml
├── config.yaml
├── docker-compose.yml
└── docs/
```

## Frontend — Astro

### Why Astro

- Static-first with optional server-side rendering
- Zero JavaScript by default — ships only what's needed
- Built-in component islands for interactive parts
- Fast build times, optimized output
- Good for content-heavy company profile sites

### Pages

| Route       | Purpose                                |
|-------------|----------------------------------------|
| `/`         | Homepage — hero, services overview, CTA |
| `/about`    | Company story, team, values            |
| `/services` | Detailed service offerings             |
| `/contact`  | Contact form (submits to backend API)  |
| `/blog`     | Blog listing (fetched from backend)    |

### Configuration

```javascript
// astro.config.mjs
import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';
import node from '@astrojs/node';

export default defineConfig({
  output: 'server',
  adapter: node({ mode: 'standalone' }),
  integrations: [tailwind()],
  server: { port: 11000, host: '0.0.0.0' },
});
```

### Docker

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine AS runtime
WORKDIR /app
COPY --from=build /app/dist ./dist
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./
ENV HOST=0.0.0.0
ENV PORT=11000
EXPOSE 11000
CMD ["node", "./dist/server/entry.mjs"]
```

## Backend — FastAPI

### Endpoints

| Method | Route             | Purpose                      |
|--------|-------------------|------------------------------|
| GET    | `/`               | API root / health message    |
| GET    | `/health`         | Health check                 |
| GET    | `/api/services`   | List company services        |
| POST   | `/api/contact`    | Submit contact form          |
| GET    | `/api/blog`       | List blog posts              |
| GET    | `/api/blog/{slug}`| Get single blog post         |

### Database Models

```python
# db_models.py
class ContactSubmission(Base):
    __tablename__ = "contact_submissions"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    company = Column(String, nullable=True)
    message = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String, default="new")  # new, read, replied

class BlogPost(Base):
    __tablename__ = "blog_posts"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False)
    content = Column(String, nullable=False)
    excerpt = Column(String, nullable=True)
    author = Column(String, default="CloudMindra")
    published = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class Service(Base):
    __tablename__ = "services"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=False)
    icon = Column(String, nullable=True)
    order = Column(Integer, default=0)
```

### Database Connection

```python
# database.py
DATABASE_URL = os.getenv("DATABASE_URL")
# Format: postgresql://user:password@host:5432/cloudmindra
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
```

### Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home app && chown -R app:app /app
USER app
EXPOSE 11001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "11001"]
```

### Dependencies

```
# requirements.txt
fastapi==0.115.0
uvicorn[standard]==0.30.0
sqlalchemy==2.0.35
psycopg2-binary==2.9.9
python-dotenv==1.0.1
pydantic==2.9.0
alembic==1.13.0
```

## Database — PostgreSQL

### Setup

The PostgreSQL database runs on the Contabo VPS, firewalled to accept connections only from localhost.

```
Database name: cloudmindra
User: cloudmindra
Port: 5432
```

### Environment Variable

```
DATABASE_URL=postgresql://cloudmindra:PASSWORD@localhost:5432/cloudmindra
```

### Initial Setup (on server)

```bash
sudo -u postgres psql
CREATE DATABASE cloudmindra;
CREATE USER cloudmindra WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE cloudmindra TO cloudmindra;
\c cloudmindra
GRANT ALL ON SCHEMA public TO cloudmindra;
```

## Docker Compose

```yaml
# docker-compose.yml
services:
  frontend:
    build: ./app/frontend
    container_name: cloudmindra-frontend
    ports:
      - "11000:11000"
    environment:
      - PUBLIC_API_URL=https://api.cloudmindra.com
    restart: unless-stopped

  backend:
    build: ./app/backend
    container_name: cloudmindra-backend
    ports:
      - "11001:11001"
    env_file:
      - ./app/backend/.env
    depends_on:
      - db
    restart: unless-stopped

  db:
    image: postgres:16-alpine
    container_name: cloudmindra-db
    ports:
      - "127.0.0.1:5432:5432"
    environment:
      POSTGRES_DB: cloudmindra
      POSTGRES_USER: cloudmindra
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  pgdata:
```

## DNS — Cloudflare (Terraform)

DNS records are managed via Terraform in the `cloudflare/` directory.

### Current Records

| Type | Name               | Content         | Proxied |
|------|--------------------|-----------------|---------|
| A    | cloudmindra.com    | 207.180.248.214 | Yes     |
| A    | api.cloudmindra.com| 207.180.248.214 | Yes     |

### Adding api subdomain

The `api.cloudmindra.com` DNS record needs to be added to `cloudflare/dns.tf`:

```hcl
resource "cloudflare_record" "api_cloudmindra" {
  zone_id = data.cloudflare_zones.cloudmindra.zones[0].id
  name    = "api"
  content = local.contabo_ip
  type    = "A"
  proxied = true
  ttl     = 1
}
```

## Nginx — Reverse Proxy

Nginx on the Contabo VPS routes traffic to the correct container port. The configuration is managed in the `nasir.id` repo (`nginx/list`).

The entries already exist:

```
cloudmindra.com,11000
api.cloudmindra.com,11001
```

## CI/CD — GitHub Actions

### Deployment Workflow

```yaml
# .github/workflows/deploy.yml
name: Deploy CloudMindra

on:
  push:
    branches: [main]
    paths:
      - 'app/frontend/**'
      - 'app/backend/**'
      - 'docker-compose.yml'

permissions:
  id-token: write
  contents: read

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS Credentials (OIDC)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_IAM_ROLE_ARN }}
          aws-region: ${{ secrets.AWS_REGION }}

      - name: Download .env from S3
        working-directory: app/backend
        run: aws s3 cp s3://cloudmindra.com/backend/.env .env

      - name: Deploy to Contabo
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.CONTABO_HOST }}
          username: ${{ secrets.CONTABO_USER }}
          key: ${{ secrets.CONTABO_SSH_KEY }}
          script: |
            cd /opt/cloudmindra
            git pull origin main
            docker compose up -d --build
```

## Environment Variables

### Backend (.env)

The `.env` file is stored in S3 at `s3://cloudmindra.com/backend/.env` and downloaded during CI/CD deployment. This keeps secrets out of the repository and GitHub secrets.

```
DATABASE_URL=postgresql://cloudmindra:PASSWORD@localhost:5432/cloudmindra
CORS_ORIGINS=https://cloudmindra.com
```

### Upload .env to S3

```bash
# app/backend/upload.sh
aws s3 rm s3://cloudmindra.com/backend/.env
aws s3 cp .env s3://cloudmindra.com/backend/.env
```

Run this locally (with AWS credentials configured) whenever the `.env` changes:

```bash
cd app/backend
aws s3 cp .env s3://cloudmindra.com/backend/.env
```

### Download .env in CI/CD

The deployment workflow downloads the `.env` from S3 before building:

```yaml
- name: Download .env from S3
  working-directory: app/backend
  run: aws s3 cp s3://cloudmindra.com/backend/.env .env
```

This works because the GitHub Actions workflow authenticates to AWS via OIDC (the `github-actions` role has S3 access).

### Frontend

```
PUBLIC_API_URL=https://api.cloudmindra.com
```

### GitHub Actions Secrets

| Secret                | Purpose                                |
|-----------------------|----------------------------------------|
| AWS_IAM_ROLE_ARN      | OIDC role for AWS access               |
| AWS_REGION            | ap-southeast-1                         |
| CLOUDFLARE_API_TOKEN  | Terraform Cloudflare provider          |
| CONTABO_HOST          | VPS IP address                         |
| CONTABO_USER          | SSH username                           |
| CONTABO_SSH_KEY       | SSH private key for deployment         |

> **Note:** `POSTGRES_PASSWORD` and other app secrets are NOT stored in GitHub secrets. They live in the `.env` file on S3 (`s3://cloudmindra.com/backend/.env`).

## Implementation Order

1. **Database** — Create PostgreSQL database on Contabo
2. **Backend** — FastAPI app with models, routes, Dockerfile
3. **Frontend** — Astro site with pages, components, Dockerfile
4. **Docker Compose** — Wire everything together
5. **DNS** — Add `api.cloudmindra.com` A record via Terraform
6. **Deploy** — Push, build containers, verify
7. **CI/CD** — Add deployment workflow

## Services Offered (Content)

CloudMindra's service offerings for the website:

1. **Cloud Infrastructure** — AWS, GCP, Azure architecture and migration
2. **AI & Machine Learning** — Custom AI solutions, model deployment, LLM integration
3. **DevOps & Automation** — CI/CD pipelines, Infrastructure as Code, monitoring
4. **Data Engineering** — Data pipelines, analytics, data lake architecture
5. **Cloud Security** — IAM, compliance, vulnerability assessment
6. **Consulting** — Cloud strategy, cost optimization, architecture review
