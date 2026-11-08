from __future__ import annotations

import html
import mimetypes
import threading
import uuid
from pathlib import Path
from urllib.parse import quote
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from app.analytics import AnalyticsService
from app.collaboration import CollaborationService
from app.config import settings
from app.cua import CUABroker
from app.errors import Conflict, NotFound, ValidationProblem
from app.integrations import EverygenAdapter, MCPRegistry
from app.media import MediaPipeline, media_tools
from app.orchestrator import CEOOrchestrator
from app.publishing import PublishingService
from app.services import FactoryService
from app.storage import store
from pipeline.config import load_settings as load_pipeline_settings
from pipeline.cua_sandbox import CuaSandbox
from pipeline.db import PipelineDB

router = APIRouter(prefix="/api")

service = FactoryService(store)
media = MediaPipeline(store)
ceo = CEOOrchestrator(store, service)
everygen = EverygenAdapter(store, service)
mcp = MCPRegistry(store)
cua = CUABroker(store, service)
publishing = PublishingService(store, service)
analytics = AnalyticsService(store, service)
collaboration = CollaborationService(store, service)


# --------------------------------------------------------------------- payloads
class ApprovalRequest(BaseModel):
    type: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    reason: str | None = None
    subject_type: str | None = None


class DecisionRequest(BaseModel):
    status: str
    note: str | None = None


class BusinessRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    brand_rules: dict[str, Any] = Field(default_factory=dict)


class TaskRequest(BaseModel):
    title: str = Field(min_length=1)
    department: str = Field(min_length=1)
    worker: str | None = None
    initiative_id: str | None = None
    type: str = "general"
    priority: int = Field(default=3, ge=1, le=5)
    input_ref: str | None = None


class TaskUpdateRequest(BaseModel):
    title: str | None = None
    department: str | None = None
    worker: str | None = None
    status: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)


class WorkerUpdateRequest(BaseModel):
    status: str


class DepartmentPauseRequest(BaseModel):
    paused: bool = True


class RightsRequest(BaseModel):
    source_asset_id: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    license_type: str = Field(min_length=1)
    commercial_use: bool = False
    proof_uri: str | None = None
    platforms: list[str] = Field(default_factory=list)
    attribution: str | None = None
    takedown_contact: str | None = None
    expires_at: str | None = None
    notes: str | None = None


class IngestRequest(BaseModel):
    path: str = Field(min_length=1)
    rights_id: str | None = None
    owner: str = "founder"
    source_url: str | None = None


class TranscriptRequest(BaseModel):
    text: str | None = None
    segments: list[dict[str, Any]] | None = None
    language: str = "en"


class VariantsRequest(BaseModel):
    styles: list[str] | None = None
    force: bool = False


class RenderRequest(BaseModel):
    force: bool = False


class ProviderQuoteRequest(BaseModel):
    request: dict[str, Any]


class ProviderJobRequest(BaseModel):
    quote_id: str = Field(min_length=1)
    approval_id: str | None = None


class MCPServerRequest(BaseModel):
    name: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)
    transport: str = "stdio"
    scopes: list[str] = Field(default_factory=list)


class MCPToolRequest(BaseModel):
    server_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    risk: str = "low"


class MCPCallRequest(BaseModel):
    server_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    approval_id: str | None = None


class CUARequest(BaseModel):
    target: str = Field(min_length=1)
    mode: str = "observe"
    approval_id: str | None = None
    worker_id: str | None = None


class CUAActionRequest(BaseModel):
    action_type: str = Field(min_length=1)
    token: str = Field(min_length=1)
    target: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)


class PublishingAccountRequest(BaseModel):
    platform: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    credential_ref: str | None = None


class PublishingAccountUpdate(BaseModel):
    status: str


class PublishingJobRequest(BaseModel):
    video_variant_id: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    account_id: str | None = None
    schedule_at: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class SnapshotRequest(BaseModel):
    platform_post_id: str = Field(min_length=1)
    views: int = Field(default=0, ge=0)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    shares: int = Field(default=0, ge=0)
    follows: int = Field(default=0, ge=0)
    retention: float | None = Field(default=None, ge=0, le=100)
    watch_time: float | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    captured_at: str | None = None


class CostRequest(BaseModel):
    provider: str = Field(min_length=1)
    category: str = Field(min_length=1)
    amount: float = Field(ge=0)
    currency: str = "USD"
    task_id: str | None = None
    job_id: str | None = None
    note: str | None = None


class CEOInstructionRequest(BaseModel):
    objective: str = Field(min_length=3)
    risk_level: str | None = None


class InitiativeDecisionRequest(BaseModel):
    decision: str


class TickRequest(BaseModel):
    limit: int = Field(default=5, ge=1, le=25)


# ----------------------------------------------------------------------- system
@router.get("/system/status", tags=["system"])
def system_status() -> dict[str, Any]:
    return service.system_status()


@router.get("/system/audit", tags=["system"])
def audit_events(
    limit: int = Query(default=100, ge=1, le=500),
    actor: str | None = None,
    action: str | None = None,
) -> list[dict[str, Any]]:
    return service.activity(limit=limit, actor=actor, action=action)


@router.post("/system/emergency-stop", tags=["system"])
def emergency_stop() -> dict[str, Any]:
    status = service.set_emergency_stop(True)
    cua.emergency_stop()
    return status


@router.post("/system/resume", tags=["system"])
def resume_operations() -> dict[str, Any]:
    status = service.set_emergency_stop(False)
    store.set_state("cua_emergency_stop", False)
    return status


@router.post("/system/backup", status_code=201, tags=["system"])
def backup_database() -> dict[str, Any]:
    return service.backup()


@router.get("/system/backups", tags=["system"])
def list_backups() -> list[dict[str, Any]]:
    return service.list_backups()


@router.get("/dashboard/summary", tags=["dashboard"])
def dashboard_summary() -> dict[str, Any]:
    return service.dashboard_summary()


@router.get("/dashboard/activity", tags=["dashboard"])
def dashboard_activity(limit: int = Query(default=20, ge=1, le=200)) -> list[dict[str, Any]]:
    return service.activity(limit)


# -------------------------------------------------------------------- enterprise
@router.get("/businesses", tags=["enterprise"])
def businesses() -> list[dict[str, Any]]:
    return service.list_businesses()


@router.post("/businesses", status_code=201, tags=["enterprise"])
def create_business(payload: BusinessRequest) -> dict[str, Any]:
    return service.create_business(payload.name, payload.brand_rules)


@router.get("/departments", tags=["enterprise"])
def departments(include_workers: bool = True) -> list[dict[str, Any]]:
    return service.list_departments(include_workers=include_workers)


@router.get("/departments/interactions", tags=["enterprise"])
def department_interactions() -> dict[str, Any]:
    return collaboration.interaction_map()


@router.post("/departments/{department_id}/pause", tags=["enterprise"])
def pause_department(department_id: str, payload: DepartmentPauseRequest) -> dict[str, Any]:
    return service.pause_department(department_id, payload.paused)


@router.get("/workers", tags=["enterprise"])
def workers(department: str | None = None) -> list[dict[str, Any]]:
    return service.list_workers(department)


@router.patch("/workers/{worker_id}", tags=["enterprise"])
def update_worker(worker_id: str, payload: WorkerUpdateRequest) -> dict[str, Any]:
    return service.update_worker(worker_id, payload.status)


@router.get("/initiatives", tags=["ceo"])
def initiatives(status: str | None = None) -> list[dict[str, Any]]:
    return ceo.list_initiatives(status)


@router.get("/initiatives/{initiative_id}", tags=["ceo"])
def initiative(initiative_id: str) -> dict[str, Any]:
    return ceo.get_initiative(initiative_id)


@router.post("/initiatives/{initiative_id}/decision", tags=["ceo"])
def decide_initiative(initiative_id: str, payload: InitiativeDecisionRequest) -> dict[str, Any]:
    return ceo.decide_initiative(initiative_id, payload.decision)


@router.post("/ceo/instructions", status_code=201, tags=["ceo"])
def ceo_instruction(payload: CEOInstructionRequest) -> dict[str, Any]:
    return ceo.create_initiative(payload.objective, risk_level=payload.risk_level)


@router.post("/ceo/tick", tags=["ceo"])
def ceo_tick(payload: TickRequest | None = None) -> dict[str, Any]:
    limit = payload.limit if payload else 5
    return ceo.tick(limit)


@router.get("/ceo/report", tags=["ceo"])
def ceo_report() -> dict[str, Any]:
    return service.ceo_report()


@router.get("/tasks", tags=["enterprise"])
def tasks(
    status: str | None = None,
    department: str | None = None,
    initiative_id: str | None = None,
) -> list[dict[str, Any]]:
    return service.list_tasks(status, department, initiative_id)


@router.post("/tasks", status_code=201, tags=["enterprise"])
def create_task(payload: TaskRequest) -> dict[str, Any]:
    return service.create_task(
        payload.title,
        payload.department,
        payload.worker,
        initiative_id=payload.initiative_id,
        task_type=payload.type,
        priority=payload.priority,
        input_ref=payload.input_ref,
    )


@router.get("/tasks/{task_id}", tags=["enterprise"])
def task(task_id: str) -> dict[str, Any]:
    return service.get_task(task_id)


@router.patch("/tasks/{task_id}", tags=["enterprise"])
def update_task(task_id: str, payload: TaskUpdateRequest) -> dict[str, Any]:
    return service.update_task(task_id, payload.model_dump(exclude_none=True))


@router.post("/tasks/{task_id}/run", tags=["enterprise"])
def run_task(task_id: str) -> dict[str, Any]:
    return ceo.run_task(task_id)


@router.post("/tasks/{task_id}/retry", tags=["enterprise"])
def retry_task(task_id: str) -> dict[str, Any]:
    return ceo.retry_task(task_id)


@router.post("/tasks/{task_id}/cancel", tags=["enterprise"])
def cancel_task(task_id: str) -> dict[str, Any]:
    return service.cancel_task(task_id)


@router.get("/approvals", tags=["approvals"])
def approvals(status: str | None = None, type: str | None = None) -> list[dict[str, Any]]:
    return service.list_approvals(status, type)


@router.get("/approvals/{approval_id}", tags=["approvals"])
def approval(approval_id: str) -> dict[str, Any]:
    return service.get_approval(approval_id)


@router.post("/approvals", status_code=201, tags=["approvals"])
def create_approval(payload: ApprovalRequest) -> dict[str, Any]:
    return service.create_approval(
        payload.type,
        payload.subject_id,
        subject_type=payload.subject_type,
        reason=payload.reason,
    )


@router.post("/approvals/{approval_id}/decision", tags=["approvals"])
def decide_approval(approval_id: str, payload: DecisionRequest) -> dict[str, Any]:
    return service.decide_approval(approval_id, payload.status, note=payload.note)


# ------------------------------------------------------------------------ media
@router.post("/assets/upload", status_code=201, tags=["media"])
async def upload_asset(
    file: UploadFile = File(...),
    owner: str = Form("founder"),
    rights_id: str | None = Form(None),
    source_url: str | None = Form(None),
) -> dict[str, Any]:
    if not file.filename:
        raise ValidationProblem("uploaded file needs a filename")
    safe_name = Path(file.filename).name
    destination = settings.upload_dir / f"upload-{uuid.uuid4().hex[:10]}-{safe_name}"
    limit = settings.max_upload_mb * 1024 * 1024
    written = 0
    try:
        with destination.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    raise ValidationProblem(
                        f"upload exceeds the {settings.max_upload_mb} MB limit"
                    )
                handle.write(chunk)
    finally:
        await file.close()
    try:
        return media.register_asset(
            destination,
            owner=owner,
            rights_id=rights_id,
            source_url=source_url,
        )
    except Exception:
        destination.unlink(missing_ok=True)
        raise


@router.post("/assets/ingest", status_code=201, tags=["media"])
def ingest_asset(payload: IngestRequest) -> dict[str, Any]:
    return media.register_asset(
        payload.path,
        owner=payload.owner,
        rights_id=payload.rights_id,
        source_url=payload.source_url,
    )


@router.get("/assets", tags=["media"])
def assets(status: str | None = None) -> list[dict[str, Any]]:
    return service.list_assets(status)


@router.get("/assets/{asset_id}", tags=["media"])
def asset(asset_id: str) -> dict[str, Any]:
    return media.get_asset(asset_id)


@router.get("/assets/{asset_id}/file", tags=["media"])
def asset_file(asset_id: str) -> FileResponse:
    row = store.one("SELECT * FROM source_assets WHERE id = ?", (asset_id,), "source_assets")
    if not row:
        raise NotFound("source asset not found")
    path = Path(row.get("path") or "")
    if not path.is_file():
        raise NotFound("source file is missing from local storage")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.post("/assets/{asset_id}/analyze", tags=["media"])
def analyze_asset(asset_id: str, refresh: bool = False) -> dict[str, Any]:
    return media.analyze_asset(asset_id, refresh=refresh)


@router.post("/assets/{asset_id}/transcript", tags=["media"])
def attach_transcript(asset_id: str, payload: TranscriptRequest) -> dict[str, Any]:
    return media.attach_transcript(
        asset_id, payload.text, payload.segments, language=payload.language
    )


@router.get("/assets/{asset_id}/transcript", tags=["media"])
def get_transcript(asset_id: str) -> dict[str, Any]:
    asset = store.one("SELECT * FROM source_assets WHERE id = ?", (asset_id,), "source_assets")
    if not asset:
        raise NotFound("source asset not found")
    media_asset = store.one(
        "SELECT * FROM media_assets WHERE source_asset_id = ? AND kind = 'source' "
        "ORDER BY created_at ASC LIMIT 1",
        (asset_id,),
        "media_assets",
    )
    if not media_asset:
        raise NotFound("source media asset not found")
    transcript = store.one(
        "SELECT * FROM transcripts WHERE media_asset_id = ?",
        (media_asset["id"],),
        "transcripts",
    )
    if not transcript:
        return {
            "status": "missing",
            "message": "No transcript yet. Analyze the asset or attach a manual transcript.",
        }
    return transcript


@router.get("/rights", tags=["rights"])
def rights(status: str | None = None) -> list[dict[str, Any]]:
    return service.list_rights(status)


@router.post("/rights", status_code=201, tags=["rights"])
def create_rights(payload: RightsRequest) -> dict[str, Any]:
    return service.create_rights(
        source_asset_id=payload.source_asset_id,
        owner=payload.owner,
        license_type=payload.license_type,
        commercial_use=payload.commercial_use,
        proof_uri=payload.proof_uri,
        platforms=payload.platforms,
        attribution=payload.attribution,
        takedown_contact=payload.takedown_contact,
        expires_at=payload.expires_at,
        notes=payload.notes,
    )


@router.get("/candidates", tags=["media"])
def candidates(asset_id: str | None = None) -> list[dict[str, Any]]:
    where = "WHERE m.source_asset_id = ?" if asset_id else ""
    params = (asset_id,) if asset_id else ()
    return store.many(
        f"""
        SELECT c.*, m.source_asset_id, s.filename, s.duration AS source_duration
        FROM highlight_candidates c
        JOIN media_assets m ON m.id = c.media_asset_id
        LEFT JOIN source_assets s ON s.id = m.source_asset_id
        {where}
        ORDER BY c.score DESC
        """,
        params,
        "highlight_candidates",
    )


@router.post("/candidates/{candidate_id}/variants", status_code=201, tags=["media"])
def create_variants(candidate_id: str, payload: VariantsRequest) -> list[dict[str, Any]]:
    return media.create_variants(candidate_id, payload.styles, payload.force)


@router.get("/variants", tags=["media"])
def variants(
    candidate_id: str | None = None, status: str | None = None
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if candidate_id:
        clauses.append("v.candidate_id = ?")
        params.append(candidate_id)
    if status:
        clauses.append("v.status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return store.many(
        f"""
        SELECT v.*, c.score, c.hook, c.start_ms, c.end_ms, m.source_asset_id, s.filename
        FROM video_variants v
        JOIN highlight_candidates c ON c.id = v.candidate_id
        JOIN media_assets m ON m.id = c.media_asset_id
        LEFT JOIN source_assets s ON s.id = m.source_asset_id
        {where}
        ORDER BY v.created_at DESC
        """,
        params,
        "video_variants",
    )


@router.get("/variants/{variant_id}", tags=["media"])
def variant(variant_id: str) -> dict[str, Any]:
    return media.get_variant(variant_id)


@router.post("/variants/{variant_id}/render", tags=["media"])
def render_variant(variant_id: str, payload: RenderRequest | None = None) -> dict[str, Any]:
    force = payload.force if payload else False
    return media.render_variant(variant_id, force=force)


@router.post("/variants/{variant_id}/qc", tags=["media"])
def qc_variant(variant_id: str) -> dict[str, Any]:
    return media.qc_variant(variant_id)


@router.post("/variants/{variant_id}/submit-review", tags=["media"])
def submit_review(variant_id: str) -> dict[str, Any]:
    return media.submit_for_review(variant_id)


@router.get("/variants/{variant_id}/file", tags=["media"])
def variant_file(variant_id: str) -> FileResponse:
    row = store.one(
        "SELECT * FROM video_variants WHERE id = ?", (variant_id,), "video_variants"
    )
    if not row:
        raise NotFound("variant not found")
    path = Path(row.get("render_uri") or "")
    if not path.is_file():
        raise NotFound("rendered file is not available")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@router.get("/variants/{variant_id}/captions", tags=["media"])
def variant_captions(variant_id: str) -> FileResponse:
    row = store.one(
        "SELECT * FROM video_variants WHERE id = ?", (variant_id,), "video_variants"
    )
    if not row:
        raise NotFound("variant not found")
    path = Path(row.get("caption_uri") or "")
    if not path.is_file():
        raise NotFound("caption file is not available")
    return FileResponse(
        path, media_type="application/x-subrip", filename=path.name
    )


@router.get("/render-jobs", tags=["media"])
def render_jobs() -> list[dict[str, Any]]:
    return store.many(
        "SELECT * FROM render_jobs ORDER BY created_at DESC", (), "render_jobs"
    )


# -------------------------------------------------------------------- providers
@router.get("/providers", tags=["integrations"])
def providers() -> dict[str, Any]:
    return {
        "everygen": everygen.capabilities(),
        "mcp": {
            "servers": mcp.list_servers(),
            "live_enabled": settings.mcp_live_enabled,
        },
        "cua": {
            "enabled": settings.cua_enabled,
            "allowed_domains": cua.allowed_domains(),
            "max_actions": settings.cua_max_actions,
            "session_minutes": settings.cua_session_minutes,
        },
        "publishing": {
            "enabled": settings.publishing_enabled,
            "dry_run": settings.publishing_dry_run,
            "accounts": publishing.list_accounts(),
        },
        "local": {"media_tools": media_tools()},
    }


@router.get("/providers/everygen/capabilities", tags=["integrations"])
def everygen_capabilities() -> dict[str, Any]:
    return everygen.capabilities()


@router.get("/providers/everygen/quotes", tags=["integrations"])
def everygen_quotes() -> list[dict[str, Any]]:
    return everygen.list_quotes()


@router.post("/providers/everygen/quotes", status_code=201, tags=["integrations"])
def everygen_quote(payload: ProviderQuoteRequest) -> dict[str, Any]:
    return everygen.quote(payload.request)


@router.get("/providers/everygen/jobs", tags=["integrations"])
def everygen_jobs() -> list[dict[str, Any]]:
    return everygen.list_jobs()


@router.post("/providers/everygen/jobs", status_code=202, tags=["integrations"])
def everygen_create_job(payload: ProviderJobRequest) -> dict[str, Any]:
    return everygen.create_job(payload.quote_id, payload.approval_id)


@router.post("/providers/everygen/jobs/{job_id}/poll", tags=["integrations"])
def everygen_poll_job(job_id: str) -> dict[str, Any]:
    return everygen.poll_job(job_id)


@router.post("/providers/everygen/jobs/{job_id}/cancel", tags=["integrations"])
def everygen_cancel_job(job_id: str) -> dict[str, Any]:
    return everygen.cancel_job(job_id)


# -------------------------------------------------------------------------- MCP
@router.get("/mcp/servers", tags=["integrations"])
def mcp_servers() -> list[dict[str, Any]]:
    return mcp.list_servers()


@router.post("/mcp/servers", status_code=201, tags=["integrations"])
def mcp_register_server(payload: MCPServerRequest) -> dict[str, Any]:
    return mcp.register_server(payload.name, payload.endpoint, payload.transport, payload.scopes)


@router.post("/mcp/servers/{server_id}/connect", tags=["integrations"])
def mcp_connect(server_id: str) -> dict[str, Any]:
    return mcp.connect(server_id)


@router.get("/mcp/tools", tags=["integrations"])
def mcp_tools(server_id: str | None = None) -> list[dict[str, Any]]:
    return mcp.list_tools(server_id)


@router.post("/mcp/tools", status_code=201, tags=["integrations"])
def mcp_register_tool(payload: MCPToolRequest) -> dict[str, Any]:
    return mcp.register_tool(
        payload.server_id,
        payload.name,
        payload.description,
        payload.input_schema,
        payload.risk,
    )


@router.get("/mcp/tool-calls", tags=["integrations"])
def mcp_calls() -> list[dict[str, Any]]:
    return mcp.list_calls()


@router.post("/mcp/tool-calls", status_code=201, tags=["integrations"])
def mcp_invoke(payload: MCPCallRequest) -> dict[str, Any]:
    return mcp.invoke(payload.server_id, payload.tool_name, payload.payload, payload.approval_id)


# -------------------------------------------------------------------------- CUA
@router.get("/cua/sessions", tags=["cua"])
def cua_sessions() -> list[dict[str, Any]]:
    return cua.list_sessions()


@router.post("/cua/sessions", status_code=202, tags=["cua"])
def cua_create_session(payload: CUARequest) -> dict[str, Any]:
    return cua.create_session(payload.target, payload.mode, payload.approval_id, payload.worker_id)


@router.get("/cua/sessions/{session_id}", tags=["cua"])
def cua_session(session_id: str) -> dict[str, Any]:
    return cua.get_session(session_id)


@router.post("/cua/sessions/{session_id}/activate", tags=["cua"])
def cua_activate(session_id: str) -> dict[str, Any]:
    return cua.activate_session(session_id)


@router.post("/cua/sessions/{session_id}/actions", status_code=201, tags=["cua"])
def cua_action(session_id: str, payload: CUAActionRequest) -> dict[str, Any]:
    return cua.record_action(
        session_id, payload.action_type, payload.target, payload.result, payload.token
    )


@router.post("/cua/sessions/{session_id}/stop", tags=["cua"])
def cua_stop(session_id: str) -> dict[str, Any]:
    return cua.stop_session(session_id)


@router.get("/cua/actions", tags=["cua"])
def cua_actions(session_id: str | None = None) -> list[dict[str, Any]]:
    return cua.list_actions(session_id)


@router.post("/cua/emergency-stop", tags=["cua"])
def cua_emergency_stop() -> dict[str, Any]:
    return cua.emergency_stop()


# -------------------------------------------------------------------- publishing
@router.get("/publishing/accounts", tags=["publishing"])
def publishing_accounts() -> list[dict[str, Any]]:
    return publishing.list_accounts()


@router.post("/publishing/accounts", status_code=201, tags=["publishing"])
def create_publishing_account(payload: PublishingAccountRequest) -> dict[str, Any]:
    return publishing.create_account(payload.platform, payload.display_name, payload.credential_ref)


@router.patch("/publishing/accounts/{account_id}", tags=["publishing"])
def update_publishing_account(
    account_id: str, payload: PublishingAccountUpdate
) -> dict[str, Any]:
    return publishing.update_account(account_id, payload.status)


@router.get("/publishing/jobs", tags=["publishing"])
def publishing_jobs() -> list[dict[str, Any]]:
    return publishing.list_jobs()


@router.post("/publishing/jobs", status_code=201, tags=["publishing"])
def create_publishing_job(payload: PublishingJobRequest) -> dict[str, Any]:
    return publishing.create_job(
        payload.video_variant_id,
        payload.platform,
        payload.account_id,
        payload.schedule_at,
        payload.payload,
    )


@router.get("/publishing/jobs/{job_id}", tags=["publishing"])
def publishing_job(job_id: str) -> dict[str, Any]:
    return publishing.get_job(job_id)


@router.post("/publishing/jobs/{job_id}/publish", tags=["publishing"])
def publish_job(job_id: str) -> dict[str, Any]:
    return publishing.publish(job_id)


@router.post("/publishing/jobs/{job_id}/reconcile", tags=["publishing"])
def reconcile_job(job_id: str) -> dict[str, Any]:
    return publishing.reconcile(job_id)


@router.get("/publishing/posts", tags=["publishing"])
def publishing_posts() -> list[dict[str, Any]]:
    return publishing.list_posts()


# --------------------------------------------------------------------- analytics
@router.get("/analytics/summary", tags=["analytics"])
def analytics_summary() -> dict[str, Any]:
    return analytics.summary()


@router.get("/analytics/snapshots", tags=["analytics"])
def analytics_snapshots(platform_post_id: str | None = None) -> list[dict[str, Any]]:
    return analytics.list_snapshots(platform_post_id)


@router.post("/analytics/snapshots", status_code=201, tags=["analytics"])
def create_snapshot(payload: SnapshotRequest) -> dict[str, Any]:
    return analytics.record_snapshot(
        payload.platform_post_id,
        views=payload.views,
        likes=payload.likes,
        comments=payload.comments,
        shares=payload.shares,
        follows=payload.follows,
        retention=payload.retention,
        watch_time=payload.watch_time,
        metadata=payload.metadata,
        captured_at=payload.captured_at,
    )


@router.get("/analytics/costs", tags=["analytics"])
def analytics_costs(limit: int = Query(default=100, ge=1, le=1000)) -> list[dict[str, Any]]:
    return analytics.list_costs(limit)


@router.post("/analytics/costs", status_code=201, tags=["analytics"])
def create_cost(payload: CostRequest) -> dict[str, Any]:
    return analytics.record_cost(
        payload.provider,
        payload.category,
        payload.amount,
        currency=payload.currency,
        task_id=payload.task_id,
        job_id=payload.job_id,
        note=payload.note,
    )


@router.get("/reports/daily", tags=["analytics"])
def daily_report() -> dict[str, Any]:
    return analytics.daily_report()


@router.get("/reports/weekly", tags=["analytics"])
def weekly_report() -> dict[str, Any]:
    return analytics.weekly_report()


@router.post("/reports/export", status_code=201, tags=["analytics"])
def export_report() -> dict[str, Any]:
    return analytics.export_report()


# ---------------------------------------------------------------- CUA pipeline
# Read-only visibility for the autonomous Shorts pipeline. Mutating actions
# (cycle/generate/publish) stay in the CLI so a dashboard refresh can never
# accidentally start a paid generation or a live post.
class PipelineClipRequest(BaseModel):
    urls: list[str] = Field(default_factory=list)
    link_ids: list[int] = Field(default_factory=list)
    count: int = Field(default=2, ge=1, le=6)
    start: float | None = None
    end: float | None = None
    rights_ack: bool = False


class PipelinePublishRequest(BaseModel):
    live: bool = False
    confirm: bool = False
    rights_ack: bool = False
    platforms: list[str] = Field(default_factory=list)
    limit: int = Field(default=4, ge=1, le=12)


_pipeline_db_cache: PipelineDB | None = None
_pipeline_db_path_cache: str | None = None
_pipeline_clip_jobs: dict[str, dict[str, Any]] = {}
_pipeline_clip_lock = threading.Lock()
_pipeline_clip_busy = False
_pipeline_publish_busy = False


def _pipeline_database() -> PipelineDB:
    global _pipeline_db_cache, _pipeline_db_path_cache
    pipeline_settings = load_pipeline_settings()
    path = str(pipeline_settings.db_path)
    if _pipeline_db_cache is None or _pipeline_db_path_cache != path:
        _pipeline_db_cache = PipelineDB(path)
        _pipeline_db_path_cache = path
    return _pipeline_db_cache


def _run_pipeline_clip_job(
    run_id: str,
    link_ids: list[int],
    count: int,
    start: float | None,
    end: float | None,
) -> None:
    global _pipeline_clip_busy
    from pipeline.orchestrator import Pipeline

    stats: dict[str, Any] = {
        "requested_links": len(link_ids),
        "clips": 0,
        "ready": 0,
        "failed": 0,
    }
    try:
        pipeline_settings = load_pipeline_settings()
        pipeline_settings.rights_ack = True
        pipeline = Pipeline(pipeline_settings)
        try:
            store.audit(
                "pipeline",
                "clip_job_started",
                run_id,
                {"links": link_ids, "count": count},
            )
        except Exception:
            pass
        with _pipeline_clip_lock:
            job = _pipeline_clip_jobs.get(run_id)
            if job:
                job.update({"status": "running"})
        for index, link_id in enumerate(link_ids, start=1):
            link = pipeline.db.get_link(link_id)
            if not link:
                continue
            result = pipeline.clipper.clip_link(
                link,
                count=count,
                start=start,
                end=end,
                run_id=run_id,
            )
            stats["clips"] += int(result.get("clips") or 0)
            stats["ready"] += int(result.get("ready") or 0)
            stats["failed"] += int(result.get("failed") or 0)
            with _pipeline_clip_lock:
                job = _pipeline_clip_jobs.get(run_id)
                if job:
                    job.update({"status": "running", "done": index, **stats})
        pipeline.db.finish_run(run_id, "completed", stats)
        try:
            store.audit("pipeline", "clip_job_completed", run_id, stats)
        except Exception:
            pass
        with _pipeline_clip_lock:
            job = _pipeline_clip_jobs.get(run_id)
            if job:
                job.update({"status": "completed", **stats})
    except Exception as error:  # noqa: BLE001 - the job must report its failure
        try:
            from pipeline.config import load_settings

            PipelineDB(load_settings().db_path).finish_run(
                run_id, "failed", stats, str(error)
            )
        except Exception:  # pragma: no cover - best effort
            pass
        try:
            store.audit(
                "pipeline",
                "clip_job_failed",
                run_id,
                {"error": str(error)[:800], **stats},
            )
        except Exception:
            pass
        with _pipeline_clip_lock:
            job = _pipeline_clip_jobs.get(run_id)
            if job:
                job.update({"status": "failed", "error": str(error)[:1000], **stats})
    finally:
        with _pipeline_clip_lock:
            _pipeline_clip_busy = False


def _run_pipeline_publish_job(
    run_id: str,
    platforms: list[str],
    limit: int,
    live: bool,
) -> None:
    global _pipeline_publish_busy
    stats: dict[str, Any] = {"live": live, "platforms": platforms}
    try:
        from pipeline.orchestrator import Pipeline

        pipeline_settings = load_pipeline_settings()
        pipeline_settings.live = live
        pipeline = Pipeline(pipeline_settings)
        store.audit(
            "pipeline",
            "publish_job_started",
            run_id,
            {"live": live, "platforms": platforms, "limit": limit},
        )
        with _pipeline_clip_lock:
            job = _pipeline_clip_jobs.get(run_id)
            if job:
                job.update({"status": "running"})
        pipeline.prepare()
        stats.update(
            pipeline.publish(
                limit=limit,
                platforms=platforms or None,
                live=live,
                run_id=run_id,
            )
        )
        pipeline.db.finish_run(run_id, "completed", stats)
        store.audit("pipeline", "publish_job_completed", run_id, stats)
        with _pipeline_clip_lock:
            job = _pipeline_clip_jobs.get(run_id)
            if job:
                job.update({"status": "completed", **stats})
    except Exception as error:  # noqa: BLE001
        try:
            from pipeline.config import load_settings

            PipelineDB(load_settings().db_path).finish_run(
                run_id, "failed", stats, str(error)
            )
        except Exception:
            pass
        store.audit(
            "pipeline",
            "publish_job_failed",
            run_id,
            {"error": str(error)[:800], **stats},
        )
        with _pipeline_clip_lock:
            job = _pipeline_clip_jobs.get(run_id)
            if job:
                job.update(
                    {"status": "failed", "error": str(error)[:1000], **stats}
                )
    finally:
        with _pipeline_clip_lock:
            _pipeline_publish_busy = False


@router.post("/pipeline/publish", status_code=202, tags=["pipeline"])
def pipeline_publish(
    payload: PipelinePublishRequest, background: BackgroundTasks
) -> dict[str, Any]:
    global _pipeline_publish_busy
    if payload.live and not (payload.confirm and payload.rights_ack):
        raise ValidationProblem(
            "confirm the public-publish and rights checkboxes before going live"
        )
    platforms = [
        platform
        for platform in payload.platforms
        if platform in {"youtube", "tiktok"}
    ]
    with _pipeline_clip_lock:
        if _pipeline_publish_busy:
            raise Conflict("another publish job is already running")
        _pipeline_publish_busy = True
        run_id = _pipeline_database().create_run("publish-manual")
        _pipeline_clip_jobs[run_id] = {
            "job_id": run_id,
            "kind": "publish",
            "status": "queued",
            "live": bool(payload.live),
            "platforms": platforms,
            "limit": int(payload.limit),
            "error": None,
        }
    background.add_task(
        _run_pipeline_publish_job,
        run_id,
        platforms,
        int(payload.limit),
        bool(payload.live),
    )
    return {
        "ok": True,
        "job_id": run_id,
        "live": bool(payload.live),
        "platforms": platforms,
        "limit": int(payload.limit),
    }


@router.post("/pipeline/clip", status_code=202, tags=["pipeline"])
def pipeline_clip(
    payload: PipelineClipRequest, background: BackgroundTasks
) -> dict[str, Any]:
    global _pipeline_clip_busy
    if not payload.rights_ack:
        raise ValidationProblem(
            "confirm the rights acknowledgement before clipping third-party sources"
        )
    urls = [url.strip() for url in payload.urls if url.strip()]
    if not urls and not payload.link_ids:
        raise ValidationProblem("provide at least one YouTube URL or link id")
    database = _pipeline_database()
    link_ids = list(payload.link_ids)
    for url in urls:
        link_id, _created = database.add_link(
            {"url": url, "title": url, "query": "dashboard"}
        )
        if link_id not in link_ids:
            link_ids.append(link_id)
    with _pipeline_clip_lock:
        if _pipeline_clip_busy:
            raise Conflict("another clip job is already running")
        _pipeline_clip_busy = True
        run_id = database.create_run("clip-manual")
        _pipeline_clip_jobs[run_id] = {
            "job_id": run_id,
            "status": "queued",
            "total": len(link_ids),
            "done": 0,
            "clips": 0,
            "ready": 0,
            "failed": 0,
            "error": None,
        }
    background.add_task(
        _run_pipeline_clip_job,
        run_id,
        link_ids,
        int(payload.count),
        payload.start,
        payload.end,
    )
    return {
        "ok": True,
        "job_id": run_id,
        "links": link_ids,
        "count": int(payload.count),
    }


@router.get("/pipeline/jobs/{job_id}", tags=["pipeline"])
def pipeline_job(job_id: str) -> dict[str, Any]:
    with _pipeline_clip_lock:
        return _pipeline_clip_jobs.get(
            job_id, {"job_id": job_id, "status": "unknown"}
        )


@router.get("/pipeline/status", tags=["pipeline"])
def pipeline_status() -> dict[str, Any]:
    pipeline_settings = load_pipeline_settings()
    database = _pipeline_database()
    sandbox = CuaSandbox(pipeline_settings)
    return {
        "ok": True,
        "db": database.stats(),
        "sandbox": sandbox.status(),
        "view_url": sandbox.view_url(),
        "settings": {
            "mode": pipeline_settings.mode,
            "cua_enabled": pipeline_settings.cua_enabled,
            "platforms": pipeline_settings.platforms,
            "live_default": pipeline_settings.live,
            "queries": pipeline_settings.queries,
            "variants_per_link": pipeline_settings.variants_per_link,
            "clip_count": pipeline_settings.clip_count,
            "clip_min_seconds": pipeline_settings.clip_min_seconds,
            "clip_max_seconds": pipeline_settings.clip_max_seconds,
            "clip_quality": pipeline_settings.clip_quality,
            "clip_layout": pipeline_settings.clip_layout,
            "clip_show_title": pipeline_settings.clip_show_title,
            "clip_show_captions": pipeline_settings.clip_show_captions,
            "rights_ack": pipeline_settings.rights_ack,
            "max_shorts_per_cycle": pipeline_settings.max_shorts_per_cycle,
            "everygen_format": pipeline_settings.everygen_format,
            "everygen_budget_credits": pipeline_settings.everygen_budget_credits,
            "daily_limit_youtube": pipeline_settings.daily_limit_youtube,
            "daily_limit_tiktok": pipeline_settings.daily_limit_tiktok,
        },
    }


@router.get("/pipeline/links", tags=["pipeline"])
def pipeline_links(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict[str, Any]]:
    return _pipeline_database().links(status=status, limit=limit)


@router.get("/pipeline/generations", tags=["pipeline"])
def pipeline_generations(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict[str, Any]]:
    return _pipeline_database().generations(status=status, limit=limit)


@router.get("/pipeline/posts", tags=["pipeline"])
def pipeline_posts(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict[str, Any]]:
    return _pipeline_database().posts(status=status, limit=limit)


@router.get("/pipeline/runs", tags=["pipeline"])
def pipeline_runs(limit: int = Query(default=20, ge=1, le=200)) -> list[dict[str, Any]]:
    return _pipeline_database().runs(limit=limit)


@router.get("/pipeline/events", tags=["pipeline"])
def pipeline_events(
    run_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    return _pipeline_database().events(limit=limit, run_id=run_id)


@router.get("/pipeline/videos/{filename}", tags=["pipeline"])
def pipeline_video(filename: str) -> FileResponse:
    """Serve a generated clip for the local dashboard preview player."""
    pipeline_settings = load_pipeline_settings()
    root = pipeline_settings.videos_dir.resolve()
    path = (root / filename).resolve()
    if root not in path.parents or not path.is_file():
        raise NotFound("clip not found")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@router.get("/pipeline/showcase", response_class=HTMLResponse, tags=["pipeline"])
def pipeline_showcase() -> HTMLResponse:
    """Tiny local gallery so the owner can watch every rendered clip."""
    pipeline_settings = load_pipeline_settings()
    root = pipeline_settings.videos_dir
    files = sorted(
        (path for path in root.glob("*.mp4") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    cards = "".join(
        f"""
        <article>
          <h2>{html.escape(path.name)}</h2>
          <p>{path.stat().st_size / (1024 * 1024):.1f} MB</p>
          <video controls playsinline preload="metadata"
                 src="/api/pipeline/videos/{quote(path.name)}"></video>
          <a href="/api/pipeline/videos/{quote(path.name)}" download>Download MP4</a>
        </article>"""
        for path in files
    )
    if not cards:
        cards = "<p class='empty'>No clips yet. Run the clipper first.</p>"
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GTA 6 Shorts Factory · Clip Showcase</title>
<style>
 body {{ margin:0; background:#070a10; color:#f2f5ff;
        font-family:Inter,-apple-system,Segoe UI,sans-serif; }}
 header {{ padding:24px 28px; border-bottom:1px solid #1d2638;
           display:flex; justify-content:space-between; align-items:center; }}
 h1 {{ font-size:20px; margin:0; }}
 a {{ color:#5bb8ff; }}
 main {{ padding:24px; display:grid; gap:24px;
         grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); }}
 article {{ background:#0f1522; border:1px solid #1d2638;
            border-radius:16px; padding:14px; }}
 h2 {{ font-size:12px; font-weight:600; overflow-wrap:anywhere; margin:0 0 4px; }}
 p {{ font-size:11px; color:#909bb4; margin:0 0 10px; }}
 video {{ width:100%; border-radius:10px; background:#000; }}
 .empty {{ color:#909bb4; }}
</style></head>
<body>
<header><h1>Clip Showcase</h1><a href="/">Back to dashboard</a></header>
<main>{cards}</main>
</body></html>"""
    )
