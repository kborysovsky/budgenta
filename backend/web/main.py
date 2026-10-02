"""FastAPI composition root: middleware, lifecycle, routers, and Vue assets."""
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from backend.services import budget as service
from backend.web.auth import serializer
from backend.persistence.database import engine
from backend.persistence.migrations import migrate
from backend.web.routes import system, auth, accounts, transactions, planning, savings, reports

@asynccontextmanager
async def lifespan(app):
    serializer()
    migrate(engine)
    yield

app = FastAPI(title="Budgenta · personal budget", lifespan=lifespan)

@app.middleware("http")
async def protect_origin(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if request.headers.get("origin") != os.getenv("APP_ORIGIN", "http://localhost:8000"):
            return JSONResponse({"detail": "Request origin is not allowed."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response

@app.exception_handler(service.BudgetError)
async def budget_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


for routes in (system, auth, accounts, transactions, planning, savings, reports):
    app.include_router(routes.router)

static = Path(os.getenv("STATIC_DIR", str(Path(__file__).resolve().parents[2] / "frontend" / "dist")))
if static.exists():
    app.mount("/", StaticFiles(directory=static, html=True), name="frontend")
