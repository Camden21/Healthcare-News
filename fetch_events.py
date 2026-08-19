#!/usr/bin/env python3
"""
Daily fetch for the CIB Healthcare News Tracker.

Pulls from free government sources, applies rule-based scoring, and appends
NEW events to events.json. Existing events are never modified.

Every auto-fetched event is written with:
    sourceVerification: "Auto-drafted — pending review"
so it is visibly distinct from your hand-audited entries on the site.

No API keys. No paid services. Runs on GitHub Actions.
"""

import json
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from xml.etree import ElementTree

EVENTS_FILE = "events.json"
USER_AGENT = "CIB-Healthcare-Tracker/1.0 (GitHub Actions; daily digest)"
TIMEOUT = 30

# ----------------------------------------------------------------------
# SOURCES
# ----------------------------------------------------------------------
# RSS/Atom feeds. If a feed URL changes, the script logs it and continues
# rather than failing the whole run.
RSS_SOURCES = [
    {
        "name": "U.S. Department of Justice",
        "url": "https://www.justice.gov/feeds/opa/justice-news.xml",
        "jurisdiction": "Federal",
        # Only keep items that look healthcare-related
        "require_keywords": [
            "medicare", "medicaid", "health care", "healthcare", "hospice",
            "home health", "nursing home", "skilled nursing", "pharmacy",
            "durable medical", "dme", "telehealth", "clinic", "laboratory",
            "kickback", "false claims", "patient",
        ],
    },
    {
        "name": "CMS",
        "url": "https://www.cms.gov/newsroom/rss.xml",
        "jurisdiction": "Federal",
        "require_keywords": [],  # CMS is already domain-relevant
    },
    {
        "name": "HHS Office of Inspector General",
        "url": "https://oig.hhs.gov/rss/reports.xml",
        "jurisdiction": "Federal",
        "require_keywords": [],
    },
]

# FEMA OpenFEMA API — free, no key required.
FEMA_API = (
    "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
    "?$filter=declarationDate%20ge%20%27{since}%27"
    "&$orderby=declarationDate%20desc"
    "&$top=200"
)

# ----------------------------------------------------------------------
# RULE-BASED CLASSIFICATION
# ----------------------------------------------------------------------

CATEGORY_RULES = [
    ("disaster", [
        "disaster", "hurricane", "wildfire", "fire", "flood", "tornado",
        "typhoon", "storm", "emergency declaration", "public health emergency",
        "evacuation", "mudslide", "landslide", "fema",
    ]),
    ("fraud", [
        "fraud", "kickback", "false claims", "indicted", "convicted",
        "pleads guilty", "sentenced", "settlement", "takedown", "strike force",
        "moratorium", "revocation", "program integrity", "improper payment",
        "overpayment", "audit", "oig", "enforcement", "deferral", "suspend",
    ]),
    ("medicaid", [
        "medicaid", "medi-cal", "chip", "state directed payment",
        "provider tax", "provider rate", "eligibility", "redetermination",
        "work requirement", "waiver", "hcbs", "state plan amendment",
    ]),
    ("cms", [
        "medicare", "cms", "payment system", "fee schedule", "pps",
        "wage index", "prospective payment", "final rule", "proposed rule",
        "physician fee", "quality reporting", "value-based",
    ]),
    ("regulation", [
        "regulation", "rulemaking", "federal register", "compliance",
        "civil rights", "conditions of participation",
    ]),
]

NEGATIVE_TERMS = [
    "fraud", "kickback", "false claims", "convicted", "pleads guilty",
    "sentenced", "indicted", "charged", "moratorium", "revocation", "revoke",
    "deferral", "defers", "defer", "deferred", "suspend", "suspends",
    "suspension", "cut", "cuts", "reduction", "reduce", "decrease",
    "penalty", "overpayment", "improper", "disallowance", "terminate",
    "termination", "denial", "denies", "restrict", "restricts", "limit",
    "limits", "freeze", "halts", "halt", "pause",
    # disaster signals
    "disaster", "wildfire", "fire", "flood", "flooding", "hurricane",
    "tornado", "typhoon", "storm", "emergency", "evacuation", "mudslide",
    "landslide",
]

POSITIVE_TERMS = [
    "increase", "increases", "funding", "funds", "fully fund", "expand",
    "expands", "grant", "grants", "relief", "flexibility", "waiver approved",
    "rate increase", "investment", "invests", "restore", "restores", "raise",
    "raises", "boost", "add", "adds", "bolster", "secures",
]

# Highest-severity signals: things that stop cash flow or block enrollment
CRITICAL_TERMS = [
    "moratorium", "deferral", "defers", "suspend", "suspends", "suspension",
    "revocation", "revoke", "terminate", "termination", "billion",
    "nationwide", "disallowance", "takedown", "statewide",
]

HIGH_TERMS = [
    "million", "final rule", "finalize", "finalizes", "finalized",
    "proposed rule", "proposes", "convicted", "sentenced", "indicted",
    "pleads guilty", "settlement", "settles", "strike force",
    "major disaster", "public health emergency", "audit", "overpayment",
    "payment update", "rate update", "wage index", "charged",
]


def _normalize(text):
    """Lowercase and treat hyphens/slashes as spaces so 'provider-rate'
    matches the term 'provider rate'."""
    return re.sub(r"[-/\u2010-\u2015]", " ", (text or "").lower())


def _matches(text, term):
    """Word-boundary match so 'add' doesn't fire inside 'additional'."""
    return re.search(r"\b" + re.escape(term) + r"\b", text) is not None


def classify_category(text):
    t = _normalize(text)
    for cat, terms in CATEGORY_RULES:
        if any(_matches(t, term) for term in terms):
            return cat
    return "other"


def classify_direction(text):
    t = _normalize(text)
    neg = sum(1 for term in NEGATIVE_TERMS if _matches(t, term))
    pos = sum(1 for term in POSITIVE_TERMS if _matches(t, term))
    if neg and pos:
        return "Mixed"
    if pos and not neg:
        return "Positive"
    if neg and not pos:
        return "Negative"
    # Nothing matched either way — don't assert a direction we can't support.
    return "Mixed"


def extract_dollars(text):
    """Return the largest dollar figure mentioned, in dollars, or None.

    Handles '$6.5 billion', '$539,000', '$24 million', '$1.7B'.
    Magnitude is the single best automatic proxy for how much an event
    actually matters, so it drives scoring more than keywords do.
    """
    t = _normalize(text)
    best = None

    pattern = r"\$\s?([\d,]+(?:\.\d+)?)\s*(trillion|billion|million|thousand|[tbmk])?\b"
    for match in re.finditer(pattern, t):
        raw, unit = match.group(1), (match.group(2) or "")
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue

        multipliers = {
            "trillion": 1e12, "t": 1e12,
            "billion": 1e9, "b": 1e9,
            "million": 1e6, "m": 1e6,
            "thousand": 1e3, "k": 1e3,
        }
        value *= multipliers.get(unit, 1)

        if best is None or value > best:
            best = value

    return best


# Scope terms that widen an event's blast radius regardless of dollar size
BROAD_SCOPE_TERMS = [
    "nationwide", "national", "statewide", "all states", "every state",
    "moratorium", "final rule", "interim final rule", "all providers",
]


def classify_severity(text):
    """Returns (severity_label, risk_score) on the tracker's 0-12 scale.

    Priority order:
      1. Dollar magnitude (most reliable automatic signal)
      2. Scope (nationwide / statewide / rulemaking)
      3. Keyword severity terms
    """
    t = _normalize(text)

    score = 0

    # --- 1. Dollar magnitude ---
    dollars = extract_dollars(text)
    if dollars is not None:
        if dollars >= 1e9:
            score = max(score, 12)
        elif dollars >= 1e8:
            score = max(score, 11)
        elif dollars >= 1e7:
            score = max(score, 9)
        elif dollars >= 1e6:
            score = max(score, 8)
        else:
            score = max(score, 6)

    # --- 2. Scope ---
    if any(_matches(t, term) for term in BROAD_SCOPE_TERMS):
        score = max(score, 10)

    # --- 3. Keyword severity ---
    if any(_matches(t, term) for term in CRITICAL_TERMS):
        score = max(score, 10)
    elif any(_matches(t, term) for term in HIGH_TERMS):
        score = max(score, 8)

    if score == 0:
        score = 6

    score = min(score, 12)

    if score >= 10:
        label = "Critical"
    elif score >= 7:
        label = "High"
    else:
        label = "Medium"

    return label, score


CATEGORY_LABELS = {
    "borrower": "Borrower News",
    "industry": "Industry / Trade",
    "fraud": "Fraud / Investigation",
    "medicaid": "Federal Medicaid Action",
    "cms": "CMS / Medicare",
    "disaster": "Natural Disaster",
    "regulation": "Federal Healthcare Regulation",
    "other": "Healthcare Policy",
}



# ----------------------------------------------------------------------
# BORROWER WATCHLIST
# ----------------------------------------------------------------------
# Two tiers of matching to control false positives:
#
#   strong  - distinctive enough to match on their own
#   weak    - generic phrases that only count when the article ALSO mentions
#             healthcare context (SNF, DME, home health, Medicare, etc.)
#
# Add or edit entries here as the portfolio changes.

BORROWERS = [
    {
        "name": "Drumm Merger / Cuarzo",
        "strong": ["cuarzo", "drumm merger", "drumm corp"],
        "weak": ["drumm"],
    },
    {
        "name": "PACS Holdings",
        "strong": ["pacs holdings", "pacs group"],
        "weak": ["pacs"],
    },
    {
        "name": "New Day Healthcare",
        "strong": ["new day healthcare", "new day health care"],
        "weak": [],
    },
    {
        "name": "Purpose Healing",
        "strong": ["purpose healing"],
        "weak": [],
    },
    {
        "name": "Pathnostics",
        "strong": ["pathnostics"],
        "weak": [],
    },
    {
        "name": "CCGEN Jefferson / Autumn Lake",
        "strong": ["autumn lake", "ccgen"],
        "weak": ["jefferson healthcare"],
    },
    {
        "name": "Complete Care at Glendale",
        "strong": ["complete care at glendale"],
        "weak": ["complete care"],
    },
    {
        "name": "HCS-Girling",
        "strong": ["hcs-girling", "hcs girling", "girling health", "girling home"],
        "weak": ["girling"],
    },
    {
        "name": "Quipt Home Medical",
        "strong": ["quipt"],
        "weak": [],
    },
    {
        "name": "Diversified Healthcare Trust",
        "strong": ["diversified healthcare trust", "diversified healthcare"],
        "weak": [],
    },
    {
        "name": "Oxford Finance",
        "strong": ["oxford finance"],
        "weak": [],
    },
]

# Context terms that make a weak (generic) borrower match credible.
SECTOR_CONTEXT = [
    "healthcare", "health care", "snf", "skilled nursing", "nursing home",
    "nursing facility", "dme", "dmepos", "durable medical", "home health",
    "home care", "hospice", "medicare", "medicaid", "senior living",
    "assisted living", "long term care", "long-term care", "behavioral health",
    "patient", "provider", "clinic", "pharmacy", "hospital", "therapy",
    "rehabilitation", "caregiver", "physician",
]


def has_sector_context(text):
    t = _normalize(text)
    return any(term in t for term in SECTOR_CONTEXT)


def match_borrowers(text):
    """Return the list of borrower names plausibly referenced in this text."""
    t = _normalize(text)
    context = has_sector_context(text)
    hits = []

    for b in BORROWERS:
        matched = False

        for term in b.get("strong", []):
            if _matches(t, _normalize(term)):
                matched = True
                break

        if not matched and context:
            for term in b.get("weak", []):
                if _matches(t, _normalize(term)):
                    matched = True
                    break

        if matched:
            hits.append(b["name"])

    return hits


# ----------------------------------------------------------------------
# FETCHING
# ----------------------------------------------------------------------
# Trade press. These are secondary sources, not primary government records,
# so items are labelled accordingly and held to a higher relevance bar:
# they are only kept if they name a portfolio borrower or contain
# credit-relevant signal. Otherwise routine industry coverage floods the feed.
TRADE_SOURCES = [
    {"name": "Skilled Nursing News", "url": "https://skillednursingnews.com/feed/"},
    {"name": "Home Health Care News", "url": "https://homehealthcarenews.com/feed/"},
    {"name": "Hospice News", "url": "https://hospicenews.com/feed/"},
    {"name": "Behavioral Health Business", "url": "https://bhbusiness.com/feed/"},
    {"name": "Senior Housing News", "url": "https://seniorhousingnews.com/feed/"},
    {"name": "McKnight's Long-Term Care News", "url": "https://www.mcknights.com/feed/"},
]

# Credit-relevant signal for trade press. Broad industry coverage is skipped;
# these are the things that actually move a credit view.
CREDIT_SIGNAL_TERMS = [
    "bankruptcy", "chapter 11", "chapter 7", "default", "defaults",
    "covenant", "forbearance", "restructuring", "restructure", "receivership",
    "downgrade", "downgraded", "distress", "distressed", "insolvency",
    "closure", "closures", "closing", "shut down", "shutter", "layoff",
    "layoffs", "acquisition", "acquires", "acquired", "merger", "sells",
    "divest", "ipo", "sec investigation", "subpoena", "lawsuit", "settlement",
    "fraud", "indictment", "false claims", "occupancy", "census",
    "reimbursement", "rate cut", "margin", "earnings", "guidance",
    "credit facility", "refinanc", "debt", "liquidity", "going concern",
]


def fetch_trade_source(source):
    """Trade press: keep only borrower mentions or credit-relevant items."""
    print(f"  Fetching {source['name']}...")
    try:
        raw = http_get(source["url"])
    except Exception as exc:
        print(f"    ! FAILED ({exc})")
        return [], False

    items = parse_rss(raw)
    print(f"    {len(items)} items returned")

    results = []
    borrower_count = 0

    for item in items:
        text = f"{item['title']} {item['summary']}"
        blob = _normalize(text)

        borrowers = match_borrowers(text)
        has_signal = any(_matches(blob, t) for t in CREDIT_SIGNAL_TERMS)

        # Skip routine industry coverage
        if not borrowers and not has_signal:
            continue

        dt = parse_date(item["published"])
        if dt is None:
            continue

        cat = classify_category(blob)
        if cat == "other":
            cat = "borrower" if borrowers else "industry"

        direction = classify_direction(blob)
        severity, score = classify_severity(blob)

        if borrowers:
            score = max(score, 11)
            severity = "Critical"
            borrower_count += 1
        else:
            # Trade coverage without a borrower is context, not an alert.
            score = min(score, 8)

        results.append({
            "date": dt.strftime("%b %-d, %Y"),
            "dateSort": dt.strftime("%Y-%m-%dT00:00:00"),
            "jurisdiction": "Trade Press",
            "state": "U.S.",
            "category": "Borrower News" if borrowers else "Industry / Trade",
            "broadCategory": cat,
            "sector": "Pending review",
            "headline": item["title"][:200],
            "detail": (item["summary"] or item["title"])[:700],
            "creditDirection": direction,
            "severity": severity,
            "riskScore": score,
            "sourceAgency": source["name"],
            "sourceVerification": "Trade press — not a primary source",
            "sourceURL": item["link"],
            "effectiveDate": "Pending review",
            "borrowers": borrowers,
        })

    print(f"    {len(results)} kept ({borrower_count} borrower mentions)")
    return results, True



def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def strip_html(raw):
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_rss(xml_bytes):
    """Handles both RSS 2.0 and Atom."""
    items = []
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError as exc:
        print(f"    ! XML parse error: {exc}")
        return items

    # RSS 2.0
    for item in root.iter("item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        desc = item.findtext("description") or ""
        pub = item.findtext("pubDate") or ""
        items.append({"title": title.strip(), "link": link.strip(),
                      "summary": strip_html(desc), "published": pub.strip()})

    # Atom
    ns = "{http://www.w3.org/2005/Atom}"
    for entry in root.iter(f"{ns}entry"):
        title = entry.findtext(f"{ns}title") or ""
        link_el = entry.find(f"{ns}link")
        link = link_el.get("href") if link_el is not None else ""
        summary = entry.findtext(f"{ns}summary") or entry.findtext(f"{ns}content") or ""
        pub = entry.findtext(f"{ns}updated") or entry.findtext(f"{ns}published") or ""
        items.append({"title": title.strip(), "link": (link or "").strip(),
                      "summary": strip_html(summary), "published": pub.strip()})

    return items


DATE_FORMATS = [
    "%a, %d %b %Y %H:%M:%S %z",
    "%a, %d %b %Y %H:%M:%S %Z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d",
]


def parse_date(raw):
    raw = (raw or "").strip()
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=None)
        except ValueError:
            continue
    return None


def fetch_rss_source(source):
    print(f"  Fetching {source['name']}...")
    try:
        raw = http_get(source["url"])
    except Exception as exc:
        print(f"    ! FAILED ({exc})")
        return [], False

    items = parse_rss(raw)
    print(f"    {len(items)} items returned")

    results = []
    for item in items:
        blob = f"{item['title']} {item['summary']}".lower()

        if source["require_keywords"] and not any(
            k in blob for k in source["require_keywords"]
        ):
            continue

        dt = parse_date(item["published"])
        if dt is None:
            continue

        cat = classify_category(blob)
        direction = classify_direction(blob)
        severity, score = classify_severity(blob)

        borrowers = match_borrowers(f"{item['title']} {item['summary']}")
        if borrowers:
            # Anything naming a borrower is portfolio-relevant by definition.
            score = max(score, 11)
            severity = "Critical"

        results.append({
            "date": dt.strftime("%b %-d, %Y"),
            "dateSort": dt.strftime("%Y-%m-%dT00:00:00"),
            "jurisdiction": source["jurisdiction"],
            "state": "U.S.",
            "category": CATEGORY_LABELS.get(cat, "Healthcare Policy"),
            "broadCategory": cat,
            "sector": "Pending review",
            "headline": item["title"][:200],
            "detail": (item["summary"] or item["title"])[:700],
            "creditDirection": direction,
            "severity": severity,
            "riskScore": score,
            "sourceAgency": source["name"],
            "sourceVerification": "Auto-drafted — pending review",
            "sourceURL": item["link"],
            "effectiveDate": "Pending review",
            "borrowers": borrowers,
        })

    print(f"    {len(results)} healthcare-relevant items kept")
    return results, True


def fetch_fema(since_iso):
    print("  Fetching FEMA OpenFEMA API...")
    url = FEMA_API.format(since=since_iso)
    try:
        raw = http_get(url)
        payload = json.loads(raw)
    except Exception as exc:
        print(f"    ! FAILED ({exc})")
        return [], False

    records = payload.get("DisasterDeclarationsSummaries", [])
    print(f"    {len(records)} declarations returned")

    # One declaration produces many county-level rows; collapse to one per
    # disaster number so the feed isn't flooded.
    seen = set()
    results = []
    for rec in records:
        num = rec.get("disasterNumber")
        if num in seen:
            continue
        seen.add(num)

        decl_date = (rec.get("declarationDate") or "")[:10]
        dt = parse_date(decl_date)
        if dt is None:
            continue

        title = rec.get("declarationTitle") or "Disaster declaration"
        state = rec.get("state") or "U.S."
        dtype = rec.get("incidentType") or "Disaster"

        headline = f"FEMA declares {dtype.lower()} disaster in {state}: {title.title()}"
        detail = (
            f"FEMA declaration {rec.get('femaDeclarationString', num)} for {state}. "
            f"Incident type: {dtype}. Incident period began "
            f"{(rec.get('incidentBeginDate') or '')[:10] or 'not stated'}. "
            f"Declared {decl_date}. Facility-level operational impact requires review."
        )

        decl_type = (rec.get("declarationType") or "").upper()
        # DR = Major Disaster, EM = Emergency, FM = Fire Management Assistance.
        # FM grants are routine, local, and rarely material to a credit
        # portfolio, so they must not score like a statewide major disaster.
        if decl_type == "DR":
            severity, score = "High", 9
        elif decl_type == "EM":
            severity, score = "High", 8
        else:
            severity, score = "Medium", 5

        # Widescale events affecting many counties matter more.
        designated = rec.get("designatedArea") or ""
        if decl_type == "DR" and "statewide" in designated.lower():
            score = 10
            severity = "Critical"

        results.append({
            "date": dt.strftime("%b %-d, %Y"),
            "dateSort": dt.strftime("%Y-%m-%dT00:00:00"),
            "jurisdiction": "Disaster",
            "state": state,
            "category": "Natural Disaster",
            "broadCategory": "disaster",
            "sector": "Skilled Nursing; Assisted Living; Home Health; Hospice; HME/DME",
            "headline": headline[:200],
            "detail": detail[:700],
            "creditDirection": "Negative",
            "severity": severity,
            "riskScore": score,
            "sourceAgency": "FEMA",
            "sourceVerification": "Auto-drafted — pending review",
            "sourceURL": f"https://www.fema.gov/disaster/{num}",
            "effectiveDate": f"Declared {decl_date}",
            "borrowers": [],
        })

    print(f"    {len(results)} unique declarations kept")
    return results, True


# ----------------------------------------------------------------------
# MERGE
# ----------------------------------------------------------------------

def normalize(url):
    return (url or "").split("?")[0].rstrip("/").lower()


def next_id(existing, prefix):
    nums = []
    for e in existing:
        eid = e.get("id") or ""
        if eid.startswith(prefix + "-"):
            tail = eid.split("-")[-1]
            if tail.isdigit():
                nums.append(int(tail))
    return f"{prefix}-{(max(nums) + 1) if nums else 1:03d}"


PREFIX_BY_CATEGORY = {
    "borrower": "BOR",
    "industry": "IND",
    "fraud": "FRD",
    "disaster": "DIS",
    "medicaid": "FED",
    "cms": "FED",
    "regulation": "FED",
    "other": "FED",
}


def main():
    try:
        with open(EVENTS_FILE) as f:
            events = json.load(f)
    except FileNotFoundError:
        print(f"{EVENTS_FILE} not found — starting empty")
        events = []

    print(f"Existing events: {len(events)}")

    existing_urls = {normalize(e.get("sourceURL")) for e in events}
    existing_headlines = {(e.get("headline") or "").strip().lower() for e in events}

    # Look back 30 days so a missed run self-heals on the next day.
    lookback = time.time() - (30 * 86400)
    since_iso = datetime.fromtimestamp(lookback, tz=timezone.utc).strftime("%Y-%m-%d")
    print(f"Looking back to {since_iso}\n")

    candidates = []
    ok_count = 0
    total_sources = len(RSS_SOURCES) + len(TRADE_SOURCES) + 1

    for source in RSS_SOURCES:
        items, ok = fetch_rss_source(source)
        candidates.extend(items)
        if ok:
            ok_count += 1

    for source in TRADE_SOURCES:
        items, ok = fetch_trade_source(source)
        candidates.extend(items)
        if ok:
            ok_count += 1

    fema_items, fema_ok = fetch_fema(since_iso)
    candidates.extend(fema_items)
    if fema_ok:
        ok_count += 1

    print(f"\nSources reachable: {ok_count} of {total_sources}")
    print(f"Total candidates:  {len(candidates)}")

    if ok_count == 0:
        print("\nERROR: every source failed. The tracker cannot update.")
        print("This is usually a changed feed URL or a blocked request.")
        print("Failing the run so this does not pass silently.")
        return 1

    # Deduplicate against existing events AND within this batch
    added = []
    for cand in candidates:
        url_key = normalize(cand["sourceURL"])
        head_key = cand["headline"].strip().lower()

        if not url_key:
            continue
        if url_key in existing_urls or head_key in existing_headlines:
            continue
        if cand["dateSort"] < since_iso:
            continue

        prefix = PREFIX_BY_CATEGORY.get(cand["broadCategory"], "FED")
        cand["id"] = next_id(events + added, prefix)

        added.append(cand)
        existing_urls.add(url_key)
        existing_headlines.add(head_key)

    print(f"New events to add: {len(added)}")
    borrower_hits = [e for e in added if e.get("borrowers")]
    for e in added:
        tag = f"  <<< BORROWER: {', '.join(e['borrowers'])}" if e.get("borrowers") else ""
        print(f"  [{e['id']}] {e['date']} — {e['headline'][:60]}{tag}")
    if borrower_hits:
        print(f"\n*** {len(borrower_hits)} event(s) reference portfolio borrowers ***")

    if not added:
        print("\nNo new events. events.json unchanged.")
        return 0

    combined = added + events
    combined.sort(key=lambda e: e.get("dateSort") or "", reverse=True)

    with open(EVENTS_FILE, "w") as f:
        json.dump(combined, f, indent=2)

    print(f"\nWrote {len(combined)} total events to {EVENTS_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
