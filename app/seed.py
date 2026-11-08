from __future__ import annotations

import json

from app.storage import Store

BUSINESS_ID = "gta6-clips"

BRAND_RULES = {
    "voice": "high-energy, factual, creator-respectful",
    "target_format": "9:16 vertical, 1080x1920",
    "attribution": "required for every licensed source",
    "caption_safe_margin_px": 180,
    "banned": [
        "unverified GTA 6 claims",
        "clickbait that misrepresents gameplay",
        "watermark removal",
        "creator impersonation",
    ],
    "disclosure": "Label AI-generated assets internally and follow platform disclosure rules.",
    "approval_rule": "No paid provider call or final publish without a founder approval record.",
}

DEPARTMENTS = [
    (
        "research",
        "Research & Rights",
        "Trend discovery, source verification, and rights-cleared partnerships.",
    ),
    (
        "creative",
        "Creative",
        "Formats, hooks, scripts, covers, and brand guardrails.",
    ),
    (
        "production",
        "Production",
        "Ingest, analysis, captions, vertical editing, audio, and QC.",
    ),
    (
        "publishing",
        "Publishing",
        "Metadata, platform policy checks, scheduling, and channel delivery.",
    ),
    (
        "analytics",
        "Analytics",
        "Performance, retention, experiments, and learning.",
    ),
    (
        "engineering",
        "Engineering & Automation",
        "Pipeline, MCP, CUA, infrastructure, security, and tests.",
    ),
    (
        "operations",
        "Operations & Finance",
        "Queue health, costs, assets, backups, and incidents.",
    ),
]

# id, department, name, role, avatar, capabilities, permissions
WORKERS = [
    ("trend-researcher", "research", "Trend Researcher", "Trend discovery", "🔭",
     ["trend_scan", "source_discovery"], ["read_assets"]),
    ("game-news-researcher", "research", "Game News Researcher", "News verification", "📰",
     ["news_scan", "fact_check"], ["read_assets"]),
    ("partnership-researcher", "research", "Creator Partnership Researcher", "Creator outreach", "🤝",
     ["creator_scan", "license_outreach"], ["read_assets"]),
    ("rights-officer", "research", "Rights and Licensing Officer", "Rights gatekeeper", "⚖️",
     ["rights_review", "licence_validation"], ["read_assets", "manage_rights"]),
    ("source-verifier", "research", "Source Verification Worker", "Source provenance", "🔎",
     ["hash_verify", "source_verify"], ["read_assets"]),

    ("format-strategist", "creative", "Format Strategist", "Format planning", "🧭",
     ["format_plan", "audience_fit"], ["read_assets", "create_drafts"]),
    ("hook-writer", "creative", "Hook Writer", "Hooks and titles", "🪝",
     ["hook_writing", "title_writing"], ["create_drafts"]),
    ("script-writer", "creative", "Script Writer", "Scripts and commentary", "✍️",
     ["script_writing", "commentary"], ["create_drafts"]),
    ("cover-designer", "creative", "Thumbnail and Cover Designer", "Covers", "🖼️",
     ["cover_design", "thumbnail_design"], ["create_drafts"]),
    ("brand-guardian", "creative", "Brand Guardian", "Brand policy", "🛡️",
     ["brand_check", "claims_check"], ["read_assets", "create_drafts"]),

    ("ingest-worker", "production", "Ingest Worker", "Media intake", "📥",
     ["ingest", "hash", "probe"], ["read_assets", "create_drafts"]),
    ("scene-detector", "production", "Scene Detection Worker", "Scene analysis", "🎬",
     ["scene_detection", "audio_energy"], ["read_assets", "create_drafts"]),
    ("highlight-scout", "production", "Highlight Scout", "Moment scoring", "🔦",
     ["highlight_detection", "hook_detection"], ["read_assets", "create_drafts"]),
    ("transcription-worker", "production", "Transcription Worker", "Speech to text", "🎙️",
     ["transcription", "caption_timing"], ["read_assets", "create_drafts"]),
    ("caption-designer", "production", "Caption Designer", "Caption styling", "🔤",
     ["caption_design", "safe_area_check"], ["create_drafts"]),
    ("vertical-editor", "production", "Vertical Editor", "9:16 edit and render", "📱",
     ["vertical_edit", "render_video"], ["create_drafts", "render_video"]),
    ("audio-mixer", "production", "Audio Mixer", "Audio balance", "🎚️",
     ["audio_mix", "loudness_check"], ["create_drafts"]),
    ("qc-worker", "production", "Quality-Control Worker", "Final QC", "✅",
     ["qc_decode", "qc_safe_area", "qc_metadata"], ["read_assets", "create_drafts"]),

    ("metadata-writer", "publishing", "Metadata Writer", "Titles and descriptions", "🏷️",
     ["metadata_writing", "hashtag_planning"], ["create_drafts", "publish_draft"]),
    ("policy-checker", "publishing", "Platform Policy Checker", "Platform rules", "📋",
     ["platform_policy_check", "disclosure_check"], ["read_assets"]),
    ("youtube-publisher", "publishing", "YouTube Publisher", "YouTube delivery", "▶️",
     ["youtube_upload", "schedule"], ["publish_draft"]),
    ("tiktok-publisher", "publishing", "TikTok Publisher", "TikTok delivery", "🎵",
     ["tiktok_upload", "schedule"], ["publish_draft"]),
    ("schedule-coordinator", "publishing", "Schedule Coordinator", "Publishing calendar", "🗓️",
     ["schedule_planning", "reconcile"], ["read_assets"]),

    ("performance-analyst", "analytics", "Performance Analyst", "Performance reporting", "📈",
     ["analytics_import", "reporting"], ["read_assets"]),
    ("ab-analyst", "analytics", "A/B Test Analyst", "Experiment analysis", "🧪",
     ["ab_testing", "variant_compare"], ["read_assets"]),
    ("retention-analyst", "analytics", "Retention Analyst", "Retention curves", "⏱️",
     ["retention_analysis"], ["read_assets"]),
    ("experiment-planner", "analytics", "Experiment Planner", "Learning agenda", "💡",
     ["experiment_design", "hypothesis_writing"], ["read_assets"]),

    ("pipeline-engineer", "engineering", "Pipeline Engineer", "Media pipeline", "🛠️",
     ["pipeline_build", "render_debug"], ["read_assets"]),
    ("mcp-engineer", "engineering", "MCP Integration Engineer", "MCP gateway", "🔌",
     ["mcp_registry", "tool_schema"], ["read_assets", "request_provider_quote"]),
    ("cua-engineer", "engineering", "CUA/Desktop Automation Engineer", "CUA broker", "🖥️",
     ["cua_session", "evidence_capture"], ["run_cua_observe", "run_cua_draft"]),
    ("infra-engineer", "engineering", "Infrastructure Engineer", "Local infrastructure", "🏗️",
     ["storage", "queue", "backup"], ["read_assets"]),
    ("security-engineer", "engineering", "Security and Secrets Engineer", "Secrets and access", "🔐",
     ["secret_management", "access_review"], ["read_assets"]),
    ("test-engineer", "engineering", "Test Engineer", "Verification and tests", "🧫",
     ["test_authoring", "regression"], ["read_assets"]),

    ("queue-manager", "operations", "Queue Manager", "Queue health", "📚",
     ["queue_monitor", "retry_policy"], ["read_assets"]),
    ("cost-controller", "operations", "Cost Controller", "Budgets and quotes", "💰",
     ["cost_tracking", "budget_check"], ["read_assets", "request_provider_quote"]),
    ("asset-librarian", "operations", "Asset Librarian", "Asset registry", "🗂️",
     ["asset_catalog", "metadata_audit"], ["read_assets"]),
    ("backup-worker", "operations", "Backup Worker", "Backups and restore", "💾",
     ["backup", "restore_drill"], ["read_assets"]),
    ("incident-coordinator", "operations", "Incident Coordinator", "Incident response", "🚨",
     ["incident_triage", "escalation"], ["read_assets"]),
]


def seed_defaults(store: Store) -> None:
    """Seed the organisation without creating approvals or production data."""
    now = None  # let SQLite defaults apply
    del now

    existing = store.one("SELECT * FROM businesses WHERE id = ?", (BUSINESS_ID,), "businesses")
    if not existing:
        store.execute(
            """
            INSERT INTO businesses (id, name, status, brand_rules)
            VALUES (?, ?, 'active', ?)
            """,
            (BUSINESS_ID, "GTA 6 Clips", json.dumps(BRAND_RULES, sort_keys=True)),
        )

    for department_id, name, description in DEPARTMENTS:
        store.execute(
            """
            INSERT OR IGNORE INTO departments (id, business_id, name, description, status)
            VALUES (?, ?, ?, ?, 'active')
            """,
            (department_id, BUSINESS_ID, name, description),
        )

    manager_by_department: dict[str, str] = {}
    for worker_id, department_id, name, role, avatar, capabilities, permissions in WORKERS:
        manager_by_department.setdefault(department_id, worker_id)
        store.execute(
            """
            INSERT OR IGNORE INTO workers
            (id, department_id, name, role, avatar, capabilities, permissions, status, last_action)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 'Awaiting assignment')
            """,
            (
                worker_id,
                department_id,
                name,
                role,
                avatar,
                json.dumps(capabilities),
                json.dumps(permissions),
            ),
        )

    for department_id, worker_id in manager_by_department.items():
        store.execute(
            "UPDATE departments SET manager_worker_id = ? WHERE id = ? AND manager_worker_id IS NULL",
            (worker_id, department_id),
        )

    if store.get_state("emergency_stop") is None:
        store.set_state("emergency_stop", False)
    if store.get_state("paused_departments") is None:
        store.set_state("paused_departments", [])
    if store.get_state("seeded_at") is None:
        store.execute(
            "INSERT INTO audit_events (actor, action, target, payload) VALUES (?, ?, ?, ?)",
            ("system", "company_seeded", BUSINESS_ID, json.dumps({"workers": len(WORKERS)})),
        )
        store.set_state("seeded_at", True)
