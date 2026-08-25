#!/usr/bin/env python3
"""
Emails the latest weekly AI-written Medicaid / Home Health / HCBS briefing.

Reuses the same SMTP_*/DIGEST_FROM/DIGEST_RECIPIENTS/DIGEST_SITE_URL secrets
already configured for the daily event digest (send_digest.py) — the only
new secret this weekly pipeline needs is ANTHROPIC_API_KEY, for
weekly_briefing.py.

    SMTP_HOST          e.g. smtp.gmail.com
    SMTP_PORT          e.g. 587
    SMTP_USER          the sending account
    SMTP_PASSWORD      an app password, NOT your login password
    DIGEST_FROM        display sender, e.g. "Healthcare Tracker <you@x.com>"
    DIGEST_RECIPIENTS  comma-separated list
    DIGEST_SITE_URL    optional link back to the site

Run weekly via .github/workflows/weekly-briefing.yml, after weekly_briefing.py
and build_page.py.
"""

import json
import os
import re
import smtplib
import ssl
import sys
from email.message import EmailMessage

BRIEFINGS_FILE = "weekly_briefings.json"


def env(name, default=None, required=False):
    val = os.environ.get(name, default)
    if required and not val:
        print(f"ERROR: required secret {name} is not set.")
        sys.exit(1)
    return val


def load_latest():
    try:
        with open(BRIEFINGS_FILE) as f:
            briefings = json.load(f)
    except FileNotFoundError:
        print(f"{BRIEFINGS_FILE} not found — nothing to send.")
        sys.exit(1)
    if not briefings:
        print(f"{BRIEFINGS_FILE} is empty — nothing to send.")
        sys.exit(1)
    return briefings[0]


# ----------------------------------------------------------------------
# Rendering — table layout + inline styles, matching send_digest.py's
# approach, because Outlook renders HTML with Word's engine and drops most
# modern CSS.
# ----------------------------------------------------------------------

def render_html(entry, site_url):
    section_blocks = "".join(f"""
<tr><td style="padding:0 0 20px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
    <tr><td height="2" bgcolor="#1A1A18"
            style="height:2px;background:#1A1A18;font-size:0;line-height:0;">&nbsp;</td></tr>
    <tr><td style="padding-top:10px;font-family:Georgia,'Times New Roman',serif;
                   font-size:19px;font-weight:bold;color:#1A1A18;">
      {s['heading']}
    </td></tr>
    <tr><td style="padding-top:8px;font-family:Georgia,'Times New Roman',serif;
                   font-size:14px;color:#2A2A28;line-height:1.65;">
      {s['bodyHtml']}
    </td></tr>
  </table>
</td></tr>""" for s in entry["sections"])

    site_link = ""
    if site_url:
        site_link = f"""
<tr><td align="center" style="padding:22px 0 0;">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0">
    <tr><td bgcolor="#1A1A18" style="background:#1A1A18;">
      <a href="{site_url}"
         style="display:inline-block;padding:11px 26px;
                font-family:Arial,Helvetica,sans-serif;font-size:12px;
                font-weight:bold;color:#FFFFFF;text-decoration:none;
                letter-spacing:0.06em;">VIEW ON THE TRACKER</a>
    </td></tr>
  </table>
</td></tr>"""

    return f"""<!DOCTYPE html>
<html xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<!--[if mso]><xml><o:OfficeDocumentSettings>
<o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml><![endif]-->
<title>{entry['title']}</title>
</head>
<body style="margin:0;padding:0;background:#F7F6F2;" bgcolor="#F7F6F2">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       bgcolor="#F7F6F2" style="background:#F7F6F2;">
  <tr><td align="center" style="padding:22px 16px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="width:100%;max-width:700px;">

      <tr><td style="padding-bottom:12px;">
        <div style="font-family:Arial,Helvetica,sans-serif;font-size:10px;
                    font-weight:bold;letter-spacing:0.2em;text-transform:uppercase;
                    color:#A81C1C;">Weekly Briefing</div>
        <div style="font-family:Georgia,'Times New Roman',serif;font-size:26px;
                    font-weight:bold;color:#1A1A18;padding:7px 0 5px;">
          {entry['title']}</div>
        <div style="font-family:Arial,Helvetica,sans-serif;font-size:11px;
                    color:#7A7A74;line-height:1.6;">
          Compiled automatically by Claude from public sources. Verify anything
          compliance-sensitive against the primary source before relying on it.
        </div>
      </td></tr>

      <tr><td style="padding-bottom:6px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr><td height="3" bgcolor="#1A1A18"
                  style="height:3px;background:#1A1A18;font-size:0;line-height:0;">&nbsp;</td></tr>
        </table>
      </td></tr>

      {section_blocks}
      {site_link}

      <tr><td align="center" style="padding:26px 10px 0;">
        <div style="font-family:Arial,Helvetica,sans-serif;font-size:10.5px;
                    color:#9A9A94;line-height:1.6;">
          This weekly briefing is generated separately from the tracker's daily,
          rule-scored event feed.
        </div>
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>"""


def render_text(entry):
    lines = [entry["title"], "=" * min(len(entry["title"]), 70), ""]
    for s in entry["sections"]:
        lines.append(s["heading"].upper())
        lines.append("-" * len(s["heading"]))
        text = re.sub(r"<[^>]+>", "", s["bodyHtml"])
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        lines.append(text.strip())
        lines.append("")
    return "\n".join(lines)


# ----------------------------------------------------------------------

def main():
    host = env("SMTP_HOST", required=True)
    port = int(env("SMTP_PORT", "587"))
    user = env("SMTP_USER", required=True)
    password = env("SMTP_PASSWORD", required=True)
    sender = env("DIGEST_FROM") or user
    recipients_raw = env("DIGEST_RECIPIENTS", required=True)
    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]
    if not recipients:
        print("ERROR: DIGEST_RECIPIENTS is set but contains no addresses.")
        sys.exit(1)
    site_url = env("DIGEST_SITE_URL", "")

    entry = load_latest()

    msg = EmailMessage()
    msg["Subject"] = entry["title"]
    msg["From"] = sender
    # Recipients go in Bcc so the distribution list isn't exposed to everyone.
    msg["To"] = sender
    msg["Bcc"] = ", ".join(recipients)
    msg.set_content(render_text(entry))
    msg.add_alternative(render_html(entry, site_url), subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls(context=context)
        server.login(user, password)
        server.send_message(msg)

    print(f"Sent weekly briefing ({entry['date']}) to {len(recipients)} recipient(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
