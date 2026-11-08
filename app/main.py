from __future__ import annotations

import hmac
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.errors import (
    ApprovalRequired,
    Conflict,
    FactoryError,
    MediaToolUnavailable,
    NotFound,
    PolicyError,
    RightsError,
    ValidationProblem,
)
from app.media import media_tools
from app.realtime import stream_dashboard
from app.routes import router
from app.seed import seed_defaults
from app.storage import store


def _error(status_code: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail, "code": code})


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_seed:
        seed_defaults(store)
    yield


app = FastAPI(
    title="GTA 6 Shorts Factory",
    version=settings.app_version,
    description=(
        "Local-first Founder Control Tower for rights-cleared short-form video production. "
        "External providers, CUA, and live publishing are disabled by default."
    ),
    lifespan=lifespan,
)
app.include_router(router)

STATIC_DIR = Path(__file__).parent / "static"
app.mount(
    "/static",
    StaticFiles(directory=str(STATIC_DIR), check_dir=False),
    name="static",
)

if settings.auto_seed:
    seed_defaults(store)


# ------------------------------------------------------------------ middleware
@app.middleware("http")
async def founder_guard(request: Request, call_next):
    path = request.url.path
    if settings.founder_token and path.startswith("/api"):
        supplied = request.headers.get("x-founder-token", "")
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            supplied = authorization[7:]
        if request.method != "OPTIONS" and not hmac.compare_digest(
            supplied, settings.founder_token
        ):
            return _error(401, "unauthorized", "a valid founder token is required")
    if (
        store.is_emergency_stopped()
        and path.startswith("/api")
        and request.method not in {"GET", "HEAD", "OPTIONS"}
    ):
        allowed = (
            "/api/system",
            "/api/approvals",
            "/api/cua/emergency-stop",
        )
        if not path.startswith(allowed):
            return _error(
                423,
                "emergency_stop",
                "emergency stop is active; resume operations before making changes",
            )
    return await call_next(request)


# --------------------------------------------------------------- error mapping
@app.exception_handler(NotFound)
async def not_found_handler(_: Request, error: NotFound) -> JSONResponse:
    return _error(404, "not_found", str(error))


@app.exception_handler(ApprovalRequired)
async def approval_handler(_: Request, error: ApprovalRequired) -> JSONResponse:
    return _error(403, "approval_required", str(error))


@app.exception_handler(MediaToolUnavailable)
async def media_tool_handler(_: Request, error: MediaToolUnavailable) -> JSONResponse:
    return _error(503, "media_tool_unavailable", str(error))


@app.exception_handler(PolicyError)
async def policy_handler(_: Request, error: PolicyError) -> JSONResponse:
    return _error(403, "policy_blocked", str(error))


@app.exception_handler(RightsError)
async def rights_handler(_: Request, error: RightsError) -> JSONResponse:
    return _error(403, "rights_blocked", str(error))


@app.exception_handler(Conflict)
async def conflict_handler(_: Request, error: Conflict) -> JSONResponse:
    return _error(409, "conflict", str(error))


@app.exception_handler(ValidationProblem)
async def validation_handler(_: Request, error: ValidationProblem) -> JSONResponse:
    return _error(400, "validation_error", str(error))


@app.exception_handler(ValueError)
async def value_handler(_: Request, error: ValueError) -> JSONResponse:
    return _error(400, "invalid_request", str(error))


@app.exception_handler(FileNotFoundError)
async def file_handler(_: Request, error: FileNotFoundError) -> JSONResponse:
    return _error(404, "not_found", str(error))


@app.exception_handler(PermissionError)
async def permission_handler(_: Request, error: PermissionError) -> JSONResponse:
    return _error(403, "permission_denied", str(error))


@app.exception_handler(sqlite3.IntegrityError)
async def integrity_handler(_: Request, error: sqlite3.IntegrityError) -> JSONResponse:
    return _error(409, "conflict", str(error))


@app.exception_handler(FactoryError)
async def factory_handler(_: Request, error: FactoryError) -> JSONResponse:
    return _error(400, "factory_error", str(error))


# ----------------------------------------------------------------------- routes
@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/detail", tags=["system"])
def health_detail() -> dict:
    return {
        "status": "ok",
        "version": settings.app_version,
        "database_integrity": store.integrity_check(),
        "emergency_stop": store.is_emergency_stopped(),
        "media_tools": media_tools(),
        "flags": {
            "local_processing": settings.local_processing_enabled,
            "everygen": settings.everygen_enabled,
            "cua": settings.cua_enabled,
            "publishing": settings.publishing_enabled,
            "publishing_dry_run": settings.publishing_dry_run,
        },
    }


@app.get("/", include_in_schema=False)
def founder_control_tower() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.svg", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.websocket("/ws/dashboard")
async def dashboard_updates(websocket: WebSocket) -> None:
    await stream_dashboard(websocket)
