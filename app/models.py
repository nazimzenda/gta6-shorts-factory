from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ApprovalStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class TaskStatus(StrEnum):
    proposed = "proposed"
    queued = "queued"
    running = "running"
    retry = "retry"
    waiting_approval = "waiting_approval"
    completed = "completed"
    failed = "failed"
    dead_letter = "dead_letter"
    cancelled = "cancelled"


class AssetStatus(StrEnum):
    pending_rights = "pending_rights"
    rights_pending = "rights_pending"
    rights_approved = "rights_approved"
    rights_rejected = "rights_rejected"
    analyzed = "analyzed"


class VariantStatus(StrEnum):
    draft = "draft"
    rendering = "rendering"
    rendered = "rendered"
    render_failed = "render_failed"
    qc_passed = "qc_passed"
    qc_failed = "qc_failed"
    in_review = "in_review"
    approved = "approved"
    rejected = "rejected"
    published = "published"


class Approval(BaseModel):
    id: str
    type: str
    subject_id: str
    status: ApprovalStatus = ApprovalStatus.pending


class DashboardSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    company_name: str
    active_initiatives: int = Field(ge=0)
    pending_approvals: int = Field(ge=0)
    active_workers: int = Field(ge=0)
    local_processing_enabled: bool
    everygen_enabled: bool
    cua_enabled: bool
    publishing_enabled: bool = False
    emergency_stop: bool = False
