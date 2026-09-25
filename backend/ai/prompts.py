"""Prompt templates for the LLM service.

Only the minimum project/history context needed for the task is included.
These are internal - never exposed through any API endpoint.
"""

SYSTEM_ANALYZE = (
    "You are the analysis engine of Sankalp, an Indian government "
    "infrastructure early-warning system. Analyze a single project update "
    "and answer only with valid JSON matching the provided schema. "
    "Do not invent facts. Base every judgment on the text provided. "
    "If the update contains no new risk information, set risk_detected=false."
)

USER_ANALYZE = """Project update (ID {update_id}, type {update_type}, date {created_at}):
\"\"\"
{content}
\"\"\"

Reply with ONLY this JSON (no markdown, no commentary):
{{
  "risk_detected": true|false,
  "risk_category": "STAKEHOLDER_CONFLICT|COMMUNITY_OPPOSITION|CONTRACTOR_DISPUTE|DESIGN_CHANGE|PROCUREMENT_DISRUPTION|RESOURCE_SHORTAGE|REGULATORY_CHANGE|LAND_ACQUISITION|INTER_DEPARTMENT_COORDINATION|FUNDING_ISSUE|TECHNICAL_COMPLEXITY|ENVIRONMENTAL_CONCERN|POLITICAL_OR_ADMINISTRATIVE_DEPENDENCY|OTHER",
  "risk_title": "short title",
  "confidence": 0.0-1.0,
  "severity": "LOW|MEDIUM|HIGH|CRITICAL",
  "potential_impact": "LOW|MEDIUM|HIGH|CRITICAL",
  "time_horizon_days": days or null,
  "evidence": ["quote/paraphrase from the update", ...],
  "recommended_actions": ["actionable step", ...]
}}"""

SYSTEM_EXPLAIN = (
    "You are Sankalp's risk-explanation engine. Using ONLY the evidence "
    "provided, explain in one paragraph why the project may fail or be "
    "delayed, and give the single most likely next event. Answer with JSON."
)

USER_EXPLAIN = """Deterministic evidence (current risk assessment):
{deterministic}

Historical signals (from updates):
{history}

Reply with ONLY this JSON:
{{
  "summary": "one paragraph",
  "predicted_events": ["next likely event"],
  "ai_evidence": ["specific evidence from the data"]
}}"""


def build_analyze_messages(update_id, update_type, created_at, content) -> list:
    return [
        {"role": "system", "content": SYSTEM_ANALYZE},
        {
            "role": "user",
            "content": USER_ANALYZE.format(
                update_id=update_id,
                update_type=update_type,
                created_at=created_at or "unknown",
                content=content[:1800],
            ),
        },
    ]


def build_explain_messages(deterministic: str, history: str) -> list:
    return [
        {"role": "system", "content": SYSTEM_EXPLAIN},
        {"role": "user", "content": USER_EXPLAIN.format(
            deterministic=deterministic[:2000], history=history[:2000]
        )},
    ]