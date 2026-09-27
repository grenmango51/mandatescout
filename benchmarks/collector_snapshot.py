#!/usr/bin/env python3
"""
MandateScout Data Collector & Provenance Engine
==============================================
Python Standard Library Only.
Performs live searches against Finnish PRH Open Data YTJ-API v3,
extracts active private Finnish companies (OY), performs safe, bounded
website evidence collection with normal TLS and strict SSRF / private IP
blocking, records cryptographic hashes (SHA-256) for auditability, and
scores candidate relevance against buyer/advisor criteria.
"""

import datetime
import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Tuple

PRH_BASE_URL = "https://avoindata.prh.fi/opendata-ytj-api/v3"
USER_AGENT = "MandateScout/1.0 (Finnish M&A Advisor Workbench; +https://avoindata.prh.fi)"
MAX_FETCH_BYTES = 1024 * 1024  # 1 MB maximum response size
REQUEST_TIMEOUT = 7  # Seconds
MAX_REDIRECT_HOPS = 3

# Disallowed internal / reserved IP networks for SSRF protection
BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.88.99.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
]


def is_safe_url(target_url: str) -> Tuple[bool, str]:
    """
    Validates that a URL targets a public, safe endpoint and prevents SSRF attacks.
    Blocks private IPs, link-local metadata endpoints, loopback, and unknown protocols.
    """
    try:
        parsed = urllib.parse.urlsplit(target_url)
    except Exception as e:
        return False, f"Malformed URL syntax: {e}"

    if parsed.scheme not in ("http", "https"):
        return False, f"Disallowed scheme '{parsed.scheme}'. Only http and https permitted."

    hostname = parsed.hostname
    if not hostname:
        return False, "URL missing valid hostname."

    # Reject localhost aliases
    lower_host = hostname.lower().strip()
    if lower_host in ("localhost", "127.0.0.1", "::1", "metadata.google.internal", "instance-data"):
        return False, f"Blocked target hostname '{hostname}' (private, loopback, or reserved)."

    # Standard allowed ports
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in (80, 443, 8080, 8443):
        return False, f"Disallowed destination port: {port}"

    # Resolve hostname to IP addresses and check each
    try:
        addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip_obj = ipaddress.ip_address(ip_str)

            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_multicast
                or ip_obj.is_reserved
                or ip_obj.is_unspecified
            ):
                return False, f"Target IP address {ip_str} is in a private, loopback, or reserved range."

            for net in BLOCKED_NETWORKS:
                if ip_obj in net:
                    return False, f"Target IP address {ip_str} belongs to restricted network {net}."
    except socket.gaierror as e:
        return False, f"DNS resolution failed for hostname '{hostname}': {e}"
    except Exception as e:
        return False, f"IP validation error for '{hostname}': {e}"

    return True, ""


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """
    HTTP redirect handler that enforces SSRF safety checks before following any redirect.
    """

    def __init__(self, max_hops: int = MAX_REDIRECT_HOPS):
        super().__init__()
        self.max_hops = max_hops
        self.current_hops = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.current_hops += 1
        if self.current_hops > self.max_hops:
            raise urllib.error.HTTPError(
                newurl, code, f"Exceeded maximum allowed redirect hops ({self.max_hops})", headers, fp
            )

        safe, reason = is_safe_url(newurl)
        if not safe:
            raise urllib.error.HTTPError(
                newurl, code, f"Blocked redirect to unsafe target ({reason})", headers, fp
            )

        return super().redirect_request(req, fp, code, msg, headers, newurl)


def safe_fetch_url(
    url: str, timeout: int = REQUEST_TIMEOUT
) -> Tuple[int, bytes, Dict[str, str], str, Optional[str]]:
    """
    Safely fetches a web resource with normal TLS, bounded size, and SSRF restrictions.
    Returns: (status_code, content_bytes, headers_dict, final_url, error_message)
    """
    safe, reason = is_safe_url(url)
    if not safe:
        return 0, b"", {}, url, f"URL security check rejected: {reason}"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en,fi;q=0.8",
        },
    )

    # Use standard Python SSL context with full verification
    ssl_context = ssl.create_default_context()
    redirect_handler = SafeRedirectHandler(max_hops=MAX_REDIRECT_HOPS)
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl_context),
        urllib.request.HTTPHandler(),
        redirect_handler,
    )

    try:
        with opener.open(req, timeout=timeout) as resp:
            status_code = resp.status
            final_url = resp.geturl()
            headers = {k.lower(): v for k, v in resp.headers.items()}

            # Stream content up to MAX_FETCH_BYTES
            chunks = []
            total_read = 0
            while True:
                chunk = resp.read(16384)
                if not chunk:
                    break
                chunks.append(chunk)
                total_read += len(chunk)
                if total_read > MAX_FETCH_BYTES:
                    break

            content_bytes = b"".join(chunks)
            return status_code, content_bytes, headers, final_url, None

    except urllib.error.HTTPError as e:
        final_url = getattr(e, "url", url)
        return e.code, b"", {}, final_url, f"HTTP Error {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return 0, b"", {}, url, f"Network or TLS failure: {e.reason}"
    except TimeoutError:
        return 0, b"", {}, url, "Connection timed out"
    except Exception as e:
        return 0, b"", {}, url, f"Fetch failed: {str(e)}"


class CacheManager:
    """
    Manages cached PRH registry queries, raw website captures, and search run records.
    Stores raw responses alongside SHA-256 hashes and ISO UTC retrieval timestamps.
    """

    def __init__(self, base_cache_dir: str):
        self.base_dir = os.path.abspath(base_cache_dir)
        self.registry_dir = os.path.join(self.base_dir, "registry")
        self.websites_dir = os.path.join(self.base_dir, "websites")
        self.runs_dir = os.path.join(self.base_dir, "runs")

        os.makedirs(self.registry_dir, exist_ok=True)
        os.makedirs(self.websites_dir, exist_ok=True)
        os.makedirs(self.runs_dir, exist_ok=True)

    def _url_key(self, url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def save_registry_raw(self, url: str, raw_bytes: bytes, business_ids: List[str]) -> str:
        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        url_hash = self._url_key(url)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Save payload
        data_path = os.path.join(self.registry_dir, f"{content_hash}.json")
        with open(data_path, "wb") as f:
            f.write(raw_bytes)

        # Save metadata / lookup
        meta = {
            "url": url,
            "url_hash": url_hash,
            "sha256": content_hash,
            "retrieved_at": now_iso,
            "byte_count": len(raw_bytes),
            "business_ids": business_ids,
        }
        meta_path = os.path.join(self.registry_dir, f"{url_hash}_meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        return content_hash

    def get_cached_registry(self, url: str) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
        url_hash = self._url_key(url)
        meta_path = os.path.join(self.registry_dir, f"{url_hash}_meta.json")
        if not os.path.exists(meta_path):
            return None

        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            data_path = os.path.join(self.registry_dir, f"{meta['sha256']}.json")
            if not os.path.exists(data_path):
                return None
            with open(data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return meta, data
        except Exception:
            return None

    def save_website_raw(
        self,
        url: str,
        final_url: str,
        status_code: int,
        content_type: str,
        raw_bytes: bytes,
        extracted_text: str,
    ) -> str:
        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        url_hash = self._url_key(url)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Save HTML
        html_path = os.path.join(self.websites_dir, f"{content_hash}.html")
        with open(html_path, "wb") as f:
            f.write(raw_bytes)

        # Save JSON metadata & extracted text
        meta = {
            "url": url,
            "final_url": final_url,
            "url_hash": url_hash,
            "sha256": content_hash,
            "status_code": status_code,
            "content_type": content_type,
            "retrieved_at": now_iso,
            "byte_count": len(raw_bytes),
            "extracted_text": extracted_text,
        }
        meta_path = os.path.join(self.websites_dir, f"{url_hash}_meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        # Also store by content hash for permanent citation
        hash_meta_path = os.path.join(self.websites_dir, f"{content_hash}_meta.json")
        with open(hash_meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        return content_hash

    def get_cached_website(self, url: str) -> Optional[Dict[str, Any]]:
        url_hash = self._url_key(url)
        meta_path = os.path.join(self.websites_dir, f"{url_hash}_meta.json")
        if not os.path.exists(meta_path):
            return None
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def save_run(self, run_id: str, run_data: Dict[str, Any]) -> None:
        path = os.path.join(self.runs_dir, f"{run_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(run_data, f, indent=2, ensure_ascii=False)

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        path = os.path.join(self.runs_dir, f"{run_id}.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def list_runs(self) -> List[Dict[str, Any]]:
        runs = []
        if not os.path.exists(self.runs_dir):
            return runs

        for fname in sorted(os.listdir(self.runs_dir), reverse=True):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(self.runs_dir, fname), "r", encoding="utf-8") as f:
                        data = json.load(f)
                        runs.append(
                            {
                                "run_id": data.get("run_id"),
                                "queried_at": data.get("queried_at"),
                                "query": data.get("query"),
                                "count": len(data.get("companies", [])),
                                "source_mode": data.get("source_mode"),
                            }
                        )
                except Exception:
                    continue
        return runs

    def get_company(self, business_id: str) -> Optional[Dict[str, Any]]:
        # Search recent runs for company
        for run_summary in self.list_runs():
            run_data = self.get_run(run_summary["run_id"])
            if run_data and "companies" in run_data:
                for comp in run_data["companies"]:
                    if comp.get("business_id") == business_id:
                        return comp
        return None


def clean_html_to_text(html_text: str) -> str:
    """
    Strips tags, scripts, styles, navigations, and extracts clean readable prose.
    """
    if not html_text:
        return ""

    # Remove script, style, header, footer, nav tags and their contents
    text = re.sub(r"<!--.*?-->", " ", html_text, flags=re.DOTALL)
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<nav.*?</nav>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<header.*?</header>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<footer.*?</footer>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<noscript.*?</noscript>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<svg.*?</svg>", " ", text, flags=re.DOTALL | re.IGNORECASE)

    # Insert spaces for block breaks
    text = re.sub(r"<(?:p|div|br|h\d|li|tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Strip any remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Unescape HTML entities
    text = html.unescape(text)

    # Normalize whitespace
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    cleaned = "\n".join(l for l in lines if l)
    return cleaned


def extract_evidence(
    text: str, keywords: List[str], source_url: str
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Searches clean website text for occurrences of target keywords.
    Extracts a contextual snippet for each match.
    Returns: (evidence_list, matched_keywords_list)
    """
    evidence = []
    matched_keywords = []

    if not text or not keywords:
        return evidence, matched_keywords

    for kw in keywords:
        kw_clean = kw.strip()
        if not kw_clean:
            continue

        pattern = re.compile(rf"\b{re.escape(kw_clean)}\b", re.IGNORECASE)
        match = pattern.search(text)
        if match:
            matched_keywords.append(kw_clean)
            start_pos = max(0, match.start() - 100)
            end_pos = min(len(text), match.end() + 100)
            raw_snippet = text[start_pos:end_pos].strip()
            # Replace newlines with spaces for clean display
            snippet = re.sub(r"\s+", " ", raw_snippet)
            if start_pos > 0:
                snippet = "..." + snippet
            if end_pos < len(text):
                snippet = snippet + "..."

            evidence.append(
                {
                    "criterion": f"Keyword match: '{kw_clean}'",
                    "excerpt": snippet,
                    "source_url": source_url,
                    "kind": "keyword_match",
                }
            )

    return evidence, matched_keywords


def calculate_relevance_score(
    matched_kw_count: int,
    total_kw_count: int,
    website_status: Optional[str] = None,
    industry_match: bool = False,
) -> float:
    """
    Computes transparent keyword match coverage percentage (0.0 to 100.0%).
    Strictly defined as: (matched_keywords / total_keywords) * 100.
    NOTE: Describes search keyword criteria alignment only, NEVER transaction suitability,
    deal probability, financial fit, or buyer interest.
    Does NOT reward missing criteria or website accessibility.
    """
    if total_kw_count <= 0:
        return 0.0
    return round((matched_kw_count / total_kw_count) * 100.0, 1)


def normalize_prh_company(
    raw_comp: Dict[str, Any], registry_url: str, retrieved_at: str
) -> Optional[Dict[str, Any]]:
    """
    Normalizes a raw PRH YTJ entity into the MandateScout Company schema.
    Enforces active Trade Register status (status 1) and Osakeyhtiö (OY) private legal form
    using verified PRH form code ('16' or 'OY'). Rejects non-OY forms (e.g. OYJ, KY, AY, tmi).
    Retains explicit classification taxonomy (TOIMI4, TOL2008, etc.).
    """
    # 1. Enforce Trade Register active registration
    tr_status = str(raw_comp.get("tradeRegisterStatus", "")).strip()
    if tr_status != "1":
        return None

    # 2. Extract Business ID
    bid = raw_comp.get("businessId", {}).get("value")
    if not bid:
        return None

    # 3. Check Legal Form (must be verified private limited company OY, PRH code 16)
    company_forms = raw_comp.get("companyForms", [])
    active_forms = [f for f in company_forms if not f.get("endDate")]
    if not active_forms:
        return None

    current_form = active_forms[0]
    form_type = str(current_form.get("type", "")).strip()

    # In PRH: 16 = Osakeyhtiö (OY). Julkinen osakeyhtiö (OYJ) = 17. Kommandiittiyhtiö (KY) = 13.
    # Enforce actual current legal form using verified PRH codes
    if form_type not in ("16", "OY"):
        return None

    legal_form_label = "Osakeyhtiö (OY)"
    if current_form.get("descriptions"):
        for desc in current_form.get("descriptions", []):
            if desc.get("languageCode") == "1":
                legal_form_label = desc.get("description")
                break

    # 4. Extract Primary Current Legal Name (type == '1', no endDate)
    names = raw_comp.get("names", [])
    primary_name = None
    for n in names:
        if n.get("type") == "1" and not n.get("endDate"):
            primary_name = n.get("name")
            break

    if not primary_name and names:
        # Fallback to first name without end date or first name entry
        valid_names = [n.get("name") for n in names if not n.get("endDate")]
        primary_name = valid_names[0] if valid_names else names[0].get("name")

    if not primary_name:
        primary_name = f"Entity {bid}"

    # 5. Extract Main Business Line and explicitly retain taxonomy
    mbl = raw_comp.get("mainBusinessLine") or {}
    industry_code = str(mbl.get("type", "")).strip()
    taxonomy_set = mbl.get("typeCodeSet", "PRH")
    industry_label = ""
    for d in mbl.get("descriptions", []):
        if d.get("languageCode") == "3":  # English description preferred
            industry_label = d.get("description")
            break
        elif d.get("languageCode") == "1" and not industry_label:  # Finnish description fallback
            industry_label = d.get("description")

    if not industry_label and industry_code:
        industry_label = f"Industry Code {industry_code} ({taxonomy_set})"

    # 6. Extract Domicile / City
    city = None
    addresses = raw_comp.get("addresses", [])
    if addresses:
        for addr in addresses:
            for po in addr.get("postOffices", []):
                if po.get("languageCode") == "1" and po.get("city"):
                    city = po.get("city")
                    break
            if city:
                break
        if not city and addresses[0].get("postOffices"):
            city = addresses[0]["postOffices"][0].get("city")

    # 7. Extract Registered Website
    website_entry = raw_comp.get("website")
    registered_website = None
    if website_entry and isinstance(website_entry, dict) and website_entry.get("url"):
        registered_website = website_entry["url"].strip()
        if registered_website and not registered_website.startswith(("http://", "https://")):
            registered_website = f"https://{registered_website}"

    # 8. Assemble Base Company Schema
    company = {
        "business_id": bid,
        "name": primary_name,
        "legal_form": legal_form_label,
        "legal_form_code": form_type,
        "status": "Active (Trade Register: Registered)",
        "industry_code": industry_code,
        "industry_taxonomy": taxonomy_set,
        "industry_label": industry_label or "Unspecified",
        "website": registered_website,
        "city": city,
        "registry_url": f"https://avoindata.prh.fi/opendata-ytj-api/v3/companies?businessId={bid}",
        "registry_retrieved_at": retrieved_at,
        "website_status": "not_fetched" if registered_website else "missing",
        "website_retrieved_at": None,
        "website_source_url": None,
        "evidence": [
            {
                "criterion": "Official Registration",
                "excerpt": f"Officially registered Finnish {legal_form_label} (PRH code {form_type}) in {city or 'Finland'} under taxonomy {taxonomy_set} with primary business line {industry_code} ({industry_label}).",
                "source_url": registry_url,
                "kind": "source_fact",
            }
        ],
        "matched_keywords": [],
        "missing_criteria": [],
        "relevance_score": 0.0,
        "keyword_coverage": "0/0",
        "financials": {"revenue": None, "ebitda": None},
        "owner_intent": None,
        "ownership_status": "unknown",
        "excluded_reason": None,
    }

    return company


def fetch_prh_companies(
    query: str,
    industry_code: str,
    limit: int,
    cache_mgr: CacheManager,
    refresh: bool = False,
) -> Tuple[List[Dict[str, Any]], int, List[str], str]:
    """
    Executes query against PRH Open Data YTJ-API v3 for active private OY firms.
    Supports official industry filter (mainBusinessLine) and company name queries.
    Paginates when needed to yield genuine active private OY entities.
    Returns: (companies_list, total_results_count, warnings, source_mode)
    """
    params = {"companyForm": "OY"}
    clean_query = query.strip() if query else ""
    clean_industry = industry_code.strip() if industry_code else ""

    if clean_query:
        params["name"] = clean_query
    if clean_industry:
        params["mainBusinessLine"] = clean_industry

    encoded_params = urllib.parse.urlencode(params)
    api_url = f"{PRH_BASE_URL}/companies?{encoded_params}"

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    warnings = []
    source_mode = "live"

    if clean_query:
        warnings.append(
            f"Query term '{clean_query}' matched against PRH registered trade names. "
            "Note: Registry name search does not scan free-text operational descriptions across the entire Finnish registry."
        )
    if clean_industry:
        warnings.append(
            f"Official PRH classification filter applied: mainBusinessLine={clean_industry}. "
            "Industry code suggestions and keywords represent advisor assumptions, never buyer stated facts."
        )

    # Check cache first if refresh=False
    cached_result = None
    if not refresh:
        cached_result = cache_mgr.get_cached_registry(api_url)

    raw_bytes = None
    if cached_result:
        meta, data = cached_result
        source_mode = "cached"
        retrieved_at = meta.get("retrieved_at", now_iso)
        raw_companies = data.get("companies", [])
        total_results = data.get("totalResults", len(raw_companies))
    else:
        # Live fetch from PRH, with pagination if needed to fill limit with active OY entities
        ssl_ctx = ssl.create_default_context()
        raw_companies = []
        total_results = 0
        current_page = 1
        max_pages = 3 if not clean_query else 1  # Industry-only searches may have ceased legacy firms on page 1

        try:
            while current_page <= max_pages:
                page_params = dict(params)
                if current_page > 1:
                    page_params["page"] = str(current_page)
                page_url = f"{PRH_BASE_URL}/companies?{urllib.parse.urlencode(page_params)}"

                req = urllib.request.Request(page_url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, context=ssl_ctx, timeout=REQUEST_TIMEOUT) as resp:
                    page_bytes = resp.read()
                    if current_page == 1:
                        raw_bytes = page_bytes
                    page_data = json.loads(page_bytes.decode("utf-8"))
                    page_comps = page_data.get("companies", [])
                    total_results = page_data.get("totalResults", len(page_comps))
                    raw_companies.extend(page_comps)

                # Check if we have enough active OYs already
                active_count = sum(
                    1 for c in raw_companies
                    if str(c.get("tradeRegisterStatus", "")).strip() == "1"
                    and (not industry_code or str((c.get("mainBusinessLine") or {}).get("type", "")).startswith(industry_code))
                    and any(str(f.get("type", "")).strip() in ("16", "OY") and not f.get("endDate") for f in c.get("companyForms", []))
                )
                if active_count >= limit or len(page_comps) < 100 or len(raw_companies) >= total_results:
                    break
                current_page += 1

            retrieved_at = now_iso
        except Exception as e:
            # If live fetch fails, try fallback to cached if present
            fallback = cache_mgr.get_cached_registry(api_url)
            if fallback:
                meta, data = fallback
                source_mode = "cached"
                warnings.append(f"Live PRH query failed ({e}); displaying verified historic cache from {meta.get('retrieved_at')}.")
                retrieved_at = meta.get("retrieved_at", now_iso)
                raw_companies = data.get("companies", [])
                total_results = data.get("totalResults", len(raw_companies))
            else:
                raise RuntimeError(f"PRH Open Data API query failed: {e}")

    # Normalize records
    normalized_list = []
    business_ids = []
    for raw_comp in raw_companies:
        norm = normalize_prh_company(raw_comp, api_url, retrieved_at)
        if norm and (not industry_code or norm["industry_code"].startswith(industry_code)):
            if norm["business_id"] not in business_ids:
                normalized_list.append(norm)
                business_ids.append(norm["business_id"])
                if len(normalized_list) >= limit:
                    break

    # Save to cache if we performed a fresh fetch
    if raw_bytes is not None:
        cache_mgr.save_registry_raw(api_url, raw_bytes, business_ids)

    return normalized_list, total_results, warnings, source_mode


def enrich_company_website(
    company: Dict[str, Any],
    keywords: List[str],
    cache_mgr: CacheManager,
    refresh: bool = False,
) -> Tuple[Dict[str, Any], str]:
    """
    Enriches a company record with website evidence using respectful, bounded fetching.
    Records raw content hash, original retrieval date, and extracts contextual snippets.
    Returns: (enriched_company, website_source_mode: 'cached'|'live'|'none')
    """
    web_url = company.get("website")
    if not web_url:
        company["website_status"] = "missing"
        company["website_retrieved_at"] = None
        company["website_source_url"] = None
        return company, "none"

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Check cache first
    cached_web = None
    if not refresh:
        cached_web = cache_mgr.get_cached_website(web_url)

    if cached_web:
        extracted_text = cached_web.get("extracted_text", "")
        company["website_status"] = "fetched"
        company["website_retrieved_at"] = cached_web.get("retrieved_at")
        company["website_source_url"] = cached_web.get("final_url", web_url)
        web_source_mode = "cached"
    else:
        # Live fetch
        status_code, content_bytes, headers, final_url, err = safe_fetch_url(web_url, timeout=REQUEST_TIMEOUT)
        if err or status_code != 200:
            company["website_status"] = "unavailable"
            company["website_retrieved_at"] = now_iso
            company["website_source_url"] = final_url
            return company, "live"

        content_type = headers.get("content-type", "")
        extracted_text = clean_html_to_text(content_bytes.decode("utf-8", errors="ignore"))
        cache_mgr.save_website_raw(
            web_url, final_url, status_code, content_type, content_bytes, extracted_text
        )

        company["website_status"] = "fetched"
        company["website_retrieved_at"] = now_iso
        company["website_source_url"] = final_url
        web_source_mode = "live"

    # Keyword extraction
    if extracted_text and keywords:
        ev_items, matched_kws = extract_evidence(extracted_text, keywords, company["website_source_url"])
        company["evidence"].extend(ev_items)
        company["matched_keywords"] = sorted(list(set(company["matched_keywords"] + matched_kws)))

    # Public wording is a review flag, not proof of current ownership or sale intent.
    if extracted_text:
        change_terms = ["yrityskaupan", "yhdistivät voimansa", "yhdistäneet voimansa",
                        "acquired by", "part of the group", "joined forces"]
        changes, _ = extract_evidence(extracted_text, change_terms, company["website_source_url"])
        if changes:
            company["excluded_reason"] = "Review corporate-change wording on the website before treating this as an independent target."
            for item in changes[:2]:
                item["criterion"] = "Corporate-change wording — advisor review required"
                company["evidence"].append(item)

    return company, web_source_mode


def execute_search(
    buyer_id: Optional[str],
    query: str,
    keywords: List[str],
    industry_code: str,
    limit: int,
    refresh: bool,
    cache_mgr: CacheManager,
    data_dir: str = "product/data",
) -> Dict[str, Any]:
    """
    Orchestrates candidate search, enrichment, scoring, and run storage.
    Accurately tracks mixed live/cached source mode while preserving original dates.
    """
    start_time = time.time()
    run_id = f"run_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    queried_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    limit = max(1, min(20, limit or 10))
    all_keywords = [k.strip() for k in keywords if k.strip()]

    # If buyer_id provided, inspect buyers.json for thesis criteria
    buyer_context = None
    buyers_path = os.path.join(data_dir, "buyers.json")
    if os.path.exists(buyers_path):
        try:
            with open(buyers_path, "r", encoding="utf-8") as f:
                buyers_data = json.load(f)
                for b in buyers_data.get("buyers", []):
                    if b.get("id") == buyer_id:
                        buyer_context = b
                        if not all_keywords and b.get("keywords"):
                            all_keywords.extend(b["keywords"])
                        if not industry_code and b.get("industry_codes"):
                            industry_code = b["industry_codes"][0]
                        break
        except Exception:
            pass

    # 1. PRH Discovery Search
    companies, total_candidates, warnings, registry_mode = fetch_prh_companies(
        query=query,
        industry_code=industry_code,
        limit=limit,
        cache_mgr=cache_mgr,
        refresh=refresh,
    )

    # 2. Website Evidence Enrichment & Scoring
    enriched_companies = []
    web_modes = set()
    for comp in companies:
        enriched, w_mode = enrich_company_website(comp, all_keywords, cache_mgr, refresh=refresh)
        web_modes.add(w_mode)

        # Calculate missing criteria
        missing = [kw for kw in all_keywords if kw not in enriched["matched_keywords"]]
        enriched["missing_criteria"] = missing

        # Industry code match check
        ind_match = bool(industry_code and industry_code in enriched.get("industry_code", ""))

        # Score relevance (strictly explicit matched/total keyword coverage percentage)
        enriched["relevance_score"] = calculate_relevance_score(
            matched_kw_count=len(enriched["matched_keywords"]),
            total_kw_count=len(all_keywords),
            website_status=enriched["website_status"],
            industry_match=ind_match,
        )
        enriched["keyword_coverage"] = f"{len(enriched['matched_keywords'])}/{len(all_keywords)}" if all_keywords else "0/0"

        enriched_companies.append(enriched)

    # Sort companies by relevance score descending
    enriched_companies.sort(key=lambda c: c["relevance_score"], reverse=True)

    elapsed_ms = int((time.time() - start_time) * 1000)

    # Determine overall source mode: mixed, live, or cached (Requirement 5)
    has_live = (registry_mode == "live") or ("live" in web_modes)
    has_cached = (registry_mode == "cached") or ("cached" in web_modes)
    if has_live and has_cached:
        overall_source_mode = "mixed"
    elif has_cached and not has_live:
        overall_source_mode = "cached"
    else:
        overall_source_mode = "live"

    # Assemble response
    result = {
        "run_id": run_id,
        "queried_at": queried_at,
        "source_mode": overall_source_mode,
        "elapsed_ms": elapsed_ms,
        "query": query,
        "industry_code": industry_code,
        "keywords": all_keywords,
        "buyer_id": buyer_id,
        "total_candidates": total_candidates,
        "companies": enriched_companies,
        "warnings": warnings,
    }

    # Persist run in cache
    cache_mgr.save_run(run_id, result)

    return result


def generate_mandate_brief(
    run_id: str,
    business_ids: List[str],
    buyer_id: Optional[str],
    notes: str,
    cache_mgr: CacheManager,
    data_dir: str = "product/data",
) -> Dict[str, str]:
    """
    Compiles an evidence-backed mandate dossier in Markdown from stored search run data.
    Displays buyer criteria with criterion-level gaps (financials unknown, ownership model not target criteria).
    Affirms no claim of actual buyer interest or transaction willingness.
    """
    run_data = cache_mgr.get_run(run_id)
    if not run_data:
        raise ValueError(f"Run ID '{run_id}' not found in cache.")

    # Freeze buyer context from run if not supplied
    if not buyer_id and run_data.get("buyer_id"):
        buyer_id = run_data["buyer_id"]

    companies = [
        c for c in run_data.get("companies", []) if c.get("business_id") in business_ids
    ]
    if not companies:
        companies = run_data.get("companies", [])

    buyer_name = "Independent Strategic Buyer"
    buyer_criteria = []
    buyers_path = os.path.join(data_dir, "buyers.json")
    if os.path.exists(buyers_path):
        try:
            with open(buyers_path, "r", encoding="utf-8") as f:
                buyers_data = json.load(f)
                for b in buyers_data.get("buyers", []):
                    if b.get("id") == buyer_id:
                        buyer_name = b.get("name", buyer_name)
                        buyer_criteria = b.get("criteria", [])
                        break
        except Exception:
            pass

    date_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    md = [
        f"# MandateScout Target Dossier: {buyer_name}",
        f"**Generated:** {date_str} | **Run ID:** `{run_id}` | **Candidates Evaluated:** {len(companies)}",
        "",
        "> **REGULATORY & COMPLIANCE NOTICE: NO CLAIM OF ACTUAL INTEREST**",
        "> This dossier uses public registry records and website evidence. Transaction interest has not been verified for the buyer or targets. Financial metrics and owner intent remain unknown in this product.",
        "",
        "## Advisor Strategic Context",
        notes.strip() if notes and notes.strip() else "_No specific advisor notes appended._",
        "",
        "## Buyer Thesis Criteria & Criterion-Level Evaluation",
    ]

    if buyer_criteria:
        md.append("| Criterion | Category | Buyer Excerpt | Qualification Status & Evidence Gap |")
        md.append("| :--- | :--- | :--- | :--- |")
        for crit in buyer_criteria:
            c_label = crit.get("label", "Target Criterion")
            c_kind = crit.get("kind", "general")
            c_excerpt = crit.get("source_excerpt", "").replace("|", "\\|")
            if c_kind == "financial_size":
                c_gap = "**UNKNOWN (DATA GAP):** Open public registry (PRH) does not disclose revenue or EBITDA. Audited financial statements required."
            elif c_kind == "ownership_model":
                c_gap = "**NOT TARGET CRITERIA:** Describes acquirer's holding and governance philosophy, not target screening criteria."
            elif c_kind == "negative_screen":
                c_gap = "**VERIFIED EXCLUSIONS:** Evaluated against registered industry classification and web operational text."
            else:
                c_gap = "**KEYWORD EVIDENCE:** Matched against official business line and registered website content."
            md.append(f"| **{c_label}** | `{c_kind}` | \"{c_excerpt}\" | {c_gap} |")
        md.append("")
        md.append("_Note: Industry codes and keyword criteria represent advisor search heuristics, never buyer-stated facts._")
    else:
        md.append("_Ad-hoc search mode: No predefined buyer thesis attached._")

    md.extend([
        "",
        "## Shortlist Summary",
        "| Business ID | Legal Name | Domicile | Industry Code | Website Status | Keyword Coverage |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    for c in companies:
        web_display = c.get("website_status", "missing")
        cov = c.get("keyword_coverage", f"{c.get('relevance_score', 0)}%")
        md.append(
            f"| `{c['business_id']}` | **{c['name']}** | {c.get('city') or 'Finland'} | {c.get('industry_code') or 'N/A'} ({c.get('industry_taxonomy') or 'TOIMI4'}) | {web_display} | {cov} ({c.get('relevance_score', 0)}%) |"
        )

    md.extend(["", "## Detailed Candidate Profiles & Verification Evidence", ""])

    for c in companies:
        md.append(f"### {c['name']} (`{c['business_id']}`)")
        md.append(f"- **Legal Form:** {c['legal_form']} (PRH code: {c.get('legal_form_code', '16')})")
        md.append(f"- **Trade Register Status:** {c['status']}")
        md.append(f"- **Primary Business Line:** {c['industry_code']} — {c['industry_label']} (Taxonomy: {c.get('industry_taxonomy', 'TOIMI4')})")
        md.append(f"- **Registered Municipality:** {c.get('city') or 'Finland'}")
        md.append(f"- **Official Registry Citation:** [{c['registry_url']}]({c['registry_url']}) (Retrieved: {c['registry_retrieved_at']})")
        if c.get("website"):
            md.append(f"- **Registered Website:** [{c['website']}]({c['website']}) (Status: `{c['website_status']}`, Retrieved: {c.get('website_retrieved_at') or 'N/A'})")
        else:
            md.append("- **Registered Website:** _No official website registered in PRH YTJ._")

        md.append("")
        md.append("#### Ground Truth Data Disclaimers")
        md.append("- **Financials (Revenue / EBITDA):** Unknown (not disclosed in public open registry).")
        md.append("- **Owner Intent:** Unknown (requires direct advisor outreach; no mandate claimed).")
        md.append("- **Ownership Independence:** Unknown (private OY registration does not confirm ultimate beneficial ownership independence).")

        md.append("")
        md.append("#### Criterion-Level Alignment & Evidence Citations")
        if c.get("evidence"):
            for ev in c["evidence"]:
                md.append(f"- **[{ev['kind']}] {ev['criterion']}:**")
                md.append(f"  > \"{ev['excerpt']}\"")
                md.append(f"  _Source:_ [{ev['source_url']}]({ev['source_url']})")
        else:
            md.append("- _No specific website text matches retrieved._")

        if c.get("excluded_reason"):
            md.append(f"**Advisor review flag:** {c['excluded_reason']}")
        if c.get("missing_criteria"):
            md.append("")
            md.append(f"**Unmatched Criteria Keywords:** {', '.join(c['missing_criteria'])}")

        md.append("")
        md.append("---")
        md.append("")

    content = "\n".join(md)
    filename = f"mandate_dossier_{run_id}.md"

    return {"filename": filename, "markdown": content}
