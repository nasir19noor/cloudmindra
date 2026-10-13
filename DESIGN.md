# CloudMindra Platform — Design

This is the source of truth for how the CloudMindra customer platform is built and where it is going.
Update it in the same change as any decision or structural change. Diagrams: [docs/architecture.drawio](docs/architecture.drawio).

**Status legend:** ✅ built and deployed · 🚧 built, not yet deployed · 🔜 planned

---

## 1. Product

CloudMindra sells cloud and AI consulting. The platform adds self-service **modules** customers use after logging in. Every module has a **Free** tier; customers upgrade to **Pro per module**.

| Module (`app_key`) | What it does | Status |
|---|---|---|
| `uptime` | Monitors URLs, emails on down / recovery / SSL expiry | 🚧 (per-user today; moves to workspaces in phase 2–3) |
| `review` | AI Architecture Review of uploaded Terraform/CloudFormation/diagrams | 🔜 |
| `cost` | AWS Cost Analyzer — spend trends, idle resources, savings | 🔜 |
| `security` | Cloud Security Scan — misconfigurations mapped to CIS/SOC2/ISO | 🔜 |
| `iac` | Terraform / CI-CD generator | 🔜 |

**Scope decisions:** AWS only for now (GCP/Azure later behind a provider interface) · single AWS account per connection (no AWS Organizations yet) · Pro is switched on manually by a platform admin (no payment provider yet).

---

## 2. System architecture

```
 Customer / admin browser
        │  HTTPS
        ▼
 Cloudflare DNS (DNS only, not proxied) ── Email Routing for inbound mail
        │
        ▼
 Contabo VPS 207.180.248.214
 ├─ nginx (TLS, reverse proxy)
 │   ├─ cloudmindra.com      → cloudmindra-frontend  (Astro SSR, :11000)
 │   └─ api.cloudmindra.com  → cloudmindra-backend   (FastAPI, :11001, host network)
 ├─ cloudmindra-worker  🔜   (same image, runs jobs/schedulers; WORKER_APPS selects modules)
 ├─ PostgreSQL (host, :5432, firewalled)
 └─ GitHub Actions self-hosted runner (deploy.yml)

 AWS account 647459380434 (ap-southeast-1)
 ├─ Cognito user pool  ap-southeast-1_fEjlCGN5Y  + managed login (cloudmindra-auth) + Google IdP
 ├─ SES (domain cloudmindra.com, DKIM in Cloudflare)
 ├─ S3 cloudmindra.com: Terraform state, backend/.env
 ├─ S3 reports bucket 🔜 (org/{org_id}/… private, signed downloads)
 └─ IAM Roles Anywhere 🔜 (trust anchor + profile → role CloudMindraHub)

 Customer AWS account 🔜
 └─ Role CloudMindraReadOnly (trusts CloudMindraHub, requires per-workspace ExternalId)

 Monitored customer websites  ← uptime checks (public internet only)
```

### 2.1 Deployment
| Pipeline | Trigger | Runner | Does |
|---|---|---|---|
| `deploy.yml` | push to `main` touching `app/**`, `docker-compose.yml` | self-hosted (Contabo) | pulls `.env` from `s3://cloudmindra.com/backend/.env`, `docker compose up --build` |
| `aws-apply.yml` | push to `main` touching `aws/services/**`, `config.yaml` | GitHub-hosted, AWS OIDC | `terraform apply` per changed service dir; Google client id/secret from repo secrets |
| `cloudflare-apply.yml` | push to `main` touching `cloudflare/**` | GitHub-hosted, AWS OIDC | DNS records |

`.env` changes: edit locally → `app/backend/upload.sh` → redeploy. `.env` is gitignored.

### 2.2 Containers
| Container | Command | Responsibility |
|---|---|---|
| `cloudmindra-frontend` | Astro node server | Marketing site, `/portal`, `/admin` |
| `cloudmindra-backend` | `uvicorn main:app` | HTTP API only (after phase 3) |
| `cloudmindra-worker` 🔜 | `python worker.py` | Job queue consumer + module schedulers (uptime loop, daily cost pulls, scans) |

Until phase 3 the uptime loop runs inside the API process (`MONITOR_WORKER=true`), which requires a **single** uvicorn worker.

---

## 3. Identity and authentication ✅

- **Cognito** user pool, email as username, managed login v2 at `https://cloudmindra-auth.auth.ap-southeast-1.amazoncognito.com`. Sign-in with **email/password** or **Google** (federated IdP). Verification emails sent via SES from `no-reply@cloudmindra.com`.
- **Flow:** browser → `GET /api/auth/login?provider=google&next=/portal|/admin` → Cognito → `GET /api/auth/callback` → backend exchanges the code (confidential client + PKCE + state cookie), verifies the ID token against Cognito JWKS, upserts `users`, sets **`cm_session`** (HMAC-signed, httpOnly, SameSite=Lax, 12 h) → redirect to `next` (allow-list only).
- **Logout:** `GET /api/auth/logout` clears `cm_session` and ends the Cognito session.
- **Platform admin:** `users.is_admin` (checked on every request, so revocation is immediate). Seeded by `ADMIN_EMAIL` (comma-separated, verified email only) at startup and on login; other admins toggled in `/admin`. No password login exists.
- Terraform: `aws/services/cognito/` (pool, domain, client, managed-login branding, Google IdP, groups). Cognito groups are not used for authorization.

---

## 4. Multi-tenancy 🔜

**Model:** shared database and tables; every tenant-owned row has `org_id`. UI term: **Workspace** (code: `organization`).

### 4.1 Rules (agreed)
| Topic | Decision |
|---|---|
| Who can create workspaces | Any user. Max **2 owned workspaces with no Pro module** per user (admin can raise). |
| First login | Auto-create "{Name}'s workspace" with the user as owner. |
| Roles | `owner` · `admin` · `member` · `viewer` (see 4.2). Always ≥ 1 owner. |
| Member cap | 3 if the workspace has no Pro module; 10 once any module is Pro; admin override per workspace. |
| Invitations | By email, 7-day token (only SHA-256 hash stored), sent from `no-reply@`. Accept requires the **exact verified email** invited (case-insensitive). Admin can cancel and re-invite. |
| Alerts | On by default for every role including viewers; each member can opt out per event type. |

### 4.2 Permissions
Endpoints check an **action**, not a role. Mapping lives in `core/catalog.py`:

```python
ROLE_PERMISSIONS = {
  "viewer": {"*.read"},
  "member": {"*.read", "uptime.write", "review.run", "iac.run", "security.run"},
  "admin":  {"*", "-org.delete", "-org.transfer"},
  "owner":  {"*"},
}
```

| Action | owner | admin | member | viewer |
|---|:-:|:-:|:-:|:-:|
| Read any module data | ✅ | ✅ | ✅ | ✅ |
| Create/edit/run in modules | ✅ | ✅ | ✅ | ❌ |
| Manage members, invites, roles below owner, rename | ✅ | ✅ | ❌ | ❌ |
| Manage cloud connections | ✅ | ✅ | ❌ | ❌ |
| Grant owner, delete workspace | ✅ | ❌ | ❌ | ❌ |

### 4.3 Enforcement
- All tenant routes: `/api/orgs/{org_id}/…`, guarded by `org_access("<app>.<action>")` which checks **membership → permission → module enabled**. Non-members get **404** (no probing), insufficient role **403**, module off **403**, over limit **402**.
- Queries go through `org_query(db, Model, ctx)`, never a hand-written `org_id` filter.
- A test enumerates every route under `/api/orgs/{org_id}/` and asserts 404 for non-members and 403 for viewers on writes.
- Postgres Row-Level Security is a later hardening step.

---

## 5. Modules, tiers and limits 🔜

The catalog (modules, tiers, limits, permissions, notification events) is **code** in `core/catalog.py`; per-workspace state is in `org_apps`.

| Module | Free | Pro |
|---|---|---|
| `uptime` | 10 monitors, interval ≥ 5 min, 7 days history | 100 monitors, 1-min interval, 90 days history |
| `review` | 1 review / month | 30 / month, PDF export |
| `cost` | 1 AWS account, monthly granularity, 3 months history | 10 accounts, daily, 13 months, anomaly alerts |
| `security` | 1 AWS account, 1 manual scan / month, summary | 10 accounts, daily scheduled scans, full findings, PDF + SOC2/ISO mapping |
| `iac` | 2 generations / month | 50 / month, multi-environment templates |
| workspace | 3 members | 10 members once any module is Pro |

- **Effective limit** = `org_apps.limits` override → tier default.
- Count limits are checked at create time; monthly limits use `usage_counters`, incremented atomically (`UPDATE … SET count = count + 1 WHERE count < :limit`) in the same transaction that queues the work.
- Over-limit responses: HTTP **402** with a human message and an upgrade hint.
- Pro is set manually by a platform admin in `/admin` (`tier`, `pro_since`, `pro_until`).

---

## 6. Backend structure — modular monolith (microservice-ready) 🔜

```
app/backend/
  main.py                 API entrypoint (routers only)
  worker.py               worker entrypoint (WORKER_APPS=uptime,cost,…)
  core/
    db.py  auth.py  orgs.py  catalog.py  entitlements.py
    jobs.py  notify.py  audit.py  reports.py  fx.py
    cloud/  base.py  registry.py  aws/  fake/
  apps/
    uptime/   models.py router.py worker.py
    review/   cost/   security/   iac/
  routers/   auth.py admin.py orgs.py members.py invitations.py jobs.py reports.py
  migrations/            Alembic
```

**Boundary rules (what makes later extraction possible):**
1. Each module owns its tables, in its **own Postgres schema** (`uptime`, `cost`, …). Modules never read another module's tables.
2. Modules use only `core/` interfaces (orgs, entitlements, jobs, notify, audit, reports, cloud).
3. Long or cross-module work goes through **jobs/events**, not direct calls.
4. Each module has its own route prefix `/api/orgs/{org}/{app_key}/…`.
5. Workers can run a subset of modules (`WORKER_APPS`), so one module can be scaled or moved alone.
6. **No foreign keys from a module's tables to another schema.** `org_id`, `created_by` etc. are plain indexed columns; foreign keys are only used inside one schema (e.g. `uptime.checks.monitor_id → uptime.monitors`).
7. **Access and limits only through `org_access()` / `entitlements`.** Module code never queries `core.memberships` or `core.org_apps` directly, so the same call can later become an API call or a signed token without changing module logic.
8. **Events are written with a transactional outbox** (§6.1) in the same transaction as the data change, never sent "after commit" by hand.
9. **Cross-module screens use module summary APIs** (e.g. `GET /api/orgs/{org}/uptime/summary`) for the portal Overview and `/admin`, never SQL joins across schemas.
10. Workspace deletion is an **event** (`org.deleted`); each module deletes its own rows. No cross-schema `ON DELETE CASCADE`.

### 6.1 Database layout for future microservices

**Today: one Postgres database, one schema and one database role per module.**

```
database cloudmindra
  schema core      users, organizations, memberships, invitations, org_apps, usage_counters,
                   jobs, schedules, notification_prefs, audit_events, reports, fx_rates,
                   cloud_connections, cloud_scopes, outbox
  schema uptime    monitors, checks, outbox
  schema cost      records, …, outbox
  schema security  findings, resources, outbox
  schema review    …, outbox          schema iac   …, outbox
  schema site      contact_submissions, blog_posts, services, page_visits (marketing)

role core_svc      read/write core
role uptime_svc    read/write uptime only        (likewise cost_svc, security_svc, …)
role migrator      owns all schemas, used only by Alembic
```

- Each module's SQLAlchemy models are bound to an engine that connects as **that module's role** (session `binds` per declarative base). A query that touches another schema fails with a permission error, so the boundary is **enforced by the database**, not only by code review.
- Connection settings: one URL per role in `.env` (`DATABASE_URL_CORE`, `DATABASE_URL_UPTIME`, …), falling back to `DATABASE_URL` for local development.
- **Outbox per schema:** `<schema>.outbox (id uuid, event_type, org_id, payload jsonb, created_at, published_at NULL)`. A module inserts its event in the same transaction as its data. A relay in the worker publishes unpublished rows (today into `core.jobs` / `notify()`; later to SQS/EventBridge) and marks them published. Consumers must be idempotent (event `id` is the dedupe key).
- Core data that modules need (membership, role, enabled modules, limits) is read only through `core/` functions, which run on the core engine.

**Growth path**

| Stage | Database | Messaging |
|---|---|---|
| Now | One Postgres, schema + role per module | Outbox relay → Postgres job queue |
| First split (likely `cost`, the largest data) | `pg_dump -n cost` → its own database; service gets its own Alembic history | Outbox relay → SQS/EventBridge; core exposes a membership/entitlement API (or signed tokens carrying role + enabled modules) |
| Later | Each service owns its database; core = identity, workspaces, tiers | All cross-service traffic via events and APIs |

Extraction steps for one module: move `apps/<x>` + its schema into a new service and database, point the gateway route prefix at it, switch its outbox relay to the broker, and replace direct `core/` calls with the core API client (same interface).

---

## 7. Shared platform services 🔜

| Service | Purpose | Key points |
|---|---|---|
| **Jobs** (`jobs`, `schedules`) | Background work for any module | Claimed with `SELECT … FOR UPDATE SKIP LOCKED`; retries with backoff; timeouts; status polled by the portal. Uptime keeps its own high-frequency loop inside the worker. |
| **Notifications** (`notify()`, `notification_prefs`) | Email alerts per event (`uptime.down`, `uptime.recovered`, `uptime.ssl`, `cost.anomaly`, `security.critical`, `review.done`) | Recipients = members with that event enabled. Sender `CloudMindra Monitoring <no-reply@cloudmindra.com>` (`ALERT_FROM_ADDRESS`). Slack/webhooks later as channels. |
| **Audit** (`audit()`, `audit_events`) | Who did what | Shown in workspace Settings → Activity and in `/admin`. |
| **Reports** (`reports`) | PDF/ZIP/JSON outputs | Private S3 bucket under `org/{org_id}/…`; download via 5-minute signed URL after access check; retention 90 days on Free. |
| **FX** (`fx_rates`) | Currency conversion | Daily ECB reference rates (includes IDR). |
| **Outbox relay** (`<schema>.outbox`) | Reliable events between modules | Runs in the worker; publishes each schema's unpublished events in order, retries, marks `published_at`; consumers dedupe by event id. Events: `org.created`, `org.deleted`, `member.removed`, `module.tier_changed`, `uptime.down`, … |

---

## 8. Cloud connections (AWS) 🔜

### 8.1 How CloudMindra reaches a customer account
1. **CloudMindra hub identity — IAM Roles Anywhere** (decided). The Contabo worker holds an X.509 certificate issued by a CloudMindra private CA; Roles Anywhere exchanges it for short-lived credentials of role **`CloudMindraHub`**, whose only permission is `sts:AssumeRole` on `arn:aws:iam::*:role/CloudMindra*`. No long-lived AWS keys are stored anywhere.
2. **Customer access — role ARN + External ID only** (decided). The customer launches a CloudFormation quick-create link that creates **`CloudMindraReadOnly`** (read-only managed policies for billing/config/security as each module needs) trusting `CloudMindraHub` with the workspace's random External ID. Nothing secret is stored per customer; the customer revokes access by deleting the role.
3. Customer access keys are **not** accepted. (If ever needed: envelope encryption AES-256-GCM + KMS, write-only field, worker-only decryption, audited.)

Terraform (planned): `aws/services/iam/` (CloudMindraHub, Roles Anywhere trust anchor + profile, CA), CloudFormation template for customers under `app/backend/core/cloud/aws/onboarding/`.

### 8.2 Provider interface (GCP/Azure ready)
```python
class CloudProvider(Protocol):
    key: str
    def onboarding(self, org) -> Onboarding
    def verify(self, conn) -> Capabilities
    def discover_scopes(self, conn) -> list[Scope]
    def costs(self, conn, scope, start, end) -> Iterable[CostRecord]
    def resources(self, conn, scope, types=None) -> Iterable[Resource]
    def checks(self) -> list[Check]
```
Only `aws` (and `fake` for tests) is implemented. Modules declare supported providers in the catalog. GCP would need a CloudMindra GCP project + service account; Azure a multi-tenant Entra app — not needed until those clouds are added.

### 8.3 Normalised data
- `cost_records` uses **FinOps FOCUS** column names (`charge_period_start`, `service_category`, `service_name`, `region_id`, `resource_id`, `billed_cost`, `effective_cost`, `billing_currency`, `tags`). Original currency is always stored; display currency is chosen per workspace (default) and per user (override) and converted with `fx_rates` for the cost date.
- `cloud_resources` normalised `resource_type` (`compute.vm`, `storage.bucket`, …) plus `native_type`.
- `findings` keyed by provider-neutral `control_id` (`storage.public_access`) with provider `check_id` (`aws.s3.public_bucket`) and framework mappings.

---

## 9. Data model

✅ = exists today (currently in the `public` schema) · 🔜 = planned. All tenant tables carry `org_id NOT NULL` + index, `created_by`, `created_at`, `updated_at`, UUID PKs. Foreign keys only **within** a schema (§6 rule 6); columns pointing into another schema are plain indexed values.

| Schema.table | Key columns | Status |
|---|---|---|
| `core.users` | `id` (Cognito sub), `email`, `name`, `provider`, `is_admin`, `created_at`, `last_login_at`, 🔜 `last_org_id`, 🔜 `currency` | ✅ |
| `core.organizations` | `id`, `name`, `created_by`, `currency`, `member_limit` (override) | 🔜 |
| `core.memberships` | `org_id`, `user_id`, `role` — UNIQUE(org_id,user_id) | 🔜 |
| `core.invitations` | `org_id`, `email`, `role`, `token_hash`, `invited_by`, `expires_at`, `accepted_at` | 🔜 |
| `core.org_apps` | PK(`org_id`,`app_key`), `tier` free/pro, `status`, `limits` jsonb, `pro_since`, `pro_until` | 🔜 |
| `core.usage_counters` | PK(`org_id`,`metric`,`period`), `count` | 🔜 |
| `core.jobs` | `org_id`, `app_key`, `type`, `payload`, `status`, `run_at`, `attempts`, `locked_by`, `result`, `error` | 🔜 |
| `core.schedules` | `org_id`, `app_key`, `type`, `payload`, `interval`, `next_run_at`, `enabled` | 🔜 |
| `core.notification_prefs` | PK(`membership_id`,`event_key`), `email` | 🔜 |
| `core.audit_events` | `org_id`, `actor_user_id`, `app_key`, `action`, `target_id`, `metadata`, `ip` | 🔜 |
| `core.reports` | `org_id`, `app_key`, `kind`, `title`, `s3_key`, `size_bytes`, `job_id` | 🔜 |
| `core.fx_rates` | PK(`date`,`base`,`quote`), `rate` | 🔜 |
| `core.cloud_connections` | `org_id`, `provider`, `scope_type`, `scope_id`, `auth_method`, `config` (role_arn, external_id), `capabilities`, `status` | 🔜 |
| `core.cloud_scopes` | `connection_id`, `scope_type`, `scope_id`, `name`, `included` | 🔜 |
| `<schema>.outbox` (every schema) | `id` uuid, `event_type`, `org_id`, `payload` jsonb, `created_at`, `published_at` | 🔜 |
| `public.monitors` → `uptime.monitors` | today `user_id` (FK to users); becomes `org_id` + `created_by`, no cross-schema FK | ✅ (per user) |
| `public.monitor_checks` → `uptime.checks` | `monitor_id` (FK inside schema), `checked_at`, `ok`, `status_code`, `response_ms`, `error` (30-day retention) | ✅ |
| `cost.records` | FOCUS columns, see §8.3; partitioned by month | 🔜 |
| `security.findings`, `security.resources` | see §8.3 | 🔜 |
| `public.*` marketing → `site.*` | `contact_submissions`, `blog_posts`, `services`, `page_visits` | ✅ |

**Migrations:** Alembic (phase 1), one history for now with one branch label per schema so a module's migrations can later move with it into its own service.
- `0001` baseline = current schema (`alembic stamp` on prod).
- `0002` create schemas `core`, `uptime`, `site` and roles; `ALTER TABLE … SET SCHEMA` for existing tables; drop the `monitors.user_id → users` FK; grant each role its schema.
- `0003` workspaces: organizations + memberships + invitations, backfill personal workspaces, `uptime.monitors.org_id`.
- `0004` platform tables + outbox per schema; every workspace gets every module on `free`.
- `0005` cloud tables when the first AWS module lands.

The container runs `alembic upgrade head` (as `migrator`) before start; take a `pg_dump` before each migration deploy. Until phase 1 `init_db()` uses `create_all` plus guarded `ALTER TABLE`.

---

## 10. API conventions

| Area | Routes |
|---|---|
| Auth ✅ | `GET /api/auth/login`, `/callback`, `/logout`, `/me` |
| Platform admin ✅ | `/api/admin/me`, `/analytics`, `/users`, `PUT /users/{id}` (is_admin), `POST /logout` |
| Uptime ✅ (moves to `/api/orgs/{org}/uptime/…`) | `GET/POST /api/monitors`, `PATCH/DELETE /api/monitors/{id}`, `POST /{id}/check`, `GET /{id}/checks` |
| Workspaces 🔜 | `GET/POST /api/orgs`, `PATCH/DELETE /api/orgs/{org}` |
| Team 🔜 | `/api/orgs/{org}/members[/{user}]`, `/api/orgs/{org}/invitations[/{id}]`, `POST /api/invitations/accept` |
| Platform 🔜 | `/api/orgs/{org}/jobs/{id}`, `/reports[/{id}/download]`, `/connections[/{id}]`, `/activity` |
| Modules 🔜 | `/api/orgs/{org}/{app_key}/…` |

Errors: 401 not signed in · 403 role/module · 404 not found or not a member · 402 over limit · 422 validation · 429 rate limited.

---

## 11. Frontend

| Route | Purpose | Status |
|---|---|---|
| `/portal` | Sign-in; today the uptime dashboard; later redirects to the last workspace | ✅ |
| `/admin` | Platform admin: analytics, users + admin toggle, contacts; later workspaces, tiers, jobs | ✅ |
| `/portal/[org]` | Overview tiles per enabled module (status, usage) | 🔜 |
| `/portal/[org]/{uptime,review,cost,security,iac}` | Module pages | 🔜 |
| `/portal/[org]/connections` | AWS accounts | 🔜 |
| `/portal/[org]/reports` · `/team` · `/settings` | Files · members/invites/alerts · name, tiers & usage, activity, leave/delete | 🔜 |
| `/portal/invite` | Accept invitation | 🔜 |

The sidebar is built from `GET /api/orgs/{org}` (`role`, modules with tier/limits/usage), so new modules appear without layout changes. Free modules show usage and an "Upgrade to Pro" hint; actions are hidden by role but always enforced server-side.

---

## 12. Security principles
- No long-lived cloud credentials: Roles Anywhere for CloudMindra, role + External ID for customers.
- Secrets live in GitHub secrets (Terraform) or the S3 `.env` (runtime); never in git or the database.
- Tenant isolation enforced centrally (§4.3) and tested for every route.
- Module isolation enforced by the database: each module connects as its own Postgres role with access to its own schema only (§6.1); only `migrator` can change schemas.
- Outbound requests to customer URLs only reach public IPs (private/loopback/link-local blocked; redirects not followed). Known gap: DNS rebinding between check and connect.
- All customer-supplied text is escaped before rendering; session cookie is httpOnly + signed; OAuth uses state + PKCE.
- SES must be out of sandbox before customers rely on alert emails.

---

## 13. Roadmap

| Phase | Scope | Status |
|---|---|---|
| 0 | Cognito + Google login, portal, admin via `is_admin`/`ADMIN_EMAIL`, uptime monitor (per user) | ✅/🚧 |
| 1 | Alembic, Postgres schemas + roles per module (move existing tables, drop cross-schema FKs), workspaces, memberships, backfill, `org_access` | 🔜 |
| 2 | Catalog, Free/Pro per module, `org_apps`, limits & usage, isolation test | 🔜 |
| 3 | `core/` + `apps/` layout, engine per module role, worker container, job queue, outbox per schema + relay, uptime moved, notify, audit, module summary APIs | 🔜 |
| 4 | Team: invitations, roles, alert prefs, member caps, 2-free-workspace limit | 🔜 |
| 5 | Portal: workspace switcher, module sidebar, Team, Settings | 🔜 |
| 6 | Admin: workspaces, set Pro per module, overrides, jobs | 🔜 |
| 7 | AWS: Roles Anywhere hub, CloudFormation onboarding, connections | 🔜 |
| 8+ | Cost Analyzer (currency selection), Security Scan, Review, IaC | 🔜 |

---

## 14. Decision log

| Date | Decision |
|---|---|
| 2026-10-12 | Login via Cognito managed login with Google federation; backend-held confidential client, own session cookie. |
| 2026-10-12 | Admin = `users.is_admin` toggled in `/admin`, seeded by `ADMIN_EMAIL`; removed `ADMIN_USERNAME/PASSWORD`. |
| 2026-10-12 | First module: Uptime Monitor; alerts sent from `no-reply@cloudmindra.com`. |
| 2026-10-13 | Multi-tenancy via shared tables + `org_id`; UI term "Workspace". |
| 2026-10-13 | Every module has Free; Pro bought **per module**; Pro set manually by admin. |
| 2026-10-13 | Modular monolith + separate worker container, prepared for microservices. |
| 2026-10-13 | AWS only, single account per connection; GCP/Azure later via provider interface. |
| 2026-10-13 | Customer access via role ARN + External ID only; CloudMindra identity via IAM Roles Anywhere. |
| 2026-10-13 | User-selectable display currency; store original, convert with daily ECB rates. |
| 2026-10-13 | Team rules: any user creates workspaces (max 2 free-only), member cap 3/10, exact-email invites, alerts default on for all roles. |
| 2026-10-13 | Database prepared for microservices: Postgres schema + role per module, no cross-schema foreign keys, access checks only via `org_access()`, transactional outbox per schema, cross-module screens via summary APIs, workspace deletion as an `org.deleted` event. |
