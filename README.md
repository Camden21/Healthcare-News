[README.md](https://github.com/user-attachments/files/31197448/README.md)
# CIB Healthcare News Tracker

Static site tracking healthcare enforcement, Medicaid policy, CMS actions, and
disaster declarations with credit read-through.

## Files

| File | Purpose |
|---|---|
| `index.html` | The live site. **Generated** — do not edit by hand. |
| `events.json` | The data. This is the file you edit or review. |
| `build_page.py` | Rebuilds `index.html` from `events.json`. |
| `fetch_events.py` | Pulls new events from government sources daily. |
| `.github/workflows/update-tracker.yml` | Runs the daily job on GitHub's servers. |

## Setup (one time)

1. Add all files above to your repo, keeping the folder structure
   (`.github/workflows/` must be nested exactly that way).
2. Go to **Settings → Actions → General → Workflow permissions** and select
   **Read and write permissions**, then Save. Without this the job cannot
   commit back to the repo.
3. Go to the **Actions** tab, select **Update Healthcare Tracker**, and click
   **Run workflow** to test it immediately rather than waiting for the schedule.

Your laptop does not need to be on. The job runs on GitHub's servers.

## Schedule

Runs daily at 11:00 UTC (7am ET / 4am PT). Change the `cron` line in the
workflow file to adjust. Cron is always expressed in UTC.

GitHub sometimes delays scheduled jobs during peak load, and disables schedules
on repos with no activity for 60 days. A manual run re-enables them.

## Sources

| Source | Type | Notes |
|---|---|---|
| DOJ press releases | RSS | Filtered to healthcare-related items only |
| CMS newsroom | RSS | |
| HHS OIG reports | RSS | |
| FEMA OpenFEMA | JSON API | Free, no key; collapsed to one row per declaration |

If a feed URL changes, that source is skipped with a logged warning and the run
continues. Check the Actions log if a source goes quiet.

## Review workflow — important

Auto-fetched events are written with:

```
"sourceVerification": "Auto-drafted — pending review"
```

These render on the site with a gold flag. Scoring is **keyword-based**, not
analytical — it approximates your methodology but does not replace it.

Recommended weekly pass:

1. Open `events.json`, find entries flagged `Auto-drafted — pending review`.
2. Correct `riskScore`, `severity`, `creditDirection`, `sector`, and
   `effectiveDate` against your scoring guide.
3. Change `sourceVerification` to `Primary` once verified.
4. Commit. The site rebuilds on the next scheduled run, or run the workflow
   manually to publish immediately.

Existing events are never modified by the fetch script — it only appends.

## Deduplication

New events are skipped if either the source URL or the headline already exists.
The script looks back 30 days, so a missed or failed run self-heals on the next
successful one.

## Editing data by hand

Edit `events.json`, then run `python build_page.py` locally and commit both
files — or just commit `events.json` and let the next scheduled run rebuild.

## Risk score scale

0–12. Tiers on the site: 10+ Critical, 7–9 High, 4–6 Elevated, 0–3 Lower.
