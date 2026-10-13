# CloudMindra Platform — Design

This is the source of truth for how the CloudMindra customer platform is built and where it is going.
Update it in the same change as any decision or structural change. Diagrams: [docs/architecture.drawio](docs/architecture.drawio).

**Status legend:** ✅ deployed to production · 🚧 built, not yet deployed · ⚠️ deployed but needs a manual step / not verified · 🔜 planned

## Deployment status

Last verified **2026-10-14** against production (`main` at `49d73d9`: PR #1 phase 1, PR #2 team invitations, workspace admin page, PR #3 admin seat limits). Verified from outside with unauthenticated requests: a route that exists answers `401` (sign-in required), a missing route `404`.

| Area | What | Status | Evidence / note |
|---|---|---|---|
| Website | Marketing site, contact form, analytics | ✅ | `cloudmindra.com` 200 |
| Login | Cognito managed login, Google federation, `cm_session` cookie | ✅ | `/api/auth/me` 401 |
| Platform admin | `/admin` with Google sign-in, users + `is_admin` toggle, `ADMIN_EMAIL` seed | ✅ | `/admin` 200, `/api/admin/me` 401 |
| Database | Alembic `0001`–`0003`, schemas `core` / `uptime` / `site`, personal workspaces backfilled | ✅ | Workspace routes answer; confirm once with `SELECT version_num FROM alembic_version` (expect `0003`) |
| Database roles | `core_svc` / `uptime_svc` / `site_svc` + `DATABASE_URL_CORE/UPTIME/SITE` | ⚠️ | Optional; needs `db/roles.sql` run by a DB superuser. Not verified — until done, all schemas use `DATABASE_URL` |
| Workspaces | `/api/orgs…`, `org_access`, roles owner/admin/member/viewer, workspace switcher | ✅ | `/api/orgs` 401 |
| Uptime Monitor | Workspace-scoped `/api/orgs/{org}/uptime/monitors`, alerts to all members from `no-reply@` | ✅ | New route 401, old `/api/monitors` 404 |
| Team | Members, roles, invitations by email, seats (3), leave | ✅ | `/api/orgs/{org}/members` 401, `/api/invitations/preview` answers |
| Invite page | `/portal/invite` | ✅ | 200 (one transient 502 seen while probing) |
| Workspace admin | `/portal/workspace` for owners/admins | ✅ | 200; portal shows "Manage workspace" |
| SES production access | Alert/invite emails to any address | ⚠️ | Invites to Gmail are not arriving (2026-10-13): domain, DKIM, DMARC and SMTP region are correct, so the account is most likely still in the SES sandbox. Request production access in the SES console (ap-southeast-1) |
| Admin seat limits | `/admin` Workspaces section: seats used, owners, per-workspace seat limit override | ✅ | `/api/admin/orgs` 401; `/admin` shows "Seat limit" |
| Invite delivery fallback | Invitation email sent in the request; on failure the inviter gets the link to share | ✅ | Deployed with PR #3 |
| Phase 2: tiers | Free/Pro per module (`core.org_apps`), monthly usage (`core.usage_counters`, migration `0004`), Uptime tier limits, seats 3→10 with any Pro, 2 free workspaces per user, `/admin` Free/Pro switch, portal plan badges, workspace Plan section | 🚧 | Branch `feat/phase2-tiers`; `/api/orgs/{org}/modules` is 404 on production until deployed |
| Phase 3+ | `core/` + `apps/` layout, worker container, outbox, AWS connections, other modules | 🔜 | Not built |

---

## 1. Product

CloudMindra sells cloud and AI consulting. The platform adds self-service **modules** customers use after logging in. Every module has a **Free** tier; customers upgrade to **Pro per module**.

| Module (`app_key`) | What it does | Status |
|---|---|---|
| `uptime` | Monitors URLs, emails on down / recovery / SSL expiry | ✅ (workspace-scoped; moves into `apps/uptime` + worker in phase 3) |
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

**Database migrations on deploy:** the backend container runs `python migrate.py` before uvicorn. It stamps a pre-Alembic database at `0001`, runs `alembic upgrade head` (as `DATABASE_MIGRATION_URL` or `DATABASE_URL`), then grants each existing module role (`core_svc`, `uptime_svc`, `site_svc`) access to its own schema. Take a `pg_dump` before deploying a new migration. Module roles are optional: create them once with `app/backend/db/roles.sql` and set `DATABASE_URL_CORE/UPTIME/SITE`; without them every schema uses `DATABASE_URL`.

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

## 4. Multi-tenancy ✅ (workspaces, roles, `org_access`, invitations and team management deployed; alert preferences 🔜 phase 4)

**Model:** shared database and tables; every tenant-owned row has `org_id`. UI term: **Workspace** (code: `organization`).

### 4.1 Rules (agreed)
| Topic | Decision |
|---|---|
| Who can create workspaces | Any user. Max **2 owned workspaces with no Pro module** per user (`catalog.FREE_WORKSPACES_PER_USER`); workspaces with any Pro module don't count. |
| First login | Auto-create "{Name}'s workspace" with the user as owner. |
| Roles | `owner` · `admin` · `member` · `viewer` (see 4.2). Always ≥ 1 owner. |
| Member cap | Seats = members + pending invitations. 3 if the workspace has no Pro module, 10 once any module is Pro (`catalog.WORKSPACE_SEATS`); platform-admin override per workspace (`organizations.member_limit`). |
| Invitations | By email, 7-day token (only SHA-256 hash stored), sent from `no-reply@`. Owners and admins invite as admin/member/viewer (never owner). Accept requires the **exact verified email** invited (case-insensitive). Inviting the same address again replaces the link; invitations can be cancelled. Pending invitations count as seats. Link: `/portal/invite?token=…` (token kept in sessionStorage through sign-in, removed from the address bar). |
| Leaving | Any member can leave; someone left with no workspace gets a new personal one. The last owner cannot leave, be demoted or be removed. |
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

## 5. Modules, tiers and limits 🚧 (built on `feat/phase2-tiers`, not yet deployed)

The catalog (modules, tiers, limits, features, permissions) is **code** in `catalog.py` (moves to `core/` in phase 3); per-workspace state is in `core.org_apps`. Only `uptime` is `available`; the other modules are listed in the portal as "coming soon" with their planned limits.

| Module | Free | Pro |
|---|---|---|
| `uptime` ✅ enforced | 10 monitors, interval ≥ 5 min, 7 days history | 100 monitors, 1-min interval, 90 days history |
| `review` | 1 review / month | 30 / month, PDF export |
| `cost` | 1 AWS account, monthly granularity, 3 months history | 10 accounts, daily, 13 months, anomaly alerts |
| `security` | 1 AWS account, 1 manual scan / month, summary | 10 accounts, 31 scans / month (daily), full findings, PDF + SOC2/ISO mapping |
| `iac` | 2 generations / month | 50 / month, multi-environment templates |
| workspace | 3 seats | 10 seats once any module is Pro |

- **No `org_apps` row = Free** with catalog limits, so new workspaces and new modules need no backfill. A row is created the first time an admin changes the module.
- **Pro is active** when `tier = 'pro'`, `status` is `active` or `trial`, and `pro_until` is empty or in the future. An expired `pro_until` falls back to Free automatically.
- **Effective limit** = `org_apps.limits` override (per key, e.g. `{"uptime.monitors": 200}`) → tier default.
- **`entitlements.py`** is the only place modules ask: `limit()`, `require_below()` (count limits, checked at create time), `consume()` (monthly limits). Modules report live usage through `USAGE_PROVIDERS[app]`, so core never queries module tables.
- **Monthly limits** use `core.usage_counters` (period `YYYY-MM`, UTC), incremented by one atomic `INSERT … ON CONFLICT DO UPDATE … WHERE count + n <= limit` in the caller's transaction; concurrent requests cannot overshoot (tested with 12 parallel requests on a limit of 5).
- Over-limit responses: HTTP **402** with a human message and "Contact CloudMindra to upgrade … to Pro."
- **Uptime enforcement:** monitor count and allowed intervals checked on create/update; the worker checks a monitor no more often than the tier's minimum (a 1-minute monitor waits 5 minutes after a downgrade); check history is pruned per workspace to 7 / 90 days. Existing monitors above a limit are kept; only new ones are blocked.
- **Pro is set manually** by a platform admin in `/admin` (Free/Pro per module per workspace; `PUT /api/admin/orgs/{org}/modules/{app}` also takes `pro_until` and `limits`). `updated_by` records the admin.
- Not yet: switching a module off for a workspace (every module is enabled for every workspace), billing.

---

## 6. Backend structure — modular monolith (microservice-ready) 🔜 (schemas ✅ deployed; module DB roles ⚠️ optional; `core/` + `apps/` layout, worker and outbox 🔜)

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
| `core.users` | `id` (Cognito sub), `email`, `name`, `provider`, `is_admin`, `last_org_id`, `created_at`, `last_login_at`, 🔜 `currency` | ✅ |
| `core.organizations` | `id`, `name`, `created_by`, `currency`, `member_limit` (override) | ✅ |
| `core.memberships` | `org_id`, `user_id`, `role` — UNIQUE(org_id,user_id) | ✅ |
| `core.invitations` | `org_id`, `email`, `role`, `token_hash`, `invited_by`, `expires_at`, `accepted_at` | ✅ |
| `core.org_apps` | PK(`org_id`,`app_key`), `tier` free/pro, `status` active/trial/past_due/cancelled, `limits` jsonb, `pro_since`, `pro_until`, `updated_by` — no row = Free | 🚧 |
| `core.usage_counters` | PK(`org_id`,`metric`,`period` `YYYY-MM`), `count` | 🚧 |
| `core.jobs` | `org_id`, `app_key`, `type`, `payload`, `status`, `run_at`, `attempts`, `locked_by`, `result`, `error` | 🔜 |
| `core.schedules` | `org_id`, `app_key`, `type`, `payload`, `interval`, `next_run_at`, `enabled` | 🔜 |
| `core.notification_prefs` | PK(`membership_id`,`event_key`), `email` | 🔜 |
| `core.audit_events` | `org_id`, `actor_user_id`, `app_key`, `action`, `target_id`, `metadata`, `ip` | 🔜 |
| `core.reports` | `org_id`, `app_key`, `kind`, `title`, `s3_key`, `size_bytes`, `job_id` | 🔜 |
| `core.fx_rates` | PK(`date`,`base`,`quote`), `rate` | 🔜 |
| `core.cloud_connections` | `org_id`, `provider`, `scope_type`, `scope_id`, `auth_method`, `config` (role_arn, external_id), `capabilities`, `status` | 🔜 |
| `core.cloud_scopes` | `connection_id`, `scope_type`, `scope_id`, `name`, `included` | 🔜 |
| `<schema>.outbox` (every schema) | `id` uuid, `event_type`, `org_id`, `payload` jsonb, `created_at`, `published_at` | 🔜 |
| `uptime.monitors` | `org_id` + `created_by` (plain columns, no cross-schema FK), url, interval, status, SSL fields | ✅ |
| `uptime.checks` | `monitor_id` (FK inside schema), `checked_at`, `ok`, `status_code`, `response_ms`, `error` (30-day retention) | ✅ |
| `cost.records` | FOCUS columns, see §8.3; partitioned by month | 🔜 |
| `security.findings`, `security.resources` | see §8.3 | 🔜 |
| `site.*` (marketing) | `contact_submissions`, `blog_posts`, `services`, `page_visits` | ✅ |

**Migrations:** Alembic (phase 1), one history for now with one branch label per schema so a module's migrations can later move with it into its own service.
- `0001` baseline = current schema (`alembic stamp` on prod).
- `0002` create schemas `core`, `uptime`, `site` and roles; `ALTER TABLE … SET SCHEMA` for existing tables; drop the `monitors.user_id → users` FK; grant each role its schema.
- `0003` workspaces: organizations + memberships + invitations, backfill personal workspaces, `uptime.monitors.org_id`.
- `0004` 🚧 `core.org_apps` + `core.usage_counters` (no backfill: no row = Free).
- `0005` platform tables for phase 3 (jobs, schedules, notification prefs, audit) + outbox per schema.
- `0006` cloud tables when the first AWS module lands.

The container runs `migrate.py` (see §2.1) before start; take a `pg_dump` before each migration deploy. ✅ `0001`–`0003` are deployed; `create_all` is no longer used. Models use the index naming convention `ix_<table>_<column>` (no schema prefix) so autogenerate matches the migrations.

---

## 10. API conventions

| Area | Routes |
|---|---|
| Auth ✅ | `GET /api/auth/login`, `/callback`, `/logout`, `/me` |
| Platform admin ✅ | `/api/admin/me`, `/analytics`, `/users`, `PUT /users/{id}` (is_admin), `POST /logout` · ✅ `GET /orgs` (seats used, owners, limits; 🚧 + module tiers), `PUT /orgs/{id}` (`member_limit` 1–1000, `null` = default) · 🚧 `PUT /orgs/{id}/modules/{app}` (`tier`, `pro_until`, `limits`) |
| Uptime ✅ | `GET/POST /api/orgs/{org}/uptime/monitors`, `PATCH/DELETE …/monitors/{id}`, `POST …/{id}/check`, `GET …/{id}/checks` (read: `uptime.read`, write: `uptime.write`) |
| Workspaces ✅ | `GET/POST /api/orgs`, `GET/PATCH/DELETE /api/orgs/{org}` (name, currency), `POST /api/orgs/{org}/select` (remember last workspace) · 🚧 `GET /api/orgs/{org}/modules` (tier, limits, usage, features per module; also included in `GET /api/orgs/{org}`); uptime list adds `tier`, `locked_intervals`, `history_days` |
| Team ✅ | `GET /api/orgs/{org}/members` (`members.read`) · `PATCH/DELETE /api/orgs/{org}/members/{user}` (`members.manage`; owner role needs `org.transfer`; DELETE on yourself = leave) · `GET/POST /api/orgs/{org}/invitations`, `DELETE …/invitations/{id}` (`members.manage`) · `GET /api/invitations/preview?token=` (no sign-in) · `POST /api/invitations/accept` |
| Platform 🔜 | `/api/orgs/{org}/jobs/{id}`, `/reports[/{id}/download]`, `/connections[/{id}]`, `/activity` |
| Modules 🔜 | `/api/orgs/{org}/{app_key}/…` |

Errors: 401 not signed in · 403 role/module · 404 not found or not a member · 402 over limit · 422 validation · 429 rate limited.

---

## 11. Frontend

| Route | Purpose | Status |
|---|---|---|
| `/portal` | Sign-in, workspace switcher (Manage workspace / Leave), uptime dashboard ✅; Free/Pro badge, plan note, Pro-only intervals shown as locked 🚧 | ✅ |
| `/admin` | Platform admin: analytics, users + admin toggle, contacts, Workspaces with seat-limit override ✅; Free/Pro switch per module 🚧; jobs 🔜 | ✅ |
| `/portal/[org]` | Overview tiles per enabled module (status, usage) | 🔜 |
| `/portal/[org]/{uptime,review,cost,security,iac}` | Module pages | 🔜 |
| `/portal/[org]/connections` | AWS accounts | 🔜 |
| `/portal/workspace?org=` | Workspace admin for owners and admins: name & currency, team (members, roles, invitations, seats), leave, delete (owner, type-to-confirm). Members/viewers see a "not allowed" notice and can leave from `/portal` ✅; Plan section (each module's tier, limits, usage, features) 🚧 | ✅ |
| `/portal/[org]/reports` · `/settings` | Files · tiers & usage, activity, alert preferences (later merged with `/portal/workspace`) | 🔜 |
| `/portal/invite` | Accept invitation (preview before sign-in, token kept in sessionStorage) | ✅ |

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
| 0 | Cognito + Google login, portal, admin via `is_admin`/`ADMIN_EMAIL`, uptime monitor | ✅ |
| 1 | Alembic, Postgres schemas + roles per module (move existing tables, drop cross-schema FKs), workspaces, memberships, backfill, `org_access`; uptime API scoped to workspaces; portal workspace switcher | ✅ (module DB roles ⚠️ optional, not yet set up) |
| 2 | Catalog, Free/Pro per module, `org_apps`, limits & usage, isolation test (every `/api/orgs/{org_id}/…` route returns 404 to non-members, enumerated from OpenAPI) | 🚧 |
| 3 | `core/` + `apps/` layout, engine per module role, worker container, job queue, outbox per schema + relay, uptime moved, notify, audit, module summary APIs | 🔜 |
| 4 | Team: invitations, roles, member caps, `/portal/invite`, `/portal/workspace` (✅ deployed early); alert preferences (🔜) | ✅ / 🔜 |
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
| 2026-10-13 | Deployed: phase 1 (PR #1), team invitations (PR #2), workspace admin page (`d8db972`). |
| 2026-10-14 | Tiers: no `org_apps` row means Free (no backfill); Pro set by hand per module in `/admin`; expired `pro_until` falls back to Free. |
| 2026-10-14 | Free Uptime keeps 7 days of check history (was 30 before tiers); Pro keeps 90. Monitors above a limit after a downgrade are kept, new ones blocked. |
| 2026-10-14 | Deployed: PR #3 admin seat limits and invite-link fallback. |
| 2026-10-13 | Database prepared for microservices: Postgres schema + role per module, no cross-schema foreign keys, access checks only via `org_access()`, transactional outbox per schema, cross-module screens via summary APIs, workspace deletion as an `org.deleted` event. |
