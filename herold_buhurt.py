"""Collect approved European Buhurt tournaments for the Rabenruf Herold.

The BI tournament page is the discovery source. Social posts are deliberately
not scraped; they are linked in the app and must be confirmed by the organizer
or BI before an event is accepted.
"""

import hashlib
import json
import re
import urllib.request
from datetime import date


URL = "https://www.buhurtinternational.com/tournaments"
USER_AGENT = "Mozilla/5.0 Rabenruf-Herold/1.0"
EUROPEAN_COUNTRIES = {
    "AD": "Andorra", "AL": "Albanien", "AT": "Österreich", "BA": "Bosnien und Herzegowina",
    "BE": "Belgien", "BG": "Bulgarien", "BY": "Belarus", "CH": "Schweiz",
    "CY": "Zypern", "CZ": "Tschechien", "DE": "Deutschland", "DK": "Dänemark",
    "EE": "Estland", "ES": "Spanien", "FI": "Finnland", "FR": "Frankreich",
    "GB": "Vereinigtes Königreich", "GE": "Georgien", "GR": "Griechenland",
    "HR": "Kroatien", "HU": "Ungarn", "IE": "Irland", "IS": "Island",
    "IT": "Italien", "LI": "Liechtenstein", "LT": "Litauen", "LU": "Luxemburg",
    "LV": "Lettland", "MC": "Monaco", "MD": "Moldau", "ME": "Montenegro",
    "MK": "Nordmazedonien", "MT": "Malta", "NL": "Niederlande", "NO": "Norwegen",
    "PL": "Polen", "PT": "Portugal", "RO": "Rumänien", "RS": "Serbien",
    "RU": "Russland", "SE": "Schweden", "SI": "Slowenien", "SK": "Slowakei",
    "SM": "San Marino", "TR": "Türkei", "UA": "Ukraine", "VA": "Vatikanstadt",
    "XK": "Kosovo",
}
COUNTRY_ALIASES = {
    "AUSTRIA": "AT", "AUSTRALIEN": "AU", "AUSTRALIA": "AU",
    "BELGIUM": "BE", "BELGIEN": "BE", "BOSNIA AND HERZEGOVINA": "BA",
    "CANADA": "CA", "CZECH REPUBLIC": "CZ", "CZECHIA": "CZ",
    "FRANCE": "FR", "FRANKREICH": "FR", "GERMANY": "DE", "DEUTSCHLAND": "DE",
    "HUNGARY": "HU", "UNGARN": "HU", "ITALY": "IT", "ITALIEN": "IT",
    "NETHERLANDS": "NL", "NIEDERLANDE": "NL", "POLAND": "PL", "POLEN": "PL",
    "ROMANIA": "RO", "RUMÄNIEN": "RO", "SLOVAKIA": "SK", "SLOWAKEI": "SK",
    "SLOVENIA": "SI", "SLOWENIEN": "SI", "SPAIN": "ES", "SPANIEN": "ES",
    "SWITZERLAND": "CH", "SCHWEIZ": "CH", "UNITED KINGDOM": "GB",
    "UNITED STATES": "US", "USA": "US",
}


def fetch_page():
    request = urllib.request.Request(URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8", errors="ignore")


def unescape_json_string(value):
    try:
        return json.loads('"' + value + '"')
    except json.JSONDecodeError:
        return value.replace("\\/", "/").replace('\\"', '"')


def field(text, name):
    match = re.search(r'"' + re.escape(name) + r'":"((?:\\.|[^"\\])*)"', text)
    return unescape_json_string(match.group(1)) if match else ""


def number_field(text, name):
    match = re.search(r'"' + re.escape(name) + r'":(-?\d+(?:\.\d+)?)', text)
    return float(match.group(1)) if match else 0.0


def extract_events(html):
    # Wix embeds the approved tournament records in the page's initial data.
    # Pair each eventDate with its nearest eventName, without retaining any
    # unrelated registration or competitor fields also present in that data.
    titles = list(re.finditer(r'"eventName":"((?:\\.|[^"\\])*)"', html))
    dates = list(re.finditer(r'"eventDate":"(20\d{2}-\d{2}-\d{2})"', html))
    events = []
    today = date.today().isoformat()

    for date_match in dates:
        title_match = next((item for item in reversed(titles) if item.end() < date_match.start()), None)
        if not title_match:
            continue
        following_titles = [item for item in titles if item.start() > title_match.start()]
        stop = following_titles[0].start() if following_titles else min(len(html), date_match.end() + 20000)
        record = html[title_match.start():stop]
        name = unescape_json_string(title_match.group(1)).strip()
        start = date_match.group(1)
        if not name or start < today:
            continue

        location_start = record.find('"location":')
        location = record[location_start:] if location_start >= 0 else record
        city = field(location, "city").strip()
        country_value = field(location, "country").strip()
        country_code = country_value.upper()
        country_code = COUNTRY_ALIASES.get(country_code, country_code)
        country = EUROPEAN_COUNTRIES.get(country_code)
        if not city:
            formatted = field(location, "formatted")
            city = formatted.split(",", 1)[0].strip()
        if not country or not city:
            continue

        path = field(record, "link-event-register-custom-title")
        if not path.startswith("/tournament/"):
            continue
        source = "https://www.buhurtinternational.com" + path
        lat = number_field(location, "latitude")
        lng = number_field(location, "longitude")
        raw_id = f"BI|{name}|{city}|{start}".encode("utf-8")
        events.append({
            "id": "bi-buhurt-" + hashlib.sha1(raw_id).hexdigest()[:16],
            "name": name[:180],
            "type": "Buhurt",
            "date": start,
            "start": start,
            "end": start,
            "country": country,
            "city": city[:100],
            "postcode": field(location, "postalCode"),
            "lat": lat,
            "lng": lng,
            "source": source,
        })

    unique = {}
    for item in events:
        key = (item["name"].casefold(), item["city"].casefold(), item["start"])
        unique[key] = item
    return list(unique.values())


def event_key(item):
    return (
        str(item.get("name", "")).strip().casefold(),
        str(item.get("city", "")).strip().casefold(),
        str(item.get("start", "")),
    )


def main():
    try:
        with open("herold-funde.json", "r", encoding="utf-8") as handle:
            existing = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    present = {event_key(item) for item in existing}
    new_events = []
    try:
        candidates = extract_events(fetch_page())
    except Exception as exc:
        # Keep other Herold sources working if BI is temporarily unavailable.
        print(f"Buhurt International: Abruf fehlgeschlagen: {exc}")
        return

    for item in candidates:
        key = event_key(item)
        if key not in present:
            new_events.append(item)
            present.add(key)

    existing.extend(new_events)
    with open("herold-funde.json", "w", encoding="utf-8") as handle:
        json.dump(existing, handle, ensure_ascii=False, indent=2)

    print("Buhurt International Europa:", len(candidates), "geprüfte Termine;", len(new_events), "neu im Herold")


if __name__ == "__main__":
    main()
