# CloudMindra Platform — Design

This is the source of truth for how the CloudMindra customer platform is built and where it is going.
Update it in the same change as any decision or structural change. Diagrams: [docs/architecture.drawio](docs/architecture.drawio).

**Status legend:** ✅ deployed to production · 🚧 built, not yet deployed · ⚠️ deployed but needs a manual step / not verified · 🔜 planned

## Deployment status

Last verified **2026-10-14** against production (`main` at `e9e8781`: PR #1 phase 1, PR #2 team invitations, workspace admin page, PR #3 admin seat limits, PR #4 phase 2 tiers, PR #5 phase 3 platform, PR #6 phase 4 alert preferences, PR #7 phase 5 portal). Verified from outside with unauthenticated requests: a route that exists answers `401` (sign-in required), a missing route `404`.

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
| Phase 2: tiers | Free/Pro per module (`core.org_apps`), monthly usage (`core.usage_counters`, migration `0004`), Uptime tier limits, seats 3→10 with any Pro, 2 free workspaces per user, `/admin` Free/Pro switch, portal plan badges, workspace Plan section | ✅ | `/api/orgs/{org}/modules` 401 |
| Phase 3: platform | `core/` + `apps/` + `website/` layout, `cloudmindra-worker` container, job queue + schedules, outbox per schema + relay, uptime alerts and workspace cleanup via events, `notify()`, audit log + Activity section, uptime summary API (migration `0005`) | ✅ | `/api/orgs/{org}/activity` and `/uptime/summary` 401; check `docker logs cloudmindra-worker` for "Uptime loop is leader" |
| Phase 4: alert preferences | Per-member, per-workspace email alert switches (`core.notification_prefs`, migration `0006`), "Email alerts" card in `/portal`, settings link in every alert email, one email job per recipient | ✅ | `/api/orgs/{org}/notifications` 401 |
| Phase 5: portal | `/portal/{org}` shell (workspace switcher, module sidebar from the catalog), Overview tiles from summary APIs, `/uptime`, `/alerts`, `/settings` (moved from `/portal/workspace`, which redirects), coming-soon module pages, alert emails link to the workspace's pages | ✅ | `/portal/{org}/uptime` 200 |
| Phase 6: admin tooling | `/admin`: system health (job queue, failed jobs, outbox backlog, overdue uptime monitors) with a warning banner; jobs table with filters, Retry / Cancel; platform activity; Edit plan dialog (tier, Pro end date, per-limit overrides) | 🚧 | Branch `feat/phase6-admin`; API and the page tested in Chrome |
| Phase 7+ | AWS connections (Roles Anywhere, CloudFormation onboarding), Cost / Security / Review / IaC modules | 🔜 | Not built |

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
| `cloudmindra-backend` | `python migrate.py && uvicorn main:app` | HTTP API only |
| `cloudmindra-worker` ✅ | `python migrate.py && python worker.py` | Platform loop every 3 s (outbox relay → jobs, due schedules, due jobs, stuck-job recovery every 60 s) + module loops (uptime checks) |

Both containers use the same image and `.env`; `deploy.yml` starts `backend worker` together. `migrate.py` holds an advisory lock, so the two never migrate at once. `WORKER_APPS` (comma-separated, default all) limits which module loops a worker runs. Several workers are safe: jobs are claimed with `SKIP LOCKED`, and the uptime loop elects one leader with a Postgres advisory lock (the others stand by and take over). Phase 1–2 ran the uptime loop inside the API (`MONITOR_WORKER`); that setting is gone.

---

## 3. Identity and authentication ✅

- **Cognito** user pool, email as username, managed login v2 at `https://cloudmindra-auth.auth.ap-southeast-1.amazoncognito.com`. Sign-in with **email/password** or **Google** (federated IdP). Verification emails sent via SES from `no-reply@cloudmindra.com`.
- **Flow:** browser → `GET /api/auth/login?provider=google&next=/portal|/admin` → Cognito → `GET /api/auth/callback` → backend exchanges the code (confidential client + PKCE + state cookie), verifies the ID token against Cognito JWKS, upserts `users`, sets **`cm_session`** (HMAC-signed, httpOnly, SameSite=Lax, 12 h) → redirect to `next` (allow-list only).
- **Logout:** `GET /api/auth/logout` clears `cm_session` and ends the Cognito session.
- **Platform admin:** `users.is_admin` (checked on every request, so revocation is immediate). Seeded by `ADMIN_EMAIL` (comma-separated, verified email only) at startup and on login; other admins toggled in `/admin`. No password login exists.
- Terraform: `aws/services/cognito/` (pool, domain, client, managed-login branding, Google IdP, groups). Cognito groups are not used for authorization.

---

## 4. Multi-tenancy ✅ (workspaces, roles, `org_access`, invitations, team management and alert preferences deployed)

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
| Alerts | On by default for every role including viewers; each member switches individual alerts off **for themselves, per workspace** on the "Email alerts" page `/portal/{org}/alerts` (no row in `core.notification_prefs` = on). Leaving a workspace deletes that member's settings. |

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

## 5. Modules, tiers and limits ✅ (deployed with PR #4)

The catalog (modules, tiers, limits, features, permissions) is **code** in `core/catalog.py`; per-workspace state is in `core.org_apps`. Only `uptime` is `available`; the other modules are listed in the portal as "coming soon" with their planned limits.

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
- **`core/entitlements.py`** is the only place modules ask: `limit()`, `require_below()` (count limits, checked at create time), `consume()` (monthly limits). Modules report live usage through `USAGE_PROVIDERS[app]`, so core never queries module tables.
- **Monthly limits** use `core.usage_counters` (period `YYYY-MM`, UTC), incremented by one atomic `INSERT … ON CONFLICT DO UPDATE … WHERE count + n <= limit` in the caller's transaction; concurrent requests cannot overshoot (tested with 12 parallel requests on a limit of 5).
- Over-limit responses: HTTP **402** with a human message and "Contact CloudMindra to upgrade … to Pro."
- **Uptime enforcement:** monitor count and allowed intervals checked on create/update; the worker checks a monitor no more often than the tier's minimum (a 1-minute monitor waits 5 minutes after a downgrade); check history is pruned per workspace to 7 / 90 days. Existing monitors above a limit are kept; only new ones are blocked.
- **Pro is set manually** by a platform admin in `/admin` (Free/Pro per module per workspace; `PUT /api/admin/orgs/{org}/modules/{app}` also takes `pro_until` and `limits`). `updated_by` records the admin.
- Not yet: switching a module off for a workspace (every module is enabled for every workspace), billing.

---

## 6. Backend structure — modular monolith (microservice-ready) ✅ (schemas, `core/` + `apps/` layout, worker, jobs and outbox deployed; module DB roles ⚠️ optional)

```
app/backend/
  main.py          API entrypoint: mounts website/, core/routers/ and every apps.MODULES router
  worker.py        worker entrypoint: platform loop + module loops (WORKER_APPS=uptime,…)
  migrate.py       migrations + role grants (runs before both)
  core/            the platform — schema core
    database.py    engines per schema/role, sessions, BASES
    models.py      users, organizations, memberships, invitations, org_apps, usage_counters,
                   jobs, schedules, audit_events, outbox
    auth.py        Cognito login, session cookie, require_user, require_admin, client_ip
    orgs.py        org_access(action), org_query, workspace lifecycle, alert_recipients
    catalog.py     roles/permissions, modules, tiers, limits, features
    entitlements.py tiers, limits, usage counters, USAGE_PROVIDERS
    outbox.py      OutboxMixin, emit(), subscribe(), relay()
    jobs.py        enqueue(), claim (SKIP LOCKED), run_job (retry/backoff), schedules, job_handler()
    notify.py      notify() → member emails (raises so jobs retry)
    audit.py       audit(), audit_ctx()
    mailer.py      SES SMTP
    routers/       auth, admin, orgs (+activity, jobs), team
    (later) reports.py, fx.py, cloud/
  apps/            modules; apps/__init__.py lists MODULES
    uptime/        schema uptime: models (monitors, checks, outbox), service (checks + loop),
                   router (/api/orgs/{org}/uptime/…), handlers (events, usage provider)
    (later) review/ cost/ security/ iac/
  website/         marketing site — schema site: models, schemas, routers (contact, blog, services, analytics)
  migrations/      Alembic
```
`website/` is not named `site/` because that would shadow Python's built-in `site` module.

**Boundary rules (what makes later extraction possible):**
1. Each module owns its tables, in its **own Postgres schema** (`uptime`, `cost`, …). Modules never read another module's tables.
2. Modules use only `core/` interfaces (orgs, entitlements, jobs, notify, audit, reports, cloud).
3. Long or cross-module work goes through **jobs/events**, not direct calls.
4. Each module has its own route prefix `/api/orgs/{org}/{app_key}/…`.
5. Workers can run a subset of modules (`WORKER_APPS`), so one module can be scaled or moved alone.
6. **No foreign keys from a module's tables to another schema.** `org_id`, `created_by` etc. are plain indexed columns; foreign keys are only used inside one schema (e.g. `uptime.checks.monitor_id → uptime.monitors`).
7. **Access and limits only through `org_access()` / `entitlements`.** Module code never queries `core.memberships` or `core.org_apps` directly, so the same call can later become an API call or a signed token without changing module logic.
8. **Events are written with a transactional outbox** (§6.1) in the same transaction as the data change, never sent "after commit" by hand. ✅ Uptime alerts work this way: `record_result` writes `uptime.down` / `uptime.recovered` / `uptime.ssl_expiring` to `uptime.outbox`; the `uptime.alert_members` handler emails members.
9. **Cross-module screens use module summary APIs** (e.g. `GET /api/orgs/{org}/uptime/summary`) for the portal Overview and `/admin`, never SQL joins across schemas.
10. Workspace deletion is an **event** (`org.deleted`); each module deletes its own rows. No cross-schema `ON DELETE CASCADE`. ✅ `delete_workspace` emits `org.deleted` to `core.outbox`; `uptime.delete_workspace_data` removes monitors and checks a few seconds later.

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

## 7. Shared platform services ✅ (jobs, outbox relay, notify, audit, alert preferences deployed; system health 🚧; reports, FX 🔜)

| Service | Purpose | Key points |
|---|---|---|
| **Jobs** (`jobs`, `schedules`) ✅ | Background work for any module | `enqueue()` in the caller's transaction (optional `dedupe_key`); claimed with `SELECT … FOR UPDATE SKIP LOCKED`; retries with backoff 30 s × 2ⁿ (max 1 h), `failed` after `max_attempts` (5); `running` jobs older than 15 min are re-queued; schedules enqueue a job every `interval_seconds`. Status: `GET /api/orgs/{org}/jobs/{id}`. Uptime keeps its own high-frequency loop in the worker. |
| **Notifications** (`notify()`, preferences) ✅ | Email alerts per event — the list is `catalog.NOTIFICATION_EVENTS` (`uptime.down`, `uptime.recovered`, `uptime.ssl_expiring`; later `cost.anomaly`, `security.critical`, `review.done`) | Runs inside an event job. Recipients = members who have not switched that event off; **one `notify.email` job per recipient** (dedupe `notify:<event id>:<address>`), so a failure for one member is retried alone and never re-sends to the others. Every email ends with a link to the alert settings `/portal/{org}/alerts` (older emails' `/portal#alerts` redirects there); uptime alerts link to `/portal/{org}/uptime`. Sender `CloudMindra Monitoring <no-reply@cloudmindra.com>` (`ALERT_FROM_ADDRESS`). Slack/webhooks later as channels. |
| **Audit** (`audit()`, `audit_events`) ✅ | Who did what | Recorded with actor, details and IP for: alert settings changed (🚧), workspace created/updated/deleted, member invited/joined/role changed/removed/left, invitation cancelled, monitor created/updated/deleted, module tier changed, seat limit changed, platform admin granted/revoked. Owners/admins: `GET /api/orgs/{org}/activity` (action `audit.view`, which viewers' `*.read` does not cover) and the Activity section of `/portal/workspace`; platform admins: `GET /api/admin/activity`. |
| **Reports** (`reports`) | PDF/ZIP/JSON outputs | Private S3 bucket under `org/{org_id}/…`; download via 5-minute signed URL after access check; retention 90 days on Free. |
| **FX** (`fx_rates`) | Currency conversion | Daily ECB reference rates (includes IDR). |
| **Health** (`core/health.py`, `HEALTH_PROVIDERS`) 🚧 | Is the platform keeping up? | `system_health()` for `/admin`: job counts, failed in 24 h, oldest due job (warning after 5 min), unpublished events per outbox (warning after 5 min), and each module's provider (uptime: active and overdue monitors — overdue = not checked within its own interval + 10 min). Any warning turns the status to `warning` and shows a banner. |
| **Outbox relay** (`<schema>.outbox`) ✅ | Reliable events between modules | Runs in the worker; for each unpublished event (oldest first, `SKIP LOCKED`) enqueues one `event` job per subscriber with dedupe key `<event id>:<handler>`, commits the jobs, **then** marks `published_at` — a crash in between re-relays and the duplicates are dropped, never lost. Handlers register with `@subscribe(...)` and must be idempotent. Events today: `org.deleted` (core), `uptime.down`, `uptime.recovered`, `uptime.ssl_expiring` (uptime). |

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
| `core.org_apps` | PK(`org_id`,`app_key`), `tier` free/pro, `status` active/trial/past_due/cancelled, `limits` jsonb, `pro_since`, `pro_until`, `updated_by` — no row = Free | ✅ |
| `core.usage_counters` | PK(`org_id`,`metric`,`period` `YYYY-MM`), `count` | ✅ |
| `core.jobs` | `org_id`, `app_key`, `type`, `payload`, `status` queued/running/succeeded/failed/cancelled, `dedupe_key` (unique), `run_at`, `attempts`, `max_attempts`, `locked_by/at`, `result`, `error`, `finished_at`; index `(status, run_at)` | ✅ |
| `core.schedules` | `org_id`, `app_key`, `type`, `payload`, `interval_seconds`, `next_run_at`, `last_run_at`, `enabled` | ✅ |
| `core.notification_prefs` | PK(`membership_id` → memberships, cascade; `event_key`), `email`, `updated_at` — no row = on | ✅ |
| `core.audit_events` | `org_id`, `actor_user_id`, `actor_email`, `app_key`, `action`, `target_id`, `details` (the DESIGN's "metadata"; a reserved name in SQLAlchemy), `ip` | ✅ |
| `core.reports` | `org_id`, `app_key`, `kind`, `title`, `s3_key`, `size_bytes`, `job_id` | 🔜 |
| `core.fx_rates` | PK(`date`,`base`,`quote`), `rate` | 🔜 |
| `core.cloud_connections` | `org_id`, `provider`, `scope_type`, `scope_id`, `auth_method`, `config` (role_arn, external_id), `capabilities`, `status` | 🔜 |
| `core.cloud_scopes` | `connection_id`, `scope_type`, `scope_id`, `name`, `included` | 🔜 |
| `<schema>.outbox` (`core.outbox`, `uptime.outbox`; one per future schema) | `id` uuid, `event_type`, `org_id`, `payload` jsonb, `created_at`, `published_at` | ✅ |
| `uptime.monitors` | `org_id` + `created_by` (plain columns, no cross-schema FK), url, interval, status, SSL fields | ✅ |
| `uptime.checks` | `monitor_id` (FK inside schema), `checked_at`, `ok`, `status_code`, `response_ms`, `error` (30-day retention) | ✅ |
| `cost.records` | FOCUS columns, see §8.3; partitioned by month | 🔜 |
| `security.findings`, `security.resources` | see §8.3 | 🔜 |
| `site.*` (marketing) | `contact_submissions`, `blog_posts`, `services`, `page_visits` | ✅ |

**Migrations:** Alembic (phase 1), one history for now with one branch label per schema so a module's migrations can later move with it into its own service.
- `0001` baseline = current schema (`alembic stamp` on prod).
- `0002` create schemas `core`, `uptime`, `site` and roles; `ALTER TABLE … SET SCHEMA` for existing tables; drop the `monitors.user_id → users` FK; grant each role its schema.
- `0003` workspaces: organizations + memberships + invitations, backfill personal workspaces, `uptime.monitors.org_id`.
- `0004` ✅ `core.org_apps` + `core.usage_counters` (no backfill: no row = Free).
- `0005` ✅ `core.jobs`, `core.schedules`, `core.audit_events`, `core.outbox`, `uptime.outbox`.
- `0006` ✅ `core.notification_prefs`.
- `0007` cloud tables when the first AWS module lands.

The container runs `migrate.py` (see §2.1) before start; take a `pg_dump` before each migration deploy. ✅ `0001`–`0003` are deployed; `create_all` is no longer used. Models use the index naming convention `ix_<table>_<column>` (no schema prefix) so autogenerate matches the migrations.

---

## 10. API conventions

| Area | Routes |
|---|---|
| Auth ✅ | `GET /api/auth/login`, `/callback`, `/logout`, `/me` |
| Platform admin ✅ | `/api/admin/me`, `/analytics`, `/users`, `PUT /users/{id}` (is_admin), `POST /logout`, `GET /orgs` (seats used, owners, module tiers; 🚧 + per-limit Free/Pro defaults and overrides), `PUT /orgs/{id}` (`member_limit` 1–1000, `null` = default), `PUT /orgs/{id}/modules/{app}` (`tier`, `pro_until`, `limits`), `GET /activity` · 🚧 `GET /system` (health; `status` ok/warning + `warnings`), `GET /jobs` (`?status=&type=&org_id=`), `POST /jobs/{id}/retry` (failed/cancelled → queued, attempt 1), `POST /jobs/{id}/cancel` (queued only, race-safe) |
| Uptime ✅ | `GET/POST /api/orgs/{org}/uptime/monitors`, `PATCH/DELETE …/monitors/{id}`, `POST …/{id}/check`, `GET …/{id}/checks` (read: `uptime.read`, write: `uptime.write`) |
| Workspaces ✅ | `GET/POST /api/orgs`, `GET/PATCH/DELETE /api/orgs/{org}` (name, currency), `POST /api/orgs/{org}/select` (remember last workspace) · 🚧 `GET /api/orgs/{org}/modules` (tier, limits, usage, features per module; also included in `GET /api/orgs/{org}`); uptime list adds `tier`, `locked_intervals`, `history_days` |
| Team ✅ | `GET /api/orgs/{org}/members` (`members.read`) · `PATCH/DELETE /api/orgs/{org}/members/{user}` (`members.manage`; owner role needs `org.transfer`; DELETE on yourself = leave) · `GET/POST /api/orgs/{org}/invitations`, `DELETE …/invitations/{id}` (`members.manage`) · `GET /api/invitations/preview?token=` (no sign-in) · `POST /api/invitations/accept` |
| Platform | ✅ `GET /api/orgs/{org}/jobs/{id}` (`org.read`), `GET /api/orgs/{org}/activity` (`audit.view`: owners/admins), `GET /api/admin/activity` (`?org_id=`), `GET /api/orgs/{org}/uptime/summary` (counts by status) · ✅ `GET/PUT /api/orgs/{org}/notifications` (the caller's own alert settings, any role; PUT `{"events": {"uptime.recovered": false}}`) · 🔜 `/reports[/{id}/download]`, `/connections[/{id}]` |
| Modules 🔜 | `/api/orgs/{org}/{app_key}/…` |

Errors: 401 not signed in · 403 role/module · 404 not found or not a member · 402 over limit · 422 validation · 429 rate limited.

---

## 11. Frontend

| Route | Purpose | Status |
|---|---|---|
| `/portal` | Sign-in only; signed-in users are sent to `/portal/{last_org_id}` (`#alerts` → `/alerts`) | ✅ |
| `/admin` | Platform admin: analytics, users + admin toggle, contacts, Workspaces with seat-limit override and Free/Pro switch per module ✅; 🚧 health banner + System health card, Jobs (filter, Retry, Cancel), Platform activity, Edit plan dialog (tier, Pro until, limit overrides) | ✅ |
| `/portal/{org}` | **Shell** (`layouts/PortalLayout.astro` + `lib/shell.ts` `bootPortal()`): top bar (workspace switcher that keeps the current section, role, New workspace / Leave, account, Platform admin, Sign out) and sidebar (Overview, every catalog module with Free/Pro/Soon badge, Email alerts, Settings & team for owners/admins). **Overview**: one tile per module from its summary API (Uptime: monitors of limit, down/up/paused), team & seats, your alerts, last 5 activity entries (owners/admins) | ✅ |
| `/portal/{org}/uptime` · `/portal/{org}/{review,cost,security,iac}` | Uptime dashboard (moved from `/portal`) · coming-soon pages with each module's planned limits (`[module].astro`; built modules get their own page, which Astro prefers) | ✅ |
| `/portal/{org}/alerts` | The caller's email alert switches for this workspace (any role) | ✅ |
| `/portal/{org}/settings` | Workspace admin for owners/admins (moved from `/portal/workspace`): general, plan, team & invitations, activity (`#activity`), danger zone; others see a notice | ✅ |
| `/portal/[org]/connections` | AWS accounts | 🔜 |
| `/portal/workspace?org=` | 301 redirect to `/portal/{org}/settings` (old address) | ✅ |
| `/portal/{org}/reports` · `/connections` | Generated files · AWS accounts | 🔜 |
| `/portal/invite` | Accept invitation (preview before sign-in, token kept in sessionStorage) | ✅ |

The sidebar is built from `GET /api/orgs/{org}` (`role`, modules with tier/limits/usage), so new modules appear without layout changes; a module page just calls `const ctx = await bootPortal()` and uses `ctx.api`, `ctx.orgApi()`, `ctx.workspace.role`. A workspace the user is not in shows "Workspace not found"; signed-out visitors go to `/portal`. Free modules show usage and an "Upgrade to Pro" hint; actions are hidden by role but always enforced server-side.

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
| 2 | Catalog, Free/Pro per module, `org_apps`, limits & usage, isolation test (every `/api/orgs/{org_id}/…` route returns 404 to non-members, enumerated from OpenAPI) | ✅ |
| 3 | `core/` + `apps/` layout, engine per module role, worker container, job queue, outbox per schema + relay, uptime moved, notify, audit, module summary APIs | ✅ |
| 4 | Team: invitations, roles, member caps, `/portal/invite`, `/portal/workspace` (✅ deployed early); alert preferences + per-recipient email jobs | ✅ |
| 5 | Portal: `/portal/{org}` shell with workspace switcher and module sidebar, Overview, Uptime, Alerts, Settings & team, coming-soon module pages | ✅ |
| 6 | Admin: workspaces and Pro per module (✅ earlier); system health, jobs (retry/cancel), platform activity, plan overrides editor (🚧) | 🚧 |
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
| 2026-10-14 | Deployed: PR #7 phase 5 portal. |
| 2026-10-14 | Timestamps shown as dates (`pro_until`) are returned in UTC regardless of the database session's time zone. |
| 2026-10-14 | Deployed: PR #6 phase 4 alert preferences. |
| 2026-10-14 | Portal URLs carry the workspace: `/portal/{org}/{section}`; `/portal` only signs in and redirects. Old `/portal/workspace?org=` and `/portal#alerts` links keep working via redirects. |
| 2026-10-14 | Deployed: PR #5 phase 3 (worker container, jobs, outbox, audit). |
| 2026-10-14 | Alert preferences are per member and per workspace, managed by each member in `/portal` (any role); no row = on. Alerts fan out to one email job per recipient so retries never duplicate other members' emails. |
| 2026-10-14 | Deployed: PR #4 phase 2 tiers. |
| 2026-10-14 | Phase 3 layout: `core/` (platform), `apps/<module>/` (one package per module, registered in `apps.MODULES`), `website/` (marketing; not `site/`, which shadows a Python module). |
| 2026-10-14 | Alerts and workspace cleanup go through the outbox + job queue (at-least-once, deduplicated per event and handler); the uptime loop moves to the worker and elects one leader with an advisory lock. |
| 2026-10-14 | Tiers: no `org_apps` row means Free (no backfill); Pro set by hand per module in `/admin`; expired `pro_until` falls back to Free. |
| 2026-10-14 | Free Uptime keeps 7 days of check history (was 30 before tiers); Pro keeps 90. Monitors above a limit after a downgrade are kept, new ones blocked. |
| 2026-10-14 | Deployed: PR #3 admin seat limits and invite-link fallback. |
| 2026-10-13 | Database prepared for microservices: Postgres schema + role per module, no cross-schema foreign keys, access checks only via `org_access()`, transactional outbox per schema, cross-module screens via summary APIs, workspace deletion as an `org.deleted` event. |
