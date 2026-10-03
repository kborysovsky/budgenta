"""FastAPI composition root: middleware, lifecycle, routers, and Vue assets."""
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from backend.services import budget as service
from backend.web.auth import serializer
from backend.core.config import validate_config
from backend.web.security import SecurityMiddleware
from backend.persistence.database import engine
from backend.persistence.migrations import migrate
from backend.web.routes import system, auth, accounts, transactions, planning, savings, reports, budget_limits

@asynccontextmanager
async def lifespan(app):
    validate_config()
    serializer()
    migrate(engine)
    yield

app = FastAPI(title="Budgenta · personal budget", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

app.add_middleware(SecurityMiddleware)

@app.exception_handler(service.BudgetError)
async def budget_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


for routes in (system, auth, accounts, transactions, planning, savings, reports, budget_limits):
    app.include_router(routes.router)

static = Path(os.getenv("STATIC_DIR", str(Path(__file__).resolve().parents[2] / "frontend" / "dist")))
if static.exists():
    app.mount("/", StaticFiles(directory=static, html=True), name="frontend")
