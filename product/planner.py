#!/usr/bin/env python3
"""
MandateScout Research Request Planner
====================================
Translates natural language advisor research requests into bounded, safe JSON
parameters for PRH registry retrieval and registered website evidence enrichment.

Supports:
1. Gemini 3.8 Flash planner via AGY CLI (bounded timeout, no quota retries).
2. Deterministic rule-based request planner (explicit fallback, never called AI).
3. Parameter boundary validation and sanitization.
4. Exclusion of unsupported financial/intent assertions.
5. Actionable followup refinement suggestions.
"""

import json
import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

ALLOWED_INDUSTRY_CODES = {
    "62": "Computer programming, consultancy and related activities",
    "62010": "Computer programming activities",
    "62200": "Computer consultancy activities",
    "62090": "Other information technology and computer service activities",
    "62100": "Computer programming activities (TOIMI4)",
    "70200": "Business and management consultancy",
    "71120": "Engineering activities and related technical consultancy",
    "25": "Manufacture of fabricated metal products",
    "26": "Manufacture of computer, electronic and optical products",
    "27": "Manufacture of electrical equipment",
    "28": "Manufacture of machinery and equipment",
    "33": "Repair and installation of machinery and equipment",
    "46": "Wholesale trade",
    "4669": "Wholesale of other machinery and equipment",
}

FINANCIAL_INTENT_PATTERNS = [
    r"\b(revenue|turnover|liikevaihto)\b",
    r"\b(ebitda|profit|liikevoitto|kannattava)\b",
    r"\b(exit|for sale|myynnissä|willing to sell)\b",
    r"\b(valuation|arvostus|multiple)\b",
    r"\b(ebit|net income|margin)\b",
    r"\b(funded|pe-backed|venture capital)\b",
]


def sanitize_text(text: str, max_len: int = 80) -> str:
    """Strips dangerous characters and bounds length."""
    if not text:
        return ""
    cleaned = re.sub(r"[^\w\s\-\.\,\'\"]", " ", text).strip()
    return cleaned[:max_len].strip()


def validate_plan_parameters(
    raw_plan: Dict[str, Any],
    original_request: str = ""
) -> Dict[str, Any]:
    """
    Validates and clamps plan parameters within safe bounds:
    - limit in [5, 20], default 10
    - industry_code must be numeric digits or empty
    - keywords deduplicated and capped at 10 items
    - queries cleaned
    - flags unverified financial/intent qualifiers
    """
    plan = dict(raw_plan)

    # 1. Clamp limit (5..20)
    try:
        limit = int(plan.get("limit", 10))
    except (ValueError, TypeError):
        limit = 10
    plan["limit"] = max(5, min(20, limit))

    # 2. Sanitize query
    raw_q = str(plan.get("query", "")).strip()
    plan["query"] = sanitize_text(raw_q, max_len=60)

    # 3. Industry code
    raw_ind = str(plan.get("industry_code", "")).strip()
    clean_ind = re.sub(r"[^\d]", "", raw_ind)
    plan["industry_code"] = clean_ind if clean_ind in ALLOWED_INDUSTRY_CODES or len(clean_ind) <= 5 else ""

    # 4. Keywords
    raw_kws = plan.get("keywords", [])
    if isinstance(raw_kws, str):
        raw_kws = [k.strip() for k in raw_kws.split(",") if k.strip()]
    elif not isinstance(raw_kws, list):
        raw_kws = []

    clean_kws = []
    seen = set()
    for kw in raw_kws:
        k = sanitize_text(str(kw), max_len=35).lower()
        if k and k not in seen:
            clean_kws.append(k)
            seen.add(k)
        if len(clean_kws) >= 10:
            break
    plan["keywords"] = clean_kws

    # 5. Check for unsupported financial / intent assertions in request
    detected_unverified = []
    combined_text = f"{original_request} {plan.get('rationale', '')}".lower()
    for pat in FINANCIAL_INTENT_PATTERNS:
        match = re.search(pat, combined_text, re.IGNORECASE)
        if match:
            detected_unverified.append(match.group(0))

    plan["unverified_qualifiers"] = list(set(detected_unverified))
    plan["disclaimers"] = [
        "Financial metrics (turnover, EBITDA) and owner transaction intent are unverified in public open records.",
        "Candidate scoring reflects explicit keyword coverage across public website prose, not buyer fit or acquisition readiness."
    ]
    plan["bounds_validated"] = True

    # 6. Ensure followup refinements
    followups = plan.get("followup_refinements", [])
    if not followups or not isinstance(followups, list):
        followups = generate_followup_refinements(plan)
    plan["followup_refinements"] = followups[:3]

    return plan


def generate_followup_refinements(plan: Dict[str, Any]) -> List[str]:
    """Generates 2-3 logical followup query refine commands."""
    refinements = []
    kws = plan.get("keywords", [])
    ind = plan.get("industry_code", "")
    query = plan.get("query", "")
    limit = plan.get("limit", 10)

    if ind == "62":
        if "cybersecurity" not in kws:
            refinements.append("Refine: Focus on cybersecurity & managed security")
        if "saas" not in kws:
            refinements.append("Refine: Emphasize SaaS and cloud native platforms")
        refinements.append("Refine: Restrict to IT consultancy (sector 62200)")
    elif ind in ("25", "28"):
        refinements.append("Refine: Focus on precision CNC machining & automation")
        refinements.append("Refine: Add keyword 'oem components'")
        refinements.append("Refine: Expand candidate limit to 15")
    else:
        if limit < 15:
            refinements.append(f"Refine: Expand sample size to 15 companies")
        refinements.append("Refine: Add sector filter '62' (IT & Software)")
        refinements.append("Refine: Narrow by consulting & integration services")

    return refinements[:3]


def plan_with_rules(
    request_text: str,
    buyer_id: Optional[str] = None,
    buyer_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Deterministic rule-based request planner.
    Explicitly labeled as rule-based logic — NEVER claims to be AI.
    """
    req_lower = request_text.lower()

    # Defaults
    query = ""
    keywords: List[str] = []
    industry_code = ""
    limit = 10
    rationale_parts = []

    # 1. Buyer profile prefill if provided
    if buyer_data:
        b_name = buyer_data.get("name", buyer_id)
        rationale_parts.append(f"Aligned with buyer thesis '{b_name}'.")
        for kw in buyer_data.get("keywords", []):
            if kw not in keywords:
                keywords.append(kw)
        ind_codes = buyer_data.get("industry_codes", [])
        if ind_codes:
            industry_code = ind_codes[0]

    # 2. Extract explicit quoted terms for query or explicit company name requirements
    # Avoid converting generic descriptive terms (e.g. 'Cloud', 'Automation') to company name queries!
    quoted = re.findall(r'["\']([^"\']+)["\']', request_text)
    if quoted:
        query = quoted[0].strip()
        rationale_parts.append(f"Extracted explicit target term '{query}'.")
    else:
        # Check for explicit company name phrasing (e.g. "named X", "company named X", "firm named X", "company: X")
        name_match = re.search(
            r"\b(?:named|nimeltään|company\s+named|firm\s+named|yhtiö\s+nimeltään|(?:company|firm|yhtiö)\s*[:=])\s*[\"']?([a-zA-Z0-9åäöÅÄÖ\.\-]+)[\"']?",
            request_text,
            re.IGNORECASE,
        )
        if name_match:
            candidate_name = name_match.group(1).strip()
            # Guard against generic stopwords or industry descriptors being captured as names
            if candidate_name.lower() not in {
                "oy", "oyj", "ab", "finland", "finnish", "a", "an", "the", "with", "in", "for",
                "cloud", "saas", "software", "cnc", "machining", "metal", "automation", "consulting"
            }:
                query = candidate_name
                rationale_parts.append(f"Extracted explicit target company name '{query}'.")

    # 3. Detect Industry and Bilingual Keywords from request
    # Sector 25: Fabricated Metal Products & CNC Machining
    if any(w in req_lower for w in ["cnc", "machining", "koneistus", "metal", "metall", "sorvaus", "jyrsintä", "milling", "turning", "fabrication", "konepaja"]):
        if not industry_code:
            industry_code = "25"
        for kw in ["cnc", "koneistus", "machining", "sorvaus", "jyrsintä", "milling", "turning", "sopimusvalmistus", "konepaja"]:
            if kw not in keywords:
                keywords.append(kw)
        rationale_parts.append("Mapped to Fabricated Metal & CNC Machining sector (TOL 25) with bilingual keywords.")

    # Sector 28: Machinery & Equipment / Industrial Automation
    elif any(w in req_lower for w in ["machinery", "equipment", "laitteet", "koneet", "automation", "automaatio", "robotiikka", "robotics"]):
        if not industry_code:
            industry_code = "28"
        for kw in ["automaatio", "automation", "laitteet", "machinery", "robotiikka", "robotics", "koneet", "equipment"]:
            if kw not in keywords:
                keywords.append(kw)
        rationale_parts.append("Mapped to Machinery & Equipment sector (TOL 28) with bilingual keywords.")

    # Sector 62: IT & Software / SaaS / Cloud
    elif any(w in req_lower for w in ["cloud", "saas", "software", "devops", "programming", "ohjelmisto", "pilvi", "sovellus"]):
        if not industry_code:
            industry_code = "62"
        for kw in ["ohjelmisto", "software", "pilvi", "cloud", "saas", "devops", "kehitys", "konsultointi"]:
            if kw not in keywords:
                keywords.append(kw)
        rationale_parts.append("Mapped to IT & Software sector (TOL 62) with bilingual keywords.")

    # Cybersecurity focus (augments TOL 62)
    if any(w in req_lower for w in ["cyber", "cybersecurity", "security", "tietoturva", "kyberturvallisuus"]):
        if not industry_code:
            industry_code = "62"
        for kw in ["tietoturva", "cybersecurity", "security", "kyberturvallisuus", "soc", "penetration testing"]:
            if kw not in keywords:
                keywords.append(kw)
        rationale_parts.append("Added bilingual cybersecurity focus terms.")

    # Consulting focus
    if any(w in req_lower for w in ["consulting", "consultancy", "konsultointi", "advisory", "neuvonanto"]):
        if industry_code == "62":
            industry_code = "62200"
        elif not industry_code:
            industry_code = "70200"
        for kw in ["konsultointi", "consulting", "asiantuntijapalvelut"]:
            if kw not in keywords:
                keywords.append(kw)
        rationale_parts.append(f"Specified consultancy industry code {industry_code}.")

    # 4. Detect Limit
    limit_match = re.search(r"\b(limit\s*|top\s*|max\s*)(\d+)\b", req_lower)
    if limit_match:
        try:
            parsed_lim = int(limit_match.group(2))
            limit = max(5, min(20, parsed_lim))
            rationale_parts.append(f"Applied requested candidate limit {limit}.")
        except ValueError:
            pass

    # Generic descriptive words MUST NOT be converted to company name filter!
    # If query was not explicitly provided by user, it remains empty so PRH scans sector without name restriction.

    # Fallback keywords if empty
    if not keywords:
        tokens = re.findall(r"\b[a-zA-ZåäöÅÄÖ]{3,}\b", req_lower)
        stopwords = {"find", "search", "companies", "finnish", "finland", "firm", "firms", "target", "targets", "with", "and", "the", "for", "seeking", "acquire"}
        filtered = [t for t in tokens if t not in stopwords]
        keywords = filtered[:6] if filtered else ["ohjelmisto", "palvelut"]

    rationale = " ".join(rationale_parts) if rationale_parts else "Constructed deterministic search bounds from keyword heuristics."

    plan = {
        "planner_type": "rule_based_planner",
        "planner_label": "Deterministic Rule-Based Request Planner (Safe Fallback)",
        "query": query,
        "industry_code": industry_code,
        "keywords": keywords,
        "limit": limit,
        "rationale": rationale,
        "blocker_reported": None,
    }

    return validate_plan_parameters(plan, original_request=request_text)


def try_plan_with_agy(
    request_text: str,
    buyer_id: Optional[str] = None,
    buyer_data: Optional[Dict[str, Any]] = None,
    timeout_seconds: float = 4.0
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Attempts to use the installed AGY CLI non-interactively with a strict bounded timeout.
    Returns (plan_dict, blocker_reason).
    If AGY is not installed, times out, or fails, returns (None, reason).
    """
    agy_bin = shutil.which("agy") or r"C:\Users\HoaiAnh\bin\agy.exe"
    if not os.path.exists(agy_bin):
        return None, "AGY CLI executable not found on system path."

    prompt_schema = {
        "query": "string (company name term e.g. 'Cloud' or empty string)",
        "industry_code": "string (Finnish TOL/TOIMI4 code e.g. '62', '25', '28' or empty string)",
        "keywords": ["list of strings for scoring website text, max 6 items"],
        "limit": 10,
        "rationale": "one sentence explanation"
    }

    prompt = (
        f"You are a strict M&A research planner for the Finnish trade registry.\n"
        f"Input request: \"{request_text}\"\n"
        f"Buyer thesis context: {buyer_data.get('name') if buyer_data else 'None'}\n"
        f"Respond ONLY with a valid single-line JSON object adhering to this schema: "
        f"{json.dumps(prompt_schema)}. Set 'query' to an empty string unless an explicit company name was specified. "
        f"Provide bilingual Finnish and English operational keywords. Do NOT include markdown code blocks, explanations, or any extra text."
    )

    # Sanitize environment to avoid inheriting parent AGY CLI session lock
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("ANTIGRAVITY")}

    cmd = [
        agy_bin,
        "-p", prompt,
        "--model", "gemini-3.8-flash-high",
        "--mode", "plan",
        "--sandbox",
        "--print-timeout", f"{int(timeout_seconds)}s",
        "--disable-slash-commands"
    ]

    try:
        res = subprocess.run(
            cmd,
            env=clean_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds + 1.0
        )
        if res.returncode == 0 and res.stdout.strip():
            raw_out = res.stdout.strip()
            # Extract JSON from output
            json_match = re.search(r"\{.*\}", raw_out, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group(0))
                parsed["planner_type"] = "gemini_agy"
                parsed["planner_label"] = "Gemini 3.8 Flash (AGY CLI Planner)"
                parsed["blocker_reported"] = None
                return validate_plan_parameters(parsed, original_request=request_text), None
            else:
                return None, f"AGY CLI returned unparseable text: {raw_out[:120]}"
        else:
            err = res.stderr.strip() or res.stdout.strip()
            return None, f"AGY CLI exited with code {res.returncode}: {err[:150]}"
    except subprocess.TimeoutExpired:
        return None, f"AGY CLI process timed out after {timeout_seconds}s bounded limit."
    except Exception as e:
        return None, f"AGY invocation error: {str(e)}"


def plan_research(
    request_text: str,
    buyer_id: Optional[str] = None,
    data_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Primary research planning entrypoint:
    1. Loads buyer data if buyer_id provided.
    2. Attempts Gemini 3.8 Flash via AGY CLI with bounded timeout.
    3. If infeasible/times out, activates deterministic rule-based request planner (explicitly labeled).
    """
    clean_req = str(request_text).strip()
    if not clean_req:
        clean_req = "Finnish IT and software consultancy companies"

    # Load buyer profile if available
    buyer_data = None
    if buyer_id and data_dir:
        buyers_file = os.path.join(data_dir, "buyers.json")
        if os.path.exists(buyers_file):
            try:
                with open(buyers_file, "r", encoding="utf-8") as f:
                    all_buyers = json.load(f).get("buyers", [])
                    for b in all_buyers:
                        if b.get("id") == buyer_id:
                            buyer_data = b
                            break
            except Exception:
                pass

    # 1. Attempt AGY with bounded timeout (no quota retries)
    plan, blocker = try_plan_with_agy(
        clean_req,
        buyer_id=buyer_id,
        buyer_data=buyer_data,
        timeout_seconds=4.0
    )

    if plan:
        return plan

    # 2. Rule-based fallback
    fallback_plan = plan_with_rules(clean_req, buyer_id=buyer_id, buyer_data=buyer_data)
    fallback_plan["blocker_reported"] = blocker or "Direct AGY CLI execution unavailable or timed out."
    return fallback_plan
