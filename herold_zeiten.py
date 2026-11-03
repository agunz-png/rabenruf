"""Conservative opening-hour extraction for Herold candidates.

Only explicitly dated JSON-LD Event schedules from the event's own website are
accepted. Results are proposals for admin review, never automatic approvals.
"""
import json
import re
import urllib.request
from datetime import date, datetime, timedelta
from bs4 import BeautifulSoup
from html.parser import HTMLParser
from urllib.parse import urlsplit

PATH = "herold-funde.json"
TIME = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
DATE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")

class JsonScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.scripts = []
    def handle_starttag(self, tag, attrs):
        self.inside = tag == "script" and "ld+json" in dict(attrs).get("type", "").lower()
    def handle_data(self, data):
        if self.inside:
            self.scripts.append(data)
    def handle_endtag(self, tag):
        if tag == "script":
            self.inside = False

def nodes(obj):
    if isinstance(obj, list):
        for item in obj:
            yield from nodes(item)
    elif isinstance(obj, dict):
        if "@graph" in obj:
            yield from nodes(obj["@graph"])
        yield obj

def extract(event, html, url):
    """Accept only explicit per-day Event time ranges, never inferred weekend hours."""
    parser = JsonScripts()
    parser.feed(html)
    start, end = str(event.get("start", "")), str(event.get("end") or event.get("start") or "")
    if not DATE.fullmatch(start) or not DATE.fullmatch(end) or start > end:
        return []
    found = {}
    conflicts = set()
    for script in parser.scripts:
        try:
            data = json.loads(script)
        except (ValueError, TypeError):
            continue
        for item in nodes(data):
            types = item.get("@type", [])
            if isinstance(types, str):
                types = [types]
            if not any(str(t).lower().endswith("event") for t in types):
                continue
            title = str(item.get("name", "")).lower()
            event_title = str(event.get("name", "")).lower()
            words = [w for w in re.findall(r"[a-zäöü]{4,}", event_title)
                     if w not in ("mittelalter", "markt", "fest", "mittelaltermarkt")]
            if not words or not any(w in title for w in words):
                continue
            starts = str(item.get("startDate", ""))
            ends = str(item.get("endDate", ""))
            # A multi-day parent Event gives only boundary timestamps.
            # Individual Event nodes with a same-day start/end are trustworthy day slots.
            if starts[:10] != ends[:10] or not (start <= starts[:10] <= end):
                continue
            opening = re.search(r"T(\d{2}:\d{2})", starts)
            closing = re.search(r"T(\d{2}:\d{2})", ends)
            if not opening or not closing:
                continue
            open_time, close_time = opening.group(1), closing.group(1)
            if not TIME.fullmatch(open_time) or not TIME.fullmatch(close_time) or open_time >= close_time:
                continue
            day = starts[:10]
            slot = {"date": day, "open": open_time, "close": close_time}
            if day in found and found[day] != slot:
                conflicts.add(day)
            else:
                found[day] = slot
    return [found[day] for day in sorted(found) if day not in conflicts]

WEEKDAYS = {
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3,
    "freitag": 4, "samstag": 5, "sonntag": 6,
    "mo": 0, "di": 1, "mi": 2, "do": 3, "fr": 4, "sa": 5, "so": 6,
}
DAY_LABEL = re.compile(
    r"(?<![\\w])(?P<day>montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|mo|di|mi|do|fr|sa|so)\\.?\\s*"
    r"(?:[,\\-:]\\s*)?(?P<date>\\d{1,2}\\.\\s*\\d{1,2}\\.(?:\\s*20\\d{2})?)?",
    re.IGNORECASE,
)
RANGE = re.compile(
    r"(?<!\\d)(?P<open>(?:[01]?\\d|2[0-3])(?:[:.]\\d{2})?)\\s*(?:uhr)?\\s*"
    r"(?:-|–|—|bis)\\s*(?P<close>(?:[01]?\\d|2[0-3])(?:[:.]\\d{2})?)\\s*(?:uhr)?",
    re.IGNORECASE,
)

def clock(raw):
    parts = re.split(r"[:.]", raw)
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"

def extract_text_hours(event, html):
    """Find labelled day/time rows in a small event page, not inferred hours."""
    try:
        start = date.fromisoformat(str(event.get("start", "")))
        end = date.fromisoformat(str(event.get("end") or event.get("start") or ""))
    except ValueError:
        return []
    if end < start or (end - start).days > 7:
        return []
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "form"]):
        tag.decompose()
    # Prefer compact rows/paragraphs; do not match a weekday in an unrelated paragraph.
    lines = []
    for tag in soup.find_all(["li", "tr", "p", "dd"]):
        line = tag.get_text(" ", strip=True)
        if 8 <= len(line) <= 170:
            lines.append(line)
    if not lines:
        lines = [line.strip() for line in soup.get_text("\\n", strip=True).splitlines() if 8 <= len(line.strip()) <= 170]
    matches = {}
    conflict = set()
    for line in lines:
        for day_match in DAY_LABEL.finditer(line):
            after = line[day_match.end():]
            time_match = RANGE.search(after[:65])
            if not time_match or time_match.start() > 24:
                continue
            opening, closing = clock(time_match.group("open")), clock(time_match.group("close"))
            if not opening or not closing or opening >= closing:
                continue
            explicit = day_match.group("date")
            day = None
            if explicit:
                parts = [p.strip() for p in explicit.split(".") if p.strip()]
                try:
                    day = date(int(parts[2]) if len(parts) > 2 else start.year, int(parts[1]), int(parts[0]))
                except (ValueError, IndexError):
                    continue
                if day.weekday() != WEEKDAYS[day_match.group("day").lower()]:
                    continue
            else:
                possible = [start + timedelta(days=n) for n in range((end - start).days + 1)
                            if (start + timedelta(days=n)).weekday() == WEEKDAYS[day_match.group("day").lower()]]
                if len(possible) != 1:
                    continue
                day = possible[0]
            if not start <= day <= end:
                continue
            slot = {"date": day.isoformat(), "open": opening, "close": closing}
            if day.isoformat() in matches and matches[day.isoformat()] != slot:
                conflict.add(day.isoformat())
            else:
                matches[day.isoformat()] = slot
    return [matches[key] for key in sorted(matches) if key not in conflict]

def main():
    with open(PATH, encoding="utf-8") as f:
        events = json.load(f)
    count = 0
    for event in events:
        if event.get("dailyHours") or event.get("hoursReview"):
            continue
        url = str(event.get("website") or "")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            continue
        if parsed.hostname in ("www.mirimor.ch", "mittelalterkalender.info", "www.mittelalterkalender.info"):
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Rabenruf-Herold/1.0", "Accept": "text/html"})
            with urllib.request.urlopen(req, timeout=7) as response:
                if "text/html" not in response.headers.get("Content-Type", ""):
                    continue
                html = response.read(350000).decode("utf-8", "replace")
            days = extract(event, html, url)\n            text_days = extract_text_hours(event, html)\n            if days and text_days and days != text_days:\n                # Conflicting source representations require manual investigation.\n                continue\n            if not days:\n                days = text_days
        except Exception:
            continue
        if days:
            event["hoursReview"] = {"status": "pending", "dailyHours": days, "source": url, "method": "event-jsonld-or-labelled-day-text"}
            count += 1
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, indent=2)
    print("Öffnungszeiten-Vorschläge zur Prüfung:", count)

if __name__ == "__main__":
    main()
