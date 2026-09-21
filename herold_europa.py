import hashlib
import json
import re
import urllib.request
from datetime import date, datetime

from bs4 import BeautifulSoup


URL = "https://www.mittelalterkalender.info/mittelaltermarkt/mittelaltermaerkte-europa.php"

LAENDER = {
    "Belgien",
    "Dänemark",
    "Frankreich",
    "Italien",
    "Luxemburg",
    "Niederlande",
    "Österreich",
    "Polen",
    "Schweden",
    "Schweiz",
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


req = urllib.request.Request(
    URL,
    headers={
        "User-Agent": "Mozilla/5.0 Rabenruf-Herold/1.0"
    }
)

html = urllib.request.urlopen(
    req,
    timeout=30
).read()

soup = BeautifulSoup(html, "html.parser")

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

except FileNotFoundError:
    pass

# Bereits vorhandene App-Veranstaltungen aus den Herold-Funden entfernen
funde = [
    fund for fund in funde
    if schluessel(
        str(fund.get("name", "")),
        str(fund.get("city", "")),
        vorhandenes_startdatum(fund)
    ) not in app_events
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


for heading in soup.find_all("h2"):

    country = heading.get_text(
        " ",
        strip=True
    )

    if country not in LAENDER:
        continue

    table = heading.find_next("table")

    if table is None:
        continue

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
            "source": URL
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
