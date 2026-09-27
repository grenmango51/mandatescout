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

import concurrent.futures
import datetime
import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

PRH_BASE_URL = "https://avoindata.prh.fi/opendata-ytj-api/v3"
USER_AGENT = "MandateScout/1.0 (Finnish M&A Advisor Workbench; +https://avoindata.prh.fi)"
MAX_FETCH_BYTES = 1024 * 1024  # 1 MB maximum response size
REQUEST_TIMEOUT = 7  # Seconds
MAX_REDIRECT_HOPS = 3
MAX_SUBPAGES_PER_SITE = 2  # Strict bound for 1-hop subpage crawling

# High-signal terms for internal subpage link discovery and prioritization
HIGH_SIGNAL_TERMS = [
    "palvelu", "koneis", "tuote", "sorva", "jyrsi", "valmist",
    "alihank", "service", "product", "machin", "about", "yritys",
    "toiminta", "osaaminen",
]

# Non-HTML file extensions to ignore during subpage discovery
NON_HTML_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".tiff",
    ".zip", ".tar", ".gz", ".7z", ".rar",
    ".css", ".js", ".ico", ".woff", ".woff2", ".ttf", ".eot",
    ".mp4", ".mp3", ".avi", ".mov", ".wmv", ".webm",
    ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
    ".xml", ".json", ".txt",
)

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
        self._lock = threading.Lock()

        os.makedirs(self.registry_dir, exist_ok=True)
        os.makedirs(self.websites_dir, exist_ok=True)
        os.makedirs(self.runs_dir, exist_ok=True)

    def _url_key(self, url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def save_registry_raw(self, url: str, raw_bytes: bytes, business_ids: List[str]) -> str:
        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        url_hash = self._url_key(url)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with self._lock:
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

        with self._lock:
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

    def get_website_html(self, url: str) -> Optional[str]:
        meta = self.get_cached_website(url)
        if not meta or not meta.get("sha256"):
            return None
        html_path = os.path.join(self.websites_dir, f"{meta['sha256']}.html")
        if not os.path.exists(html_path):
            return None
        try:
            with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return None

    def save_run(self, run_id: str, run_data: Dict[str, Any]) -> None:
        path = os.path.join(self.runs_dir, f"{run_id}.json")
        with self._lock:
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
        # Search recent runs for company (checking both returned and all reviewed pool candidates)
        for run_summary in self.list_runs():
            run_data = self.get_run(run_summary["run_id"])
            if run_data:
                for comp in run_data.get("companies", []):
                    if comp.get("business_id") == business_id:
                        return comp
                for comp in run_data.get("reviewed_companies", []):
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


class LinkExtractor(HTMLParser):
    """
    Lightweight HTML parser to extract internal links (<a href="...">) and anchor text.
    """

    def __init__(self):
        super().__init__()
        self.links: List[Tuple[str, str]] = []
        self._current_href: Optional[str] = None
        self._current_text: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        if tag.lower() == "a":
            if self._current_href is not None:
                text = " ".join("".join(self._current_text).split())
                self.links.append((self._current_href, text))
                self._current_href = None
                self._current_text = []
            for k, v in attrs:
                if k.lower() == "href" and v:
                    self._current_href = v.strip()
                    self._current_text = []
                    break

    def handle_data(self, data: str):
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag: str):
        if tag.lower() == "a" and self._current_href is not None:
            text = " ".join("".join(self._current_text).split())
            self.links.append((self._current_href, text))
            self._current_href = None
            self._current_text = []

    def close(self):
        super().close()
        if self._current_href is not None:
            text = " ".join("".join(self._current_text).split())
            self.links.append((self._current_href, text))
            self._current_href = None
            self._current_text = []


def discover_subpage_links(
    base_url: str,
    html_content: str,
    max_links: int = MAX_SUBPAGES_PER_SITE,
) -> List[str]:
    """
    Parses internal links (<a href="...">) from homepage HTML.
    Restricts strictly to same-domain/same-origin URLs (relative paths or same hostname).
    Never follows external domains.
    Filters out non-HTML assets (.pdf, .jpg, .png, .zip, .css, .js, etc.).
    Prioritizes links matching high-signal terms.
    Enforces SSRF safety checks.
    Returns at most max_links (default 2) highest-priority subpage URLs.
    """
    if not base_url or not html_content:
        return []

    try:
        base_split = urllib.parse.urlsplit(base_url)
    except Exception:
        return []

    base_host = (base_split.hostname or "").lower()
    if not base_host:
        return []

    # Canonical naked host (strip leading www.)
    base_naked = base_host[4:] if base_host.startswith("www.") else base_host

    parser = LinkExtractor()
    try:
        parser.feed(html_content)
        parser.close()
    except Exception:
        pass

    scored_links: Dict[str, Tuple[int, str]] = {}

    for href, anchor_text in parser.links:
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue

        try:
            abs_url = urllib.parse.urljoin(base_url, href)
            sub_split = urllib.parse.urlsplit(abs_url)
        except Exception:
            continue

        # Strictly http/https only
        if sub_split.scheme not in ("http", "https"):
            continue

        sub_host = (sub_split.hostname or "").lower()
        if not sub_host:
            continue

        # Strict same-domain restriction: sub_naked must strictly equal base_naked
        sub_naked = sub_host[4:] if sub_host.startswith("www.") else sub_host
        if sub_naked != base_naked:
            continue

        # Clean URL: strip fragment
        clean_sub_url = urllib.parse.urlunsplit(
            (sub_split.scheme, sub_split.netloc, sub_split.path, sub_split.query, "")
        )
        clean_base_url = urllib.parse.urlunsplit(
            (base_split.scheme, base_split.netloc, base_split.path, "", "")
        )

        # Do not re-crawl the homepage itself
        if clean_sub_url.rstrip("/") == clean_base_url.rstrip("/"):
            continue

        # Filter out non-HTML file extensions
        path_lower = sub_split.path.lower()
        if any(path_lower.endswith(ext) for ext in NON_HTML_EXTENSIONS):
            continue

        # SSRF safety check on candidate subpage URL
        safe, _ = is_safe_url(clean_sub_url)
        if not safe:
            continue

        # Scoring against high-signal terms
        score = 0
        anchor_lower = anchor_text.lower()
        for term in HIGH_SIGNAL_TERMS:
            if term in path_lower:
                score += 3
            if term in anchor_lower:
                score += 2

        # Only consider links matching at least one high-signal term
        if score > 0:
            if clean_sub_url not in scored_links or score > scored_links[clean_sub_url][0]:
                scored_links[clean_sub_url] = (score, anchor_text)

    if not scored_links:
        return []

    # Sort descending by score, then ascending by URL length (prefer cleaner top-level paths)
    sorted_candidates = sorted(
        scored_links.keys(),
        key=lambda u: (scored_links[u][0], -len(u)),
        reverse=True,
    )

    return sorted_candidates[:max_links]


def extract_evidence(
    text: str,
    keywords: List[str],
    source_url: str,
    compound_matching: bool = True,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Searches clean website text for occurrences of target keywords.
    Extracts a contextual snippet for each match.
    Supports Finnish compound word & morphological matching when compound_matching=True.
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

        if not compound_matching or len(kw_clean) < 4 or " " in kw_clean:
            # Strict word boundary for short acronyms (e.g. "cnc", "it"), multi-word terms, or baseline mode
            pattern = re.compile(rf"\b{re.escape(kw_clean)}\b", re.IGNORECASE)
        else:
            # Finnish compound word and morphological matching for keywords with length >= 4
            stems = [kw_clean]
            kw_lower = kw_clean.lower()
            if len(kw_clean) >= 6:
                if kw_lower.endswith(("us", "ys")):
                    stems.append(kw_clean[:-2])
                elif kw_lower.endswith(("ntä", "nta")):
                    stems.append(kw_clean[:-3])
                elif kw_lower.endswith("inen"):
                    stems.append(kw_clean[:-4])

            unique_stems = sorted(list(set(stems)), key=len, reverse=True)
            stem_group = "|".join(re.escape(s) for s in unique_stems)
            pattern = re.compile(rf"\b[\w-]*(?:{stem_group})[\w-]*\b", re.IGNORECASE)

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
        "assessment_status": "not_assessed",
        "website_note": "Registered website unread; not assessed." if registered_website else "No website registered in PRH YTJ; not assessed.",
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
        "subpages_crawled": [],
    }

    return company


def fetch_prh_companies(
    query: str,
    industry_code: str,
    limit: int,
    cache_mgr: CacheManager,
    refresh: bool = False,
    pool_limit: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], int, List[str], str]:
    """
    Executes query against PRH Open Data YTJ-API v3 for active private OY firms.
    Supports official industry filter (mainBusinessLine) and company name queries.
    Discovers a larger bounded candidate pool (up to 100-200 active current-sector OYs)
    and caches all fetched pages individually and combined, preserving traceable dates.
    Returns: (companies_pool_list, total_results_count, warnings, source_mode)
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

    target_pool = pool_limit if pool_limit is not None else max(100, min(200, limit * 15))

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

    # Check aggregated cache first if refresh=False
    cached_result = None
    if not refresh:
        cached_result = cache_mgr.get_cached_registry(api_url)

    raw_companies = []
    total_results = 0
    retrieved_at = now_iso
    pages_fetched_live = 0

    if cached_result:
        meta, data = cached_result
        source_mode = "cached"
        retrieved_at = meta.get("retrieved_at", now_iso)
        raw_companies = data.get("companies", [])
        total_results = data.get("totalResults", len(raw_companies))
    else:
        # Live fetch from PRH with multi-page discovery and per-page caching
        ssl_ctx = ssl.create_default_context()
        current_page = 1
        max_pages = 4 if not clean_query else 2

        try:
            while current_page <= max_pages:
                page_params = dict(params)
                if current_page > 1:
                    page_params["page"] = str(current_page)
                page_url = f"{PRH_BASE_URL}/companies?{urllib.parse.urlencode(page_params)}"

                page_cached = None
                if not refresh:
                    page_cached = cache_mgr.get_cached_registry(page_url)

                if page_cached:
                    p_meta, p_data = page_cached
                    page_comps = p_data.get("companies", [])
                    total_results = p_data.get("totalResults", len(page_comps))
                    if current_page == 1:
                        retrieved_at = p_meta.get("retrieved_at", now_iso)
                        source_mode = "cached"
                else:
                    req = urllib.request.Request(page_url, headers={"User-Agent": USER_AGENT})
                    with urllib.request.urlopen(req, context=ssl_ctx, timeout=REQUEST_TIMEOUT) as resp:
                        page_bytes = resp.read()
                    page_data = json.loads(page_bytes.decode("utf-8"))
                    page_comps = page_data.get("companies", [])
                    total_results = page_data.get("totalResults", len(page_comps))
                    page_bids = [
                        c.get("businessId", {}).get("value")
                        for c in page_comps
                        if c.get("businessId", {}).get("value")
                    ]
                    cache_mgr.save_registry_raw(page_url, page_bytes, page_bids)
                    pages_fetched_live += 1
                    if current_page == 1:
                        retrieved_at = now_iso

                raw_companies.extend(page_comps)

                # Check active OYs accumulated so far
                active_count = sum(
                    1 for c in raw_companies
                    if str(c.get("tradeRegisterStatus", "")).strip() == "1"
                    and (not industry_code or str((c.get("mainBusinessLine") or {}).get("type", "")).startswith(industry_code))
                    and any(str(f.get("type", "")).strip() in ("16", "OY") and not f.get("endDate") for f in c.get("companyForms", []))
                )
                if active_count >= target_pool or len(page_comps) < 100 or len(raw_companies) >= total_results:
                    break
                current_page += 1

            # Save combined aggregated raw cache for api_url to preserve all pages
            if pages_fetched_live > 0:
                all_bids = [
                    c.get("businessId", {}).get("value")
                    for c in raw_companies
                    if c.get("businessId", {}).get("value")
                ]
                combined_obj = {
                    "totalResults": total_results,
                    "companies": raw_companies,
                    "pages_cached": current_page,
                }
                combined_bytes = json.dumps(combined_obj, ensure_ascii=False).encode("utf-8")
                cache_mgr.save_registry_raw(api_url, combined_bytes, all_bids)

        except Exception as e:
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
                if len(normalized_list) >= target_pool:
                    break

    return normalized_list, total_results, warnings, source_mode


def enrich_company_website(
    company: Dict[str, Any],
    keywords: List[str],
    cache_mgr: CacheManager,
    refresh: bool = False,
    enable_subpages: bool = True,
    max_subpages: int = MAX_SUBPAGES_PER_SITE,
    compound_matching: bool = True,
) -> Tuple[Dict[str, Any], str]:
    """
    Enriches a company record with website evidence using respectful, bounded fetching.
    Records raw content hash, original retrieval date, and extracts contextual snippets.
    When homepage yields fewer than 2 keyword matches and enable_subpages=True,
    discovers and crawls up to max_subpages internal same-domain priority subpages.
    Returns: (enriched_company, website_source_mode: 'cached'|'live'|'none')
    """
    web_url = company.get("website")
    company.setdefault("subpages_crawled", [])
    if not web_url:
        company["website_status"] = "missing"
        company["assessment_status"] = "not_assessed"
        company["website_note"] = "No website registered in PRH YTJ; not assessed (no negative evidence inferred)."
        company["website_retrieved_at"] = None
        company["website_source_url"] = None
        return company, "none"

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Check cache first
    cached_web = None
    if not refresh:
        cached_web = cache_mgr.get_cached_website(web_url)

    html_text = ""
    if cached_web:
        extracted_text = cached_web.get("extracted_text", "")
        company["website_status"] = "fetched"
        company["assessment_status"] = "assessed"
        company["website_note"] = "Retrieved from verified local cache."
        company["website_retrieved_at"] = cached_web.get("retrieved_at")
        company["website_source_url"] = cached_web.get("final_url", web_url)
        web_source_mode = "cached"
        if enable_subpages:
            html_text = cache_mgr.get_website_html(web_url) or ""
    else:
        # Live fetch
        status_code, content_bytes, headers, final_url, err = safe_fetch_url(web_url, timeout=REQUEST_TIMEOUT)
        if err or status_code != 200:
            company["website_status"] = "unavailable"
            company["assessment_status"] = "not_assessed"
            company["website_note"] = f"Website unreachable ({err or status_code}); not assessed (no negative evidence inferred)."
            company["website_retrieved_at"] = now_iso
            company["website_source_url"] = final_url
            return company, "live"

        content_type = headers.get("content-type", "")
        html_text = content_bytes.decode("utf-8", errors="ignore")
        extracted_text = clean_html_to_text(html_text)
        cache_mgr.save_website_raw(
            web_url, final_url, status_code, content_type, content_bytes, extracted_text
        )

        company["website_status"] = "fetched"
        company["assessment_status"] = "assessed"
        company["website_note"] = "Live verified website prose."
        company["website_retrieved_at"] = now_iso
        company["website_source_url"] = final_url
        web_source_mode = "live"

    # Homepage Keyword extraction
    if extracted_text and keywords:
        ev_items, matched_kws = extract_evidence(
            extracted_text, keywords, company["website_source_url"], compound_matching=compound_matching
        )
        company["evidence"].extend(ev_items)
        company["matched_keywords"] = sorted(list(set(company["matched_keywords"] + matched_kws)))

    # Subpage Discovery & Crawling (1-hop internal links)
    if enable_subpages and len(company["matched_keywords"]) < 2 and html_text:
        subpage_candidates = discover_subpage_links(
            company["website_source_url"], html_text, max_links=max_subpages
        )
        for sub_url in subpage_candidates:
            cached_sub = None
            if not refresh:
                cached_sub = cache_mgr.get_cached_website(sub_url)

            sub_text = ""
            sub_source_url = sub_url

            if cached_sub:
                sub_text = cached_sub.get("extracted_text", "")
                sub_source_url = cached_sub.get("final_url", sub_url)
            else:
                s_status, s_bytes, s_headers, s_final, s_err = safe_fetch_url(sub_url, timeout=REQUEST_TIMEOUT)
                if not s_err and s_status == 200:
                    s_type = s_headers.get("content-type", "")
                    sub_text = clean_html_to_text(s_bytes.decode("utf-8", errors="ignore"))
                    sub_source_url = s_final
                    cache_mgr.save_website_raw(sub_url, s_final, s_status, s_type, s_bytes, sub_text)
                    web_source_mode = "mixed" if web_source_mode == "cached" else "live"

            if sub_text:
                if sub_source_url not in company["subpages_crawled"]:
                    company["subpages_crawled"].append(sub_source_url)

                sub_ev, sub_kws = extract_evidence(
                    sub_text, keywords, sub_source_url, compound_matching=compound_matching
                )
                new_kws = [k for k in sub_kws if k not in company["matched_keywords"]]
                if new_kws:
                    company["matched_keywords"] = sorted(list(set(company["matched_keywords"] + new_kws)))
                    for item in sub_ev:
                        kw_matched = [k for k in new_kws if item.get("criterion") == f"Keyword match: '{k}'"]
                        if kw_matched:
                            company["evidence"].append(item)

                # Check corporate-change wording on subpage
                if not company.get("excluded_reason"):
                    change_terms = [
                        "yrityskaupan", "yhdistivät voimansa", "yhdistäneet voimansa",
                        "acquired by", "part of the group", "joined forces"
                    ]
                    sub_changes, _ = extract_evidence(sub_text, change_terms, sub_source_url, compound_matching=False)
                    if sub_changes:
                        company["excluded_reason"] = "Review corporate-change wording on the website before treating this as an independent target."
                        for item in sub_changes[:2]:
                            item["criterion"] = "Corporate-change wording — advisor review required"
                            company["evidence"].append(item)

                # Stop early if 2 or more keyword matches reached
                if len(company["matched_keywords"]) >= 2:
                    break

    # Public wording check on homepage if not already flagged
    if extracted_text and not company.get("excluded_reason"):
        change_terms = [
            "yrityskaupan", "yhdistivät voimansa", "yhdistäneet voimansa",
            "acquired by", "part of the group", "joined forces"
        ]
        changes, _ = extract_evidence(extracted_text, change_terms, company["website_source_url"], compound_matching=False)
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
    progress_callback: Optional[Any] = None,
    enable_subpages: bool = True,
    compound_matching: bool = True,
) -> Dict[str, Any]:
    """
    Orchestrates candidate search, enrichment, scoring, and run storage.
    Accurately tracks mixed live/cached source mode while preserving original dates.
    Supports Approach B deep ingestion (1-hop subpages + compound word matching).
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

    if progress_callback:
        progress_callback("prh_search", 30, f"Querying Finnish PRH YTJ API v3 (query='{query}', industry='{industry_code}')...")

    # 1. PRH Discovery Search
    companies, total_candidates, warnings, registry_mode = fetch_prh_companies(
        query=query,
        industry_code=industry_code,
        limit=limit,
        cache_mgr=cache_mgr,
        refresh=refresh,
    )

    if progress_callback:
        progress_callback("website_enrichment", 50, f"Retrieved {len(companies)} PRH entities. Crawling registered websites...")

    # 2. Website Evidence Enrichment & Scoring
    # Prioritize registered websites, bound enrichment pool, and execute concurrent enrichment (4 workers)
    with_web = [c for c in companies if c.get("website")]
    without_web = [c for c in companies if not c.get("website")]

    # Bounded enrichment budget for websites (up to 40 candidates with registered websites)
    enrich_budget = min(40, len(with_web))
    to_enrich = with_web[:enrich_budget]
    unread_web = with_web[enrich_budget:]

    enriched_prioritized = []
    web_modes = set()
    total_enrich = max(1, len(to_enrich))
    completed_count = 0

    if to_enrich:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_comp = {
                executor.submit(
                    enrich_company_website,
                    comp,
                    all_keywords,
                    cache_mgr,
                    refresh,
                    enable_subpages,
                    MAX_SUBPAGES_PER_SITE,
                    compound_matching,
                ): comp
                for comp in to_enrich
            }
            for future in concurrent.futures.as_completed(future_to_comp):
                enriched, w_mode = future.result()
                web_modes.add(w_mode)
                completed_count += 1

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

                enriched_prioritized.append(enriched)

                if progress_callback:
                    pct = 50 + int(35 * completed_count / total_enrich)
                    progress_callback("website_enrichment", pct, f"Crawling registered websites ({completed_count}/{total_enrich})...")

    # Candidates whose websites were not read or missing: mark as not assessed rather than negative evidence
    for comp in unread_web:
        comp["website_status"] = "not_fetched"
        comp["assessment_status"] = "not_assessed"
        comp["website_note"] = "Candidate discovered in registry pool; website not crawled in this pass."
        comp["missing_criteria"] = list(all_keywords)
        comp["missing_criteria_note"] = "Criteria unverified: website was not read; no negative evidence inferred."
        comp["relevance_score"] = 0.0
        comp["keyword_coverage"] = f"0/{len(all_keywords)}" if all_keywords else "0/0"

    for comp in without_web:
        comp["website_status"] = "missing"
        comp["assessment_status"] = "not_assessed"
        comp["website_note"] = "No registered website in PRH YTJ; not assessed."
        comp["missing_criteria"] = list(all_keywords)
        comp["missing_criteria_note"] = "Criteria unverified: no website in registry; no negative evidence inferred."
        comp["relevance_score"] = 0.0
        comp["keyword_coverage"] = f"0/{len(all_keywords)}" if all_keywords else "0/0"

    # Combine all evaluated records
    all_reviewed = enriched_prioritized + unread_web + without_web

    # Sort all reviewed records: evidence-positive first, then accessible websites, then registered websites
    def rank_key(comp):
        has_kw_match = 1 if len(comp.get("matched_keywords", [])) > 0 else 0
        score = comp.get("relevance_score", 0.0)
        ev_count = len(comp.get("evidence", []))
        site_fetched = 1 if comp.get("website_status") == "fetched" else 0
        has_site = 1 if comp.get("website") else 0
        return (has_kw_match, score, ev_count, site_fetched, has_site)

    all_reviewed.sort(key=rank_key, reverse=True)

    # Return requested top 5-20 with evidence first
    returned_companies = all_reviewed[:limit]

    if progress_callback:
        progress_callback("scoring", 90, "Evaluating keyword evidence and scoring coverage...")

    elapsed_ms = int((time.time() - start_time) * 1000)
    elapsed_seconds = round((time.time() - start_time), 2)

    # Calculate run stats
    total_scanned = len(all_reviewed)
    website_read_count = sum(1 for c in all_reviewed if c.get("website_status") == "fetched")
    subpages_crawled_count = sum(len(c.get("subpages_crawled", [])) for c in all_reviewed)
    evidence_positive_count = sum(1 for c in all_reviewed if len(c.get("matched_keywords", [])) > 0)
    review_flags = sum(1 for c in all_reviewed if c.get("excluded_reason") or c.get("corporate_change_flag"))

    stats = {
        "companies_found": total_candidates,
        "returned_companies": len(returned_companies),
        "accessible_sites": website_read_count,
        "subpages_crawled": subpages_crawled_count,
        "matched_evidence": evidence_positive_count,
        "flags": review_flags,
        "elapsed_seconds": elapsed_seconds,
        "scanned": total_scanned,
        "website_read": website_read_count,
        "evidence_positive": evidence_positive_count,
        "returned": len(returned_companies),
    }

    diagnostics = {
        "scanned": total_scanned,
        "website_read": website_read_count,
        "subpages_crawled": subpages_crawled_count,
        "evidence_positive": evidence_positive_count,
        "returned": len(returned_companies),
        "pool_size": total_scanned,
    }

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
        "companies": returned_companies,
        "reviewed_companies": all_reviewed,
        "diagnostics": diagnostics,
        "warnings": warnings,
        "stats": stats,
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
