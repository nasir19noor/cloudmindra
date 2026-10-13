"""Platform catalog (DESIGN.md §4.2, §5): roles, modules, tiers and limits.

Changing a limit here changes it for every workspace on that tier at the next deploy.
Per-workspace exceptions live in core.org_apps.limits (set by a platform admin).
"""

ROLES = ("viewer", "member", "admin", "owner")  # lowest → highest

# Actions are "<area>.<verb>". Patterns: "*" everything, "*.read" any read,
# "<area>.*" any verb in an area, "-<action>" explicit deny (wins over grants).
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "viewer": {"*.read"},
    "member": {"*.read", "uptime.write", "review.run", "iac.run", "security.run"},
    "admin": {"*", "-org.delete", "-org.transfer"},
    "owner": {"*"},
}


def has_permission(role: str, action: str) -> bool:
    perms = ROLE_PERMISSIONS.get(role, set())
    if f"-{action}" in perms:
        return False
    area, _, verb = action.partition(".")
    return bool({"*", action, f"*.{verb}", f"{area}.*"} & perms)


# --- Modules -------------------------------------------------------------------------

TIERS = ("free", "pro")

# available=False: listed in the portal as "coming soon", not usable yet
APPS: dict[str, dict] = {
    "uptime": {"name": "Uptime Monitor", "available": True},
    "review": {"name": "Architecture Review", "available": False},
    "cost": {"name": "Cost Analyzer", "available": False},
    "security": {"name": "Security Scan", "available": False},
    "iac": {"name": "IaC Generator", "available": False},
}

# Numeric limits per module and tier. Keys are "<app>.<metric>".
# "*.per_month" metrics are counted in core.usage_counters; others are counted live.
LIMITS: dict[str, dict[str, dict[str, int]]] = {
    "uptime": {
        "free": {"uptime.monitors": 10, "uptime.min_interval": 5, "uptime.history_days": 7},
        "pro": {"uptime.monitors": 100, "uptime.min_interval": 1, "uptime.history_days": 90},
    },
    "review": {
        "free": {"review.per_month": 1},
        "pro": {"review.per_month": 30},
    },
    "cost": {
        "free": {"cost.connections": 1, "cost.history_months": 3},
        "pro": {"cost.connections": 10, "cost.history_months": 13},
    },
    "security": {
        "free": {"security.connections": 1, "security.scans_per_month": 1},
        "pro": {"security.connections": 10, "security.scans_per_month": 31},
    },
    "iac": {
        "free": {"iac.per_month": 2},
        "pro": {"iac.per_month": 50},
    },
}

# Non-numeric differences, shown in the portal next to the limits
FEATURES: dict[str, dict[str, list[str]]] = {
    "uptime": {"free": ["Email alerts", "SSL expiry warnings"], "pro": ["Email alerts", "SSL expiry warnings", "1-minute checks"]},
    "review": {"free": ["Web report"], "pro": ["Web report", "PDF export"]},
    "cost": {"free": ["Monthly figures"], "pro": ["Daily figures", "Anomaly alerts"]},
    "security": {"free": ["Summary"], "pro": ["Full findings", "Daily scheduled scans", "PDF + SOC2/ISO mapping"]},
    "iac": {"free": ["Single environment"], "pro": ["Multi-environment templates"]},
}

# Seats (members + pending invitations) per workspace: Pro on any module unlocks the larger team
WORKSPACE_SEATS = {"free": 3, "pro": 10}

# Workspaces a user may own that have no Pro module (DESIGN.md §4.1)
FREE_WORKSPACES_PER_USER = 2

# Email alerts a member can switch on/off per workspace (core.notification_prefs; no row = on)
NOTIFICATION_EVENTS: dict[str, dict[str, str]] = {
    "uptime.down": {"app": "uptime", "label": "A monitor goes down"},
    "uptime.recovered": {"app": "uptime", "label": "A monitor is back up"},
    "uptime.ssl_expiring": {"app": "uptime", "label": "An SSL certificate expires within 14 days"},
}

LABELS = {
    "uptime.monitors": "monitors",
    "uptime.min_interval": "minutes between checks (minimum)",
    "uptime.history_days": "days of check history",
    "review.per_month": "reviews per month",
    "cost.connections": "AWS accounts",
    "cost.history_months": "months of cost history",
    "security.connections": "AWS accounts",
    "security.scans_per_month": "scans per month",
    "iac.per_month": "generations per month",
}
