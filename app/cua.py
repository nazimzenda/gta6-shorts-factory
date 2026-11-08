from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.config import settings
from app.errors import ApprovalRequired, Conflict, NotFound, PolicyError, ValidationProblem
from app.policy import (
    CUA_DRAFT_ACTIONS,
    CUA_OBSERVE_ACTIONS,
    is_expired,
    require_approval,
    require_running,
)
from app.services import FactoryService
from app.storage import Store


class CUABroker:
    """Guarded computer-use broker: allowlisted, time-limited, and auditable.

    Publishing capability is intentionally unavailable. Observe and draft
    actions are recorded with local evidence files.
    """

    def __init__(self, repository: Store, service: FactoryService) -> None:
        self.repository = repository
        self.service = service

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def allowed_domains(self) -> list[str]:
        return list(settings.cua_allowed_domains)

    def normalize_target(self, target: str) -> str:
        raw = (target or "").strip()
        if not raw:
            raise ValidationProblem("CUA target is required")
        if "://" not in raw:
            raw = f"https://{raw}"
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"}:
            raise ValidationProblem("CUA target must be an http or https URL")
        host = (parsed.hostname or "").lower().strip(".")
        if not host:
            raise ValidationProblem("CUA target host is invalid")
        if not self._domain_allowed(host):
            raise PolicyError(f"domain {host} is not on the CUA allowlist")
        return host

    def _domain_allowed(self, host: str) -> bool:
        for allowed in settings.cua_allowed_domains:
            allowed = allowed.lower().strip(".")
            if host == allowed or host.endswith(f".{allowed}"):
                return True
        return False

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions = self.repository.many(
            "SELECT * FROM cua_sessions ORDER BY created_at DESC", (), "cua_sessions"
        )
        for session in sessions:
            session.pop("capability_token_hash", None)
            session["action_count"] = self.repository.count(
                "cua_actions", "session_id = ?", (session["id"],)
            )
            session["expired"] = is_expired(session.get("expires_at"))
            session["approval"] = self.repository.one(
                "SELECT * FROM approvals WHERE type = 'cua_session' AND subject_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (session["id"],),
                "approvals",
            )
            session["activation_required"] = session["status"] == "pending_approval"
        return sessions

    def get_session(self, session_id: str) -> dict[str, Any]:
        session = self.repository.one(
            "SELECT * FROM cua_sessions WHERE id = ?", (session_id,), "cua_sessions"
        )
        if not session:
            raise NotFound("CUA session not found")
        session.pop("capability_token_hash", None)
        session["actions"] = self.list_actions(session_id)
        session["approval"] = self.repository.one(
            "SELECT * FROM approvals WHERE type = 'cua_session' AND subject_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (session_id,),
            "approvals",
        )
        session["activation_required"] = session["status"] == "pending_approval"
        return session

    def create_session(
        self,
        target: str,
        mode: str = "observe",
        approval_id: str | None = None,
        worker_id: str | None = None,
    ) -> dict[str, Any]:
        if not settings.cua_enabled:
            raise PolicyError("CUA is disabled; enable CUA_ENABLED after policy review")
        require_running(self.repository)
        if mode not in {"observe", "draft"}:
            raise ValidationProblem("CUA mode must be observe or draft")
        host = self.normalize_target(target)
        session_id = str(uuid.uuid4())
        if approval_id:
            approval = require_approval(
                self.repository, approval_id, expected_type="cua_session"
            )
            if approval["subject_id"] not in {session_id, host}:
                raise ApprovalRequired(
                    "CUA approval must be scoped to this target or session"
                )
            token = secrets.token_urlsafe(32)
            expires = (
                datetime.now(timezone.utc) + timedelta(minutes=settings.cua_session_minutes)
            ).isoformat()
            session = self.repository.insert(
                "cua_sessions",
                {
                    "id": session_id,
                    "worker_id": worker_id,
                    "target": host,
                    "mode": mode,
                    "allowlist": list(settings.cua_allowed_domains),
                    "capability_token_hash": self._hash_token(token),
                    "status": "active",
                    "approval_id": approval["id"],
                    "max_actions": settings.cua_max_actions,
                    "expires_at": expires,
                    "evidence_dir": str(settings.evidence_dir / session_id),
                },
            )
            Path(str(session["evidence_dir"])).mkdir(parents=True, exist_ok=True)
            self.repository.audit(
                "cua",
                "session_created",
                session_id,
                {"target": host, "mode": mode, "approval_id": approval["id"]},
                approval["id"],
            )
            session.pop("capability_token_hash", None)
            session["capability_token"] = token
            session["activation_required"] = False
            return session

        session = self.repository.insert(
            "cua_sessions",
            {
                "id": session_id,
                "worker_id": worker_id,
                "target": host,
                "mode": mode,
                "allowlist": list(settings.cua_allowed_domains),
                "status": "pending_approval",
                "max_actions": settings.cua_max_actions,
                "evidence_dir": str(settings.evidence_dir / session_id),
            },
        )
        approval = self.service.create_approval(
            "cua_session",
            session_id,
            subject_type="cua_session",
            requested_by="cua",
            reason=f"Approve {mode} session for {host}",
        )
        self.repository.audit(
            "cua",
            "session_requested",
            session_id,
            {"target": host, "mode": mode, "approval_id": approval["id"]},
            approval["id"],
        )
        session["approval"] = approval
        session["activation_required"] = True
        return session

    def activate_session(self, session_id: str) -> dict[str, Any]:
        require_running(self.repository)
        session = self.repository.one(
            "SELECT * FROM cua_sessions WHERE id = ?", (session_id,), "cua_sessions"
        )
        if not session:
            raise NotFound("CUA session not found")
        if session["status"] != "pending_approval":
            raise Conflict("only sessions awaiting approval can be activated")
        approval = self.repository.one(
            "SELECT * FROM approvals WHERE type = 'cua_session' AND subject_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (session_id,),
            "approvals",
        )
        if not approval or approval["status"] != "approved":
            raise ApprovalRequired("founder approval is required before activation")
        token = secrets.token_urlsafe(32)
        expires = (
            datetime.now(timezone.utc) + timedelta(minutes=settings.cua_session_minutes)
        ).isoformat()
        self.repository.update(
            "cua_sessions",
            session_id,
            {
                "status": "active",
                "capability_token_hash": self._hash_token(token),
                "approval_id": approval["id"],
                "expires_at": expires,
            },
        )
        Path(str(session["evidence_dir"])).mkdir(parents=True, exist_ok=True)
        self.repository.audit(
            "cua", "session_activated", session_id, {"approval_id": approval["id"]}, approval["id"]
        )
        result = self.get_session(session_id)
        result["capability_token"] = token
        return result

    def record_action(
        self,
        session_id: str,
        action_type: str,
        target: str | None,
        result: dict[str, Any] | None,
        token: str,
    ) -> dict[str, Any]:
        require_running(self.repository)
        session = self.repository.one(
            "SELECT * FROM cua_sessions WHERE id = ?", (session_id,), "cua_sessions"
        )
        if not session:
            raise NotFound("CUA session not found")
        if session["status"] != "active":
            raise PolicyError(f"CUA session is {session['status']}")
        if is_expired(session.get("expires_at")):
            self.repository.update("cua_sessions", session_id, {"status": "expired"})
            raise PolicyError("CUA session has expired")
        if not token or not secrets.compare_digest(
            self._hash_token(token), str(session.get("capability_token_hash") or "")
        ):
            raise ApprovalRequired("a valid per-session capability token is required")
        allowed = CUA_OBSERVE_ACTIONS if session["mode"] == "observe" else CUA_DRAFT_ACTIONS
        if action_type not in allowed:
            raise PolicyError(
                f"action {action_type} is not allowed in {session['mode']} mode"
            )
        if action_type == "publish":
            raise PolicyError("publishing is never available through the CUA broker")
        if session["actions_used"] >= session["max_actions"]:
            raise PolicyError("CUA session action limit reached")
        if target:
            raw = target.strip()
            if raw.startswith(("http://", "https://")):
                self.normalize_target(raw)

        sequence = int(session["actions_used"]) + 1
        evidence_dir = Path(session.get("evidence_dir") or settings.evidence_dir / session_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_path = evidence_dir / f"{sequence:03d}-{action_type}.json"
        evidence = {
            "session_id": session_id,
            "sequence": sequence,
            "action_type": action_type,
            "target": target,
            "mode": session["mode"],
            "result": result or {},
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
        action = self.repository.insert(
            "cua_actions",
            {
                "id": str(uuid.uuid4()),
                "session_id": session_id,
                "sequence": sequence,
                "action_type": action_type,
                "target": target,
                "evidence_uri": str(evidence_path),
                "result": result or {},
                "status": "recorded",
            },
        )
        self.repository.execute(
            "UPDATE cua_sessions SET actions_used = ? WHERE id = ?",
            (sequence, session_id),
        )
        self.repository.audit(
            "cua",
            "action_recorded",
            action["id"],
            {"session_id": session_id, "action_type": action_type, "sequence": sequence},
        )
        return action

    def list_actions(self, session_id: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE session_id = ?" if session_id else ""
        params = (session_id,) if session_id else ()
        return self.repository.many(
            f"SELECT * FROM cua_actions {where} ORDER BY created_at ASC",
            params,
            "cua_actions",
        )

    def stop_session(self, session_id: str) -> dict[str, Any]:
        session = self.repository.one(
            "SELECT * FROM cua_sessions WHERE id = ?", (session_id,), "cua_sessions"
        )
        if not session:
            raise NotFound("CUA session not found")
        if session["status"] in {"stopped", "closed"}:
            return self.get_session(session_id)
        self.repository.execute(
            "UPDATE cua_sessions SET status = 'stopped', closed_at = CURRENT_TIMESTAMP, "
            "capability_token_hash = NULL WHERE id = ?",
            (session_id,),
        )
        self.repository.audit("cua", "session_stopped", session_id)
        return self.get_session(session_id)

    def emergency_stop(self) -> dict[str, Any]:
        self.repository.execute(
            "UPDATE cua_sessions SET status = 'stopped', closed_at = CURRENT_TIMESTAMP, "
            "capability_token_hash = NULL WHERE status IN ('active','pending_approval')"
        )
        self.repository.set_state("cua_emergency_stop", True)
        self.repository.audit("founder", "cua_emergency_stop", "cua")
        return {"stopped": True, "sessions": self.list_sessions()}
