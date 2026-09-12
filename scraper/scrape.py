#!/usr/bin/env python3
"""
SVNIT Result Scraper
====================
Fetches the SVNIT student notice page, extracts result notices,
and writes results.json in the shape the widget expects.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


SOURCE_URL = "https://www.svnit.ac.in/web/student_notice.php"
BASE_URL   = "https://www.svnit.ac.in"
OUTPUT     = Path("results.json")

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


def make_session():
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://",  HTTPAdapter(max_retries=retry))
    return s


def fetch_page(session):
    r = session.get(SOURCE_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def parse_notices(html):
    soup = BeautifulSoup(html, "html.parser")
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
        url = href if href.startswith("http") else urljoin(BASE_URL, href)

        session_name = "Other"
        for name, pat in SESSION_PATTERNS.items():
            if pat.search(text):
                session_name = name
                break

        year_match = re.search(r"20\d{2}", url + " " + text)
        year = int(year_match.group(0)) if year_match else datetime.now().year

        results.append({
            "title": title,
            "url": url,
            "is_result": True,
            "session": session_name,
            "year": year,
        })

    return results


def load_previous_urls():
    if OUTPUT.exists():
        try:
            data = json.loads(OUTPUT.read_text(encoding="utf-8"))
            return {item["url"] for item in data.get("items", [])}
        except Exception:
            return set()
    return set()


def main():
    print(f"Fetching {SOURCE_URL} ...")
    session = make_session()

    try:
        html = fetch_page(session)
    except requests.RequestException as e:
        print(f"Network error: {e}", file=sys.stderr)
        sys.exit(1)

    results = parse_notices(html)
    print(f"Scraped {len(results)} result notices.")

    if len(results) < 1:
        print(
            "SAFETY CHECK FAILED: 0 result notices found. "
            "The site layout may have changed.",
            file=sys.stderr,
        )
        sys.exit(1)

    previous_urls = load_previous_urls()
    for item in results:
        item["is_new"] = item["url"] not in previous_urls

    output = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "items": results,
    }

    OUTPUT.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(results)} results to {OUTPUT} ({sum(i['is_new'] for i in results)} new)")


if __name__ == "__main__":
    main()
