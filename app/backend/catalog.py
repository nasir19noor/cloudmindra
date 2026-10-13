"""Platform catalog (DESIGN.md §4.2, §5). Phase 1 holds role permissions only;
modules, tiers and limits are added in phase 2."""

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
