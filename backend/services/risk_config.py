"""Central configuration for the Sankalp rule-based risk engine.

Everything an analyst or adjuster would want to tune lives here, so the
engine behaviour is adjustable in ONE place:

- factor weights (must total 100)
- risk bands for factor scores and the overall project score
- interaction penalty rules
- critical blocker override rules and floors
- baseline probability/impact used when data is missing

This module is intentionally free of logic so it can be replaced by a
config file (or an ML model configuration) later without touching the
engine.
"""

# 15 core risk factors and their weights. Total must equal 100.
FACTOR_WEIGHTS = {
    "budget": 10,          # Budget & Cost Overrun
    "schedule": 12,        # Schedule & Delay
    "completion": 8,       # Completion Rate
    "financial": 10,       # Financial Progress Gap
    "weather": 5,          # Weather Conditions
    "ground": 6,           # Ground / Geological Conditions
    "calamity": 5,         # Natural Calamity Risk
    "material": 7,         # Material Quality & Availability
    "workforce": 6,        # Workforce Availability & Productivity
    "contractor": 8,       # Contractor Performance
    "engineering": 7,      # Engineering / Design Risk
    "clearance": 5,        # Land & Environmental Clearance
    "administrative": 5,   # Government / Administrative Delays
    "supply_chain": 4,     # Supply Chain & Logistics
    "legal_social": 2,     # Legal / Social Issues
}

FACTOR_NAMES = {
    "budget": "Budget & Cost Overrun",
    "schedule": "Schedule & Delay",
    "completion": "Completion Rate",
    "financial": "Financial Progress Gap",
    "weather": "Weather Conditions",
    "ground": "Ground / Geological Conditions",
    "calamity": "Natural Calamity Risk",
    "material": "Material Quality & Availability",
    "workforce": "Workforce Availability & Productivity",
    "contractor": "Contractor Performance",
    "engineering": "Engineering / Design Risk",
    "clearance": "Land & Environmental Clearance",
    "administrative": "Government / Administrative Delays",
    "supply_chain": "Supply Chain & Logistics",
    "legal_social": "Legal / Social Issues",
}

# Individual factor severity bands (score on 0-100)
#   0-20 VERY LOW | 21-40 LOW | 41-60 MODERATE | 61-80 HIGH | 81-100 CRITICAL
FACTOR_BANDS = [
    (81, "CRITICAL"),
    (61, "HIGH"),
    (41, "MODERATE"),
    (21, "LOW"),
    (0, "VERY LOW"),
]

# Overall project risk bands (score on 0-100)
#   0-25 LOW | 26-50 MEDIUM | 51-75 HIGH | 76-100 CRITICAL
OVERALL_BANDS = [
    (76, "CRITICAL"),
    (51, "HIGH"),
    (26, "MEDIUM"),
    (0, "LOW"),
]

# Sum of interaction penalties is never allowed above this (see section 20).
MAX_INTERACTION_PENALTY = 15

# Dominant-risk exposure (section 19). A pure weighted mean lets many healthy
# lower-weight factors mask one severe factor. We add up to this much based on
# the single highest factor score so a genuinely serious problem is never
# hidden (e.g. a project with a severe schedule problem must read HIGH).
TOP_FACTOR_BOOST_SHARE = 0.15
TOP_FACTOR_BOOST_CAP = 15

# Floors applied when a critical blocker exists (section 21): the project may
# not remain LOW just because other factors look healthy.
BLOCKER_HIGH_FLOOR = 60
BLOCKER_CRITICAL_FLOOR = 80

# When a factor has no evidence at all we do NOT assume zero risk. A neutral
# baseline keeps the factor contributing a small, honest amount while data
# availability (and therefore confidence) drops.
UNKNOWN_PROBABILITY = 0.30
UNKNOWN_IMPACT = 0.60
UNKNOWN_BASELINE_SCORE = 18

# Interaction penalty rules (section 20). A rule fires when every `conditions`
# tuple `(factor_key, min_score)` is satisfied. Summed penalties are capped at
# MAX_INTERACTION_PENALTY.
INTERACTION_RULES = [
    {
        "key": "schedule_contractor_completion",
        "label": "Schedule + Contractor + Completion",
        "conditions": [("schedule", 60), ("contractor", 55), ("completion", 40)],
        "penalty": 10,
        "reason": "Project is behind schedule while contractor performance is poor and completion is trailing",
    },
    {
        "key": "cost_financial_gap",
        "label": "Cost Overrun + Financial Gap",
        "conditions": [("budget", 55), ("financial", 45)],
        "penalty": 8,
        "reason": "Cost overruns combined with a large financial/physical progress gap warrant financial intervention",
    },
    {
        "key": "land_admin_schedule",
        "label": "Land + Administrative + Schedule",
        "conditions": [("clearance", 45), ("administrative", 45), ("schedule", 55)],
        "penalty": 12,
        "reason": "Land acquisition and administrative delays are blocking a project already behind schedule",
    },
    {
        "key": "weather_ground_completion",
        "label": "Weather + Ground + Completion",
        "conditions": [("weather", 45), ("ground", 45), ("completion", 35)],
        "penalty": 8,
        "reason": "Adverse weather and difficult ground conditions are suppressing completion progress",
    },
    {
        "key": "material_workforce_schedule",
        "label": "Material + Workforce + Schedule",
        "conditions": [("material", 45), ("workforce", 45), ("schedule", 50)],
        "penalty": 8,
        "reason": "Material shortages and low workforce productivity are compounding schedule delay",
    },
    {
        "key": "engineering_schedule",
        "label": "Design Changes + Schedule",
        "conditions": [("engineering", 50), ("schedule", 55)],
        "penalty": 5,
        "reason": "Frequent design changes are feeding additional schedule risk",
    },
    {
        "key": "legal_clearance",
        "label": "Legal/Social + Land Clearance",
        "conditions": [("legal_social", 45), ("clearance", 45)],
        "penalty": 6,
        "reason": "Legal/social opposition is compounding land acquisition problems",
    },
]

# Critical blocker overrides (section 21). Each entry is matched by the engine;
# when matched the final risk level is lifted to at least the given floor.
BLOCKER_RULES = [
    {
        "key": "court_stay",
        "level": "CRITICAL",
        "reason": "A court stay / injunction is blocking construction",
        "recommendation": "Obtain a legal review to vacate, scope or mitigate the court stay",
    },
    {
        "key": "environmental_rejected",
        "level": "CRITICAL",
        "reason": "Environmental clearance has been rejected",
        "recommendation": "Prioritize the environmental clearance process at the highest level",
    },
    {
        "key": "environmental_pending",
        "level": "HIGH",
        "reason": "Environmental clearance is still pending",
        "recommendation": "Escalate the pending environmental clearance approval",
    },
    {
        "key": "land_blocked",
        "level": "HIGH",
        "reason": "Major land acquisition blockage",
        "recommendation": "Escalate land acquisition to the highest competent authority",
    },
    {
        "key": "contractor_critical",
        "level": "HIGH",
        "reason": "Contractor performance is critical (possible abandonment)",
        "recommendation": "Assess contractor capability and mobilize a backup contractor if needed",
    },
    {
        "key": "approval_blocked",
        "level": "HIGH",
        "reason": "Project is blocked by an unresolved government approval",
        "recommendation": "Escalate the blocked approval to the responsible department",
    },
    {
        "key": "severe_design_failure",
        "level": "HIGH",
        "reason": "Severe engineering/design failures requiring extensive rework",
        "recommendation": "Conduct an independent engineering review before proceeding",
    },
    {
        "key": "severe_natural_disaster",
        "level": "HIGH",
        "reason": "Site is facing a severe natural hazard exposure",
        "recommendation": "Strengthen disaster mitigation measures and review site vulnerability",
    },
]