from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from config import validate_config, ML_ENABLED
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Preload the trained PARIKSHAN ML artifacts once at startup.

    Loading 8 .joblib models (~240MB) per request is unacceptable; this keeps
    them resident for the lifetime of the process. If any artifact is missing
    or fails to deserialize the registry reports `unavailable` and the app
    continues on the deterministic engine - ML is an additive signal, not a
    hard dependency.
    """
    try:
        from services.ml_prediction_service import install_ml_service

        service = install_ml_service(enabled=ML_ENABLED)
    except Exception as exc:  # noqa: BLE001 - missing ML deps must never block startup
        print(f"PARIKSHAN ML UNAVAILABLE error={type(exc).__name__}: {exc}")
        service = None
    app.state.ml_service = service
    if service is not None:
        status = service.status()
        print(
            f"PARIKSHAN ML {'AVAILABLE' if status['available'] else 'UNAVAILABLE'} "
            f"version={status['model_version']} error={status['error']}"
        )
    yield


app = FastAPI(
    title="Sankalp API",
    description="AI-Powered Infrastructure Risk Intelligence Platform",
    version="0.2.0",
    lifespan=lifespan,
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
    return {"status": "ok", "service": "sankalp-api"}
