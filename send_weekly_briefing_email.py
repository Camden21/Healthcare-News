#!/usr/bin/env python3
"""
Emails the latest weekly Medicaid / Home Health / HCBS briefing.

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

# Status tier -> (badge label, badge background, tinted row background, text colour)
TIERS = {
    "implemented": ("In effect", "#A81C1C", "#F7EAEA", "#6E1414"),
    "proposed":    ("Proposed only", "#8A6014", "#F6EFDF", "#66470F"),
    "pending":     ("Enacted — not yet operative", "#6E5A2E", "#F6EFDF", "#514526"),
    "rhetoric":    ("Messaging", "#7A7A74", "#EDEDE7", "#55554F"),
}


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


def esc(text):
    return (str(text or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def table_stat_color(status):
    s = (status or "").lower()
    if "not newly" in s or "rhetoric" in s:
        return "#7A7A74"
    if "propos" in s:
        return "#8A6014"
    if "implement" in s or "enacted" in s:
        return "#A81C1C"
    return "#5A5A56"


# ----------------------------------------------------------------------
# Rendering — table layout + inline styles, matching send_digest.py's
# approach, because Outlook renders HTML with Word's engine and drops most
# modern CSS. Filled background chips survive where bordered boxes do not.
# ----------------------------------------------------------------------

def render_item(item, index):
    label, badge_bg, tint, text_col = TIERS.get(
        item.get("statusTier"), TIERS["pending"])

    sources = ""
    if item.get("sources"):
        links = " &nbsp;&middot;&nbsp; ".join(
            f'<a href="{s["url"]}" style="color:#A81C1C;text-decoration:none;'
            f'font-weight:bold;">{esc(s["label"])} &rsaquo;</a>'
            for s in item["sources"]
        )
        sources = (
            f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:10.5px;'
            f'color:#7A7A74;letter-spacing:0.04em;text-transform:uppercase;'
            f'padding-top:4px;">Source: {links}</div>'
        )

    return f"""
<tr><td style="padding:0 0 26px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">

    <tr><td style="padding-bottom:9px;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
        <tr>
          <td valign="top" width="26"
              style="font-family:'Courier New',monospace;font-size:13px;
                     font-weight:bold;color:#A81C1C;padding-top:3px;">{index}</td>
          <td valign="top"
              style="font-family:Georgia,'Times New Roman',serif;font-size:20px;
                     font-weight:bold;color:#1A1A18;line-height:1.3;">
            {item['headline']}</td>
        </tr>
      </table>
    </td></tr>

    <tr><td bgcolor="{tint}" style="background:{tint};padding:9px 13px;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td bgcolor="{badge_bg}"
              style="background:{badge_bg};padding:3px 9px;
                     font-family:Arial,Helvetica,sans-serif;font-size:9.5px;
                     font-weight:bold;color:#FFFFFF;letter-spacing:0.1em;
                     text-transform:uppercase;white-space:nowrap;">{label}</td>
          <td style="padding-left:10px;font-family:Arial,Helvetica,sans-serif;
                     font-size:12px;color:{text_col};line-height:1.5;">
            {item['status']}</td>
        </tr>
      </table>
    </td></tr>

    <tr><td style="padding-top:13px;font-family:Georgia,'Times New Roman',serif;
                   font-size:14px;color:#333330;line-height:1.68;">
      {item['bodyHtml']}
    </td></tr>

    <tr><td style="padding-top:2px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
             bgcolor="#F3F2EC" style="background:#F3F2EC;">
        <tr><td style="padding:12px 16px;border-left:3px solid #1A1A18;">
          <div style="font-family:Arial,Helvetica,sans-serif;font-size:9.5px;
                      font-weight:bold;letter-spacing:0.12em;text-transform:uppercase;
                      color:#1A1A18;padding-bottom:5px;">Credit implication</div>
          <div style="font-family:Georgia,'Times New Roman',serif;font-size:14px;
                      color:#1A1A18;line-height:1.6;">{item['creditImplication']}</div>
        </td></tr>
      </table>
    </td></tr>

    <tr><td style="padding-top:8px;">{sources}</td></tr>

  </table>
</td></tr>"""


def render_table(rows):
    if not rows:
        return ""
    body = "".join(f"""
        <tr>
          <td style="font-family:Georgia,serif;font-size:13px;font-weight:bold;
                     color:#1A1A18;padding:9px 10px 9px 0;
                     border-bottom:1px solid #E2E0D8;vertical-align:top;
                     width:32%;">{r['development']}</td>
          <td style="font-family:Arial,Helvetica,sans-serif;font-size:10px;
                     font-weight:bold;letter-spacing:0.05em;text-transform:uppercase;
                     color:{table_stat_color(r['status'])};padding:9px 10px 9px 0;
                     border-bottom:1px solid #E2E0D8;vertical-align:top;
                     width:27%;">{r['status']}</td>
          <td style="font-family:Georgia,serif;font-size:13px;color:#333330;
                     line-height:1.5;padding:9px 0;
                     border-bottom:1px solid #E2E0D8;vertical-align:top;">{r['read']}</td>
        </tr>""" for r in rows)

    return f"""
<tr><td style="padding:8px 0 26px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
    <tr><td height="3" bgcolor="#1A1A18"
            style="height:3px;background:#1A1A18;font-size:0;line-height:0;">&nbsp;</td></tr>
    <tr><td style="padding:12px 0 12px;font-family:Arial,Helvetica,sans-serif;
                   font-size:11px;font-weight:bold;letter-spacing:0.14em;
                   text-transform:uppercase;color:#1A1A18;">
      What is actually changing vs. political messaging</td></tr>
  </table>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
    <tr>
      <th align="left" style="font-family:Arial,Helvetica,sans-serif;font-size:9.5px;
                 font-weight:bold;letter-spacing:0.1em;text-transform:uppercase;
                 color:#7A7A74;padding:0 10px 7px 0;
                 border-bottom:1px solid #1A1A18;">Development</th>
      <th align="left" style="font-family:Arial,Helvetica,sans-serif;font-size:9.5px;
                 font-weight:bold;letter-spacing:0.1em;text-transform:uppercase;
                 color:#7A7A74;padding:0 10px 7px 0;
                 border-bottom:1px solid #1A1A18;">Current status</th>
      <th align="left" style="font-family:Arial,Helvetica,sans-serif;font-size:9.5px;
                 font-weight:bold;letter-spacing:0.1em;text-transform:uppercase;
                 color:#7A7A74;padding:0 0 7px;
                 border-bottom:1px solid #1A1A18;">My credit read</th>
    </tr>
    {body}
  </table>
</td></tr>"""


def render_html(entry, site_url):
    items = "".join(render_item(it, i + 1) for i, it in enumerate(entry.get("items", [])))

    focus = ""
    if entry.get("focusHtml"):
        focus = f"""
<tr><td style="padding:0 0 8px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
    <tr><td height="3" bgcolor="#1A1A18"
            style="height:3px;background:#1A1A18;font-size:0;line-height:0;">&nbsp;</td></tr>
    <tr><td style="padding:12px 0 10px;font-family:Arial,Helvetica,sans-serif;
                   font-size:11px;font-weight:bold;letter-spacing:0.14em;
                   text-transform:uppercase;color:#1A1A18;">
      What I would focus on</td></tr>
    <tr><td style="font-family:Georgia,'Times New Roman',serif;font-size:14px;
                   color:#333330;line-height:1.68;">{entry['focusHtml']}</td></tr>
  </table>
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
           style="width:100%;max-width:720px;">

      <tr><td style="padding-bottom:10px;">
        <div style="font-family:Arial,Helvetica,sans-serif;font-size:10px;
                    font-weight:bold;letter-spacing:0.2em;text-transform:uppercase;
                    color:#A81C1C;">Weekly Briefing</div>
        <div style="font-family:Georgia,'Times New Roman',serif;font-size:27px;
                    font-weight:bold;color:#1A1A18;padding:7px 0 3px;line-height:1.2;">
          {entry['title']}</div>
        <div style="font-family:Arial,Helvetica,sans-serif;font-size:12.5px;
                    color:#7A7A74;">{esc(entry.get('throughDate', entry.get('date','')))}</div>
      </td></tr>

      <tr><td style="padding-bottom:4px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr><td height="3" bgcolor="#1A1A18"
                  style="height:3px;background:#1A1A18;font-size:0;line-height:0;">&nbsp;</td></tr>
        </table>
      </td></tr>

      <tr><td style="padding:16px 0 16px;font-family:Georgia,'Times New Roman',serif;
                     font-size:15px;color:#1A1A18;line-height:1.68;
                     border-bottom:1px solid #E2E0D8;">
        {entry.get('overviewHtml','')}
      </td></tr>

      <tr><td style="padding:11px 0 22px;font-family:Arial,Helvetica,sans-serif;
                     font-size:10.5px;color:#9A9A94;line-height:1.6;">
        Compiled automatically by Claude from public sources. Status labels
        distinguish what has taken effect from what is only proposed &mdash;
        verify anything underwriting-critical against the primary source.
      </td></tr>

      {items}
      {render_table(entry.get('table', []))}
      {focus}
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


def unescape(text):
    """Reverse the HTML escaping applied when the briefing was stored, so the
    plain-text alternative reads as prose rather than showing '&amp;'."""
    return (str(text or "")
            .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&#39;", "'")
            .replace("&mdash;", "—").replace("&ndash;", "–")
            .replace("&middot;", "·").replace("&rsaquo;", "›")
            .replace("&nbsp;", " "))


def strip_tags(html):
    text = re.sub(r"</p\s*>", "\n\n", html or "")
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip()


def render_text(entry):
    lines = [
        unescape(entry["title"]).upper(),
        unescape(entry.get("throughDate", entry.get("date", ""))),
        "=" * 62,
        "",
        strip_tags(entry.get("overviewHtml", "")),
        "",
    ]

    for i, it in enumerate(entry.get("items", []), 1):
        label = TIERS.get(it.get("statusTier"), TIERS["pending"])[0]
        lines += [
            "-" * 62,
            f"{i}. {unescape(it['headline'])}",
            f"[{label.upper()}] {unescape(it['status'])}",
            "",
            strip_tags(it["bodyHtml"]),
            "",
            f"CREDIT IMPLICATION: {unescape(it['creditImplication'])}",
        ]
        for s in it.get("sources", []):
            lines.append(f"Source: {unescape(s['label'])} — {s['url']}")
        lines.append("")

    if entry.get("table"):
        lines += ["=" * 62, "WHAT IS ACTUALLY CHANGING VS. POLITICAL MESSAGING", ""]
        for r in entry["table"]:
            lines.append(f"  {unescape(r['development'])}")
            lines.append(f"    Status: {unescape(r['status'])}")
            lines.append(f"    Read:   {unescape(r['read'])}")
            lines.append("")

    if entry.get("focusHtml"):
        lines += ["=" * 62, "WHAT I WOULD FOCUS ON", "",
                  strip_tags(entry["focusHtml"]), ""]

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
    msg["Subject"] = f"{entry['title']} — {entry['date']}"
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
