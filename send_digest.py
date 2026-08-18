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
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr

EVENTS_FILE = "events.json"
STATE_FILE = "digest_state.json"
DEFAULT_MIN_SCORE = 9


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

    return {
        "host": env("SMTP_HOST", required=True),
        "port": int(env("SMTP_PORT", "587")),
        "user": env("SMTP_USER", required=True),
        "password": env("SMTP_PASSWORD", required=True),
        "sender": env("DIGEST_FROM") or env("SMTP_USER"),
        "recipients": recipients,
        "min_score": min_score,
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


def select_events(events, already_sent, min_score):
    picked = []
    for e in events:
        eid = e.get("id")
        if not eid or eid in already_sent:
            continue
        if (e.get("riskScore") or 0) < min_score:
            continue
        picked.append(e)

    picked.sort(key=lambda e: (e.get("riskScore") or 0), reverse=True)
    return picked


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


def tier_of(score):
    if score >= 10:
        return "Critical"
    if score >= 7:
        return "High"
    return "Elevated"


def render_html(events, site_url):
    today = datetime.utcnow().strftime("%B %d, %Y")

    rows = []
    for e in events:
        score = e.get("riskScore") or 0
        color = DIRECTION_COLOR.get(e.get("creditDirection"), "#5A5A56")
        cat = CAT_LABELS.get(e.get("broadCategory"), e.get("category", ""))

        flag = ""
        if e.get("sourceVerification") and e["sourceVerification"] != "Primary":
            flag = (
                '<div style="font:600 11px Arial,sans-serif;color:#8A6014;'
                'margin-top:6px;">&#9873; Auto-drafted &mdash; pending review</div>'
            )

        jurisdiction = esc(e.get("jurisdiction", ""))
        state = esc(e.get("state", ""))
        locale = jurisdiction
        if state and state != jurisdiction:
            locale = f"{jurisdiction} &middot; {state}"

        rows.append(f"""
<tr>
  <td style="padding:18px 0;border-bottom:1px solid #D6D3C9;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td width="46" valign="top">
          <div style="width:38px;height:38px;border:1.5px solid {color};
                      color:{color};font:700 15px 'Courier New',monospace;
                      text-align:center;line-height:38px;">{score}</div>
        </td>
        <td valign="top" style="padding-left:14px;">
          <div style="font:700 10px Arial,sans-serif;letter-spacing:0.06em;
                      text-transform:uppercase;color:{color};margin-bottom:6px;">
            {esc(cat)} &nbsp;|&nbsp; {esc(e.get('creditDirection',''))}
            &nbsp;|&nbsp; {tier_of(score)} Impact
          </div>
          <div style="font:700 17px Georgia,serif;color:#121212;
                      line-height:1.3;margin-bottom:7px;">
            <a href="{esc(e.get('sourceURL','#'))}"
               style="color:#121212;text-decoration:none;">{esc(e.get('headline',''))}</a>
          </div>
          <div style="font:400 14px Georgia,serif;color:#333330;
                      line-height:1.55;margin-bottom:9px;">
            {esc(e.get('detail',''))}
          </div>
          <div style="font:400 11px Arial,sans-serif;color:#5A5A56;
                      text-transform:uppercase;letter-spacing:0.03em;">
            <strong style="color:#121212;">{esc(e.get('sourceAgency',''))}</strong>
            &nbsp;&middot;&nbsp; {locale}
            &nbsp;&middot;&nbsp; {esc(e.get('date',''))}
            &nbsp;&middot;&nbsp;
            <a href="{esc(e.get('sourceURL','#'))}"
               style="color:#A81C1C;font-weight:600;text-decoration:none;">Read source &rarr;</a>
          </div>
          {flag}
        </td>
      </tr>
    </table>
  </td>
</tr>""")

    site_link = ""
    if site_url:
        site_link = (
            f'<div style="margin-top:26px;text-align:center;">'
            f'<a href="{esc(site_url)}" style="font:600 13px Arial,sans-serif;'
            f'color:#A81C1C;text-decoration:none;">View the full tracker &rarr;</a></div>'
        )

    count = len(events)
    plural = "event" if count == 1 else "events"

    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#FCFBF8;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:#FCFBF8;padding:26px 12px;">
  <tr><td align="center">
    <table role="presentation" width="640" cellpadding="0" cellspacing="0"
           style="max-width:640px;background:#FCFBF8;">
      <tr><td style="padding-bottom:6px;">
        <div style="font:600 11px Arial,sans-serif;letter-spacing:0.2em;
                    text-transform:uppercase;color:#A81C1C;">Sector Desk</div>
        <div style="font:900 30px Georgia,serif;color:#121212;margin:5px 0 4px;">
          CIB Healthcare News Tracker</div>
        <div style="font:400 13px Arial,sans-serif;color:#5A5A56;">
          Daily digest &middot; {today} &middot; {count} high-impact {plural}</div>
      </td></tr>
      <tr><td style="border-top:3px solid #121212;padding-top:2px;"></td></tr>
      {''.join(rows)}
      <tr><td>{site_link}
        <div style="font:400 11px Arial,sans-serif;color:#8A8A84;
                    margin-top:22px;line-height:1.5;text-align:center;">
          Risk scores and credit direction reflect this tracker's internal
          weighting methodology, not the source agency's assessment.<br>
          Items flagged as auto-drafted have not yet been analyst-reviewed.
        </div>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""


def render_text(events):
    lines = [
        "CIB HEALTHCARE NEWS TRACKER",
        f"Daily digest - {datetime.utcnow().strftime('%B %d, %Y')}",
        f"{len(events)} high-impact events",
        "=" * 60,
        "",
    ]
    for e in events:
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
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Send
# ----------------------------------------------------------------------

def send(cfg, events):
    count = len(events)
    top = max((e.get("riskScore") or 0) for e in events)
    subject = f"Healthcare Tracker — {count} high-impact event{'s' if count != 1 else ''} (top score {top})"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["sender"]
    # Recipients go in Bcc so the distribution list isn't exposed to everyone.
    msg["To"] = cfg["sender"]
    msg["Bcc"] = ", ".join(cfg["recipients"])

    msg.set_content(render_text(events))
    msg.add_alternative(render_html(events, cfg["site_url"]), subtype="html")

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
    picked = select_events(events, already_sent, cfg["min_score"])

    print(f"Events in file:   {len(events)}")
    print(f"Previously sent:  {len(already_sent)}")
    print(f"Min score:        {cfg['min_score']}")
    print(f"Qualifying now:   {len(picked)}")

    if first_run:
        # Don't blast the entire back catalogue on first run. Mark everything
        # currently in the file as already-seen and start fresh tomorrow.
        print("\nFirst run detected — seeding state without sending.")
        print("Future runs will email only newly added events.")
        save_state({e.get("id") for e in events if e.get("id")})
        return 0

    if not picked:
        print("\nNothing new above threshold. No email sent.")
        return 0

    for e in picked:
        print(f"  [{e.get('riskScore')}] {e.get('headline','')[:66]}")

    send(cfg, picked)
    save_state(already_sent | {e.get("id") for e in picked if e.get("id")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
