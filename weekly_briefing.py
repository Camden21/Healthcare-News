#!/usr/bin/env python3
"""
Weekly AI-written Medicaid / Home Health / HCBS briefing.

Calls the Claude API directly over HTTPS (no third-party SDK — same
zero-dependency philosophy as fetch_events.py) with the web_search server
tool enabled, restricted to a curated list of authoritative healthcare-policy
domains. Claude researches the last 7 days and drafts a narrative update,
which is parsed into weekly_briefings.json (newest first).

This is a separate, narrative companion to events.json's rule-scored event
log — build_page.py reads both and renders "Weekly Briefing" as its own tab.

Required env var:
    ANTHROPIC_API_KEY   (GitHub secret)

Optional env var:
    ANTHROPIC_MODEL     defaults to "claude-sonnet-5" — check
                        https://docs.claude.com/en/docs/about-claude/models
                        for the current recommended model ID and update if needed.

Run weekly via .github/workflows/weekly-briefing.yml, before build_page.py.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

BRIEFINGS_FILE = "weekly_briefings.json"
MAX_STORED = 26  # ~6 months of weekly history

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

# Curated to authoritative federal sources plus the trade/policy outlets
# already used elsewhere in this repo (fetch_events.py's TRADE_SOURCES).
# Adjust freely — this only constrains where web_search is allowed to look.
ALLOWED_DOMAINS = [
    "cms.gov",
    "medicaid.gov",
    "allianceforcareathome.org",  # formerly NAHC
    "homehealthcarenews.com",
    "mcknightshomecare.com",
    "kff.org",  # Kaiser Family Foundation — Medicaid Watch
]

REQUIRED_SECTIONS = ["Medicaid", "Home Health", "HCBS"]

PROMPT_TEMPLATE = """You write the weekly "Medicaid, Home Health & HCBS Update" \
for a healthcare credit-risk news tracker used by a bank's healthcare lending \
desk. Use web search to find the most significant, verifiable news published \
in the last 7 days (today is {today}). Search across Medicaid policy, \
funding, and regulatory action; home health industry and reimbursement news; \
and HCBS (Home and Community-Based Services) waiver, workforce, and access \
news.

Output ONLY Markdown, in exactly this structure, nothing before or after it:

## Medicaid
- <one or two sentence summary of a real, dated development> ([Source Name](url), Mon D, YYYY)
- (3 to 6 bullets total)

## Home Health
- (same format, 3 to 6 bullets)

## HCBS
- (same format, 3 to 6 bullets)

Rules:
- Every bullet must cite a source you actually found via search, with a working URL.
- Only include items genuinely published in the last 7 days.
- If a section has no significant news this week, write a single bullet: \
"No significant updates this week." with no citation.
- Write for a credit/lending audience: note dollar amounts, effective dates, \
and scope (nationwide vs. state) wherever the source states them.
- Do not editorialize. Report what changed and cite it.
- Do not include a title, a preamble, or any text outside the three ## sections.
"""


# ----------------------------------------------------------------------
# Claude API call
# ----------------------------------------------------------------------

def call_claude(prompt):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY is not set.")
        sys.exit(1)

    payload = {
        "model": MODEL,
        "max_tokens": 4000,
        "tools": [{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 10,
            "allowed_domains": ALLOWED_DOMAINS,
        }],
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": API_VERSION,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Claude API error {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Claude API: {exc}") from exc

    if data.get("type") == "error":
        raise RuntimeError(f"Claude API returned an error: {data}")

    text = "\n".join(
        block.get("text", "") for block in data.get("content", [])
        if block.get("type") == "text"
    ).strip()
    return text


def fetch_briefing_markdown():
    today = datetime.now(timezone.utc).date()
    text = call_claude(PROMPT_TEMPLATE.format(today=today.isoformat()))

    idx = text.find("## Medicaid")
    if idx == -1:
        raise RuntimeError(
            "Claude's response did not contain the expected '## Medicaid' "
            "section header — aborting before publish.\n\n"
            "--- raw output (first 2000 chars) ---\n" + text[:2000]
        )
    return text[idx:].strip()


# ----------------------------------------------------------------------
# Minimal Markdown -> HTML (bullets + inline links only — deliberately not
# a full Markdown parser, to avoid a third-party dependency for a tightly
# constrained output format).
# ----------------------------------------------------------------------

LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def esc(text):
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def inline_md_to_html(text):
    text = esc(text)

    def repl(m):
        label, url = m.group(1), m.group(2)
        return f'<a href="{url}" target="_blank" rel="noopener">{label}</a>'

    return LINK_RE.sub(repl, text)


def bullets_to_html(body):
    items = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("- ") or line.startswith("* "):
            items.append(inline_md_to_html(line[2:].strip()))
        elif items:
            # a wrapped continuation line for the previous bullet
            items[-1] += " " + inline_md_to_html(line)
    if not items:
        return f"<p>{inline_md_to_html(body)}</p>"
    return "<ul>" + "".join(f"<li>{it}</li>" for it in items) + "</ul>"


def parse_sections(markdown_text):
    chunks = re.split(r"(?m)^##\s+", markdown_text)
    sections = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        heading, _, body = chunk.partition("\n")
        heading = heading.strip()
        body = body.strip()
        if not body:
            continue
        sections.append({"heading": heading, "bodyHtml": bullets_to_html(body)})
    return sections


# ----------------------------------------------------------------------

def main():
    briefing_md = fetch_briefing_markdown()
    sections = parse_sections(briefing_md)

    found = {s["heading"] for s in sections}
    missing = [s for s in REQUIRED_SECTIONS if s not in found]
    if missing:
        raise RuntimeError(
            f"Missing expected section(s): {missing} — aborting before publish.\n\n"
            "--- parsed markdown ---\n" + briefing_md[:2000]
        )

    today = datetime.now(timezone.utc).date()
    entry = {
        "date": today.strftime("%b %-d, %Y"),
        "dateSort": today.strftime("%Y-%m-%dT00:00:00"),
        "title": f"Medicaid, Home Health & HCBS Update — {today.strftime('%B %-d, %Y')}",
        "sections": sections,
    }

    try:
        with open(BRIEFINGS_FILE) as f:
            briefings = json.load(f)
    except FileNotFoundError:
        briefings = []

    # Re-running the same day (e.g. a manual workflow_dispatch retry)
    # replaces today's entry instead of duplicating it.
    briefings = [b for b in briefings if b.get("dateSort") != entry["dateSort"]]
    briefings.insert(0, entry)
    briefings = briefings[:MAX_STORED]

    with open(BRIEFINGS_FILE, "w") as f:
        json.dump(briefings, f, indent=2)

    print(f"Wrote briefing for {entry['date']} — {len(briefings)} stored total.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
