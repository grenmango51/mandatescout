#!/usr/bin/env python3
"""
MandateScout Deep Ingestion Pipeline (Approach B) Test Suite
===========================================================
Python Standard Library Only (unittest).
Validates:
1. Subpage same-domain restriction (no off-domain crawling).
2. SSRF protection on subpage URLs.
3. Finnish compound word & morphological matching.
4. Bounded subpage limit per site (max 2).
5. Non-HTML asset filtering (.pdf, .jpg, .zip, etc.).
6. Subpage evidence extraction attribution and metadata caching.
"""

import os
import shutil
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from product.collector import (
    CacheManager,
    discover_subpage_links,
    enrich_company_website,
    extract_evidence,
    is_safe_url,
)


def mock_getaddrinfo(host, port, *args, **kwargs):
    """Mock getaddrinfo for deterministic, offline testing."""
    if host in ("127.0.0.1", "localhost"):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]
    if host == "169.254.169.254":
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))]
    if host == "10.0.0.1":
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", port))]
    if host == "192.168.1.1":
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", port))]
    # Public simulated IPs
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", port))]


class TestSubpageDiscoveryAndRestrictions(unittest.TestCase):
    """Verifies subpage link parsing, same-domain enforcement, SSRF checks, and bounds."""

    @patch("socket.getaddrinfo", side_effect=mock_getaddrinfo)
    def test_same_domain_restriction(self, _mock_dns):
        base_url = "https://koneistuspaja.fi"
        html_sample = """
        <html>
        <body>
            <nav>
                <a href="/palvelut">Palvelumme</a>
                <a href="https://koneistuspaja.fi/tuotteet">Tuotteet</a>
                <a href="https://www.koneistuspaja.fi/koneistus">Koneistus</a>
                <a href="https://google.com/search">Google</a>
                <a href="https://facebook.com/koneistuspaja">Facebook</a>
                <a href="https://other-company.fi/palvelut">Other Company</a>
                <a href="https://sub.koneistuspaja.evil.com/koneistus">Phishing</a>
            </nav>
        </body>
        </html>
        """
        discovered = discover_subpage_links(base_url, html_sample, max_links=10)
        self.assertTrue(len(discovered) > 0)
        for link in discovered:
            self.assertTrue(
                link.startswith("https://koneistuspaja.fi") or link.startswith("https://www.koneistuspaja.fi"),
                f"Discovered link must be strictly same domain: {link}"
            )
            self.assertNotIn("google.com", link)
            self.assertNotIn("facebook.com", link)
            self.assertNotIn("other-company.fi", link)
            self.assertNotIn("evil.com", link)

    @patch("socket.getaddrinfo", side_effect=mock_getaddrinfo)
    def test_ssrf_protection_on_subpage_urls(self, _mock_dns):
        base_url = "http://127.0.0.1"
        html_sample = """
        <html>
        <body>
            <a href="http://127.0.0.1/palvelut">Localhost Services</a>
            <a href="http://169.254.169.254/latest/meta-data/">AWS Metadata</a>
            <a href="http://10.0.0.1/admin/koneistus">Internal IP</a>
        </body>
        </html>
        """
        discovered = discover_subpage_links(base_url, html_sample, max_links=5)
        # All private IP endpoints must be rejected by is_safe_url
        self.assertEqual(discovered, [])

    @patch("socket.getaddrinfo", side_effect=mock_getaddrinfo)
    def test_bounded_subpage_limit(self, _mock_dns):
        base_url = "https://tarkkuustyo.fi"
        html_sample = """
        <html>
        <body>
            <a href="/palvelut">Palvelut</a>
            <a href="/koneistus">Koneistus</a>
            <a href="/sorvaus">Sorvaus</a>
            <a href="/jyrsinta">Jyrsintä</a>
            <a href="/alihankinta">Alihankinta</a>
            <a href="/valmistus">Valmistus</a>
            <a href="/tuotteet">Tuotteet</a>
        </body>
        </html>
        """
        # Default bound is max 2
        discovered = discover_subpage_links(base_url, html_sample, max_links=2)
        self.assertLessEqual(len(discovered), 2, "Must return at most 2 subpage links")

        # Custom bound 1
        discovered_1 = discover_subpage_links(base_url, html_sample, max_links=1)
        self.assertEqual(len(discovered_1), 1)

    @patch("socket.getaddrinfo", side_effect=mock_getaddrinfo)
    def test_asset_and_special_link_filtering(self, _mock_dns):
        base_url = "https://sorvaamo.fi"
        html_sample = """
        <html>
        <body>
            <a href="/esite_koneistus.pdf">Koneistus PDF Esite</a>
            <a href="/kuva_sorvaus.png">Sorvaus Kuva</a>
            <a href="/arkisto_tuotteet.zip">Tuotteet Zip</a>
            <a href="/tyylit.css">CSS Tiedosto</a>
            <a href="mailto:info@sorvaamo.fi">Ota yhteyttä</a>
            <a href="tel:+358401234567">Soita</a>
            <a href="javascript:void(0)">Klikkaa</a>
            <a href="#osio_palvelut">Hyppää</a>
            <a href="/palvelut">Oikea Palvelusivu</a>
        </body>
        </html>
        """
        discovered = discover_subpage_links(base_url, html_sample, max_links=10)
        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0], "https://sorvaamo.fi/palvelut")


class TestFinnishCompoundAndMorphologicalMatching(unittest.TestCase):
    """Verifies Finnish compound word expansion, stem inflections, and strict acronym boundaries."""

    def test_compound_word_matches_stem(self):
        text = "Yrityksemme ydinosaamista on alihankintakoneistus ja vaativa tarkkuuskoneistus."
        evidence, matched_kws = extract_evidence(text, ["koneistus"], "https://example.fi", compound_matching=True)
        self.assertIn("koneistus", matched_kws)
        self.assertEqual(len(evidence), 1)
        self.assertIn("alihankintakoneistus", evidence[0]["excerpt"])

    def test_inflected_finnish_words(self):
        text = "Koneistamme ja sorvaamme tarkkuusosia asiakkaan toiveiden mukaisesti."
        evidence, matched_kws = extract_evidence(text, ["koneistus", "sorvaus"], "https://example.fi", compound_matching=True)
        self.assertIn("koneistus", matched_kws)
        self.assertIn("sorvaus", matched_kws)
        self.assertEqual(len(evidence), 2)
        # Excerpt contains the inflected words
        self.assertIn("Koneistamme", evidence[0]["excerpt"])
        self.assertIn("sorvaamme", evidence[1]["excerpt"])

    def test_hyphenated_compounds(self):
        text = "Käytössämme on moderni 5-akselinen cnc-koneistus ja tarkkuus-jyrsintä."
        evidence, matched_kws = extract_evidence(text, ["koneistus", "jyrsintä"], "https://example.fi", compound_matching=True)
        self.assertIn("koneistus", matched_kws)
        self.assertIn("jyrsintä", matched_kws)
        self.assertIn("cnc-koneistus", evidence[0]["excerpt"])

    def test_short_acronym_strict_word_boundary(self):
        text = "Tarjoamme huippuluokan CNC työstöä. Emme valmista acncb tuotteita."
        evidence, matched_kws = extract_evidence(text, ["cnc"], "https://example.fi", compound_matching=True)
        self.assertIn("cnc", matched_kws)
        self.assertEqual(len(matched_kws), 1)

        # Negative check: only the word with acncb
        negative_text = "Tämä sivu sisältää vain sanan acncb ja bcnca."
        neg_ev, neg_kws = extract_evidence(negative_text, ["cnc"], "https://example.fi", compound_matching=True)
        self.assertEqual(len(neg_kws), 0, "Short acronym must not match substrings inside longer unrelated words")

    def test_baseline_exact_match_fallback(self):
        text = "Yrityksemme tekee alihankintakoneistusta."
        # When compound_matching=False, exact word boundary is required
        _, matched_baseline = extract_evidence(text, ["koneistus"], "https://example.fi", compound_matching=False)
        self.assertEqual(len(matched_baseline), 0)

        # When compound_matching=True, matches compound
        _, matched_deep = extract_evidence(text, ["koneistus"], "https://example.fi", compound_matching=True)
        self.assertIn("koneistus", matched_deep)


class TestDeepIngestionEnrichment(unittest.TestCase):
    """Verifies end-to-end enrichment with subpage crawl and caching."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cache_mgr = CacheManager(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("socket.getaddrinfo", side_effect=mock_getaddrinfo)
    def test_enrichment_crawls_subpage_when_homepage_sparse(self, _mock_dns):
        # Homepage with 0 keyword matches, but linking to /palvelut
        home_url = "https://testivalmistaja.fi"
        sub_url = "https://testivalmistaja.fi/palvelut"

        home_html = (
            "<html><body>"
            "<h1>Tervetuloa yrityksemme sivuille</h1>"
            "<a href='/palvelut'>Tutustu koneistuspalveluihin</a>"
            "</body></html>"
        ).encode("utf-8")
        sub_html = (
            "<html><body>"
            "<h2>Palvelumme</h2>"
            "<p>Korkealaatuista CNC koneistusta ja alihankintaa vuosikymmenten kokemuksella.</p>"
            "</body></html>"
        ).encode("utf-8")

        # Pre-seed cache
        from product.collector import clean_html_to_text
        self.cache_mgr.save_website_raw(
            home_url, home_url, 200, "text/html", home_html, clean_html_to_text(home_html.decode())
        )
        self.cache_mgr.save_website_raw(
            sub_url, sub_url, 200, "text/html", sub_html, clean_html_to_text(sub_html.decode())
        )

        comp = {
            "business_id": "2999999-9",
            "name": "Testivalmistaja Oy",
            "website": home_url,
            "website_status": "not_fetched",
            "evidence": [],
            "matched_keywords": [],
            "subpages_crawled": [],
        }

        enriched, mode = enrich_company_website(
            company=comp,
            keywords=["cnc", "koneistus", "sorvaus"],
            cache_mgr=self.cache_mgr,
            refresh=False,
            enable_subpages=True,
            max_subpages=2,
            compound_matching=True,
        )

        self.assertEqual(enriched["website_status"], "fetched")
        # Subpage crawled
        self.assertIn(sub_url, enriched["subpages_crawled"])
        # Evidence found from subpage
        self.assertIn("cnc", enriched["matched_keywords"])
        self.assertIn("koneistus", enriched["matched_keywords"])

        # Check source_url attribution on subpage evidence
        sub_evidence = [e for e in enriched["evidence"] if e.get("source_url") == sub_url]
        self.assertTrue(len(sub_evidence) > 0, "Subpage evidence must cite subpage URL as source_url")


if __name__ == "__main__":
    unittest.main()
