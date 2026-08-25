# Weekly Medicaid / Home Health / HCBS Briefing — setup

Adds a third, AI-written "Weekly Briefing" tab to the tracker and a weekly
email, alongside the existing daily rule-scored event feed. Fully automated
— no review step before publish/send, matching how the daily tracker already
runs.

## What's new

| File | Purpose |
|---|---|
| `weekly_briefing.py` | Calls the Claude API (web search restricted to CMS, Medicaid.gov, allianceforcareathome.org, homehealthcarenews.com, mcknightshomecare.com, kff.org) and writes `weekly_briefings.json`. |
| `send_weekly_briefing_email.py` | Emails the latest entry from `weekly_briefings.json`. |
| `.github/workflows/weekly-briefing.yml` | Runs the two scripts above plus `build_page.py`, weekly. |
| `build_page.py` | **Replaces your existing file.** Adds a "Weekly Briefing" tab that reads `weekly_briefings.json` the same way the News Feed tab reads `events.json`. |

`weekly_briefings.json` is created automatically on first run — nothing to
add by hand. It's a plain list (newest first), so it works the same way
`events.json` does: inspectable, editable, and safe to leave alone.

## Setup (one time)

1. Add `weekly_briefing.py`, `send_weekly_briefing_email.py`, and
   `.github/workflows/weekly-briefing.yml` to your repo, then **replace**
   your existing `build_page.py` with the one here.
2. Get an Anthropic API key from
   [console.anthropic.com](https://console.anthropic.com) (Settings → API
   Keys). This is a separate product from your claude.ai subscription — the
   weekly briefing costs a small amount per run in API usage (a few cents;
   the `web_search` tool is $10 per 1,000 searches, and this uses roughly
   5–10 searches per week).
3. Go to **Settings → Secrets and variables → Actions** in your repo and add
   one new secret: `ANTHROPIC_API_KEY`. Your existing `SMTP_HOST`,
   `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `DIGEST_FROM`, and
   `DIGEST_RECIPIENTS` secrets are reused as-is — nothing else to add.
4. Go to the **Actions** tab, select **Weekly Medicaid/Home Health/HCBS
   Briefing**, and click **Run workflow** to test it immediately.
5. Open `index.html` (or the live site) and click the **Weekly Briefing**
   tab to see the result. Check your inbox for the email.

## Schedule

Runs every Monday at 12:00 UTC (8am ET / 5am PT) — one hour after the daily
tracker run, so the two jobs don't race to commit `index.html` at the same
time. Change the `cron` line in `weekly-briefing.yml` to adjust.

## If something looks off

- **Workflow fails at the "Generate weekly briefing" step:** check the
  Actions log. `weekly_briefing.py` deliberately raises an error (rather
  than publishing) if Claude's response doesn't come back in the expected
  `## Medicaid` / `## Home Health` / `## HCBS` format — this is the
  automated safety net standing in for manual review. A failed run leaves
  the site and email untouched; nothing partial gets published.
- **Sources feel off or too narrow:** edit `ALLOWED_DOMAINS` near the top of
  `weekly_briefing.py`. Web search only looks at domains in that list.
- **Model ID:** the script defaults to `ANTHROPIC_MODEL=claude-sonnet-5`.
  Check [docs.claude.com/en/docs/about-claude/models](https://docs.claude.com/en/docs/about-claude/models)
  periodically and update the default (or set the `ANTHROPIC_MODEL` secret)
  if a newer model is recommended.
- **Cadence:** this is weekly by design (matching what you asked for) and
  intentionally separate from `send_digest.py`'s daily high-impact-event
  digest — the two serve different purposes and both keep running
  independently.

## Design notes

- No new third-party Python dependencies — `weekly_briefing.py` calls the
  Claude API directly over HTTPS (`urllib.request`) and hand-rolls the small
  bullet-list-to-HTML conversion it needs, matching how `fetch_events.py`
  avoids `feedparser`. No `pip install` step was added to the workflow.
- Web search is restricted to a fixed domain allowlist (not open web
  search) so results stay traceable to sources you'd trust for a lending
  desk, and so a bad week of general web results can't creep in unnoticed.
- Every bullet is required to carry a link back to its source, and the
  email/site both carry a standing disclaimer that this is AI-compiled and
  should be checked against the primary source before being relied on for
  compliance decisions — reasonable given this feeds a credit-risk tracker.
