"""Modules (DESIGN.md §6). Each module package exposes APP_KEY, `router` and optionally
`worker_loop`, and registers its event handlers / usage provider when imported.

Rules: a module owns its own schema, never reads another module's tables, and reaches
the platform only through core/. Adding a module = a package here + an entry below.
"""
from apps import uptime

MODULES = {uptime.APP_KEY: uptime}
