import hashlib
import json
import re
import urllib.request
from difflib import SequenceMatcher
from datetime import date, datetime
from urllib.parse import urljoin, urlsplit

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

        if key in vorhanden or key in app_events:
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
            "source": page_url
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
