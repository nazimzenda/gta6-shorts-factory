from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.errors import ApprovalRequired, PolicyError, RightsError
from app.storage import Store

APPROVAL_TYPES = {
    "rights",
    "provider_quote",
    "final_video",
    "publish_final",
    "cua_session",
    "initiative_plan",
    "mcp_tool",
    "script",
}

PLATFORMS = {"youtube", "tiktok"}

CAPABILITIES = {
    "read_assets",
    "create_drafts",
    "render_video",
    "request_provider_quote",
    "execute_paid_generation",
    "manage_rights",
    "manage_credentials",
    "publish_draft",
    "publish_final",
    "run_cua_observe",
    "run_cua_draft",
    "run_cua_publish",
}

HIGH_RISK_CAPABILITIES = {"execute_paid_generation", "manage_credentials", "publish_final"}

CUA_OBSERVE_ACTIONS = {"navigate", "screenshot", "read", "scroll"}
CUA_DRAFT_ACTIONS = CUA_OBSERVE_ACTIONS | {"click", "fill", "keypress", "hover"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def is_expired(value: str | None) -> bool:
    parsed = parse_timestamp(value)
    return parsed is not None and parsed < utcnow()


def require_approval(
    store: Store,
    approval_id: str | None,
    *,
    expected_type: str | None = None,
    subject_id: str | None = None,
) -> dict[str, Any]:
    if not approval_id:
        raise ApprovalRequired("a founder approval record is required")
    approval = store.one("SELECT * FROM approvals WHERE id = ?", (approval_id,), "approvals")
    if not approval:
        raise ApprovalRequired("approval record not found")
    if approval["status"] != "approved":
        raise ApprovalRequired("founder approval has not been granted")
    if expected_type and approval["type"] != expected_type:
        raise ApprovalRequired(f"approval must be of type {expected_type}")
    if subject_id and approval["subject_id"] != subject_id:
        raise ApprovalRequired("approval does not cover this subject")
    return approval


def valid_rights(
    store: Store,
    source_asset_id: str,
    *,
    platform: str | None = None,
    require_commercial: bool = True,
) -> dict[str, Any]:
    records = store.many(
        "SELECT * FROM rights_records WHERE source_asset_id = ? AND status = 'approved' "
        "ORDER BY created_at DESC",
        (source_asset_id,),
        "rights_records",
    )
    if not records:
        raise RightsError("source has no approved rights record")
    for record in records:
        if require_commercial and not record.get("commercial_use"):
            continue
        if is_expired(record.get("expires_at")):
            continue
        platforms = record.get("platforms") or []
        if platform and platforms and platform not in platforms:
            continue
        return record
    raise RightsError("source rights are expired, non-commercial, or do not cover this platform")


def require_worker_capability(worker: dict[str, Any], capability: str) -> None:
    permissions = set(worker.get("permissions") or [])
    if capability not in permissions and "all" not in permissions:
        raise PolicyError(f"worker {worker.get('name', 'unknown')} lacks {capability}")


def require_running(store: Store) -> None:
    if store.is_emergency_stopped():
        raise PolicyError("emergency stop is active; resume operations before continuing")


def require_local_processing() -> None:
    from app.config import settings

    if not settings.local_processing_enabled:
        raise PolicyError("local processing is disabled")
