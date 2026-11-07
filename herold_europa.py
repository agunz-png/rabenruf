import hashlib
import json
import re
import urllib.request
from difflib import SequenceMatcher
from datetime import date, datetime
from urllib.parse import urljoin, urlsplit
from functools import lru_cache

from bs4 import BeautifulSoup


URL = "https://www.mittelalterkalender.info/mittelaltermarkt/mittelaltermaerkte-europa.php"

LAENDER = {
    "Albanien",
    "Andorra",
    "Armenien",
    "Aserbaidschan",
    "Belarus",
    "Belgien",
    "Bosnien und Herzegowina",
    "Bulgarien",
    "Dänemark",
    "Deutschland",
    "Estland",
    "Finnland",
    "Frankreich",
    "Georgien",
    "Großbritannien",
    "Griechenland",
    "Irland",
    "Island",
    "Italien",
    "Kosovo",
    "Kroatien",
    "Lettland",
    "Liechtenstein",
    "Litauen",
    "Luxemburg",
    "Malta",
    "Moldau",
    "Monaco",
    "Montenegro",
    "Niederlande",
    "Nordmazedonien",
    "Norwegen",
    "Österreich",
    "Polen",
    "Portugal",
    "Rumänien",
    "Russland",
    "San Marino",
    "Schweden",
    "Schweiz",
    "Serbien",
    "Slowakei",
    "Slowenien",
    "Spanien",
    "Tschechien",
    "Türkei",
    "Ukraine",
    "Ungarn",
    "Vereinigtes Königreich",
    "Zypern",
}


def datum_lesen(text):
    treffer = re.search(r"\d{1,2}\.\d{1,2}\.\d{4}", text)
    if not treffer:
        return ""

    return datetime.strptime(
        treffer.group(0),
        "%d.%m.%Y"
    ).date().isoformat()


def vorhandenes_startdatum(fund):
    start = fund.get("start", "")
    if start:
        return start

    text = str(fund.get("date", ""))

    iso = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if iso:
        return iso.group(0)

    deutsch = re.search(
        r"(\d{1,2})\.(\d{1,2})\.(20\d{2})",
        text
    )

    if deutsch:
        tag, monat, jahr = deutsch.groups()
        return f"{jahr}-{monat.zfill(2)}-{tag.zfill(2)}"

    return ""


def schluessel(name, city, start):
    return (
        name.strip().lower(),
        city.strip().lower(),
        start
    )


def seite_laden(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Rabenruf-Herold/1.0"
        }
    )
    html = urllib.request.urlopen(req, timeout=30).read()
    return BeautifulSoup(html, "html.parser")


@lru_cache(maxsize=180)
def veranstalter_details(detail_url):
    """Read a calendar detail page; never confuse the listing URL with organizer site."""
    try:
        page = seite_laden(detail_url)
    except Exception as exc:
        print("Detailseite nicht erreichbar:", detail_url, str(exc)[:100])
        return {}
    details = {}
    text = page.get_text(" ", strip=True)
    # Read a named organizer when the detail page explicitly labels it.
    match = re.search(r"(?:Veranstalter|Organisator)\s*:?\s*(.{3,100}?)(?=\s+(?:Start der Veranstaltung|Adresse der Veranstaltung|PLZ|Ort|Bundesland|Land|Ende der Veranstaltung)\b|$)", text, re.I)
    if match:
        organizer = re.sub(r"\s+", " ", match.group(1)).strip(" :-")
        if 3 <= len(organizer) <= 100:
            details["organizer"] = organizer
    external_links = []
    for anchor in page.find_all("a", href=True):
        url = urljoin(detail_url, anchor["href"]).split("#", 1)[0]
        parsed = urlsplit(url)
        domain = parsed.netloc.lower().removeprefix("www.")
        if parsed.scheme not in ("http", "https") or not domain or domain == "mittelalterkalender.info":
            continue
        external_links.append(url)
        label = anchor.get_text(" ", strip=True).lower()
        parent_text = anchor.parent.get_text(" ", strip=True).lower() if anchor.parent else ""
        # Only accept links explicitly identified as the event/organizer site.
        if ("veranstaltungsseite" in parent_text or "website des veranstalters" in parent_text
                or "webseite des veranstalters" in parent_text
                or "veranstalterseite" in label):
            details["website"] = url
            break
    # Some calendar templates show the URL in a separate box after the
    # explanatory text. Only use a unique external candidate in that case.
    if not details.get("website") and "veranstaltungsseite" in text.casefold():
        unique = list(dict.fromkeys(external_links))
        if len(unique) == 1:
            details["website"] = unique[0]
    return details


soup = seite_laden(URL)
seiten = [(URL, soup)]
besucht = {URL}
seiten_index = 0

# Der Kalender verlinkt die Europaübersicht für jedes verfügbare Jahr separat.
# Den Links folgen, damit auch neu veröffentlichte Jahresübersichten gefunden werden.
while seiten_index < len(seiten) and len(seiten) < 8:
    basis_url, basis_soup = seiten[seiten_index]
    seiten_index += 1

    for link in basis_soup.find_all("a", href=True):
        label = link.get_text(" ", strip=True).casefold()
        if label not in {"europa", "nach bundesland"}:
            continue

        ziel_url = urljoin(basis_url, link["href"]).split("#", 1)[0]
        ziel = urlsplit(ziel_url)
        host = ziel.netloc.lower().removeprefix("www.")
        if host != "mittelalterkalender.info" or not ziel.path.endswith(".php"):
            continue
        if ziel_url in besucht:
            continue

        besucht.add(ziel_url)
        try:
            seiten.append((ziel_url, seite_laden(ziel_url)))
        except Exception as exc:
            print(f"Mittelalterkalender-Seite nicht erreichbar ({ziel_url}): {exc}")

try:
    with open(
        "herold-funde.json",
        "r",
        encoding="utf-8"
    ) as f:
        funde = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    funde = []

# Bereits fest in der App vorhandene Veranstaltungen laden
app_events = set()
app_events_details = []
try:
    with open("index.html", "r", encoding="utf-8") as f:
        index_text = f.read()

    for block in re.findall(r"\{.*?\}", index_text, re.S):
        name_match = re.search(r'name:\s*["\']([^"\']+)["\']', block)
        start_match = re.search(r'start:\s*["\'](\d{4}-\d{2}-\d{2})["\']', block)
        city_match = re.search(r'city:\s*["\']([^"\']*)["\']', block)

        if name_match and start_match and city_match:
            app_events.add(
                schluessel(
                    name_match.group(1),
                    city_match.group(1),
                    start_match.group(1)
                )
            )
            app_events_details.append({
                "name": name_match.group(1),
                "city": city_match.group(1),
                "start": start_match.group(1)
})

except FileNotFoundError:
    pass

# Bereits vorhandene App-Veranstaltungen aus den Herold-Funden entfernen
def fund_ist_in_app(fund):
    name = str(fund.get("name", ""))
    city = str(fund.get("city", ""))
    start = vorhandenes_startdatum(fund)

    key = schluessel(name, city, start)

    if key in app_events:
        return True

    return any(
        event["start"] == start
        and (
            (
                event["city"].strip().lower() == city.strip().lower()
                and SequenceMatcher(
                    None,
                    event["name"].strip().lower(),
                    name.strip().lower()
                ).ratio() >= 0.60
            )
            or SequenceMatcher(
                None,
                event["name"].strip().lower(),
                name.strip().lower()
            ).ratio() >= 0.90
        )
        for event in app_events_details
    )


funde = [
    fund for fund in funde
    if not fund_ist_in_app(fund)
]
vorhanden = set()

for fund in funde:
    vorhanden.add(
        schluessel(
            str(fund.get("name", "")),
            str(fund.get("city", "")),
            vorhandenes_startdatum(fund)
        )
    )


heute = date.today().isoformat()

neue_funde = []
pro_land = {}


headings = [
    (page_url, heading)
    for page_url, page_soup in seiten
    for heading in page_soup.find_all("h2")
]

for page_url, heading in headings:

    page_path = urlsplit(page_url).path.casefold()
    if "nach-bundesland" in page_path:
        # Die Bundeslandübersicht enthält nur deutsche Veranstaltungen.
        country = "Deutschland"
    else:
        country = heading.get_text(
            " ",
            strip=True
        )

        if country not in LAENDER:
            continue

    # Nicht versehentlich die Tabelle des nächsten Landes übernehmen,
    # wenn dieses Land auf der Seite aktuell keine Veranstaltungen hat.
    section_start = heading.find_next(["h2", "table"])
    if section_start is None or section_start.name != "table":
        continue
    table = section_start

    for row in table.find_all("tr"):

        cells = row.find_all("td")

        if len(cells) < 5:
            continue

        start = datum_lesen(
            cells[0].get_text(" ", strip=True)
        )

        end = datum_lesen(
            cells[1].get_text(" ", strip=True)
        )

        name = cells[2].get_text(
            " ",
            strip=True
        )

        postcode = cells[3].get_text(
            " ",
            strip=True
        )

        city = cells[4].get_text(
            " ",
            strip=True
        )

        if not start or not name or not city:
            continue

        if not end:
            end = start

        # Vergangene Veranstaltungen nicht aufnehmen
        if end < heute:
            continue

        key = schluessel(
            name,
            city,
            start
        )

        if key in vorhanden:
            # Enrich an existing pending fund instead of generating a duplicate.
            existing = next((item for item in funde if schluessel(
                str(item.get("name", "")), str(item.get("city", "")),
                vorhandenes_startdatum(item)) == key), None)
            if existing and (not existing.get("website") or not existing.get("organizer")):
                link = cells[2].find("a", href=True)
                detail_url = urljoin(page_url, link["href"]) if link else ""
                if detail_url and urlsplit(detail_url).netloc.lower().removeprefix("www.") == "mittelalterkalender.info":
                    details = veranstalter_details(detail_url)
                    for field in ("website", "organizer"):
                        if not existing.get(field) and details.get(field):
                            existing[field] = details[field]
                    if not existing.get("source"):
                        existing["source"] = detail_url
            continue
        if key in app_events:
            continue
        # Ähnliche bereits vorhandene App-Veranstaltung erkennen
    
        aehnlich_in_app = any(
            event["start"] == start
            and (
                (
                    event["city"].strip().lower() == city.strip().lower()
                    and SequenceMatcher(
                        None,
                        event["name"].strip().lower(),
                        name.strip().lower()
                    ).ratio() >= 0.60
                )
                or SequenceMatcher(
                    None,
                    event["name"].strip().lower(),
                    name.strip().lower()
                ).ratio() >= 0.90
            )
            for event in app_events_details
        )

        if aehnlich_in_app:
            continue
        raw_id = (
            f"{country}|{name}|{city}|{start}"
        ).encode("utf-8")

        fund_id = (
            "mittelalterkalender-"
            + hashlib.sha1(raw_id).hexdigest()[:16]
        )

        # Extract the actual organizer site from the linked detail page.
        # Never use the calendar's own detail URL as the organizer website.
        detail_anchor = cells[2].find("a", href=True)
        detail_url = urljoin(page_url, detail_anchor["href"]) if detail_anchor else ""
        detail_data = {}
        if detail_url and urlsplit(detail_url).netloc.lower().removeprefix("www.") == "mittelalterkalender.info":
            detail_data = veranstalter_details(detail_url)

        neues_event = {
            "id": fund_id,
            "name": name,
            "type": "Markt",
            "date": f"{start} bis {end}",
            "start": start,
            "end": end,
            "country": country,
            "city": city,
            "postcode": postcode,
            "source": detail_url or page_url,
            **detail_data
        }

        neue_funde.append(neues_event)
        vorhanden.add(key)

        pro_land[country] = (
            pro_land.get(country, 0) + 1
        )


funde.extend(neue_funde)


with open(
    "herold-funde.json",
    "w",
    encoding="utf-8"
) as f:
    json.dump(
        funde,
        f,
        ensure_ascii=False,
        indent=2
    )


print(
    "Mittelalterkalender neue Funde:",
    len(neue_funde)
)

for country in sorted(pro_land):
    print(
        country + ":",
        pro_land[country]
    )

print(
    "Herold-Funde insgesamt:",
    len(funde)
)
