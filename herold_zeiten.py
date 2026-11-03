"""Conservative opening-hour extraction for Herold candidates.

Only explicitly dated JSON-LD Event schedules from the event's own website are
accepted. Results are proposals for admin review, never automatic approvals.
"""
import json
import re
import urllib.request
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

PATH = "herold-funde.json"
TIME = re.compile(r"^(?:[01]\\d|2[0-3]):[0-5]\\d$")
DATE = re.compile(r"^20\\d{2}-\\d{2}-\\d{2}$")

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
    parser = JsonScripts()
    parser.feed(html)
    start, end = str(event.get("start", "")), str(event.get("end") or event.get("start") or "")
    found = {}
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
            words = [w for w in re.findall(r"[a-zäöü]{4,}", event_title) if w not in ("mittelalter", "markt", "fest", "mittelaltermarkt")]
            if not words or not any(w in title for w in words):
                continue
            starts = str(item.get("startDate", ""))
            ends = str(item.get("endDate", ""))
            if not (starts[:10] == start and ends[:10] == end):
                continue
            for date_str, stamp in ((start, starts), (end, ends)):
                if not DATE.fullmatch(date_str) or "T" not in stamp:
                    continue
                match = re.search(r"T(\\d{2}:\\d{2})", stamp)
                if not match or not TIME.fullmatch(match.group(1)):
                    continue
                # A startDate/endDate pair describes event boundaries, not daily opening hours.
                # Only accept single-day events; multi-day boundaries are not daily hours.
                if start != end:
                    continue
                opening = re.search(r"T(\\d{2}:\\d{2})", starts)
                closing = re.search(r"T(\\d{2}:\\d{2})", ends)
                if opening and closing and opening.group(1) < closing.group(1):
                    found[start] = {"date": start, "open": opening.group(1), "close": closing.group(1)}
    return [{"date": k, **v} for k, v in sorted(found.items())]

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
            days = extract(event, html, url)
        except Exception:
            continue
        if days:
            event["hoursReview"] = {"status": "pending", "dailyHours": days, "source": url, "method": "event-jsonld"}
            count += 1
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, indent=2)
    print("Öffnungszeiten-Vorschläge zur Prüfung:", count)

if __name__ == "__main__":
    main()
