#!/usr/bin/env python3
"""
SVNIT Result Scraper
====================
Fetches the SVNIT student notice page, extracts result notices,
diffs against the last known state, and writes results.json.

Safety features:
- Fails loudly if fewer than 10 notices found (catches HTML layout changes)
- Only commits if data actually changed (avoids noisy commit history)
- Retries on network failures
- Handles both relative and absolute URLs gracefully
"""

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ── Configuration ──────────────────────────────────────────────
SOURCE_URL = "https://www.svnit.ac.in/web/student_notice.php"
BASE_URL   = "https://www.svnit.ac.in"
OUTPUT     = Path("results.json")
MIN_ITEMS  = 10  # Safety: real page always has dozens of notices

RESULT_KEYWORDS = {"result", "results", "declared", "grade", "marks"}
SESSION_PATTERNS = {
    "Even":          re.compile(r"\beven\b", re.I),
    "Odd":           re.compile(r"\bodd\b",  re.I),
    "Supplementary": re.compile(r"\bsuppl(?:ementary|ement|y)\b", re.I),
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    )
}


# ── HTTP session with retries ──────────────────────────────────
def make_session():
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://",  HTTPAdapter(max_retries=retry))
    return s


# ── Core scraper ───────────────────────────────────────────────
def fetch_page(session):
    """Fetch the notice page, raise on failure."""
    r = session.get(SOURCE_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def parse_notices(html):
    """
    Walk the notice list and extract structured result entries.
    Returns a list of dicts sorted newest-first.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Primary selector (matches the live site); fall back to broader one
    items = soup.select("#no-more-tables ul.bullet li")
    if not items:
        items = soup.select("ul.bullet li")
    if not items:
        items = soup.select("li p.title")

    results = []
    for li in items:
        text = li.get_text(" ", strip=True)
        if not any(kw in text.lower() for kw in RESULT_KEYWORDS):
            continue

        link = li.find("a", href=True)
        if not link:
            continue

        href  = link["href"].strip()
        title = link.get_text(strip=True) or text[:120]

        # Build absolute URL (handles relative and already-absolute)
        url = href if href.startswith("http") else urljoin(BASE_URL, href)

        # Extract a stable id from the URL path
        slug = re.sub(r"[^a-z0-9]+", "-", href.split("/")[-1].lower()).strip("-")
        if not slug:
            slug = str(hash(url))[:12]

        # Try to detect session from text
        session = "Other"
        for name, pat in SESSION_PATTERNS.items():
            if pat.search(text):
                session = name
                break

        # Try to guess year from the URL / text
        year_match = re.search(r"20\d{2}", url + " " + text)
        year = int(year_match.group(0)) if year_match else datetime.now().year

        results.append({
            "id":      slug,
            "title":   title,
            "url":     url,
            "date":    datetime.utcnow().strftime("%Y-%m-%d"),
            "session": session,
            "year":    year,
        })

    # Newest first
    results.sort(key=lambda r: r["date"], reverse=True)
    return results


def load_previous():
    if OUTPUT.exists():
        try:
            return json.loads(OUTPUT.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save(results):
    OUTPUT.write_text(
        json.dumps(results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ── Main ───────────────────────────────────────────────────────
def main():
    print(f"Fetching {SOURCE_URL} ...")
    session = make_session()

    try:
        html = fetch_page(session)
    except requests.RequestException as e:
        print(f"❌ Network error: {e}", file=sys.stderr)
        sys.exit(1)

    results = parse_notices(html)
    print(f"Scraped {len(results)} result notices.")

    # Safety check: if the page structure changed, we'd scrape 0 items
    if len(results) < MIN_ITEMS:
        print(
            f"❌ SAFETY CHECK FAILED: only {len(results)} items found "
            f"(expected ≥ {MIN_ITEMS}). The site layout may have changed.",
            file=sys.stderr,
        )
        sys.exit(1)

    previous = load_previous()
    if results == previous:
        print("✅ No changes since last run. Skipping write.")
        sys.exit(0)

    save(results)
    print(f"✅ Wrote {len(results)} results to {OUTPUT}")


if __name__ == "__main__":
    main()