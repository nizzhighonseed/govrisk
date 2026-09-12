from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import validate_config
from database import engine, Base
from auth.database import auth_engine, AuthBase
from auth.dependencies import get_current_user
from migration import run_migrations, run_auth_migrations
from routers import projects, alerts, dashboard, analytics, risk_map, assistant, ai
from routers import auth as auth_router
from routers import users as users_router
from routers import admin as admin_router

validate_config()

Base.metadata.create_all(bind=engine)
AuthBase.metadata.create_all(bind=auth_engine)
run_migrations(engine)
run_auth_migrations(auth_engine)

app = FastAPI(
    title="GovRisk API",
    description="AI-Powered Infrastructure Risk Intelligence Platform",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(admin_router.router)
app.include_router(projects.router)
app.include_router(alerts.router)
app.include_router(dashboard.router)
app.include_router(analytics.router)
app.include_router(risk_map.router)
app.include_router(assistant.router)
app.include_router(ai.router)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "govrisk-api"}
