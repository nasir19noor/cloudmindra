"""HTTP API (DESIGN.md §2.2). Background work runs in the worker container (worker.py)."""
import os
from datetime import datetime

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps import MODULES
from core.database import init_db
from core.routers import admin, auth, orgs, team
from website.routers import analytics, blog, contact, services

app = FastAPI(
    title="CloudMindra API",
    description="CloudMindra Company Profile API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "https://cloudmindra.com").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/")
async def root():
    return {"message": "CloudMindra API", "version": "1.0.0"}


@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


# Marketing website
for website_router in (contact, services, blog, analytics):
    app.include_router(website_router.router)

# Platform (core)
for core_router in (admin, auth, orgs, team):
    app.include_router(core_router.router)

# Modules
for module in MODULES.values():
    app.include_router(module.router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=11001)
