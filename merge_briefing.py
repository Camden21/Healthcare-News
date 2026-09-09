#!/usr/bin/env python3
"""
Validates the weekly briefing draft written by Claude Code, then merges it
into weekly_briefings.json.

Claude Code (running in .github/workflows/weekly-briefing.yml) does the
research and writes a single-entry file, briefing_draft.json. This script
is the deterministic half: it checks the draft is well-formed, escapes it,
stamps the date, prepends it to the history and deletes the draft.

Splitting it this way matters. The agent is good at research and judgement
and bad at reliably rewriting a growing JSON array in place; Python is the
reverse. So the agent writes one small object, and Python owns the history.

If the draft is missing or malformed, this script exits non-zero and the
workflow stops BEFORE the site is rebuilt or any email goes out. That
failure is the automated safety net standing in for manual review.

No API key needed — Claude Code authenticates with your Claude subscription
via the CLAUDE_CODE_OAUTH_TOKEN secret.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

DRAFT_FILE = "briefing_draft.json"
BRIEFINGS_FILE = "weekly_briefings.json"
MAX_STORED = 26  # ~6 months of weekly history

# The whole point of the briefing is this distinction.
STATUS_TIERS = ["implemented", "proposed", "pending", "rhetoric"]


# ----------------------------------------------------------------------
# Validation — fail loudly rather than publish something malformed.
# ----------------------------------------------------------------------

def validate(payload):
    problems = []

    if not isinstance(payload, dict):
        raise RuntimeError(f"{DRAFT_FILE} must contain a single JSON object.")

    for key in ("overview", "items", "table", "focus"):
        if not payload.get(key):
            problems.append(f"missing or empty '{key}'")

    items = payload.get("items")
    if not isinstance(items, list) or not (1 <= len(items) <= 8):
        problems.append(
            f"expected 1-8 items, got "
            f"{len(items) if isinstance(items, list) else 'non-list'}"
        )
        items = items if isinstance(items, list) else []

    for i, item in enumerate(items, 1):
        if not isinstance(item, dict):
            problems.append(f"item {i} is not an object")
            continue
        for key in ("headline", "status", "statusTier", "body", "creditImplication"):
            if not item.get(key):
                problems.append(f"item {i} missing '{key}'")
        tier = item.get("statusTier")
        if tier and tier not in STATUS_TIERS:
            problems.append(
                f"item {i} has unknown statusTier {tier!r} "
                f"(expected one of {STATUS_TIERS})"
            )
        sources = item.get("sources") or []
        if not sources:
            problems.append(f"item {i} has no sources")
        for s in sources:
            if not isinstance(s, dict) or not str(s.get("url", "")).startswith("http"):
                problems.append(f"item {i} has a source without a valid URL")

    table = payload.get("table")
    if isinstance(table, list):
        for i, row in enumerate(table, 1):
            if not isinstance(row, dict):
                problems.append(f"table row {i} is not an object")
                continue
            for key in ("development", "status", "read"):
                if not row.get(key):
                    problems.append(f"table row {i} missing '{key}'")
    elif table:
        problems.append("'table' must be a list")

    if problems:
        raise RuntimeError(
            "Briefing draft failed validation — aborting before publish:\n  - "
            + "\n  - ".join(problems)
        )


# ----------------------------------------------------------------------
# Escaping / shaping
# ----------------------------------------------------------------------

def esc(text):
    return (str(text or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def paragraphs_to_html(text):
    parts = [p.strip() for p in re.split(r"\n\s*\n", str(text or "")) if p.strip()]
    return "".join(f"<p>{esc(p)}</p>" for p in parts)


def build_entry(payload, today):
    items = []
    for item in payload["items"]:
        items.append({
            "headline": esc(item["headline"]),
            "status": esc(item["status"]),
            "statusTier": item["statusTier"],
            "bodyHtml": paragraphs_to_html(item["body"]),
            "creditImplication": esc(item["creditImplication"]),
            "sources": [
                {"label": esc(s.get("label") or "Source"), "url": s["url"]}
                for s in (item.get("sources") or [])
                if isinstance(s, dict) and str(s.get("url", "")).startswith("http")
            ],
        })

    table = [{
        "development": esc(row.get("development")),
        "status": esc(row.get("status")),
        "read": esc(row.get("read")),
    } for row in (payload.get("table") or []) if isinstance(row, dict)]

    return {
        "date": today.strftime("%b %-d, %Y"),
        "dateSort": today.strftime("%Y-%m-%dT00:00:00"),
        "title": "Weekly Medicaid, Home Health & HCBS Update",
        "throughDate": f"Through {today.strftime('%B %-d, %Y')}",
        "overviewHtml": paragraphs_to_html(payload["overview"]),
        "items": items,
        "table": table,
        "focusHtml": paragraphs_to_html(payload["focus"]),
    }


# ----------------------------------------------------------------------

def main():
    try:
        with open(DRAFT_FILE) as f:
            payload = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {DRAFT_FILE} not found.")
        print("Claude Code did not write a draft — check the previous workflow")
        print("step's log. Nothing was published.")
        return 1
    except json.JSONDecodeError as exc:
        print(f"ERROR: {DRAFT_FILE} is not valid JSON: {exc}")
        return 1

    validate(payload)

    today = datetime.now(timezone.utc).date()
    entry = build_entry(payload, today)

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

    # The draft is scratch — don't commit it.
    try:
        os.remove(DRAFT_FILE)
    except OSError:
        pass

    print(f"Merged briefing for {entry['date']}: {len(entry['items'])} items, "
          f"{len(entry['table'])} table rows. {len(briefings)} stored total.")
    for i, it in enumerate(entry["items"], 1):
        print(f"  {i}. [{it['statusTier']}] {it['headline'][:64]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
