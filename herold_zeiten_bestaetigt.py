"""Daily conservative recheck of approved Rabenruf events.
Produces review proposals only. Never updates approved events or guesses hours.
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from herold_zeiten import extract, extract_text_hours

OUT = Path("herold-zeiten-pruefung.json")
URL = "https://xsrcdvtavnftwkndcfsr.supabase.co"
KEY = "sb_publishable_YeEqizrxcYL2mRZQai9HUw__Z8GlkPD"

def approved_events():
    query = urllib.parse.urlencode({"select": "event_id,status,event", "status": "eq.approved", "limit": "2000"})
    req = urllib.request.Request(URL + "/rest/v1/herold_decisions?" + query,
        headers={"apikey": KEY, "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.load(response)

def get_html(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return ""
    if parsed.hostname in {"www.mirimor.ch", "mittelalterkalender.info", "www.mittelalterkalender.info"}:
        return ""
    req = urllib.request.Request(url, headers={"User-Agent": "Rabenruf-Herold/1.0", "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=5) as response:
        if "text/html" not in response.headers.get("Content-Type", ""):
            return ""
        return response.read(350000).decode("utf-8", "replace")

def scan(rows, previous, today=None, fetch=get_html):
    today = today or date.today()
    existing = {str(p["event_id"]): p for p in previous if isinstance(p, dict) and p.get("event_id")}
    approved = {}
    for row in rows:
        event = row.get("event")
        if row.get("status") == "approved" and isinstance(event, dict):
            approved[str(row.get("event_id") or "")] = event
    result = {}
    for event_id, proposal in existing.items():
        event = approved.get(event_id)
        if event and not event.get("dailyHours") and proposal.get("start") == event.get("start") and proposal.get("end") == (event.get("end") or event.get("start")) and proposal.get("status") == "pending":
            result[event_id] = proposal
    # Rotate the workload across seven days; each eligible event is checked weekly.
    for event_id, event in sorted(approved.items()):
        start = str(event.get("start") or "")
        end = str(event.get("end") or start)
        if not start or end < today.isoformat() or event.get("dailyHours") or event_id in result:
            continue
        if sum(event_id.encode("utf-8")) % 7 != today.toordinal() % 7:
            continue
        url = str(event.get("website") or "")
        try:
            html = fetch(url)
            if not html:
                continue
            # Explicitly dated JSON-LD is acceptable. Text must explicitly contain
            # the event year; otherwise weekend hours may be from an earlier edition.
            days = extract(event, html, url)
            if not days:
                continue
            result[event_id] = {
                "event_id": event_id, "name": event.get("name", ""),
                "city": event.get("city", ""), "country": event.get("country", ""),
                "start": start, "end": end, "source": url,
                "status": "pending", "dailyHours": days,
                "checked_at": today.isoformat()
            }
        except Exception as error:
            print("Source skipped:", event_id, str(error)[:100])
    return sorted(result.values(), key=lambda p: (p.get("start", ""), p.get("name", ""), p.get("event_id", "")))

def main():
    previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
    proposals = scan(approved_events(), previous)
    OUT.write_text(json.dumps(proposals, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Pending approved-event hours reviews:", len(proposals))

if __name__ == "__main__":
    main()
