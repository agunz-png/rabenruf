import hashlib
import json
import re
import unicodedata
import urllib.request
from datetime import date, datetime
from difflib import SequenceMatcher

from bs4 import BeautifulSoup


VEHI_BASE = "https://vehi-mercatus.fr/calendrier-des-marches/"
MIRIMOR_URL = "https://www.mirimor.ch/kalender/"
USER_AGENT = "Mozilla/5.0 Rabenruf-Herold/1.0"
MONTHS = {
    "janvier": 1, "januar": 1, "février": 2, "februar": 2,
    "mars": 3, "märz": 3, "avril": 4, "april": 4,
    "mai": 5, "juin": 6, "juni": 6, "juillet": 7, "juli": 7,
    "août": 8, "august": 8, "septembre": 9, "september": 9,
    "octobre": 10, "oktober": 10, "novembre": 11, "november": 11,
    "décembre": 12, "dezember": 12,
}
ROMANDIE_CANTONS = {"GE", "VD", "NE", "JU", "FR", "VS"}
ITALIAN_REGIONS = {
    "abruzzo", "basilicata", "calabria", "campania", "emilia romagna",
    "friuli venezia giulia", "lazio", "liguria", "lombardia", "marche",
    "molise", "piemonte", "puglia", "sardegna", "sicilia", "toscana",
    "trentino alto adige", "umbria", "valle d'aosta", "veneto",
}
FRENCH_REGIONS = {
    "auvergne rhone alpes", "bourgogne franche comte", "bretagne",
    "centre val de loire", "corse", "grand est", "hauts de france",
    "ile de france", "normandie", "nouvelle aquitaine", "occitanie",
    "pays de la loire", "provence alpes cote d azur",
}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=40) as response:
        return response.read().decode("utf-8", errors="ignore")


def plain(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    value = unicodedata.normalize("NFKD", plain(value).lower())
    return "".join(c for c in value if not unicodedata.combining(c))


def parse_iso(value):
    if not value:
        return ""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return str(value)[:10] if re.match(r"^20\d{2}-\d{2}-\d{2}$", str(value)) else ""


def event_record(name, city, country, start, end, source, postcode=""):
    name, city = plain(name), plain(city)
    if not name or not city or not start:
        return None
    raw_id = f"{country}|{name}|{city}|{start}|{source}".encode("utf-8")
    return {
        "id": "eu-source-" + hashlib.sha1(raw_id).hexdigest()[:16],
        "name": name[:180],
        "type": "Markt",
        "date": f"{start} bis {end or start}",
        "start": start,
        "end": end or start,
        "country": country,
        "city": city[:100],
        "postcode": plain(postcode),
        "source": source,
    }


def jsonld_events(soup, source):
    found = []

    def visit(obj):
        if isinstance(obj, list):
            for item in obj:
                visit(item)
            return
        if not isinstance(obj, dict):
            return
        types = obj.get("@type", [])
        if isinstance(types, str):
            types = [types]
        if any(t.lower() == "event" for t in types):
            location = obj.get("location") or {}
            if isinstance(location, list):
                location = location[0] if location else {}
            address = location.get("address") or {}
            if isinstance(address, str):
                address = {"streetAddress": address}
            country_obj = address.get("addressCountry") or location.get("addressCountry") or ""
            if isinstance(country_obj, dict):
                country_obj = country_obj.get("name", "")
            country = str(country_obj).strip()
            mapping = {"FR": "Frankreich", "France": "Frankreich", "IT": "Italien",
                       "Italy": "Italien", "CH": "Schweiz", "Switzerland": "Schweiz",
                       "Suisse": "Schweiz"}
            country = mapping.get(country, country)
            start = parse_iso(obj.get("startDate"))
            end = parse_iso(obj.get("endDate")) or start
            city = address.get("addressLocality") or location.get("name") or ""
            name = obj.get("name") or ""
            if country in {"Frankreich", "Italien", "Schweiz"}:
                item = event_record(name, city, country, start, end,
                                    obj.get("url") or source,
                                    address.get("postalCode", ""))
                if item:
                    found.append(item)
        for key in ("@graph", "itemListElement", "mainEntity", "events"):
            if key in obj:
                visit(obj[key])

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            visit(json.loads(script.string or script.get_text()))
        except (json.JSONDecodeError, TypeError):
            continue
    return found


def vehi_date(text):
    # Formats include 11.–13.09.2026 and 30.07.–01.08.2027.
    cross_month = re.search(
        r"(?P<d1>\d{1,2})\.(?P<m1>\d{1,2})\.\s*[–—-]\s*"
        r"(?P<d2>\d{1,2})\.(?P<m2>\d{1,2})\.(?P<y>20\d{2})",
        text,
    )
    if cross_month:
        try:
            year = int(cross_month.group("y"))
            return (
                date(year, int(cross_month.group("m1")), int(cross_month.group("d1"))).isoformat(),
                date(year, int(cross_month.group("m2")), int(cross_month.group("d2"))).isoformat(),
            )
        except ValueError:
            return "", ""
    m = re.search(
        r"(?P<d1>\d{1,2})\.?\s*(?:[–—-]\s*(?P<d2>\d{1,2})\.)?"
        r"(?P<m1>\d{1,2})\.(?:(?P<m2>\d{1,2})\.)?(?P<y>20\d{2})",
        text,
    )
    if not m:
        return "", ""
    d1 = int(m.group("d1"))
    d2 = int(m.group("d2") or d1)
    month1 = int(m.group("m1"))
    month2 = int(m.group("m2") or month1)
    year = int(m.group("y"))
    try:
        return date(year, month1, d1).isoformat(), date(year, month2, d2).isoformat()
    except ValueError:
        return "", ""

def country_from_vehi(text, postal):
    t = norm(text)
    # Region names/codes outrank postal length: some Italian postcodes lose
    # their leading zero in third-party calendars (e.g. 6024 Gubbio).
    if any(region in t for region in ITALIAN_REGIONS) or re.search(
        r"\b(?:umb|tos|sic|fri|ven|pie|cam|pug|lom|laz|sar|mar|lig|cal|abr|emi|mol|bas|val)(?:\.|\b)", t
    ) or any(city in t for city in (
        "foligno", "gubbio", "altamura", "cividale del friuli", "venezia",
        "firenze", "siena", "bologna", "milano", "bergamo", "napoli",
        "lecce", "torino", "verona", "civita di bagnoregio",
    )) or "italia" in t or "italy" in t or "italien" in t:
        return "Italien"
    if any(region in t for region in FRENCH_REGIONS) or re.search(
        r"\b(?:bret|norm|occ|als|bre|idf|naq|pdl|ara|ges|hdf|cor)(?:\.|\b)", t
    ) or "france" in t or "frankreich" in t:
        return "Frankreich"
    if re.search(r"\b(?:suisse|switzerland|schweiz|swiss)\b", t) or re.search(r"\b\d{4}\s+[\wÀ-ÿ]", text):
        return "Schweiz"
    if re.search(r"\bfr\b", t) and postal and len(postal) == 5:
        return "Frankreich"
    return ""

def scrape_vehi():
    results = []
    today_year = date.today().year
    # The annual Vehi pages expose the whole Europe list for each year.
    for year in range(today_year, today_year + 3):
        url = f"{VEHI_BASE}{year}/"
        try:
            soup = BeautifulSoup(fetch(url), "html.parser")
        except Exception as exc:
            print(f"Vehi Mercatus {year}: Abruf fehlgeschlagen: {exc}")
            continue

        year_results = jsonld_events(soup, url)
        for link in soup.find_all("a", href=True):
            label = plain(link.get_text(" ", strip=True))
            if not label:
                continue
            start, end = vehi_date(label)
            if not start or (end or start) < date.today().isoformat():
                continue
            # Ignore navigation links and require a plausible event date/name.
            date_match = re.search(
                r"\d{1,2}\.?\s*(?:[–—-]\s*\d{1,2}\.)?\d{1,2}\.(?:\d{1,2}\.)?20\d{2}",
                label,
            )
            if not date_match:
                continue
            remainder = plain(label[date_match.end():])
            postal_match = re.search(r"\b(\d{4,5})\s+([^,]+)", remainder)
            postal = postal_match.group(1) if postal_match else ""
            city = postal_match.group(2).strip() if postal_match else ""
            if city:
                city = re.split(
                    r"\s+(?:marché|fête|festival|tournoi|spectacle|mittelalter|medieval)\b",
                    city,
                    maxsplit=1,
                    flags=re.I,
                )[0].strip(" ,–-")
            if not city:
                # Some French/Italian entries have no postal code in the list.
                tail = re.split(r"\s+(?:Marché|Fête|Festival|Tournoi|Spectacle)\b", remainder)
                city = tail[-1].strip(" ,") if len(tail) > 1 else ""
            country = country_from_vehi(remainder, postal)
            if not country or not city:
                continue
            name = remainder[:postal_match.start()].strip(" ,–-") if postal_match else remainder
            if not name or len(name) < 4:
                continue
            source = link["href"]
            if source.startswith("/"):
                source = "https://vehi-mercatus.fr" + source
            item = event_record(name, city, country, start, end, source, postal)
            if item:
                year_results.append(item)

        # De-duplicate schema markup and listing rows.
        unique = {}
        for item in year_results:
            unique[(item["name"].lower(), item["city"].lower(), item["start"])] = item
        results.extend(unique.values())
        print(f"Vehi Mercatus {year}: {len(unique)} Funde")
    return results


def month_context(text, year, month):
    normalized = norm(text)
    year_match = re.search(r"\b(20\d{2})\b", normalized)
    if year_match:
        year = int(year_match.group(1))
    for name, number in MONTHS.items():
        if re.search(rf"\b{re.escape(norm(name))}\b", normalized):
            month = number
            break
    return year, month


def mirimor_date(text, year, month):
    text = plain(text)
    # Examples: 25-27.09, 30.10-01.11, 10.10, 05, 12, 18, 19.
    m = re.search(
        r"(?<!\d)(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?\.(\d{1,2})"
        r"(?:\s*[-–]\s*(\d{1,2})\.(\d{1,2}))?(?:\.(20\d{2}))?",
        text,
    )
    if m:
        d1 = int(m.group(1))
        d2 = int(m.group(2) or m.group(1))
        m1 = int(m.group(3) or month)
        d3 = int(m.group(4) or d2)
        m2 = int(m.group(5) or m1)
        yr = int(m.group(6) or year)
        try:
            return date(yr, m1, d1).isoformat(), date(yr, m2, d3).isoformat()
        except ValueError:
            return "", ""
    # Occasionally Mirimor lists several isolated days, e.g. "05, 12, 18, 19".
    day = re.match(r"^\s*(\d{1,2})\s*$", text)
    if day and year and month:
        try:
            value = date(year, month, int(day.group(1))).isoformat()
            return value, value
        except ValueError:
            pass
    return "", ""


def mirimor_canton(text):
    upper = text.upper()
    for canton in ROMANDIE_CANTONS:
        if re.search(rf"\b{canton}\b", upper):
            return canton
    # Entries may use a postal code and a well-known Romandie locality without
    # displaying the canton abbreviation.
    places = {
        "grandson", "buttes", "neuchatel", "neuchâtel", "geneve", "genève",
        "lausanne", "montreux", "vevey", "nyon", "sion", "martigny",
        "fribourg", "bulle", "st-ursanne", "saint-ursanne", "le landeron",
        "biel/nidau", "biel/bienne", "nidau", "yverdon",
    }
    normalized = norm(text)
    return "Romandie" if any(norm(place) in normalized for place in places) else ""


def scrape_mirimor():
    try:
        soup = BeautifulSoup(fetch(MIRIMOR_URL), "html.parser")
    except Exception as exc:
        print(f"Mirimor: Abruf fehlgeschlagen: {exc}")
        return []

    results = jsonld_events(soup, MIRIMOR_URL)
    year, month = date.today().year, date.today().month
    seen_text = set()

    # Walk visible text in document order so month/year headings provide context.
    for node in soup.find_all(string=True):
        value = plain(node)
        if not value:
            continue
        if re.search(r"20\d{2}", value) or any(norm(m) in norm(value) for m in MONTHS):
            year, month = month_context(value, year, month)
        start, end = mirimor_date(value, year, month)
        if not start:
            continue

        # Select the smallest card/container that has one date and its location.
        container = node.parent
        for _ in range(5):
            if not container or not getattr(container, "get_text", None):
                break
            text = plain(container.get_text(" ", strip=True))
            date_count = len(re.findall(
                r"\b\d{1,2}(?:\s*[-–]\s*\d{1,2})?\.\d{1,2}(?:\.20\d{2})?",
                text,
            ))
            if date_count == 1 and len(text) <= 900 and mirimor_canton(text):
                break
            container = container.parent
        if not container:
            continue
        block = plain(container.get_text(" ", strip=True))
        if block in seen_text or not mirimor_canton(block):
            continue
        seen_text.add(block)
        # Derive event title and city from the location/canton text.
        parts = [plain(x) for x in container.stripped_strings if plain(x)]
        parts = [p for p in parts if not re.fullmatch(r"(?:Sonstiges|Markt|Image)", p, re.I)]
        title = ""
        for part in parts:
            if part == value or mirimor_date(part, year, month)[0]:
                continue
            if any(word in norm(part) for word in (
                "markt", "march", "medieval", "mittelalter", "spectacle",
                "spektakel", "fete", "festival", "tournoi", "handwerker",
            )):
                title = part
                break
        if not title:
            title = next((p for p in parts if len(p) > 8 and not re.search(r"\b\d{4}\b", p)), "")
        canton = mirimor_canton(block)
        location_line = next(
            (p for p in parts if re.search(r"\b(?:GE|VD|NE|JU|FR|VS)\b", p, re.I)),
            "",
        )
        if location_line:
            city = re.sub(r"\b\d{4}\b", "", location_line)
            city = re.sub(r"\b(?:GE|VD|NE|JU|FR|VS)\b", "", city, flags=re.I)
            city = plain(re.sub(r"^[,\s]+|[,\s]+$", "", city))
            city = city.split(",")[-1].strip() if "," in city else city
        else:
            places = (
                "Grandson", "Buttes", "Neuchâtel", "Genève", "Lausanne", "Montreux",
                "Vevey", "Nyon", "Sion", "Martigny", "Fribourg", "Bulle",
                "Saint-Ursanne", "Le Landeron", "Biel/Nidau", "Yverdon",
            )
            city = next((place for place in places if norm(place) in norm(block)), "")
        if not title or not city:
            continue
        item = event_record(title, city, "Schweiz", start, end, MIRIMOR_URL)
        if item and (item["end"] or item["start"]) >= date.today().isoformat():
            results.append(item)

    unique = {}
    for item in results:
        unique[(item["name"].lower(), item["city"].lower(), item["start"])] = item
    print(f"Mirimor Romandie: {len(unique)} Funde")
    return list(unique.values())


def event_key(item):
    return (
        norm(item.get("name", "")),
        norm(item.get("city", "")),
        item.get("start", ""),
    )


def already_present(candidate, existing):
    name = norm(candidate.get("name", ""))
    city = norm(candidate.get("city", ""))
    for item in existing:
        if event_key(candidate) == event_key(item):
            return True
        if candidate.get("start") != item.get("start"):
            continue
        other_name = norm(item.get("name", ""))
        other_city = norm(item.get("city", ""))
        if (city == other_city and SequenceMatcher(None, name, other_name).ratio() >= 0.60):
            return True
        if SequenceMatcher(None, name, other_name).ratio() >= 0.90:
            return True
    return False


def main():
    try:
        with open("herold-funde.json", "r", encoding="utf-8") as handle:
            existing = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    new_events = []
    for candidate in scrape_vehi() + scrape_mirimor():
        if (candidate.get("end") or candidate.get("start") or "9999-12-31") < date.today().isoformat():
            continue
        if not already_present(candidate, existing + new_events):
            new_events.append(candidate)

    existing.extend(new_events)
    with open("herold-funde.json", "w", encoding="utf-8") as handle:
        json.dump(existing, handle, ensure_ascii=False, indent=2)

    print("Neue Funde aus Vehi Mercatus und Mirimor:", len(new_events))


if __name__ == "__main__":
    main()
