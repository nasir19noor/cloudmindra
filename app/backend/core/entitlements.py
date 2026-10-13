"""Tiers, limits and usage per workspace and module (DESIGN.md §5).

Modules ask here — never read core.org_apps themselves (DESIGN.md §6 rule 7):
    limit(db, org_id, "uptime.monitors")          effective numeric limit
    require_below(db, org_id, "uptime.monitors", current)   402 when at the limit
    consume(db, org_id, "review.per_month")       atomic monthly counter, 402 when used up
Modules report live usage through USAGE_PROVIDERS so core never queries module tables.
"""
from datetime import datetime, timezone
from typing import Callable

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.catalog import APPS, FEATURES, FREE_WORKSPACES_PER_USER, LABELS, LIMITS, WORKSPACE_SEATS
from core import models as db_models
PRO_STATUSES = ("active", "trial")

# app_key -> fn(db, org_id) -> {metric: current usage}; registered by each module
USAGE_PROVIDERS: dict[str, Callable[[Session, str], dict[str, int]]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def current_period(now: datetime | None = None) -> str:
    return (now or _now()).strftime("%Y-%m")


def _row(db: Session, org_id: str, app_key: str) -> db_models.OrgApp | None:
    return db.get(db_models.OrgApp, (org_id, app_key))


def row_is_pro(row: db_models.OrgApp | None) -> bool:
    if row is None or row.tier != "pro" or row.status not in PRO_STATUSES:
        return False
    return row.pro_until is None or _aware(row.pro_until) > _now()


def tier(db: Session, org_id: str, app_key: str) -> str:
    return "pro" if row_is_pro(_row(db, org_id, app_key)) else "free"


def limits(db: Session, org_id: str, app_key: str) -> dict[str, int]:
    row = _row(db, org_id, app_key)
    effective = dict(LIMITS[app_key]["pro" if row_is_pro(row) else "free"])
    if row is not None and row.limits:
        effective.update({k: int(v) for k, v in row.limits.items() if k in effective})
    return effective


def limit(db: Session, org_id: str, key: str) -> int:
    return limits(db, org_id, key.split(".", 1)[0])[key]


def upgrade_hint(app_key: str) -> str:
    return f"Contact CloudMindra to upgrade {APPS[app_key]['name']} to Pro."


def over_limit(key: str, value: int) -> HTTPException:
    app_key = key.split(".", 1)[0]
    return HTTPException(
        status_code=402,
        detail=f"This workspace's {tier_label_for(key)} limit is {value} {LABELS.get(key, key)}. {upgrade_hint(app_key)}",
    )


def tier_label_for(key: str) -> str:
    return APPS[key.split(".", 1)[0]]["name"]


def require_below(db: Session, org_id: str, key: str, current: int) -> None:
    value = limit(db, org_id, key)
    if current >= value:
        raise over_limit(key, value)


def consume(db: Session, org_id: str, metric: str, amount: int = 1) -> int:
    """Count one use of a monthly metric, refusing (402) when it would pass the limit.
    Atomic: the check and the increment are one statement, so concurrent requests cannot overshoot.
    Runs in the caller's transaction; returns the new count."""
    value = limit(db, org_id, metric)
    if amount > value:
        raise over_limit(metric, value)
    new = db.execute(
        text("""
            INSERT INTO core.usage_counters (org_id, metric, period, count)
            VALUES (:org, :metric, :period, :amount)
            ON CONFLICT (org_id, metric, period) DO UPDATE
              SET count = core.usage_counters.count + :amount
              WHERE core.usage_counters.count + :amount <= :limit
            RETURNING count
        """),
        {"org": org_id, "metric": metric, "period": current_period(), "amount": amount, "limit": value},
        bind_arguments={"mapper": db_models.UsageCounter},
    ).scalar()
    if new is None:
        raise over_limit(metric, value)
    return new


def monthly_usage(db: Session, org_id: str) -> dict[str, int]:
    rows = db.query(db_models.UsageCounter).filter(
        db_models.UsageCounter.org_id == org_id, db_models.UsageCounter.period == current_period()
    )
    return {r.metric: r.count for r in rows}


# --- Workspace-level rules that depend on tiers ------------------------------------------

def pro_apps(db: Session, org_id: str) -> list[str]:
    rows = db.query(db_models.OrgApp).filter(db_models.OrgApp.org_id == org_id, db_models.OrgApp.tier == "pro")
    return [r.app_key for r in rows if row_is_pro(r)]


def pro_org_ids(db: Session, app_key: str) -> set[str]:
    rows = db.query(db_models.OrgApp).filter(db_models.OrgApp.app_key == app_key, db_models.OrgApp.tier == "pro")
    return {r.org_id for r in rows if row_is_pro(r)}


def seat_limit(db: Session, org: db_models.Organization) -> int:
    """Members + pending invitations: admin override, else 10 with any Pro module, else 3."""
    if org.member_limit:
        return org.member_limit
    return WORKSPACE_SEATS["pro" if pro_apps(db, org.id) else "free"]


def owned_free_workspace_count(db: Session, user_id: str) -> int:
    owned = [m.org_id for m in db.query(db_models.Membership).filter(
        db_models.Membership.user_id == user_id, db_models.Membership.role == "owner")]
    return sum(1 for org_id in owned if not pro_apps(db, org_id))


def free_workspace_limit() -> int:
    return FREE_WORKSPACES_PER_USER


# --- Overview for the portal and admin -------------------------------------------------

def modules_overview(db: Session, org_id: str) -> list[dict]:
    rows = {r.app_key: r for r in db.query(db_models.OrgApp).filter(db_models.OrgApp.org_id == org_id)}
    monthly = monthly_usage(db, org_id)
    out = []
    for key, app in APPS.items():
        row = rows.get(key)
        t = "pro" if row_is_pro(row) else "free"
        lim = limits(db, org_id, key)
        usage = dict(USAGE_PROVIDERS[key](db, org_id)) if key in USAGE_PROVIDERS else {}
        usage.update({m: monthly.get(m, 0) for m in lim if m.endswith("per_month")})
        out.append({
            "key": key,
            "name": app["name"],
            "available": app["available"],
            "tier": t,
            "status": row.status if row else "active",
            "pro_until": _aware(row.pro_until).isoformat() if row and row.pro_until else None,
            "limits": lim,
            "overrides": (row.limits or {}) if row else {},
            "usage": usage,
            "features": FEATURES[key][t],
            "labels": {k: LABELS.get(k, k) for k in lim},
        })
    return out
