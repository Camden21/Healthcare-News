#!/usr/bin/env python3
"""
Daily email digest for the CIB Healthcare News Tracker.

Sends the highest-impact NEW events to a distribution list. An event is
emailed exactly once, tracked in digest_state.json.

Configuration comes entirely from environment variables (GitHub Secrets) so
that no email address or credential is ever committed to this public repo:

    SMTP_HOST          e.g. smtp.gmail.com
    SMTP_PORT          e.g. 587
    SMTP_USER          the sending account
    SMTP_PASSWORD      an app password, NOT your login password
    DIGEST_FROM        display sender, e.g. "Healthcare Tracker <you@x.com>"
    DIGEST_RECIPIENTS  comma-separated list
    DIGEST_MIN_SCORE   optional, default 9
    DIGEST_SITE_URL    optional link back to the site
"""

import json
import os
import re
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr

EVENTS_FILE = "events.json"
STATE_FILE = "digest_state.json"
DEFAULT_MIN_SCORE = 9
DEFAULT_MAX_ITEMS = 5
DEFAULT_MAX_PER_CATEGORY = 2
DEFAULT_EXCLUDE = "disaster"


# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------

def env(name, default=None, required=False):
    val = os.environ.get(name, default)
    if required and not val:
        print(f"ERROR: required secret {name} is not set.")
        sys.exit(1)
    return val


def load_config():
    recipients_raw = env("DIGEST_RECIPIENTS", required=True)
    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]
    if not recipients:
        print("ERROR: DIGEST_RECIPIENTS is set but contains no addresses.")
        sys.exit(1)

    try:
        min_score = int(env("DIGEST_MIN_SCORE", str(DEFAULT_MIN_SCORE)))
    except ValueError:
        min_score = DEFAULT_MIN_SCORE

    try:
        max_items = int(env("DIGEST_MAX_ITEMS", str(DEFAULT_MAX_ITEMS)))
    except ValueError:
        max_items = DEFAULT_MAX_ITEMS

    exclude_raw = env("DIGEST_EXCLUDE_CATEGORIES", DEFAULT_EXCLUDE) or ""
    exclude = [c.strip().lower() for c in exclude_raw.split(",") if c.strip()]

    return {
        "host": env("SMTP_HOST", required=True),
        "port": int(env("SMTP_PORT", "587")),
        "user": env("SMTP_USER", required=True),
        "password": env("SMTP_PASSWORD", required=True),
        "sender": env("DIGEST_FROM") or env("SMTP_USER"),
        "recipients": recipients,
        "min_score": min_score,
        "max_items": max_items,
        "exclude": exclude,
        "site_url": env("DIGEST_SITE_URL", ""),
    }


# ----------------------------------------------------------------------
# Selection
# ----------------------------------------------------------------------

def load_state():
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        return set(data.get("sent_ids", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_state(sent_ids):
    with open(STATE_FILE, "w") as f:
        json.dump(
            {
                "sent_ids": sorted(sent_ids),
                "last_run": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            f,
            indent=2,
        )


def select_events(events, already_sent, min_score, max_items=5,
                  max_per_category=2, exclude_categories=None):
    """Pick what to email.

    Returns (picked, overflow, excluded).

    - exclude_categories are never emailed, but are still marked as seen so
      they don't accumulate and flood the digest if the filter is later
      removed. They remain visible on the site.
    - max_per_category stops one noisy source from crowding out everything else.
    - max_items caps total length.
    """
    exclude_categories = set(exclude_categories or [])

    candidates = []
    excluded = []
    borrower_hits = []

    for e in events:
        eid = e.get("id")
        if not eid or eid in already_sent:
            continue

        # Borrower mentions always go out: they bypass the category filter,
        # the score threshold, and the per-category cap.
        if e.get("borrowers"):
            borrower_hits.append(e)
            continue

        if (e.get("broadCategory") or "") in exclude_categories:
            excluded.append(e)
            continue
        if (e.get("riskScore") or 0) < min_score:
            continue
        candidates.append(e)

    # Highest impact first, then most recent
    candidates.sort(
        key=lambda e: ((e.get("riskScore") or 0), e.get("dateSort") or ""),
        reverse=True,
    )

    picked = []
    per_category = {}
    overflow = []

    for e in candidates:
        cat = e.get("broadCategory") or "other"
        if per_category.get(cat, 0) >= max_per_category:
            overflow.append(e)
            continue
        if len(picked) >= max_items:
            overflow.append(e)
            continue
        picked.append(e)
        per_category[cat] = per_category.get(cat, 0) + 1

    borrower_hits.sort(
        key=lambda e: ((e.get("riskScore") or 0), e.get("dateSort") or ""),
        reverse=True,
    )
    return borrower_hits + picked, overflow, excluded


# ----------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------

DIRECTION_COLOR = {
    "Negative": "#A81C1C",
    "Positive": "#2B5C3F",
    "Mixed": "#8A6014",
}

CAT_LABELS = {
    "fraud": "Fraud / Enforcement",
    "medicaid": "Medicaid Policy",
    "cms": "CMS / Medicare",
    "disaster": "Disaster",
    "regulation": "Regulation",
    "other": "Other",
}


def esc(text):
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ----------------------------------------------------------------------
# Executive summary rollup
# ----------------------------------------------------------------------

def extract_dollars(text):
    """Largest dollar figure mentioned, in dollars, or None."""
    t = re.sub(r"[-/]", " ", (text or "").lower())
    best = None
    pattern = r"\$\s?([\d,]+(?:\.\d+)?)\s*(trillion|billion|million|thousand|[tbmk])?\b"
    for m in re.finditer(pattern, t):
        raw, unit = m.group(1), (m.group(2) or "")
        try:
            val = float(raw.replace(",", ""))
        except ValueError:
            continue
        val *= {
            "trillion": 1e12, "t": 1e12, "billion": 1e9, "b": 1e9,
            "million": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3,
        }.get(unit, 1)
        if best is None or val > best:
            best = val
    return best


def humanize_dollars(amount):
    if amount is None:
        return None
    if amount >= 1e12:
        return f"${amount/1e12:.1f}T".replace(".0T", "T")
    if amount >= 1e9:
        return f"${amount/1e9:.1f}B".replace(".0B", "B")
    if amount >= 1e6:
        return f"${amount/1e6:.1f}M".replace(".0M", "M")
    if amount >= 1e3:
        return f"${amount/1e3:.0f}K"
    return f"${amount:,.0f}"


def split_sectors(raw):
    parts = re.split(r"[;,]", raw or "")
    out = []
    for p in parts:
        p = p.strip()
        if p and p.lower() not in ("pending review", "u.s.", ""):
            out.append(p)
    return out


def build_summary(events):
    """Deterministic rollup of what this batch actually means."""
    total = len(events)

    by_direction = {}
    by_category = {}
    sectors = {}
    states = {}
    dollars = []

    for e in events:
        d = e.get("creditDirection") or "Unspecified"
        by_direction[d] = by_direction.get(d, 0) + 1

        c = CAT_LABELS.get(e.get("broadCategory"), e.get("category") or "Other")
        by_category[c] = by_category.get(c, 0) + 1

        for s in split_sectors(e.get("sector")):
            sectors[s] = sectors.get(s, 0) + 1

        st = (e.get("state") or "").strip()
        if st and st.lower() not in ("u.s.", "us", ""):
            for piece in re.split(r"[;,]", st):
                piece = piece.strip()
                if piece and piece.lower() not in ("u.s.", "us"):
                    states[piece] = states.get(piece, 0) + 1

        amt = extract_dollars(f"{e.get('headline','')} {e.get('detail','')}")
        if amt:
            dollars.append(amt)

    borrower_names = []
    for e in events:
        for b in (e.get("borrowers") or []):
            if b not in borrower_names:
                borrower_names.append(b)

    critical = sum(1 for e in events if (e.get("riskScore") or 0) >= 10)
    top_event = max(events, key=lambda e: e.get("riskScore") or 0)

    def top_n(counter, n=4):
        return [k for k, _ in sorted(counter.items(), key=lambda kv: -kv[1])[:n]]

    return {
        "total": total,
        "critical": critical,
        "by_direction": by_direction,
        "by_category": by_category,
        "top_sectors": top_n(sectors),
        "states": top_n(states, 6),
        "dollar_total": sum(dollars) if dollars else None,
        "dollar_count": len(dollars),
        "top_event": top_event,
        "borrower_names": borrower_names,
    }


def summary_sentences(s):
    """Plain-language lines describing the batch."""
    lines = []

    plural = "event" if s["total"] == 1 else "events"
    lead = f"{s['total']} new {plural} above the reporting threshold"
    if s["critical"]:
        lead += f", {s['critical']} at critical severity"
    lines.append(lead + ".")

    dirs = s["by_direction"]
    neg, pos, mixed = dirs.get("Negative", 0), dirs.get("Positive", 0), dirs.get("Mixed", 0)
    parts = []
    if neg:
        parts.append(f"{neg} negative")
    if mixed:
        parts.append(f"{mixed} mixed")
    if pos:
        parts.append(f"{pos} positive")
    if parts:
        skew = "negative" if neg > pos else ("positive" if pos > neg else "balanced")
        lines.append(f"Credit direction: {', '.join(parts)} — net {skew}.")

    if s["dollar_total"]:
        n = s["dollar_count"]
        lines.append(
            f"Aggregate disclosed exposure across {n} "
            f"{'event' if n == 1 else 'events'}: {humanize_dollars(s['dollar_total'])}."
        )

    if s["top_sectors"]:
        lines.append("Sectors touched: " + ", ".join(s["top_sectors"]) + ".")

    if s["states"]:
        lines.append("Jurisdictions: " + ", ".join(s["states"]) + ".")

    if s.get("borrower_names"):
        lines.insert(0, "PORTFOLIO BORROWERS referenced: "
                        + ", ".join(s["borrower_names"]) + ".")

    te = s["top_event"]
    lines.append(
        f"Highest-scoring item ({te.get('riskScore')}): {te.get('headline','')}"
    )

    return lines


def render_summary_html(s):
    rows = "".join(
        f'<li style="margin-bottom:5px;">{esc(line)}</li>'
        for line in summary_sentences(s)
    )
    return f"""
<tr><td style="padding:16px 0 4px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background:#F2F0E9;border-left:3px solid #A81C1C;">
    <tr><td style="padding:15px 18px;">
      <div style="font:700 11px Arial,sans-serif;letter-spacing:0.14em;
                  text-transform:uppercase;color:#A81C1C;margin-bottom:9px;">
        Impact Summary</div>
      <ul style="margin:0;padding-left:18px;font:400 13.5px Georgia,serif;
                 color:#26302A;line-height:1.55;">{rows}</ul>
    </td></tr>
  </table>
</td></tr>"""


def tier_of(score):
    if score >= 10:
        return "Critical"
    if score >= 7:
        return "High"
    return "Elevated"


def render_html(events, site_url, overflow=None):
    """Email-safe HTML.

    Built with tables and inline styles because Outlook renders HTML with
    Word's engine: it clips borders on fixed-height divs, ignores line-height
    centering, and drops many modern CSS properties. Filled background chips
    survive where bordered boxes do not.
    """
    overflow = overflow or []
    today = datetime.utcnow().strftime("%B %d, %Y")

    # Tinted chip colours keyed to credit direction
    palette = {
        "Negative": ("#A81C1C", "#F7EAEA"),
        "Positive": ("#2B5C3F", "#E9F0EB"),
        "Mixed":    ("#8A6014", "#F6EFDF"),
    }

    cards = []
    for e in events:
        score = e.get("riskScore") or 0
        fg, bg = palette.get(e.get("creditDirection"), ("#4A4A46", "#EFEEE9"))
        cat = CAT_LABELS.get(e.get("broadCategory"), e.get("category") or "")

        jurisdiction = esc(e.get("jurisdiction", ""))
        state = esc(e.get("state", ""))
        locale = jurisdiction
        if state and state != jurisdiction:
            locale = f"{jurisdiction} &middot; {state}"

        borrower_badge = ""
        if e.get("borrowers"):
            names = ", ".join(e["borrowers"])
            borrower_badge = (
                f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
                f'style="margin-bottom:9px;"><tr>'
                f'<td bgcolor="#1A1A18" style="background:#1A1A18;padding:4px 10px;'
                f'font-family:Arial,Helvetica,sans-serif;font-size:10px;font-weight:bold;'
                f'color:#FFFFFF;letter-spacing:0.08em;">'
                f'PORTFOLIO BORROWER &nbsp;&bull;&nbsp; {esc(names)}</td>'
                f'</tr></table>'
            )

        flag = ""
        if e.get("sourceVerification") and e["sourceVerification"] != "Primary":
            flag = (
                '<div style="font:400 11px Arial,sans-serif;color:#8A6014;'
                'padding-top:8px;">Auto-drafted &mdash; pending review</div>'
            )

        cards.append(f"""
<tr><td style="padding:0 0 12px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
         bgcolor="#FFFFFF" style="background:#FFFFFF;border:1px solid #E2E0D8;">
    <tr>
      <td valign="top" style="padding:18px 0 18px 18px;" width="62">
        <!-- score chip: filled cell, no border, fixed line-height for Outlook -->
        <table role="presentation" cellpadding="0" cellspacing="0" border="0">
          <tr><td align="center" valign="middle" width="44" height="44"
                  bgcolor="{bg}"
                  style="width:44px;height:44px;background:{bg};color:{fg};
                         font-family:Arial,Helvetica,sans-serif;font-size:18px;
                         font-weight:bold;text-align:center;
                         mso-line-height-rule:exactly;line-height:44px;">
            {score}
          </td></tr>
          <tr><td align="center"
                  style="font:400 9px Arial,sans-serif;color:#8A8A84;
                         padding-top:5px;letter-spacing:0.06em;
                         text-transform:uppercase;">Risk</td></tr>
        </table>
      </td>
      <td valign="top" style="padding:18px 20px 18px 14px;">
        {borrower_badge}
        <div style="font-family:Arial,Helvetica,sans-serif;font-size:10px;
                    font-weight:bold;letter-spacing:0.07em;
                    text-transform:uppercase;color:{fg};padding-bottom:7px;">
          {esc(cat)} &nbsp;&bull;&nbsp; {esc(e.get('creditDirection',''))}
          &nbsp;&bull;&nbsp; {tier_of(score)}
        </div>

        <div style="font-family:Georgia,'Times New Roman',serif;font-size:17px;
                    font-weight:bold;color:#1A1A18;line-height:1.32;
                    padding-bottom:8px;">
          <a href="{esc(e.get('sourceURL','#'))}"
             style="color:#1A1A18;text-decoration:none;">{esc(e.get('headline',''))}</a>
        </div>

        <div style="font-family:Georgia,'Times New Roman',serif;font-size:13.5px;
                    color:#4A4A46;line-height:1.6;padding-bottom:11px;">
          {esc(e.get('detail',''))}
        </div>

        <div style="font-family:Arial,Helvetica,sans-serif;font-size:10.5px;
                    color:#7A7A74;letter-spacing:0.03em;">
          <span style="color:#1A1A18;font-weight:bold;">{esc(e.get('sourceAgency',''))}</span>
          &nbsp;&bull;&nbsp; {locale}
          &nbsp;&bull;&nbsp; {esc(e.get('date',''))}
        </div>

        <div style="padding-top:10px;">
          <a href="{esc(e.get('sourceURL','#'))}"
             style="font-family:Arial,Helvetica,sans-serif;font-size:11px;
                    font-weight:bold;color:{fg};text-decoration:none;
                    letter-spacing:0.04em;">READ SOURCE &rsaquo;</a>
        </div>
        {flag}
      </td>
    </tr>
  </table>
</td></tr>""")

    # ---- summary ----
    s = build_summary(events)
    summary_rows = "".join(
        f'<tr><td valign="top" style="font-family:Georgia,serif;font-size:13px;'
        f'color:#2A2A28;line-height:1.5;padding:0 0 6px 0;">'
        f'<span style="color:#A81C1C;font-weight:bold;">&bull;</span>&nbsp;&nbsp;{esc(line)}'
        f'</td></tr>'
        for line in summary_sentences(s)
    )

    summary_block = f"""
<tr><td style="padding:0 0 18px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
         bgcolor="#F2F0E8" style="background:#F2F0E8;">
    <tr><td style="padding:16px 20px;border-left:3px solid #A81C1C;">
      <div style="font-family:Arial,Helvetica,sans-serif;font-size:10px;
                  font-weight:bold;letter-spacing:0.15em;text-transform:uppercase;
                  color:#A81C1C;padding-bottom:11px;">Impact Summary</div>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
        {summary_rows}
      </table>
    </td></tr>
  </table>
</td></tr>"""

    # ---- overflow ----
    overflow_note = ""
    if overflow:
        n = len(overflow)
        overflow_note = f"""
<tr><td style="padding:4px 0 0;">
  <div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;
              color:#7A7A74;border-top:1px solid #E2E0D8;padding-top:13px;">
    {n} additional lower-priority {"event" if n == 1 else "events"} not shown &mdash;
    available on the tracker.</div>
</td></tr>"""

    site_link = ""
    if site_url:
        site_link = f"""
<tr><td align="center" style="padding:24px 0 0;">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0">
    <tr><td bgcolor="#1A1A18" style="background:#1A1A18;">
      <a href="{esc(site_url)}"
         style="display:inline-block;padding:11px 26px;
                font-family:Arial,Helvetica,sans-serif;font-size:12px;
                font-weight:bold;color:#FFFFFF;text-decoration:none;
                letter-spacing:0.06em;">VIEW FULL TRACKER</a>
    </td></tr>
  </table>
</td></tr>"""

    count = len(events)
    plural = "event" if count == 1 else "events"

    return f"""<!DOCTYPE html>
<html xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<!--[if mso]><xml><o:OfficeDocumentSettings>
<o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml><![endif]-->
<title>CIB Healthcare News Tracker</title>
</head>
<body style="margin:0;padding:0;background:#F7F6F2;" bgcolor="#F7F6F2">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       bgcolor="#F7F6F2" style="background:#F7F6F2;">
  <tr><td align="center" style="padding:22px 16px;">

    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="width:100%;max-width:1000px;">

      <!-- masthead -->
      <tr><td style="padding-bottom:12px;">
        <div style="font-family:Arial,Helvetica,sans-serif;font-size:10px;
                    font-weight:bold;letter-spacing:0.2em;text-transform:uppercase;
                    color:#A81C1C;">Sector Desk</div>
        <div style="font-family:Georgia,'Times New Roman',serif;font-size:29px;
                    font-weight:bold;color:#1A1A18;padding:7px 0 5px;">
          CIB Healthcare News Tracker</div>
        <div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;
                    color:#7A7A74;">
          Daily digest &nbsp;&bull;&nbsp; {today} &nbsp;&bull;&nbsp;
          {count} high-impact {plural}</div>
      </td></tr>

      <tr><td style="padding-bottom:18px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr><td height="3" bgcolor="#1A1A18"
                  style="height:3px;background:#1A1A18;font-size:0;line-height:0;">&nbsp;</td></tr>
        </table>
      </td></tr>

      {summary_block}
      {''.join(cards)}
      {overflow_note}
      {site_link}

      <tr><td align="center" style="padding:26px 10px 0;">
        <div style="font-family:Arial,Helvetica,sans-serif;font-size:10.5px;
                    color:#9A9A94;line-height:1.6;">
          Risk scores and credit direction reflect this tracker's internal weighting
          methodology, not the source agency's assessment.<br>
          Items marked auto-drafted have not yet been analyst-reviewed.
        </div>
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>"""


def render_text(events, overflow=None):
    lines = [
        "CIB HEALTHCARE NEWS TRACKER",
        f"Daily digest - {datetime.utcnow().strftime('%B %d, %Y')}",
        "=" * 60,
        "",
        "IMPACT SUMMARY",
        "",
    ]
    for line in summary_sentences(build_summary(events)):
        lines.append(f"  - {line}")
    lines += ["", "=" * 60, ""]
    for e in events:
        if e.get("borrowers"):
            lines.append("*** PORTFOLIO BORROWER: " + ", ".join(e["borrowers"]) + " ***")
        lines.append(f"[{e.get('riskScore')}] {e.get('creditDirection','')} - "
                     f"{CAT_LABELS.get(e.get('broadCategory'), '')}")
        lines.append(e.get("headline", ""))
        lines.append("")
        lines.append(e.get("detail", ""))
        lines.append("")
        lines.append(f"{e.get('sourceAgency','')} | {e.get('date','')}")
        lines.append(e.get("sourceURL", ""))
        lines.append("-" * 60)
        lines.append("")
    if overflow:
        n = len(overflow)
        lines.append(f"{n} additional lower-priority {'event' if n == 1 else 'events'} not shown - view on the tracker.")
        lines.append("")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Send
# ----------------------------------------------------------------------

def send(cfg, events, overflow=None):
    count = len(events)
    top = max((e.get("riskScore") or 0) for e in events)
    n_borrower = sum(1 for e in events if e.get("borrowers"))
    if n_borrower:
        subject = (f"Healthcare Tracker — BORROWER ALERT: {n_borrower} item"
                   f"{'s' if n_borrower != 1 else ''} + {count - n_borrower} sector")
    else:
        subject = (f"Healthcare Tracker — {count} high-impact event"
                   f"{'s' if count != 1 else ''} (top score {top})")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["sender"]
    # Recipients go in Bcc so the distribution list isn't exposed to everyone.
    msg["To"] = cfg["sender"]
    msg["Bcc"] = ", ".join(cfg["recipients"])

    overflow = overflow or []
    msg.set_content(render_text(events, overflow))
    msg.add_alternative(render_html(events, cfg["site_url"], overflow), subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as server:
        server.starttls(context=context)
        server.login(cfg["user"], cfg["password"])
        server.send_message(msg)

    print(f"Sent to {len(cfg['recipients'])} recipient(s).")


def main():
    try:
        with open(EVENTS_FILE) as f:
            events = json.load(f)
    except FileNotFoundError:
        print(f"{EVENTS_FILE} not found.")
        return 1

    already_sent = load_state()
    first_run = not already_sent

    cfg = load_config()
    picked, overflow, excluded = select_events(
        events, already_sent, cfg["min_score"],
        max_items=cfg["max_items"],
        max_per_category=DEFAULT_MAX_PER_CATEGORY,
        exclude_categories=cfg["exclude"],
    )

    print(f"Events in file:   {len(events)}")
    print(f"Previously sent:  {len(already_sent)}")
    print(f"Min score:        {cfg['min_score']}")
    print(f"Max per email:    {cfg['max_items']}")
    print(f"Emailing:         {len(picked)}")
    print(f"Held back:        {len(overflow)} (on site, marked as seen)")
    print(f"Excluded categs:  {', '.join(cfg['exclude']) or 'none'} "
          f"({len(excluded)} filtered out)")

    if first_run:
        # Don't blast the entire back catalogue on first run. Mark everything
        # currently in the file as already-seen and start fresh tomorrow.
        print("\nFirst run detected — seeding state without sending.")
        print("Future runs will email only newly added events.")
        save_state({e.get("id") for e in events if e.get("id")})
        return 0

    if not picked:
        print("\nNothing new above threshold. No email sent.")
        seen = {e.get("id") for e in overflow + excluded if e.get("id")}
        if seen:
            save_state(already_sent | seen)
            print(f"Marked {len(seen)} filtered/held item(s) as seen.")
        return 0

    for e in picked:
        print(f"  [{e.get('riskScore')}] {e.get('headline','')[:66]}")

    send(cfg, picked, overflow)
    newly = {e.get("id") for e in picked + overflow + excluded if e.get("id")}
    save_state(already_sent | newly)
    return 0


if __name__ == "__main__":
    sys.exit(main())
