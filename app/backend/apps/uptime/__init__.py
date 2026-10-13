"""Uptime Monitor module (DESIGN.md §1, §6).

Owns schema `uptime`; talks to the platform only through core/ (access, tiers, outbox,
notify, audit). Importing the package registers its handlers and usage provider.
"""
from apps.uptime import handlers  # noqa: F401  (registers event handlers + usage provider)
from apps.uptime.router import router
from apps.uptime.service import worker as worker_loop

APP_KEY = "uptime"

__all__ = ["APP_KEY", "router", "worker_loop"]
