from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import uvicorn
import os

from database import init_db
from routers import contact, services, blog, analytics, admin

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


app.include_router(contact.router)
app.include_router(services.router)
app.include_router(blog.router)
app.include_router(analytics.router)
app.include_router(admin.router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=11001)
