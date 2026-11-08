from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.errors import ApprovalRequired, Conflict, NotFound, PolicyError, ValidationProblem
from app.policy import is_expired, require_approval
from app.services import FactoryService
from app.storage import Store

SUPPORTED_KINDS = {
    "image": {"base_credits": 8.0, "per_second": 0.0},
    "video": {"base_credits": 40.0, "per_second": 2.0},
    "voice": {"base_credits": 10.0, "per_second": 0.5},
}


class EverygenAdapter:
    """Optional remote creative provider behind a quote-before-spend boundary.

    No network request is made. ``EVERYGEN_MOCK=true`` is the only enabled
    execution mode until the official MCP contract has been verified and a
    live adapter is implemented. The adapter remains fully removable.
    """

    provider = "everygen"

    def __init__(self, repository: Store, service: FactoryService) -> None:
        self.repository = repository
        self.service = service

    def _spent(self) -> float:
        row = self.repository.one(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM cost_events WHERE provider = ?",
            (self.provider,),
            "cost_events",
        )
        return round(float(row["total"] if row else 0), 4)

    def capabilities(self) -> dict[str, Any]:
        spent = self._spent()
        return {
            "provider": self.provider,
            "enabled": settings.everygen_enabled,
            "mode": "mock" if settings.everygen_mock else "live",
            "mock": settings.everygen_mock,
            "live_adapter_configured": bool(settings.everygen_live_url),
            "kinds": {
                kind: {
                    "base_credits": values["base_credits"],
                    "per_second_credits": values["per_second"],
                }
                for kind, values in SUPPORTED_KINDS.items()
            },
            "credit_usd": settings.everygen_credit_usd,
            "budget_usd": settings.everygen_budget_usd,
            "spent_usd": spent,
            "remaining_usd": round(max(0.0, settings.everygen_budget_usd - spent), 4),
            "notes": (
                "Mock mode records asynchronous jobs locally and never calls Everygen. "
                "Verify official endpoints, tool names, pricing, and authentication before "
                "implementing the live adapter."
            ),
        }

    def list_quotes(self) -> list[dict[str, Any]]:
        return self.repository.many(
            "SELECT * FROM provider_quotes WHERE provider = ? ORDER BY created_at DESC",
            (self.provider,),
            "provider_quotes",
        )

    def quote(self, request: dict[str, Any]) -> dict[str, Any]:
        if not settings.everygen_enabled:
            raise PolicyError("Everygen provider is disabled; enable EVERYGEN_ENABLED first")
        if not isinstance(request, dict) or not request:
            raise ValidationProblem("a provider request object is required")
        kind = str(request.get("kind", "")).lower()
        if kind not in SUPPORTED_KINDS:
            raise ValidationProblem("request.kind must be image, video, or voice")
        try:
            seconds = max(0.0, float(request.get("duration_seconds", 0) or 0))
        except (TypeError, ValueError) as error:
            raise ValidationProblem("duration_seconds must be numeric") from error
        request_hash = hashlib.sha256(
            json.dumps(request, sort_keys=True, default=str).encode()
        ).hexdigest()
        existing = self.repository.one(
            "SELECT * FROM provider_quotes WHERE provider = ? AND request_hash = ? "
            "AND status IN ('quoted','approved') ORDER BY created_at DESC LIMIT 1",
            (self.provider, request_hash),
            "provider_quotes",
        )
        if existing:
            existing["duplicate"] = True
            existing["approval"] = self.repository.one(
                "SELECT * FROM approvals WHERE id = ?", (existing.get("approval_id"),), "approvals"
            )
            return existing

        pricing = SUPPORTED_KINDS[kind]
        credits = pricing["base_credits"] + pricing["per_second"] * seconds
        cost = round(credits * settings.everygen_credit_usd, 4)
        spent = self._spent()
        if spent + cost > settings.everygen_budget_usd:
            raise PolicyError(
                f"quote would exceed the Everygen budget "
                f"(${settings.everygen_budget_usd:.2f}); spent ${spent:.2f}"
            )
        expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        quote_id = str(uuid.uuid4())
        quote = self.repository.insert(
            "provider_quotes",
            {
                "id": quote_id,
                "provider": self.provider,
                "request_hash": request_hash,
                "request": request,
                "credits": round(credits, 2),
                "cost_usd": cost,
                "currency": "USD",
                "expires_at": expires,
                "status": "quoted",
            },
        )
        approval = self.service.create_approval(
            "provider_quote",
            quote_id,
            subject_type="provider_quote",
            requested_by="cost",
            reason=(
                f"Approve {kind} generation for {credits:.1f} credits "
                f"(${cost:.2f}); quote expires {expires}"
            ),
        )
        self.repository.update("provider_quotes", quote_id, {"approval_id": approval["id"]})
        self.repository.audit(
            "mcp",
            "provider_quote_requested",
            quote_id,
            {"credits": credits, "cost_usd": cost, "kind": kind},
        )
        quote = self.repository.one(
            "SELECT * FROM provider_quotes WHERE id = ?", (quote_id,), "provider_quotes"
        )
        quote["approval"] = approval
        quote["duplicate"] = False
        return quote or {}

    def list_jobs(self) -> list[dict[str, Any]]:
        rows = self.repository.many(
            "SELECT * FROM provider_jobs WHERE provider = ? ORDER BY created_at DESC",
            (self.provider,),
            "provider_jobs",
        )
        for row in rows:
            row["quote"] = self.repository.one(
                "SELECT * FROM provider_quotes WHERE id = ?",
                (row.get("provider_quote_id"),),
                "provider_quotes",
            )
        return rows

    def create_job(
        self, quote_id: str, approval_id: str | None = None
    ) -> dict[str, Any]:
        if not settings.everygen_enabled:
            raise PolicyError("Everygen provider is disabled; enable EVERYGEN_ENABLED first")
        quote = self.repository.one(
            "SELECT * FROM provider_quotes WHERE id = ?", (quote_id,), "provider_quotes"
        )
        if not quote:
            raise NotFound("provider quote not found")
        if quote["status"] != "approved":
            raise ApprovalRequired("the provider quote must be approved before execution")
        if is_expired(quote.get("expires_at")):
            raise PolicyError("provider quote has expired; request a fresh quote")
        approval_id = approval_id or quote.get("approval_id")
        require_approval(
            self.repository,
            approval_id,
            expected_type="provider_quote",
            subject_id=quote_id,
        )
        existing = self.repository.one(
            "SELECT * FROM provider_jobs WHERE provider_quote_id = ? "
            "AND status NOT IN ('failed','cancelled') ORDER BY created_at DESC LIMIT 1",
            (quote_id,),
            "provider_jobs",
        )
        if existing:
            existing["duplicate"] = True
            return existing
        spent = self._spent()
        if spent + float(quote["cost_usd"]) > settings.everygen_budget_usd:
            raise PolicyError("provider budget exhausted; no job was created")
        job_id = str(uuid.uuid4())
        job = self.repository.insert(
            "provider_jobs",
            {
                "id": job_id,
                "provider": self.provider,
                "provider_quote_id": quote_id,
                "external_job_id": None,
                "status": "queued",
                "approval_id": approval_id,
                "request_hash": quote["request_hash"],
                "mock": 1 if settings.everygen_mock else 0,
            },
        )
        self.repository.audit(
            "mcp",
            "provider_job_created",
            job_id,
            {"quote_id": quote_id, "approval_id": approval_id, "mock": settings.everygen_mock},
            approval_id,
        )
        job["duplicate"] = False
        return job

    def poll_job(self, job_id: str) -> dict[str, Any]:
        job = self.repository.one(
            "SELECT * FROM provider_jobs WHERE id = ? AND provider = ?",
            (job_id, self.provider),
            "provider_jobs",
        )
        if not job:
            raise NotFound("provider job not found")
        if not settings.everygen_mock:
            raise PolicyError(
                "live Everygen execution is not enabled. Verify the official MCP contract "
                "and implement the live adapter before setting EVERYGEN_MOCK=false."
            )
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            return self._job_detail(job_id)
        quote = self.repository.one(
            "SELECT * FROM provider_quotes WHERE id = ?",
            (job.get("provider_quote_id"),),
            "provider_quotes",
        )
        if job["status"] == "queued":
            self.repository.update(
                "provider_jobs",
                job_id,
                {"status": "running", "external_job_id": f"mock-{job_id[:12]}"},
            )
            self.repository.audit("mcp", "provider_job_running", job_id)
            return self._job_detail(job_id)

        result = {
            "provider": self.provider,
            "job_id": job_id,
            "mock": True,
            "ai_generated": True,
            "provenance": {
                "quote_id": job.get("provider_quote_id"),
                "approval_id": job.get("approval_id"),
                "request": quote.get("request") if quote else {},
                "provider_terms": "mock result; no external service was contacted",
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        result_path = settings.provider_dir / f"{job_id}.json"
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        self.repository.update(
            "provider_jobs",
            job_id,
            {"status": "succeeded", "result_uri": str(result_path), "error": None},
        )
        if quote:
            self.repository.insert(
                "cost_events",
                {
                    "id": str(uuid.uuid4()),
                    "provider": self.provider,
                    "category": "paid_generation",
                    "amount": float(quote["cost_usd"]),
                    "currency": "USD",
                    "job_id": job_id,
                    "note": f"mock {quote.get('request', {}).get('kind', 'creative')} generation",
                },
            )
        self.repository.audit(
            "mcp",
            "provider_job_succeeded",
            job_id,
            {"result_uri": str(result_path), "mock": True},
        )
        return self._job_detail(job_id)

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        job = self.repository.one(
            "SELECT * FROM provider_jobs WHERE id = ? AND provider = ?",
            (job_id, self.provider),
            "provider_jobs",
        )
        if not job:
            raise NotFound("provider job not found")
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            raise Conflict(f"job is already {job['status']}")
        self.repository.update(
            "provider_jobs", job_id, {"status": "cancelled", "external_job_id": None}
        )
        self.repository.audit("mcp", "provider_job_cancelled", job_id)
        return self._job_detail(job_id)

    def _job_detail(self, job_id: str) -> dict[str, Any]:
        job = self.repository.one(
            "SELECT * FROM provider_jobs WHERE id = ?", (job_id,), "provider_jobs"
        ) or {}
        job["quote"] = self.repository.one(
            "SELECT * FROM provider_quotes WHERE id = ?",
            (job.get("provider_quote_id"),),
            "provider_quotes",
        )
        return job


class MCPRegistry:
    """Registry and audit boundary for MCP servers and scoped tool calls.

    Live transport execution is deliberately disabled until a verified MCP
    server is configured. Registered calls still produce auditable records.
    """

    def __init__(self, repository: Store) -> None:
        self.repository = repository

    def list_servers(self) -> list[dict[str, Any]]:
        servers = self.repository.many(
            "SELECT * FROM mcp_servers ORDER BY created_at ASC", (), "mcp_servers"
        )
        for server in servers:
            server["tool_count"] = self.repository.count(
                "mcp_tools", "server_id = ?", (server["id"],)
            )
            server["call_count"] = self.repository.count(
                "mcp_tool_calls", "server_id = ?", (server["id"],)
            )
        return servers

    def register_server(
        self,
        name: str,
        endpoint: str,
        transport: str = "stdio",
        scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        if not name.strip() or not endpoint.strip():
            raise ValidationProblem("server name and endpoint are required")
        if transport not in {"stdio", "http", "sse", "streamable-http"}:
            raise ValidationProblem("unsupported MCP transport")
        existing = self.repository.one(
            "SELECT * FROM mcp_servers WHERE name = ?", (name.strip(),), "mcp_servers"
        )
        if existing:
            raise Conflict("an MCP server with that name already exists")
        server_id = str(uuid.uuid4())
        server = self.repository.insert(
            "mcp_servers",
            {
                "id": server_id,
                "name": name.strip(),
                "endpoint": endpoint.strip(),
                "transport": transport,
                "scopes": scopes or [],
                "status": "registered",
            },
        )
        self.repository.audit("mcp", "server_registered", server_id, {"name": name})
        return server

    def connect(self, server_id: str) -> dict[str, Any]:
        server = self.repository.one(
            "SELECT * FROM mcp_servers WHERE id = ?", (server_id,), "mcp_servers"
        )
        if not server:
            raise NotFound("MCP server not found")
        if settings.mcp_live_enabled:
            raise PolicyError(
                "live MCP transport is not implemented in this local build; keep "
                "MCP_LIVE_ENABLED=false until a verified adapter is configured"
            )
        self.repository.execute(
            "UPDATE mcp_servers SET status = 'healthy', last_seen = CURRENT_TIMESTAMP WHERE id = ?",
            (server_id,),
        )
        self.repository.audit(
            "mcp", "server_health_checked", server_id, {"transport": server["transport"]}
        )
        return self.repository.one(
            "SELECT * FROM mcp_servers WHERE id = ?", (server_id,), "mcp_servers"
        ) or {}

    def list_tools(self, server_id: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE server_id = ?" if server_id else ""
        params = (server_id,) if server_id else ()
        rows = self.repository.many(
            f"SELECT * FROM mcp_tools {where} ORDER BY created_at ASC",
            params,
            "mcp_tools",
        )
        for row in rows:
            row["server"] = self.repository.one(
                "SELECT id, name, status FROM mcp_servers WHERE id = ?",
                (row["server_id"],),
                "mcp_servers",
            )
        return rows

    def register_tool(
        self,
        server_id: str,
        name: str,
        description: str = "",
        input_schema: dict[str, Any] | None = None,
        risk: str = "low",
    ) -> dict[str, Any]:
        server = self.repository.one(
            "SELECT * FROM mcp_servers WHERE id = ?", (server_id,), "mcp_servers"
        )
        if not server:
            raise NotFound("MCP server not found")
        if not name.strip():
            raise ValidationProblem("tool name is required")
        if risk not in {"low", "medium", "high"}:
            raise ValidationProblem("tool risk must be low, medium, or high")
        existing = self.repository.one(
            "SELECT * FROM mcp_tools WHERE server_id = ? AND name = ?",
            (server_id, name.strip()),
            "mcp_tools",
        )
        if existing:
            raise Conflict("this tool is already registered")
        tool = self.repository.insert(
            "mcp_tools",
            {
                "id": str(uuid.uuid4()),
                "server_id": server_id,
                "name": name.strip(),
                "description": description,
                "input_schema": input_schema or {},
                "risk": risk,
                "enabled": True,
            },
        )
        self.repository.audit(
            "mcp", "tool_registered", tool["id"], {"server_id": server_id, "risk": risk}
        )
        return tool

    def list_calls(self) -> list[dict[str, Any]]:
        return self.repository.many(
            "SELECT * FROM mcp_tool_calls ORDER BY created_at DESC", (), "mcp_tool_calls"
        )

    def invoke(
        self,
        server_id: str,
        tool_name: str,
        payload: dict[str, Any],
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        server = self.repository.one(
            "SELECT * FROM mcp_servers WHERE id = ?", (server_id,), "mcp_servers"
        )
        if not server:
            raise NotFound("MCP server not found")
        tool = self.repository.one(
            "SELECT * FROM mcp_tools WHERE server_id = ? AND name = ?",
            (server_id, tool_name),
            "mcp_tools",
        )
        if not tool or not tool.get("enabled"):
            raise NotFound("enabled MCP tool not found")
        if tool.get("risk") == "high":
            require_approval(
                self.repository, approval_id, expected_type="mcp_tool", subject_id=tool["id"]
            )
        input_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()
        call_id = str(uuid.uuid4())
        output = {
            "status": "recorded",
            "tool": tool_name,
            "server": server["name"],
            "mock": True,
            "note": (
                "MCP call recorded for audit. Live transport is disabled; no external "
                "tool was executed."
            ),
        }
        if settings.mcp_live_enabled:
            raise PolicyError(
                "live MCP transport is not implemented in this local build; no call was made"
            )
        self.repository.insert(
            "mcp_tool_calls",
            {
                "id": call_id,
                "server_id": server_id,
                "tool_name": tool_name,
                "input_hash": input_hash,
                "approval_id": approval_id,
                "status": "recorded",
                "output_ref": json.dumps(output, sort_keys=True),
            },
        )
        self.repository.audit(
            "mcp",
            "tool_call_recorded",
            call_id,
            {"server_id": server_id, "tool": tool_name, "risk": tool.get("risk")},
            approval_id,
        )
        return {
            "id": call_id,
            "server_id": server_id,
            "tool_name": tool_name,
            "input_hash": input_hash,
            "approval_id": approval_id,
            "status": "recorded",
            "output": output,
        }
