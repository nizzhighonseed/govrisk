"""Deterministic, explainable, rule-based Project Risk Assessment Engine.

Design principles (per requirement set v3):
- NO LLM / NO ML. The engine is a pure rule-based system that a predictive
  ML model may replace later, so every output is traceable to concrete inputs.
- Every factor produces a probability (0-1), an impact (0-1) and
      Risk Score = round(clamp(probability * impact, 0, 1) * 100)
- Weighted combination, interaction penalties and critical overrides are
  driven entirely by `risk_config.py` so the behaviour can be tuned centrally.
- Missing data NEVER silently becomes zero risk; unknown factors contribute a
  neutral baseline while `dataAvailable=false` lowers confidence.
"""

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models import Project
from services import risk_config as CFG
from services.text_guard import strip_html_tags


def _safe_text(value) -> str:
    """User-controlled text for assistant replies, stripped of HTML tags.

    The frontend renders replies as text (primary trust boundary); this is
    defense in depth so the backend can never emit executable markup.
    """
    return strip_html_tags(value)


# --------------------------------------------------------------------------
# small deterministic helpers
# --------------------------------------------------------------------------

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _num(v, default=None):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(v, default=None):
    try:
        if v is None or v == "":
            return default
        return int(round(float(v)))
    except (TypeError, ValueError):
        return default


def _date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _now():
    return datetime.now()


def _prob_from_anchors(value, anchors):
    """Piecewise linear interpolation over (x, prob) anchor points."""
    if value is None:
        return None
    pts = sorted(anchors)
    if value <= pts[0][0]:
        return pts[0][1]
    if value >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= value <= x1:
            r = (value - x0) / (x1 - x0)
            return y0 + (y1 - y0) * r
    return pts[-1][1]


def _enum_prob(mapping, value):
    if value is None:
        return None
    key = str(value).strip().upper()
    return mapping.get(key)


def _is_evidence(v):
    """True when a raw input value counts as real evidence (vs. a default)."""
    return v is not None and v != "" and v is not False and v != 0


def _branch_available(branch):
    if not isinstance(branch, dict):
        return False
    return any(_is_evidence(v) for v in branch.values())


# --------------------------------------------------------------------------
# input extraction
# --------------------------------------------------------------------------

def _normalize_inputs(project) -> dict:
    raw = {}
    if getattr(project, "risk_inputs", None):
        try:
            parsed = json.loads(project.risk_inputs)
            if isinstance(parsed, dict):
                raw = parsed
        except (TypeError, ValueError):
            raw = {}

    def branch(*names):
        for name in names:
            b = raw.get(name)
            if isinstance(b, dict):
                return b
        return {}

    return {
        "weather": branch("weather"),
        "ground": branch("ground"),
        "calamity": branch("calamity"),
        "material": branch("material"),
        "workforce": branch("workforce"),
        "contractor": branch("contractor"),
        "engineering": branch("engineering"),
        "clearance": branch("clearance"),
        "administrative": branch("administrative"),
        "supply_chain": branch("supplyChain"),
        "legal_social": branch("legalSocial"),
    }


def _derived(project, now=None):
    """Pure numeric signals every factor can rely on from core project fields."""
    now = now or _now()
    original = _num(project.original_cost, 0)
    current = _num(project.current_cost, 0)
    expenditure = _num(project.expenditure, 0)
    physical = _num(project.physical_progress, 0)
    planned = _num(project.planned_progress, 0)
    financial = _num(project.financial_progress)

    overrun_pct = ((current - original) / original * 100) if original > 0 else None
    burn_pct = (expenditure / current * 100) if current > 0 else None

    # Financial progress: explicit value preferred, otherwise derived from the
    # expenditure burn (real evidence of money spent, not a fabrication).
    fin = financial if financial is not None else burn_pct

    start = _date(project.start_date)
    completion = _date(project.expected_completion)
    predicted = _date(project.predicted_completion)

    elapsed_pct = None
    remaining_pct = None
    if start and completion and completion > start:
        total = (completion - start).days
        if total > 0:
            elapsed = (now - start).days
            elapsed_pct = _clamp(elapsed / total * 100, 0, 100)
            remaining_pct = _clamp(100 - elapsed_pct, 0, 100)

    slippage_months = None
    if completion and predicted:
        months = (predicted.year - completion.year) * 12 + (predicted.month - completion.month)
        slippage_months = max(0, months)

    milestones_total = _int(project.milestones_total, 0)
    milestones_delayed = _int(project.milestones_delayed, 0)
    milestone_frac = None
    if milestones_total and milestones_total > 0:
        milestone_frac = _clamp(milestones_delayed / milestones_total, 0, 1)

    return {
        "original": original,
        "current": current,
        "expenditure": expenditure,
        "overrun_pct": overrun_pct,
        "burn_pct": burn_pct,
        "physical": physical,
        "planned": planned,
        "gap": max(0.0, planned - physical),
        "financial": financial,
        "fin": fin,
        "fin_gap": (fin - physical) if fin is not None else None,
        "elapsed_pct": elapsed_pct,
        "remaining_pct": remaining_pct,
        "slippage_months": slippage_months,
        "milestones_total": milestones_total,
        "milestones_delayed": milestones_delayed,
        "milestone_frac": milestone_frac,
    }


# --------------------------------------------------------------------------
# factor result builder
# --------------------------------------------------------------------------

def _factor_severity(score):
    for floor, label in CFG.FACTOR_BANDS:
        if score >= floor:
            return label
    return "VERY LOW"


def _factor_result(key, prob, impact, reason, available, demanded_score=False, conditions=None):
    """Build a factor dict. Honors the unknown-data baseline."""
    if not available:
        if prob is None:
            prob = CFG.UNKNOWN_PROBABILITY
        if impact is None:
            impact = CFG.UNKNOWN_IMPACT
        reason = (reason + " (insufficient data - neutral baseline applied)") if reason else \
            "Insufficient data - neutral baseline applied"
    probability = _num(prob)
    impact_v = _num(impact)
    if probability is None:
        probability = 0.0
    if impact_v is None:
        impact_v = 0.0
    score = round(_clamp(probability * impact_v, 0, 1) * 100)
    if demanded_score:
        score = min(score, demanded_score)
    weight = CFG.FACTOR_WEIGHTS[key]
    contribution = round(score * weight / 100.0, 2)
    triggered_conditions = [
        str(value) for value in (conditions or []) if value not in (None, "")
    ]
    return {
        "key": key,
        "factor": key,
        "name": CFG.FACTOR_NAMES[key],
        "score": score,
        "weight": weight,
        "contribution": contribution,
        "probability": round(probability, 3),
        "impact": round(impact_v, 3),
        "severity": _factor_severity(score),
        "reason": reason,
        "explanation": reason,
        "triggeredConditions": triggered_conditions,
        "dataAvailable": available,
    }


# --------------------------------------------------------------------------
# 15 factor evaluators
# --------------------------------------------------------------------------

# factor 1 - budget & cost overrun
BUDGET_PROB_ANCHORS = [(0, 0.02), (3, 0.20), (5, 0.30), (10, 0.55), (15, 0.70), (20, 0.85), (30, 0.95)]

def eval_budget(project, inputs, d):
    overrun = d["overrun_pct"]
    if overrun is None:
        return _factor_result("budget", None, 0.6, "Insufficient cost data", False)
    prob = _prob_from_anchors(overrun, BUDGET_PROB_ANCHORS)
    impact = 0.60
    if overrun > 10:
        impact = 0.85
    elif overrun > 5:
        impact = 0.75
    material = inputs["material"]
    price = _num(material.get("priceIncreasePct"))
    if price:
        prob = min(1.0, prob + min(0.30, price * 0.01))
    burn = d["burn_pct"] or 0
    physical = d["physical"]
    if burn >= 85 and physical < 60:
        impact = max(impact, 0.90)
        reason = f"{burn:.0f}% of the budget is spent with only {physical:.0f}% physical progress; cost is {overrun:.1f}% above approved cost"
    elif overrun > 0.5:
        reason = f"Revised cost is {overrun:.1f}% above approved cost"
    else:
        reason = "Cost is tracking close to the approved estimate"
    conditions = []
    if price:
        conditions.append(f"Material price increase: {price:.1f}%")
    if burn >= 85 and physical < 60:
        conditions.append(
            f"Budget burn {burn:.0f}% against {physical:.0f}% physical progress"
        )
    if overrun > 0.5:
        conditions.append(f"Revised cost variance: {overrun:.1f}%")
    return _factor_result("budget", prob, impact, reason, True, conditions=conditions)


# factor 2 - schedule & delay
SCHEDULE_PROB_ANCHORS = [(0, 0.02), (5, 0.20), (10, 0.40), (15, 0.60), (25, 0.80), (40, 0.95)]
SLIPPAGE_ANCHORS = [(0, 0.0), (6, 0.15), (12, 0.30), (24, 0.50)]

def eval_schedule(project, inputs, d):
    prob = _prob_from_anchors(d["gap"], SCHEDULE_PROB_ANCHORS)
    slippage = d["slippage_months"] or 0
    prob = min(1.0, prob + _prob_from_anchors(slippage, SLIPPAGE_ANCHORS))
    if d["milestone_frac"]:
        prob = min(1.0, prob + d["milestone_frac"] * 0.25)
    impact = 0.9 if slippage <= 12 else 1.0
    reasons = []
    if d["gap"] >= 2:
        reasons.append(f"Actual progress is {d['gap']:.0f}% behind expected progress")
    if slippage >= 2:
        reasons.append(f"Completion is sliding by ~{int(round(slippage))} months")
    if d["milestone_frac"] and d["milestone_frac"] >= 0.3:
        reasons.append(f"{d['milestones_delayed']} of {d['milestones_total']} milestones are delayed")
    reason = "; ".join(reasons) or "Project is broadly on schedule"
    conditions = []
    if d["gap"] >= 2:
        conditions.append(f"Progress gap: {d['gap']:.0f}%")
    if slippage >= 2:
        conditions.append(f"Predicted completion slippage: {int(round(slippage))} months")
    if d["milestone_frac"] and d["milestone_frac"] >= 0.3:
        conditions.append(
            f"Delayed milestones: {d['milestones_delayed']} of {d['milestones_total']}"
        )
    return _factor_result("schedule", prob, impact, reason, True, conditions=conditions)


# factor 3 - completion rate
COMPLETION_PROB_ANCHORS = [(0, 0.02), (5, 0.20), (10, 0.40), (20, 0.70), (35, 0.90)]

def eval_completion(project, inputs, d):
    deficit = d["gap"]
    elapsed = d["elapsed_pct"] if d["elapsed_pct"] is not None else 0
    prob = _prob_from_anchors(deficit, COMPLETION_PROB_ANCHORS)
    if d["physical"] < 30 and elapsed > 40:
        prob = max(prob, 0.70)
    impact = 0.5 + 0.5 * (elapsed / 100.0)
    if deficit >= 2:
        reason = (
            f"Project is {deficit:.0f}% behind expected completion "
            f"with {100 - elapsed:.0f}% of the timeline remaining"
        )
    else:
        reason = "Completion is progressing in line with expectations"
    conditions = []
    if deficit >= 2:
        conditions.append(f"Completion deficit: {deficit:.0f}%")
    if d["physical"] < 30 and elapsed > 40:
        conditions.append(
            f"Physical progress {d['physical']:.0f}% at {elapsed:.0f}% of elapsed timeline"
        )
    return _factor_result("completion", prob, impact, reason, True, conditions=conditions)


# factor 4 - financial progress gap
FIN_GAP_ANCHORS = [(0, 0.02), (10, 0.35), (20, 0.60), (35, 0.85)]

def eval_financial(project, inputs, d):
    fin = d["fin"]
    if fin is None:
        return _factor_result("financial", None, 0.7, "No financial progress information available", False)
    gap = fin - d["physical"]
    if gap >= 0:
        prob = _prob_from_anchors(gap, FIN_GAP_ANCHORS)
        if gap >= 10:
            reason = f"Financial progress is {gap:.0f} points AHEAD of physical progress - money committed before milestones achieved"
        else:
            reason = "Financial and physical progress are broadly aligned"
    else:
        neg = -gap
        prob = _prob_from_anchors(neg, [(0, 0.02), (10, 0.40), (20, 0.65), (30, 0.85)])
        if neg >= 10:
            reason = f"Physical progress is {neg:.0f} points ahead of financial progress - possible funding constraints or payment delays"
        else:
            reason = "Financial and physical progress are broadly aligned"
    impact = 0.85 if abs(gap) >= 25 else 0.70
    conditions = []
    if abs(gap) >= 10:
        conditions.append(f"Financial vs physical progress gap: {gap:+.0f} points")
    return _factor_result("financial", prob, impact, reason, True, conditions=conditions)


# factor 5 - weather
WEATHER_CONDITION = {"CLEAR": 0.05, "MILD": 0.20, "UNFAVOURABLE": 0.45, "SEVERE": 0.70}
WEATHER_DISRUPTION = {"LOW": 0.10, "MODERATE": 0.35, "HIGH": 0.60, "CRITICAL": 0.85}

def eval_weather(project, inputs, d):
    w = inputs["weather"]
    cond = _enum_prob(WEATHER_CONDITION, w.get("condition"))
    working = _num(w.get("workingDaysLost")) or 0
    disruption = _enum_prob(WEATHER_DISRUPTION, w.get("disruption"))
    avail = _branch_available(w)
    base = cond if cond is not None else (disruption if disruption is not None else None)
    prob = base if base is not None else 0.05
    prob = min(1.0, prob + working * 0.006)
    if disruption is not None:
        prob = max(prob, disruption)
    prob = min(1.0, prob)
    impact = 0.60 + (0.20 if (working >= 20 or (disruption or 0) >= 0.6) else 0.0)
    reasons = []
    if cond is not None and cond >= 0.45:
        reasons.append("Adverse weather conditions are disrupting work")
    if working >= 15:
        reasons.append(f"About {working:.0f} working days lost to weather")
    reason = "; ".join(reasons) or ("Weather conditions are favourable" if avail else "No weather information recorded")
    conditions = []
    if cond is not None and cond >= 0.45:
        conditions.append(f"Weather condition: {w.get('condition')}")
    if working >= 15:
        conditions.append(f"Weather working days lost: {working:.0f}")
    if disruption is not None and disruption >= 0.35:
        conditions.append(f"Weather disruption: {w.get('disruption')}")
    return _factor_result("weather", prob, impact, reason, avail, conditions=conditions)


# factor 6 - ground / geological
GROUND_CONDITION_PROB = {"FAVOURABLE": 0.05, "MODERATE": 0.30, "DIFFICULT": 0.55, "SEVERE": 0.80}
GROUND_CONDITION_IMPACT = {"FAVOURABLE": 0.40, "MODERATE": 0.60, "DIFFICULT": 0.80, "SEVERE": 0.90}
GROUND_ROCK = {"NONE": 0.0, "LIGHT": 0.10, "MODERATE": 0.20, "EXTENSIVE": 0.30}
GROUND_WATER = {"LOW": 0.0, "MODERATE": 0.15, "HIGH": 0.30}
GROUND_SLOPE = {"LOW": 0.0, "MODERATE": 0.15, "HIGH": 0.30}

def eval_ground(project, inputs, d):
    g = inputs["ground"]
    cond = _enum_prob(GROUND_CONDITION_PROB, g.get("condition"))
    rock = _enum_prob(GROUND_ROCK, g.get("rockExcavation")) or 0
    water = _enum_prob(GROUND_WATER, g.get("groundwater")) or 0
    slope = _enum_prob(GROUND_SLOPE, g.get("landslidePotential")) or 0
    avail = _branch_available(g)
    prob = (cond if cond is not None else 0.05) + rock + water + slope
    prob = float(_clamp(prob, 0.0, 1.0))
    impact = _enum_prob(GROUND_CONDITION_IMPACT, g.get("condition"))
    if impact is None:
        impact = 0.8 if (rock >= 0.2 or slope >= 0.3 or water >= 0.3) else 0.5
    reasons = []
    if cond is not None and cond >= 0.55:
        reasons.append("Difficult geological / ground conditions")
    if rock >= 0.2:
        reasons.append("Extensive rock excavation expected")
    if water >= 0.3:
        reasons.append("High groundwater encountered")
    if slope >= 0.3:
        reasons.append("Landslide-prone terrain")
    reason = "; ".join(reasons) or ("Ground conditions are manageable" if avail else "No ground condition data recorded")
    conditions = []
    if cond is not None and cond >= 0.55:
        conditions.append(f"Ground condition: {g.get('condition')}")
    if rock >= 0.2:
        conditions.append(f"Rock excavation: {g.get('rockExcavation')}")
    if water >= 0.3:
        conditions.append(f"Groundwater: {g.get('groundwater')}")
    if slope >= 0.3:
        conditions.append(f"Landslide potential: {g.get('landslidePotential')}")
    return _factor_result("ground", prob, impact, reason, avail, conditions=conditions)


# factor 7 - natural calamity
HAZARD_LEVEL = {"LOW": 0.10, "MODERATE": 0.35, "HIGH": 0.70}

def eval_calamity(project, inputs, d):
    cal = inputs["calamity"]
    haz_keys = ["floodExposure", "earthquakeExposure", "cycloneExposure", "landslideExposure", "droughtExposure"]
    haz = {k: _enum_prob(HAZARD_LEVEL, cal.get(k)) for k in haz_keys}
    avail = _branch_available(cal)
    present = [p for p in haz.values() if p is not None]
    if not present:
        return _factor_result("calamity", None, 0.8, "No hazard exposure data recorded", False)
    prob = max(present)
    high_count = sum(1 for p in present if p >= 0.70)
    prob = min(1.0, prob + high_count * 0.05)
    impact = 0.80 + (0.1 if high_count >= 2 else 0.0)
    names = {
        "floodExposure": "flooding", "earthquakeExposure": "earthquake",
        "cycloneExposure": "cyclones", "landslideExposure": "landslides",
        "droughtExposure": "drought",
    }
    elevated = [names[k] for k, p in haz.items() if p is not None and p >= 0.35]
    reason = f"Site exposure to {', '.join(elevated)}" if elevated else "Low natural hazard exposure"
    conditions = [
        f"{names[k]} exposure: {cal.get(k)}"
        for k, p in haz.items() if p is not None and p >= 0.35
    ]
    return _factor_result("calamity", prob, impact, reason, avail, conditions=conditions)


# factor 8 - material
MATERIAL_AVAILABILITY = {"ADEQUATE": 0.05, "TIGHT": 0.25, "SHORTAGE": 0.50, "SEVERE_SHORTAGE": 0.80}

def eval_material(project, inputs, d):
    m = inputs["material"]
    avail = _branch_available(m)
    prob = _enum_prob(MATERIAL_AVAILABILITY, m.get("availability")) or 0.05
    prob += min(0.25, (_int(m.get("qualityIssues")) or 0) * 0.08)
    price = _num(m.get("priceIncreasePct")) or 0
    prob += min(0.30, price * 0.01)
    if m.get("criticalMaterial"):
        prob += 0.12
    prob = min(1.0, prob)
    impact = 0.70 if (m.get("availability") == "SEVERE_SHORTAGE" or m.get("criticalMaterial")) else 0.60
    reasons = []
    if prob >= 0.5:
        reasons.append("Material supply is a major constraint")
    if price >= 8:
        reasons.append(f"Material price escalation of ~{price:.0f}%")
    if m.get("qualityIssues"):
        reasons.append(f"{_int(m.get('qualityIssues') or 0)} quality inspection failures")
    reason = "; ".join(reasons) or ("Material supply is healthy" if avail else "No material data recorded")
    conditions = []
    if m.get("availability") and m.get("availability") != "ADEQUATE":
        conditions.append(f"Material availability: {m.get('availability')}")
    if price > 0:
        conditions.append(f"Material price increase: {price:.1f}%")
    if m.get("qualityIssues"):
        conditions.append(f"Quality inspection failures: {_int(m.get('qualityIssues')) or 0}")
    if m.get("criticalMaterial"):
        conditions.append("Critical material dependency recorded")
    return _factor_result("material", prob, impact, reason, avail, conditions=conditions)


# factor 9 - workforce
WF_AVAILABILITY = {"ADEQUATE": 0.05, "SHORTAGE": 0.45, "SEVERE_SHORTAGE": 0.75}
WF_SKILLED = {"ADEQUATE": 0.05, "SHORTAGE": 0.40, "SEVERE_SHORTAGE": 0.70}
WF_PRODUCTIVITY = {"HIGH": 0.05, "NORMAL": 0.15, "LOW": 0.45, "VERY_LOW": 0.70}
WF_ABSENTEEISM = {"LOW": 0.05, "MODERATE": 0.25, "HIGH": 0.50}

def eval_workforce(project, inputs, d):
    w = inputs["workforce"]
    avail = _branch_available(w)
    signals = []
    for mapping, key in ((WF_AVAILABILITY, "availability"), (WF_SKILLED, "skilledAvailability"),
                         (WF_PRODUCTIVITY, "productivity"), (WF_ABSENTEEISM, "absenteeism")):
        p = _enum_prob(mapping, w.get(key))
        if p is not None:
            signals.append(p)
    prob = max(signals) if signals else 0.05
    prob += min(0.20, (_num(w.get("turnoverPct")) or 0) * 0.01)
    prob += min(0.20, (_int(w.get("safetyIncidentCount")) or 0) * 0.05)
    prob = min(1.0, prob)
    low_prod = str(w.get("productivity") or "").upper() in ("LOW", "VERY_LOW")
    severe = str(w.get("availability") or "").upper() == "SEVERE_SHORTAGE" \
        or str(w.get("skilledAvailability") or "").upper() == "SEVERE_SHORTAGE"
    impact = 0.75 if (low_prod or severe) else 0.55
    reasons = []
    if str(w.get("skilledAvailability") or "").upper() in ("SHORTAGE", "SEVERE_SHORTAGE"):
        reasons.append("Skilled labour availability is a constraint")
    if low_prod:
        reasons.append("Workforce productivity is low")
    if w.get("safetyIncidentCount"):
        reasons.append(f"{_int(w.get('safetyIncidentCount')) or 0} safety incidents reported")
    reason = "; ".join(reasons) or ("Workforce is adequate" if avail else "No workforce data recorded")
    conditions = []
    if str(w.get("availability") or "").upper() in ("SHORTAGE", "SEVERE_SHORTAGE"):
        conditions.append(f"Workforce availability: {w.get('availability')}")
    if str(w.get("skilledAvailability") or "").upper() in ("SHORTAGE", "SEVERE_SHORTAGE"):
        conditions.append(f"Skilled labour availability: {w.get('skilledAvailability')}")
    if low_prod:
        conditions.append(f"Workforce productivity: {w.get('productivity')}")
    if w.get("turnoverPct"):
        conditions.append(f"Workforce turnover: {w.get('turnoverPct')}%")
    if w.get("safetyIncidentCount"):
        conditions.append(f"Safety incidents: {_int(w.get('safetyIncidentCount')) or 0}")
    return _factor_result("workforce", prob, impact, reason, avail, conditions=conditions)


# factor 10 - contractor performance
CONTRACTOR_PERFORMANCE = {"EXCELLENT": 0.05, "GOOD": 0.15, "FAIR": 0.40, "POOR": 0.65, "CRITICAL": 0.85}
CONTRACTOR_FINANCIAL = {"NONE": 0.0, "MODERATE": 0.25, "HIGH": 0.55}

def eval_contractor(project, inputs, d):
    c = inputs["contractor"]
    avail = _branch_available(c)
    perf_prob = _enum_prob(CONTRACTOR_PERFORMANCE, c.get("performance"))
    prob = perf_prob if perf_prob is not None else 0.15
    prob += min(0.25, (_int(c.get("delayedMilestoneCount")) or 0) * 0.04)
    prob += min(0.20, (_int(c.get("qualityIssueCount")) or 0) * 0.06)
    prob += min(0.20, (_int(c.get("complianceIssueCount")) or 0) * 0.10)
    prob += _enum_prob(CONTRACTOR_FINANCIAL, c.get("financialStress")) or 0.0
    prob += min(0.20, (_int(c.get("unresolvedIssueCount")) or 0) * 0.04)
    prob = min(1.0, prob)
    perf = str(c.get("performance") or "").upper()
    impact = 0.60
    if perf == "CRITICAL":
        impact = 0.95
    elif perf in ("POOR",) or (_int(c.get("delayedMilestoneCount")) or 0) >= 5:
        impact = 0.85
    elif perf == "FAIR":
        impact = 0.70
    reasons = []
    if perf in ("POOR", "CRITICAL"):
        reasons.append("Contractor performance is poor / critical")
    elif c.get("delayedMilestoneCount"):
        reasons.append(f"{_int(c.get('delayedMilestoneCount')) or 0} milestones delayed by the contractor")
    if c.get("financialStress"):
        reasons.append("Contractor faces financial stress")
    if c.get("unresolvedIssueCount"):
        reasons.append(f"{_int(c.get('unresolvedIssueCount')) or 0} unresolved contractor issues")
    reason = "; ".join(reasons) or ("Contractor performance is satisfactory" if avail else "No contractor data recorded")
    conditions = []
    if perf in ("POOR", "CRITICAL"):
        conditions.append(f"Contractor performance: {perf}")
    if c.get("delayedMilestoneCount"):
        conditions.append(f"Contractor-delayed milestones: {_int(c.get('delayedMilestoneCount')) or 0}")
    if c.get("qualityIssueCount"):
        conditions.append(f"Contractor quality issues: {_int(c.get('qualityIssueCount')) or 0}")
    if c.get("complianceIssueCount"):
        conditions.append(f"Contractor compliance issues: {_int(c.get('complianceIssueCount')) or 0}")
    if str(c.get("financialStress") or "").upper() not in ("", "NONE"):
        conditions.append(f"Contractor financial stress: {c.get('financialStress')}")
    if c.get("unresolvedIssueCount"):
        conditions.append(f"Unresolved contractor issues: {_int(c.get('unresolvedIssueCount')) or 0}")
    return _factor_result("contractor", prob, impact, reason, avail, conditions=conditions)


# factor 11 - engineering / design
ENG_REWORK = {"NONE": 0.05, "LOW": 0.20, "MODERATE": 0.40, "HIGH": 0.65}
ENG_COMPLEXITY = {"LOW": 0.05, "MODERATE": 0.25, "HIGH": 0.50}

def eval_engineering(project, inputs, d):
    e = inputs["engineering"]
    avail = _branch_available(e)
    rework_prob = _enum_prob(ENG_REWORK, e.get("reworkLevel"))
    prob = rework_prob if rework_prob is not None else 0.05
    prob += min(0.25, (_int(e.get("designChangeCount")) or 0) * 0.05)
    prob += min(0.30, (_int(e.get("designErrorCount")) or 0) * 0.08)
    comp = _enum_prob(ENG_COMPLEXITY, e.get("technicalComplexity"))
    if comp is not None:
        prob += max(0.0, comp - 0.25)
    if e.get("approvalPending"):
        prob += 0.20
    prob = min(1.0, prob)
    impact = 0.60
    if (str(e.get("reworkLevel") or "").upper() == "HIGH") or (_int(e.get("designErrorCount")) or 0) >= 3:
        impact = 0.85
    reasons = []
    if e.get("designChangeCount"):
        reasons.append(f"{_int(e.get('designChangeCount')) or 0} design changes requested")
    if e.get("designErrorCount"):
        reasons.append(f"{_int(e.get('designErrorCount')) or 0} design errors found")
    if str(e.get("reworkLevel") or "").upper() == "HIGH":
        reasons.append("High amount of rework")
    reason = "; ".join(reasons) or ("Design is stable" if avail else "No engineering data recorded")
    conditions = []
    if str(e.get("reworkLevel") or "").upper() not in ("", "NONE"):
        conditions.append(f"Rework level: {e.get('reworkLevel')}")
    if e.get("designChangeCount"):
        conditions.append(f"Design changes: {_int(e.get('designChangeCount')) or 0}")
    if e.get("designErrorCount"):
        conditions.append(f"Design errors: {_int(e.get('designErrorCount')) or 0}")
    if e.get("technicalComplexity"):
        conditions.append(f"Technical complexity: {e.get('technicalComplexity')}")
    if e.get("approvalPending"):
        conditions.append("Design approval pending")
    return _factor_result("engineering", prob, impact, reason, avail, conditions=conditions)


# factor 12 - land & environmental clearance
ENV_CLEARANCE = {"CLEARED": 0.05, "NOT_REQUIRED": 0.05, "PENDING": 0.55, "REJECTED": 0.90}
FOREST_CLEARANCE = {"CLEARED": 0.05, "NOT_REQUIRED": 0.05, "PENDING": 0.50}

def eval_clearance(project, inputs, d):
    cl = inputs["clearance"]
    avail = _branch_available(cl)
    land_pct = _num(cl.get("landAcquiredPct"))
    env = _enum_prob(ENV_CLEARANCE, cl.get("environmentalClearance"))
    forest = _enum_prob(FOREST_CLEARANCE, cl.get("forestClearance"))
    if land_pct is None and env is None and forest is None:
        return _factor_result("clearance", None, 0.8, "No land/clearance information recorded", False)
    prob = 0.0
    if land_pct is not None:
        short = _clamp((100 - land_pct) / 100.0, 0, 1)
        prob = short * 0.80
    if env is not None:
        prob = 1.0 - (1.0 - prob) * (1.0 - env)
    if forest is not None:
        prob = 1.0 - (1.0 - prob) * (1.0 - forest)
    if cl.get("rehabilitationPending"):
        prob = 1.0 - (1.0 - prob) * 0.20
    prob = min(1.0, prob)
    impact = 0.80
    if env is not None and env >= 0.55:
        impact = 1.0 if env >= 0.90 else 0.90
    reasons = []
    if land_pct is not None and land_pct < 100:
        reasons.append(f"Land acquisition is only {land_pct:.0f}% complete - project cannot proceed on remaining land")
    if str(cl.get("environmentalClearance") or "").upper() == "PENDING":
        reasons.append("Environmental clearance is pending")
    if str(cl.get("environmentalClearance") or "").upper() == "REJECTED":
        reasons.append("Environmental clearance has been rejected")
    if land_pct is not None and land_pct >= 100 and env in (0.05,):
        reasons.append("Land and clearances are fully in place")
    reason = "; ".join(reasons) or ("Land and clearances in place" if avail else "No clearance data recorded")
    conditions = []
    if land_pct is not None and land_pct < 100:
        conditions.append(f"Land acquired: {land_pct:.0f}%")
    if str(cl.get("environmentalClearance") or "").upper() in ("PENDING", "REJECTED"):
        conditions.append(f"Environmental clearance: {cl.get('environmentalClearance')}")
    if forest is not None and forest >= 0.50:
        conditions.append(f"Forest clearance: {cl.get('forestClearance')}")
    if cl.get("rehabilitationPending"):
        conditions.append("Rehabilitation obligation pending")
    return _factor_result("clearance", prob, impact, reason, avail, conditions=conditions)


# factor 13 - government / administrative
ADMIN_TURNAROUND = {"FAST": 0.05, "NORMAL": 0.20, "SLOW": 0.50, "BLOCKED": 0.85}
ADMIN_DEPENDENCY = {"LOW": 0.05, "MODERATE": 0.30, "HIGH": 0.55}

def eval_administrative(project, inputs, d):
    a = inputs["administrative"]
    avail = _branch_available(a)
    prob = 0.1
    turn = _enum_prob(ADMIN_TURNAROUND, a.get("turnaround"))
    if turn is not None:
        prob = turn
    prob += min(0.40, (_int(a.get("pendingApprovalCount")) or 0) * 0.08)
    dep = _enum_prob(ADMIN_DEPENDENCY, a.get("interDepartmentDependency"))
    if dep is not None:
        prob += dep
    if a.get("procurementDelay"):
        prob += 0.15
    prob = min(1.0, prob)
    impact = 0.85 if turn is not None and turn >= 0.85 else 0.60
    reasons = []
    if a.get("pendingApprovalCount"):
        reasons.append(f"{_int(a.get('pendingApprovalCount')) or 0} approvals pending")
    if str(a.get("turnaround") or "").upper() in ("SLOW", "BLOCKED"):
        reasons.append("Approval turnaround is slow / blocked")
    if str(a.get("interDepartmentDependency") or "").upper() == "HIGH":
        reasons.append("Heavy inter-department dependencies")
    if a.get("procurementDelay"):
        reasons.append("Procurement is delayed")
    reason = "; ".join(reasons) or ("Approvals are progressing normally" if avail else "No administrative data recorded")
    conditions = []
    if str(a.get("turnaround") or "").upper() in ("SLOW", "BLOCKED"):
        conditions.append(f"Approval turnaround: {a.get('turnaround')}")
    if a.get("pendingApprovalCount"):
        conditions.append(f"Pending approvals: {_int(a.get('pendingApprovalCount')) or 0}")
    if dep is not None and dep >= 0.30:
        conditions.append(f"Inter-department dependency: {a.get('interDepartmentDependency')}")
    if a.get("procurementDelay"):
        conditions.append("Procurement delay recorded")
    return _factor_result("administrative", prob, impact, reason, avail, conditions=conditions)


# factor 14 - supply chain
SC_ACCESS = {"GOOD": 0.05, "MODERATE": 0.20, "POOR": 0.45, "REMOTE": 0.60}
SC_SUPPLIER = {"LOW": 0.05, "MODERATE": 0.20, "HIGH": 0.40}
SC_EQUIPMENT = {"ADEQUATE": 0.05, "TIGHT": 0.30, "SHORTAGE": 0.60}

def eval_supply_chain(project, inputs, d):
    s = inputs["supply_chain"]
    avail = _branch_available(s)
    prob = 0.05
    acc = _enum_prob(SC_ACCESS, s.get("accessibility"))
    sup = _enum_prob(SC_SUPPLIER, s.get("supplierDependency"))
    eq = _enum_prob(SC_EQUIPMENT, s.get("equipmentAvailability"))
    if sup is not None:
        prob += sup
    if s.get("importDependency"):
        prob += 0.15
    prob += min(0.30, (_int(s.get("deliveryDelayCount")) or 0) * 0.10)
    if eq is not None:
        prob += eq
    # Remoteness alone must not be penalized; only when it produces measurable friction.
    if acc in (0.45, 0.60) and ((_int(s.get("deliveryDelayCount")) or 0) > 0 or eq in (0.30, 0.60)):
        prob += 0.10
    prob = min(1.0, prob)
    impact = 0.75 if eq == 0.60 else 0.55
    reasons = []
    if prob >= 0.5:
        reasons.append("Logistics / supply friction is material")
    if str(s.get("supplierDependency") or "").upper() == "HIGH":
        reasons.append("High dependency on few suppliers")
    if s.get("importDependency"):
        reasons.append("Critical imports involved")
    if s.get("deliveryDelayCount"):
        reasons.append(f"{_int(s.get('deliveryDelayCount')) or 0} delivery delays observed")
    reason = "; ".join(reasons) or ("Logistics are reliable" if avail else "No supply chain data recorded")
    conditions = []
    if sup is not None and sup >= 0.20:
        conditions.append(f"Supplier dependency: {s.get('supplierDependency')}")
    if eq is not None and eq >= 0.30:
        conditions.append(f"Equipment availability: {s.get('equipmentAvailability')}")
    if s.get("importDependency"):
        conditions.append("Critical import dependency recorded")
    if s.get("deliveryDelayCount"):
        conditions.append(f"Delivery delays: {_int(s.get('deliveryDelayCount')) or 0}")
    if acc is not None and acc >= 0.45:
        conditions.append(f"Site accessibility: {s.get('accessibility')}")
    return _factor_result("supply_chain", prob, impact, reason, avail, conditions=conditions)


# factor 15 - legal / social
SOCIAL_OPPOSITION = {"NONE": 0.05, "LOW": 0.15, "MODERATE": 0.40, "HIGH": 0.70}

def eval_legal_social(project, inputs, d):
    ls = inputs["legal_social"]
    avail = _branch_available(ls)
    prob = 0.05
    opp = _enum_prob(SOCIAL_OPPOSITION, ls.get("oppositionLevel"))
    if opp is not None:
        prob = opp
    prob += min(0.30, (_int(ls.get("activeDisputeCount")) or 0) * 0.12)
    prob += min(0.25, (_int(ls.get("protestCount")) or 0) * 0.12)
    comp = _num(ls.get("unresolvedCompensation"))
    if comp:
        prob += min(0.20, comp * 0.04)
    if ls.get("courtStay"):
        prob = 1.0
    if ls.get("rehabilitationOutstanding"):
        prob = min(1.0, prob + 0.15)
    prob = min(1.0, prob)
    impact = 1.0 if ls.get("courtStay") else 0.60
    if (_int(ls.get("activeDisputeCount")) or 0) >= 3:
        impact = max(impact, 0.80)
    reasons = []
    if ls.get("courtStay"):
        reasons.append("Active court stay affecting construction")
    if ls.get("activeDisputeCount"):
        reasons.append(f"{_int(ls.get('activeDisputeCount')) or 0} active disputes")
    if str(ls.get("oppositionLevel") or "").upper() in ("MODERATE", "HIGH"):
        reasons.append("Local opposition to the project")
    if comp:
        reasons.append("Compensation payments outstanding")
    reason = "; ".join(reasons) or ("No legal or social issues" if avail else "No legal/social data recorded")
    conditions = []
    if str(ls.get("oppositionLevel") or "").upper() in ("MODERATE", "HIGH"):
        conditions.append(f"Local opposition: {ls.get('oppositionLevel')}")
    if ls.get("activeDisputeCount"):
        conditions.append(f"Active disputes: {_int(ls.get('activeDisputeCount')) or 0}")
    if ls.get("protestCount"):
        conditions.append(f"Protests recorded: {_int(ls.get('protestCount')) or 0}")
    if comp:
        conditions.append(f"Unresolved compensation: {comp}")
    if ls.get("courtStay"):
        conditions.append("Active court stay recorded")
    if ls.get("rehabilitationOutstanding"):
        conditions.append("Rehabilitation obligation outstanding")
    return _factor_result("legal_social", prob, impact, reason, avail, conditions=conditions)


FACTOR_EVALUATORS = {
    "budget": eval_budget,
    "schedule": eval_schedule,
    "completion": eval_completion,
    "financial": eval_financial,
    "weather": eval_weather,
    "ground": eval_ground,
    "calamity": eval_calamity,
    "material": eval_material,
    "workforce": eval_workforce,
    "contractor": eval_contractor,
    "engineering": eval_engineering,
    "clearance": eval_clearance,
    "administrative": eval_administrative,
    "supply_chain": eval_supply_chain,
    "legal_social": eval_legal_social,
}


# --------------------------------------------------------------------------
# interactions, blockers, recommendations, explanations
# --------------------------------------------------------------------------

def evaluate_interactions(factors, inputs):
    by_key = {f["key"]: f["score"] for f in factors}
    triggered = []
    for rule in CFG.INTERACTION_RULES:
        ok = True
        for factor_key, min_score in rule["conditions"]:
            if by_key.get(factor_key, 0) < min_score:
                ok = False
                break
        if ok:
            triggered.append({
                "key": rule["key"],
                "trigger": rule["key"],
                "name": rule["label"],
                "affectedFactors": [factor_key for factor_key, _ in rule["conditions"]],
                "triggeredConditions": [
                    f"{factor_key} >= {min_score}" for factor_key, min_score in rule["conditions"]
                ],
                "penalty": rule["penalty"],
                "reason": rule["reason"],
                "explanation": rule["reason"],
            })
    return triggered


def _blocker_matches(rule_key, inputs):
    ls = inputs["legal_social"]
    cl = inputs["clearance"]
    co = inputs["contractor"]
    ad = inputs["administrative"]
    en = inputs["engineering"]
    we = inputs["weather"]
    ca = inputs["calamity"]

    if rule_key == "court_stay":
        return ls.get("courtStay") is True
    if rule_key == "environmental_rejected":
        return str(cl.get("environmentalClearance") or "").upper() == "REJECTED"
    if rule_key == "environmental_pending":
        return str(cl.get("environmentalClearance") or "").upper() == "PENDING"
    if rule_key == "land_blocked":
        pct = _num(cl.get("landAcquiredPct"))
        return pct is not None and pct < 40
    if rule_key == "contractor_critical":
        return str(co.get("performance") or "").upper() == "CRITICAL"
    if rule_key == "approval_blocked":
        return str(ad.get("turnaround") or "").upper() == "BLOCKED" and (_int(ad.get("pendingApprovalCount")) or 0) > 0
    if rule_key == "severe_design_failure":
        return str(en.get("reworkLevel") or "").upper() == "HIGH" and (_int(en.get("designErrorCount")) or 0) >= 3
    if rule_key == "severe_natural_disaster":
        cal = [c for c in ("floodExposure", "earthquakeExposure", "cycloneExposure", "landslideExposure", "droughtExposure")
               if _enum_prob(HAZARD_LEVEL, ca.get(c)) is not None and _enum_prob(HAZARD_LEVEL, ca.get(c)) >= 0.70]
        severe_weather = str(we.get("condition") or "").upper() == "SEVERE"
        return bool(cal) and severe_weather
    return False


def evaluate_blockers(inputs):
    matched = []
    for rule in CFG.BLOCKER_RULES:
        if _blocker_matches(rule["key"], inputs):
            minimum_score = (
                CFG.BLOCKER_CRITICAL_FLOOR
                if rule["level"] == "CRITICAL"
                else CFG.BLOCKER_HIGH_FLOOR
            )
            matched.append({
                "key": rule["key"],
                "blocker": rule["key"],
                "level": rule["level"],
                "severity": rule["level"],
                "minimumScore": minimum_score,
                "reason": rule["reason"],
                "explanation": rule["reason"],
                "recommendation": rule["recommendation"],
            })
    return matched


RECOMMENDATIONS = [
    ("budget", 60, "Conduct a cost variance review and reassess the remaining budget"),
    ("schedule", 60, "Review the critical path and establish a recovery schedule"),
    ("completion", 60, "Prepare a completion recovery plan to close the progress gap"),
    ("financial", 50, "Review expenditure against physical progress and investigate any mismatch"),
    ("weather", 50, "Plan construction schedules around weather windows and protect completed works"),
    ("ground", 50, "Commission a geotechnical review and adjust construction methodology"),
    ("calamity", 50, "Strengthen disaster mitigation measures and review site vulnerability"),
    ("material", 50, "Identify alternate suppliers for critical materials and tighten quality checks"),
    ("workforce", 50, "Address skilled labour availability and productivity shortfalls"),
    ("contractor", 55, "Initiate a contractor performance review and enforce recovery commitments"),
    ("engineering", 50, "Implement design change control and freeze scope to stop rework"),
    ("clearance", 50, "Escalate pending land acquisition / environmental clearance issues"),
    ("administrative", 50, "Escalate pending approvals to the responsible department"),
    ("supply_chain", 50, "Secure alternate logistics routes and reduce supplier dependency"),
    ("legal_social", 45, "Resolve outstanding disputes and compensation issues through mediation"),
]


def build_recommendations(factors, blockers, level):
    by_key = {f["key"]: f["score"] for f in factors}
    recs = []
    for key, threshold, text in RECOMMENDATIONS:
        if by_key.get(key, 0) >= threshold and text not in recs:
            recs.append(text)
    if by_key.get("budget", 0) >= 55 and by_key.get("financial", 0) >= 45 and \
            "Escalate for a financial intervention review" not in recs:
        recs.append("Escalate for a financial intervention review")
    if by_key.get("clearance", 0) >= 45 and by_key.get("administrative", 0) >= 45 and by_key.get("schedule", 0) >= 55 and \
            "Convene an inter-departmental task force" not in recs:
        recs.append("Convene an inter-departmental task force for the implementation blockage")
    for b in blockers:
        if b["recommendation"] not in recs:
            recs.append(b["recommendation"])
    if level in ("HIGH", "CRITICAL"):
        recs.append("Schedule a joint monitoring committee review")
    if not recs and level == "LOW":
        recs.append("Continue routine monitoring and monthly status reporting")
    return recs[:10]


def build_explanations(project, final, level, factors, interactions, blockers):
    by_key = {f["key"]: f["score"] for f in factors}
    lines = [f"Project risk is {level} with a score of {final}/100."]
    top = sorted(factors, key=lambda f: f["contribution"], reverse=True)[:3]
    for f in top:
        lines.append(f"{f['name']} ({f['score']}/100): {f['reason']}")
    if interactions:
        for it in sorted(interactions, key=lambda x: x["penalty"], reverse=True):
            lines.append(f"Interaction: {it['name']} added {it['penalty']} risk points.")
    for b in blockers:
        lines.append(f"Critical blocker: {b['reason']}.")
    return lines


def overall_level(score):
    for floor, label in CFG.OVERALL_BANDS:
        if score >= floor:
            return label
    return "LOW"


# --------------------------------------------------------------------------
# main entry point
# --------------------------------------------------------------------------

def assess_project(project, now=None):
    """Compute the full explainable risk assessment for a Project object."""
    inputs = _normalize_inputs(project)
    d = _derived(project, now)
    factors = [FACTOR_EVALUATORS[k](project, inputs, d) for k in CFG.FACTOR_WEIGHTS]

    base = round(sum(f["score"] * f["weight"] for f in factors) / 100.0, 4)
    interactions = evaluate_interactions(factors, inputs)
    penalty = min(sum(i["penalty"] for i in interactions), CFG.MAX_INTERACTION_PENALTY)

    # Dominant-risk exposure: a single severe factor must not be masked by
    # many healthy lower-weight factors (see risk_config.TOP_FACTOR_BOOST_*).
    top_factor_score = max(f["score"] for f in factors)
    boost = min(
        top_factor_score * CFG.TOP_FACTOR_BOOST_SHARE,
        CFG.TOP_FACTOR_BOOST_CAP,
    )

    blockers = evaluate_blockers(inputs)
    blocker_floor = 0
    for b in blockers:
        floor = CFG.BLOCKER_CRITICAL_FLOOR if b["level"] == "CRITICAL" else CFG.BLOCKER_HIGH_FLOOR
        blocker_floor = max(blocker_floor, floor)

    raw_score = round(_clamp(base + penalty + boost, 0, 100))
    final = max(raw_score, blocker_floor) if blocker_floor else raw_score
    final = int(_clamp(final, 0, 100))
    level = overall_level(final)

    available_weight = sum(f["weight"] for f in factors if f["dataAvailable"])
    completeness = round(available_weight)  # weight-basis percent (weights total 100)

    total_factors = len(factors)
    available_factors = [f for f in factors if f["dataAvailable"]]
    missing_factors = [f for f in factors if not f["dataAvailable"]]
    factor_completeness = (
        round(len(available_factors) / total_factors * 100) if total_factors else 0
    )
    data_quality = {
        "totalFactors": total_factors,
        "availableFactors": len(available_factors),
        "missingFactors": len(missing_factors),
        "completeness": factor_completeness,
        "weightedCompleteness": completeness,
        "availableFactorKeys": [f["key"] for f in available_factors],
        "missingFactorKeys": [f["key"] for f in missing_factors],
        "missingFactorNames": [f["name"] for f in missing_factors],
    }
    assessment_status = "COMPLETE" if not missing_factors else "INSUFFICIENT_DATA"
    risk_level_provisional = bool(missing_factors)
    calculated_at = now.isoformat() if now else datetime.now(timezone.utc).isoformat()

    top = sorted(factors, key=lambda f: f["contribution"], reverse=True)[:3]
    top_risk_factors = top
    missing = [f["name"] for f in missing_factors]
    recommendations = build_recommendations(factors, blockers, level)
    explanations = build_explanations(project, final, level, factors, interactions, blockers)
    configured_interaction_penalty = sum(i["penalty"] for i in interactions)

    budget_prob = next(f for f in factors if f["key"] == "budget")["probability"]
    schedule_prob = next(f for f in factors if f["key"] == "schedule")["probability"]

    return {
        "projectId": project.id,
        "riskScore": final,
        "riskLevel": level,
        "confidence": completeness,
        "dataCompleteness": completeness,
        "criticalBlocker": bool(blockers),
        "criticalBlockerReasons": [b["reason"] for b in blockers],
        "factors": factors,
        "interactions": interactions,
        "blockers": blockers,
        "topRisks": [f["name"] for f in top],
        "topRiskFactors": top_risk_factors,
        "recommendations": recommendations,
        "explanations": explanations,
        "missingData": missing,
        "dataQuality": data_quality,
        "assessmentStatus": assessment_status,
        "riskLevelProvisional": risk_level_provisional,
        "interactionPenalty": penalty,
        "blockerFloor": blocker_floor,
        "scoreBreakdown": {
            "weightedBase": base,
            "interactionPenalty": penalty,
            "interactionPenaltyConfigured": configured_interaction_penalty,
            "interactionPenaltyCap": CFG.MAX_INTERACTION_PENALTY,
            "dominantFactorBoost": round(boost, 2),
            "blockerFloor": blocker_floor,
            "rawScore": raw_score,
            "finalScore": final,
        },
        "engineVersion": CFG.ENGINE_VERSION,
        "contractVersion": CFG.RISK_CONTRACT_VERSION,
        "assessedAt": calculated_at,
        "riskTrend": {
            "available": False,
            "note": "No historical risk snapshots exist yet",
        },
        "costOverrunProbability": round((budget_prob or 0.0) * 100),
        "delayProbability": round((schedule_prob or 0.0) * 100),
        "implementationRisk": round((base or 0.0)),
        "calculatedAt": calculated_at,
    }


def predicted_completion_date(project, delay_probability):
    """Deterministic shift of expected completion based on delay intensity."""
    expected = project.expected_completion
    months = 0
    if delay_probability >= 60:
        months = 12
    elif delay_probability >= 40:
        months = 6
    elif delay_probability >= 25:
        months = 3
    if months == 0:
        return expected
    d = _date(expected)
    if not d:
        return expected
    year = d.year + (d.month - 1 + months) // 12
    month = (d.month - 1 + months) % 12 + 1
    try:
        shifted = d.replace(year=year, month=month)
    except ValueError:
        shifted = d.replace(year=year, month=month, day=28)
    return shifted.strftime("%Y-%m-%d")


def apply_assessment(project, predicted=None):
    """Compute the assessment for an ORM `project` and persist the cached
    risk columns on the row. Pure deterministic - the serializer always
    recomputes too, so stored values act as a durable snapshot."""
    assessment = assess_project(project)
    project.risk_score = float(assessment["riskScore"])
    project.risk_level = assessment["riskLevel"]
    project.cost_overrun_probability = float(assessment["costOverrunProbability"])
    project.delay_probability = float(assessment["delayProbability"])
    project.implementation_risk = float(assessment["implementationRisk"])
    project.risk_factors = json.dumps(assessment["explanations"])
    project.recommendations = json.dumps(assessment["recommendations"])
    project.risk_confidence = float(assessment["confidence"])
    project.risk_report = json.dumps(assessment)
    if predicted is not None:
        project.predicted_completion = predicted
    elif not project.predicted_completion:
        project.predicted_completion = predicted_completion_date(
            project, assessment["delayProbability"]
        )
    return assessment


# --------------------------------------------------------------------------
# legacy-compatible analytics + assistant (kept, now engine-driven)
# --------------------------------------------------------------------------

def get_project_analytics(db: Session):
    projects = db.query(Project).all()
    if not projects:
        return {
            "sectorAnalytics": [],
            "ministryRankings": [],
            "scatterData": [],
            "riskTrends": [],
            "topRiskFactors": [],
            "riskByState": [],
            "scheduleGapScatter": [],
        }

    assessments = {p.id: assess_project(p) for p in projects}

    # Factor aggregate across the portfolio
    factor_totals = {}
    for a in assessments.values():
        for f in a["factors"]:
            acc = factor_totals.setdefault(f["key"], {"name": f["name"], "sum": 0, "n": 0})
            acc["sum"] += f["score"]
            acc["n"] += 1
    top_factors = sorted(
        (
            {"key": k, "name": v["name"], "avgScore": round(v["sum"] / v["n"], 1)}
            for k, v in factor_totals.items() if v["n"]
        ),
        key=lambda x: x["avgScore"],
        reverse=True,
    )[:10]

    sector_map = {}
    for p in projects:
        sector_map.setdefault(p.sector, []).append(p)

    sector_analytics = []
    for sector, projs in sorted(sector_map.items()):
        avg_risk = round(sum(assessments[p.id]["riskScore"] for p in projs) / len(projs), 1)
        avg_cost = round(sum(((p.current_cost - p.original_cost) / p.original_cost * 100)
                             for p in projs if p.original_cost) / len(projs), 1)
        avg_delay = round(
            sum(assessments[p.id]["delayProbability"] for p in projs) / len(projs), 1
        )
        sector_analytics.append({
            "sector": sector,
            "avgRisk": avg_risk,
            "projectCount": len(projs),
            "avgCostOverrun": avg_cost,
            "avgDelay": avg_delay,
        })

    ministry_map = {}
    for p in projects:
        ministry_map.setdefault(p.ministry, []).append(p)
    ministry_list = []
    for ministry, projs in ministry_map.items():
        avg_risk = round(sum(assessments[p.id]["riskScore"] for p in projs) / len(projs), 1)
        high_count = sum(
            1 for p in projs if assessments[p.id]["riskLevel"] in ("HIGH", "CRITICAL")
        )
        ministry_list.append({
            "ministry": ministry,
            "projectCount": len(projs),
            "avgRisk": avg_risk,
            "highRiskCount": high_count,
        })
    ministry_list.sort(key=lambda x: x["avgRisk"], reverse=True)
    for i, m in enumerate(ministry_list, 1):
        m["rank"] = i

    scatter = []
    for p in projects:
        cost_overrun = round((p.current_cost - p.original_cost) / p.original_cost * 100, 1) if p.original_cost else 0.0
        scatter.append({
            "name": p.name,
            "physicalProgress": round(p.physical_progress, 1),
            "progressGap": round(100 - p.physical_progress, 1),
            "costOverrun": cost_overrun,
            "riskScore": assessments[p.id]["riskScore"],
            "sector": p.sector,
        })

    schedule_gap_scatter = []
    for p in projects:
        schedule_gap = round(max(0.0, (p.planned_progress or 0) - (p.physical_progress or 0)), 1)
        schedule_gap_scatter.append({
            "name": p.name,
            "scheduleGap": schedule_gap,
            "riskScore": assessments[p.id]["riskScore"],
            "state": p.state,
        })

    state_map = {}
    for p in projects:
        st = p.state or "Unknown"
        entry = state_map.setdefault(st, {"state": st, "projectCount": 0, "riskSum": 0, "critical": 0, "high": 0})
        entry["projectCount"] += 1
        entry["riskSum"] += assessments[p.id]["riskScore"]
        level = assessments[p.id]["riskLevel"]
        if level == "CRITICAL":
            entry["critical"] += 1
        elif level == "HIGH":
            entry["high"] += 1
    risk_by_state = [
        {
            "state": e["state"],
            "projectCount": e["projectCount"],
            "avgRisk": round(e["riskSum"] / e["projectCount"], 1),
            "critical": e["critical"],
            "high": e["high"],
        }
        for e in state_map.values()
    ]

    risk_trends = [
        {"month": "Apr 2025", "low": 0, "medium": 0, "high": 0, "critical": 0, "overall": 0},
        {"month": "May 2025", "low": 0, "medium": 0, "high": 0, "critical": 0, "overall": 0},
        {"month": "Jun 2025", "low": 0, "medium": 0, "high": 0, "critical": 0, "overall": 0},
        {"month": "Jul 2025", "low": 0, "medium": 0, "high": 0, "critical": 0, "overall": 0},
        {"month": "Aug 2025", "low": 0, "medium": 0, "high": 0, "critical": 0, "overall": 0},
        {"month": "Sep 2025", "low": 0, "medium": 0, "high": 0, "critical": 0, "overall": 0},
    ]
    for i, month_data in enumerate(risk_trends):
        progress = (i + 1) / len(risk_trends)
        for p in projects:
            level = assessments[p.id]["riskLevel"]
            if level == "CRITICAL" and progress > 0.6:
                level = "HIGH"
            elif level == "HIGH" and progress > 0.8:
                level = "MEDIUM"
            month_data[level.lower()] += 1
        avg = round(sum(assessments[p.id]["riskScore"] for p in projects) / len(projects), 1)
        month_data["overall"] = round(avg + (progress - 0.5) * 4, 1)

    return {
        "sectorAnalytics": sector_analytics,
        "ministryRankings": ministry_list,
        "scatterData": scatter,
        "riskTrends": risk_trends,
        "topRiskFactors": top_factors,
        "riskByState": risk_by_state,
        "scheduleGapScatter": schedule_gap_scatter,
    }


def generate_assistant_response(query: str, db: Session) -> str:
    """Keep the existing rule-based assistant; risk figures are the same engine
    values the rest of the product uses (single source of truth)."""
    lower = query.lower()
    projects = db.query(Project).all()

    if not projects:
        return "No projects are currently monitored in the system."

    assessments = {p.id: assess_project(p) for p in projects}
    critical = [p for p in projects if assessments[p.id]["riskLevel"] == "CRITICAL"]
    high = [p for p in projects if assessments[p.id]["riskLevel"] == "HIGH"]

    if "immediate intervention" in lower or "intervention" in lower:
        flagged = critical + high
        flagged.sort(key=lambda p: assessments[p.id]["riskScore"], reverse=True)
        lines = [
            f"Based on the current demonstration portfolio of {len(projects)} projects, "
            f"{len(flagged)} projects require some level of attention. "
            f"Of these, **{len(critical)} projects are flagged CRITICAL** and should receive immediate intervention:"
        ]
        for i, p in enumerate(flagged[:4], 1):
            cost_overrun = round((p.current_cost - p.original_cost) / p.original_cost * 100, 1) if p.original_cost else 0
            assessment = assessments[p.id]
            lines.append(
                f"{i}. **{_safe_text(p.name)}** ({_safe_text(p.state)}) — Risk Score: {assessment['riskScore']}/100\n"
                f"   - Delay Probability: {assessment['delayProbability']}% | Cost Overrun: {cost_overrun}%\n"
                f"   - Status: {assessment['riskLevel']}"
            )
        lines.append(
            "**Recommended Next Step:** Convene the central monitoring committee "
            "for the top projects and instruct Ministry heads to submit a recovery plan within 14 days."
        )
        return "\n".join(lines)

    if "highest risk" in lower or "high risk" in lower:
        sorted_projects = sorted(
            projects, key=lambda p: assessments[p.id]["riskScore"], reverse=True
        )
        lines = ["Based on the current portfolio analysis, here are the highest-risk projects:"]
        for i, p in enumerate(sorted_projects[:4], 1):
            cost_overrun = round((p.current_cost - p.original_cost) / p.original_cost * 100, 1) if p.original_cost else 0
            assessment = assessments[p.id]
            lines.append(
                f"{i}. **{_safe_text(p.name)}** ({_safe_text(p.state)}) — Risk Score: {assessment['riskScore']}/100\n"
                f"   - Delay Probability: {assessment['delayProbability']}%\n"
                f"   - Cost Overrun: {cost_overrun}%\n"
                f"   - Status: {assessment['riskLevel']}"
            )
        lines.append(
            "**Recommended Action:** These projects should be escalated for "
            "immediate review by the monitoring committee."
        )
        return "\n".join(lines)

    if "delay" in lower:
        delayed = [p for p in projects if assessments[p.id]["delayProbability"] >= 50]
        delayed.sort(key=lambda p: assessments[p.id]["delayProbability"], reverse=True)
        lines = ["The following projects have a **delay probability above 50%** and require attention:"]
        for i, p in enumerate(delayed, 1):
            lines.append(
                f"{i}. **{_safe_text(p.name)}** ({_safe_text(p.state)}) — "
                f"{assessments[p.id]['delayProbability']}% delay probability"
            )
        return "\n".join(lines)

    if "cost" in lower or "overrun" in lower:
        sorted_by_cost = sorted(
            projects,
            key=lambda p: (p.current_cost - p.original_cost) / p.original_cost if p.original_cost else 0,
            reverse=True,
        )
        lines = ["Here are projects ranked by cost overrun:"]
        for i, p in enumerate(sorted_by_cost, 1):
            overrun = round((p.current_cost - p.original_cost) / p.original_cost * 100, 1) if p.original_cost else 0.0
            lines.append(
                f"{i}. **{_safe_text(p.name)}** — {overrun}% overrun\n"
                f"   - Original: ₹{p.original_cost:,.0f} Cr | Current: ₹{p.current_cost:,.0f} Cr"
            )
        return "\n".join(lines)

    if "sector" in lower:
        analytics = get_project_analytics(db)
        lines = ["Here is a comparative analysis of risk across sectors:"]
        for s in analytics["sectorAnalytics"]:
            lines.append(f"- **{_safe_text(s['sector'])}**: {s['projectCount']} projects, Avg Risk: {s['avgRisk']}, Avg Cost Overrun: {s['avgCostOverrun']}%")
        return "\n".join(lines)

    if "risk driver" in lower or "major risk" in lower:
        analytics = get_project_analytics(db)
        lines = ["Analysis of the monitored projects reveals the following top risk drivers:\n"]
        for i, f in enumerate(analytics["topRiskFactors"][:5], 1):
            lines.append(f"{i}. **{f['name']}** — avg factor score {f['avgScore']}/100")
        lines.append(
            "\n**Key Insight:** The highest-scoring factors above drive the portfolio's overall risk."
        )
        return "\n".join(lines)

    if "hello" in lower or "hi" == lower or lower.startswith("hi "):
        return (
            "Hello! I'm the **Sankalp AI Assistant**, here to help you analyze "
            "government infrastructure project risks.\n\n"
            f"I'm currently monitoring **{len(projects)} projects** across the portfolio.\n\n"
            "I can help you with:\n"
            "- Identifying highest-risk projects\n"
            "- Analyzing cost overruns and delays\n"
            "- Comparing risk across sectors\n"
            "- Understanding risk drivers\n"
            "- Portfolio overview statistics"
        )

    if "overview" in lower or "portfolio" in lower:
        total_cost = sum(p.current_cost for p in projects)
        medium = [p for p in projects if assessments[p.id]["riskLevel"] == "MEDIUM"]
        low = [p for p in projects if assessments[p.id]["riskLevel"] == "LOW"]
        average_risk = round(
            sum(assessments[p.id]["riskScore"] for p in projects) / len(projects), 1
        )
        return (
            f"**Portfolio Snapshot** ({len(projects)} monitored projects)\n\n"
            f"- **Total Current Cost:** ₹{total_cost:,.0f} Cr\n"
            f"- **Critical Risk:** {len(critical)} projects\n"
            f"- **High Risk:** {len(high)} projects\n"
            f"- **Medium Risk:** {len(medium)} projects\n"
            f"- **Low Risk:** {len(low)} projects\n"
            f"- **Average Risk Score:** {average_risk}"
        )

    if "help" in lower:
        return (
            "Here's how I can help you:\n\n"
            "**Project Analysis:**\n"
            "- \"Which projects are at highest risk?\"\n"
            "- \"Show me projects likely to be delayed.\"\n\n"
            "**Risk Intelligence:**\n"
            "- \"What are the major risk drivers?\"\n"
            "- \"Which projects require immediate intervention?\"\n\n"
            "**Sector & Cost Analysis:**\n"
            "- \"Which sector has the highest cost overrun?\"\n"
            "- \"Give me a portfolio overview.\"\n\n"
            f"Currently monitoring **{len(projects)} projects** in the demonstration portfolio."
        )

    return (
        f"I'm not sure I understand that query. Here are some things I can help with:\n\n"
        f"- Identify the highest-risk projects in the portfolio\n"
        f"- Explain why specific projects are at risk\n"
        f"- Compare risk metrics across sectors\n"
        f"- List projects with high delay probability\n"
        f"- Outline the major risk drivers\n"
        f"- Provide portfolio-wide statistics\n\n"
        f"Currently monitoring **{len(projects)} projects**. Try rephrasing your question."
    )