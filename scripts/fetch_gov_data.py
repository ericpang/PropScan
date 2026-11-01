"""Build the static data files that the PropSnap Investor extension reads from GitHub Pages.

Writes to the data/ folder at the repo root:
  hdb_transactions.json  HDB resale and rental medians per town and flat type, plus a street -> town lookup
                         (street names as in the dataset, "TAMPINES ST 41", and spelled out, "TAMPINES STREET 41")
  mrt_stations.json      MRT/LRT station exits (lat/lng) for straight-line distance
  private_psf.json       Private condo PSF and rent medians per URA postal district
                         (built only when URA_ACCESS_KEY is set; otherwise any existing file is left alone)

Environment:
  URA_ACCESS_KEY       URA Data Service AccessKey. Keep it in a GitHub Actions secret, never in the repo
                       or the extension: URA's API Terms of Service require it to stay confidential.
  DATA_GOV_SG_API_KEY  Optional Data.gov.sg API key (higher rate limits than anonymous access).

Usage: python scripts/fetch_gov_data.py [--data-dir DIR] [--site-dir DIR]
  --site-dir also stages the GitHub Pages site there: a copy of the JSON files under data/ plus an
  index.html carrying the licence notices (the workflow deploys that folder).
"""
import argparse
import html
import io
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

SQFT_PER_SQM = 10.7639
HDB_WINDOW_MONTHS = 6   # resale and rental medians cover the latest 6 months present in each dataset
URA_WINDOW_MONTHS = 12  # private transactions: the latest 4 quarters
URA_RENT_PERIODS = 4    # private rentals: the latest 4 quarterly medians

RESALE_ID = "d_8b84c4ee58e3cfc0ece0d773c8ca6abc"  # Resale flat prices, Jan 2017 onwards
RENTAL_ID = "d_c9f57187485a850908655db0e8cfe651"  # Renting Out of Flats, Jan 2021 onwards
MRT_EXITS_ID = "d_b39d3a0871985372d7e1637193335da5"  # LTA MRT Station Exit (GeoJSON)

DGS_DOWNLOAD = "https://api-open.data.gov.sg/v1/public/api/datasets/{id}"
DGS_METADATA = "https://api-production.data.gov.sg/v2/public/api/datasets/{id}/metadata"
DGS_PAUSE = 6  # seconds between Data.gov.sg API calls (anonymous limit: 2 downloads per 10 s)
URA_BASE = "https://eservice.ura.gov.sg/uraDataService"
LICENCE_URL = "https://data.gov.sg/open-data-licence"

# URA postal districts: the first two digits of a postal code (the sector) decide the district.
# Source: URA "List of Postal Districts", https://www.ura.gov.sg/realEstateIIWeb/resources/misc/list_of_postal_districts.htm
DISTRICT_SECTORS = {
    "01": (1, 2, 3, 4, 5, 6), "02": (7, 8), "03": (14, 15, 16), "04": (9, 10), "05": (11, 12, 13),
    "06": (17,), "07": (18, 19), "08": (20, 21), "09": (22, 23), "10": (24, 25, 26, 27),
    "11": (28, 29, 30), "12": (31, 32, 33), "13": (34, 35, 36, 37), "14": (38, 39, 40, 41),
    "15": (42, 43, 44, 45), "16": (46, 47, 48), "17": (49, 50, 81), "18": (51, 52),
    "19": (53, 54, 55, 82), "20": (56, 57), "21": (58, 59), "22": (60, 61, 62, 63, 64),
    "23": (65, 66, 67, 68), "24": (69, 70, 71), "25": (72, 73), "26": (77, 78),
    "27": (75, 76), "28": (79, 80),
}
SECTOR_TO_DISTRICT = {f"{s:02d}": d for d, sectors in DISTRICT_SECTORS.items() for s in sectors}

# Words that HDB abbreviates in street names, with the spelling used on listing sites and by OneMap.
# Checked against every street name in the resale dataset on 1 Nov 2026.
STREET_WORDS = {
    "AVE": "AVENUE", "BT": "BUKIT", "CL": "CLOSE", "CRES": "CRESCENT", "CTRL": "CENTRAL", "DR": "DRIVE",
    "GDNS": "GARDENS", "HTS": "HEIGHTS", "JLN": "JALAN", "KG": "KAMPONG", "LOR": "LORONG", "MKT": "MARKET",
    "NTH": "NORTH", "PK": "PARK", "PL": "PLACE", "RD": "ROAD", "ST": "STREET", "ST.": "SAINT", "STH": "SOUTH",
    "TER": "TERRACE", "TG": "TANJONG", "UPP": "UPPER", "C'WEALTH": "COMMONWEALTH",
}

_last_dgs_call = 0.0


def get_json(url, headers=None, params=None, retries=5):
    """GET a JSON document, backing off on rate limiting (429) and transient server errors."""
    delay = 5
    status = None
    for _ in range(retries):
        resp = requests.get(url, headers=headers, params=params, timeout=60)
        status = resp.status_code
        if status in (429, 500, 502, 503, 504):
            time.sleep(delay)
            delay *= 2
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"Giving up on {url} after {retries} attempts (last HTTP status {status})")


def dgs_get(url):
    """Data.gov.sg API call: spaced out, and sent with an API key when one is configured."""
    global _last_dgs_call
    wait = DGS_PAUSE - (time.monotonic() - _last_dgs_call)
    if wait > 0:
        time.sleep(wait)
    key = os.environ.get("DATA_GOV_SG_API_KEY", "").strip()
    try:
        return get_json(url, headers={"x-api-key": key} if key else None)
    finally:
        _last_dgs_call = time.monotonic()


def dataset_name(dataset_id, fallback):
    try:
        return dgs_get(DGS_METADATA.format(id=dataset_id))["data"]["name"]
    except Exception:  # the name is only used in the attribution text
        return fallback


def download_dataset(dataset_id):
    """Download a Data.gov.sg dataset file (initiate, then poll until a link is returned)."""
    base = DGS_DOWNLOAD.format(id=dataset_id)
    url = None
    for step in ["initiate-download"] + ["poll-download"] * 10:
        url = (dgs_get(f"{base}/{step}").get("data") or {}).get("url")
        if url:
            break
    if not url:
        raise RuntimeError(f"No download link returned for dataset {dataset_id}")
    resp = requests.get(url, timeout=300)
    resp.raise_for_status()
    return resp.content


def expand_street(name):
    """'TAMPINES ST 41' -> 'TAMPINES STREET 41'."""
    return " ".join(STREET_WORDS.get(word, word) for word in name.split())


def write_json(path, payload):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def attribution(dataset_names, source, accessed):
    # Wording follows the example notice in the Singapore Open Data Licence version 1.0.
    return (f"Contains information from {'; '.join(dataset_names)} accessed on {accessed} from {source} "
            f"which is made available under the terms of the Singapore Open Data Licence version 1.0 {LICENCE_URL}")


def month_window(latest, months):
    """['2026-05', ..., '2026-10'] for latest='2026-10' and months=6."""
    end = pd.Period(latest, freq="M")
    return [str(end - i) for i in range(months - 1, -1, -1)]


# --- HDB -------------------------------------------------------------------------------------------

def aggregate_hdb(resale, rental):
    """Median price, PSF and rent per town and flat type over the latest months, plus street -> town."""
    resale = resale.copy()
    resale["resale_price"] = pd.to_numeric(resale["resale_price"])
    resale["psf"] = resale["resale_price"] / (pd.to_numeric(resale["floor_area_sqm"]) * SQFT_PER_SQM)

    # Every street belongs to exactly one town today; if that ever changes keep the most common one.
    street_to_town = resale.groupby("street_name")["town"].agg(lambda s: s.value_counts().idxmax()).to_dict()
    # Add the spelled-out form ("TAMPINES STREET 41") next to the dataset's ("TAMPINES ST 41"), so the
    # extension can look up a scraped address with a plain upper-case match. Ambiguous aliases are dropped.
    aliases = {}
    for street, town in street_to_town.items():
        aliases.setdefault(expand_street(street), set()).add(town)
    for alias, alias_towns in aliases.items():
        if alias not in street_to_town and len(alias_towns) == 1:
            street_to_town[alias] = next(iter(alias_towns))

    resale_window = month_window(resale["month"].max(), HDB_WINDOW_MONTHS)
    towns = {}
    for (town, flat_type), g in resale[resale["month"].isin(resale_window)].groupby(["town", "flat_type"]):
        towns.setdefault(town, {})[flat_type] = {
            "n": len(g),
            "median_price": int(round(g["resale_price"].median())),
            "median_psf": int(round(g["psf"].median())),
        }

    rental = rental.copy()
    rental["monthly_rent"] = pd.to_numeric(rental["monthly_rent"])
    # The rental dataset spells things differently: '4-ROOM' instead of '4 ROOM', 'CENTRAL' instead of 'CENTRAL AREA'.
    rental["flat_type"] = rental["flat_type"].str.replace(r"^(\d)-ROOM$", r"\1 ROOM", regex=True)
    rental["town"] = rental["town"].replace({"CENTRAL": "CENTRAL AREA"})
    rental_window = month_window(rental["rent_approval_date"].max(), HDB_WINDOW_MONTHS)
    recent_rent = rental[rental["rent_approval_date"].isin(rental_window)]
    for (town, flat_type), g in recent_rent.groupby(["town", "flat_type"]):
        entry = towns.get(town, {}).get(flat_type)
        if entry:
            entry["median_rent"] = int(round(g["monthly_rent"].median()))
            entry["rent_n"] = len(g)

    return towns, street_to_town, resale_window, rental_window


def build_hdb(data_dir, accessed):
    resale = pd.read_csv(io.BytesIO(download_dataset(RESALE_ID)), dtype=str)
    rental = pd.read_csv(io.BytesIO(download_dataset(RENTAL_ID)), dtype=str)
    towns, street_to_town, resale_window, rental_window = aggregate_hdb(resale, rental)
    resale_name = dataset_name(RESALE_ID, "Resale flat prices based on registration date from Jan-2017 onwards")
    rental_name = dataset_name(RENTAL_ID, "Renting Out of Flats from Jan 2021")
    write_json(data_dir / "hdb_transactions.json", {
        "meta": {
            "generated_on": accessed,
            "resale": {"dataset_id": RESALE_ID, "name": resale_name,
                       "months": [resale_window[0], resale_window[-1]], "source_rows": len(resale)},
            "rental": {"dataset_id": RENTAL_ID, "name": rental_name,
                       "months": [rental_window[0], rental_window[-1]], "source_rows": len(rental)},
            "attribution": attribution([resale_name, rental_name], "Data.gov.sg (Housing & Development Board)", accessed),
        },
        "street_to_town": street_to_town,
        "towns": towns,
    })
    groups = sum(len(v) for v in towns.values())
    print(f"hdb_transactions.json: {len(towns)} towns, {groups} town/flat-type groups, "
          f"{len(street_to_town)} street keys (resale {resale_window[0]}..{resale_window[-1]}, "
          f"rental {rental_window[0]}..{rental_window[-1]})")


# --- MRT -------------------------------------------------------------------------------------------

def aggregate_mrt(geojson):
    """Group the LTA exit points by station: [{name, type, exits: [[code, lat, lng], ...]}, ...]."""
    stations = {}
    for feature in geojson["features"]:
        props = feature["properties"]
        lng, lat = feature["geometry"]["coordinates"][:2]
        raw = props["STATION_NA"].strip()
        kind = "LRT" if raw.endswith(" LRT STATION") else "MRT"
        name = raw.removesuffix(" MRT STATION").removesuffix(" LRT STATION")
        code = props["EXIT_CODE"].strip().removeprefix("Exit ").strip()
        stations.setdefault((name, kind), []).append([code, round(lat, 5), round(lng, 5)])
    return [{"name": n, "type": k, "exits": sorted(e)} for (n, k), e in sorted(stations.items())]


def build_mrt(data_dir, accessed):
    stations = aggregate_mrt(json.loads(download_dataset(MRT_EXITS_ID)))
    name = dataset_name(MRT_EXITS_ID, "LTA MRT Station Exit (GEOJSON)")
    write_json(data_dir / "mrt_stations.json", {
        "meta": {
            "generated_on": accessed,
            "dataset_id": MRT_EXITS_ID,
            "name": name,
            "attribution": attribution([name], "Data.gov.sg (Land Transport Authority)", accessed),
        },
        "stations": stations,
    })
    exits = sum(len(s["exits"]) for s in stations)
    print(f"mrt_stations.json: {len(stations)} stations, {exits} exits")


# --- Private property (URA) ------------------------------------------------------------------------

def aggregate_private(projects, rent_projects):
    """Median PSF per URA district (all / freehold / leasehold) and median rent PSF per district."""
    rows = [{"project": p["project"], **t} for p in projects for t in p.get("transaction", [])]
    if not rows:
        raise RuntimeError("URA returned no private transactions")
    df = pd.DataFrame(rows)

    # Condos and apartments only, resales and sub sales only (new-sale prices are developer prices),
    # and single-unit caveats only so that price and area describe the same unit.
    df = df[df["propertyType"].isin(["Condominium", "Apartment"])
            & (df["typeOfArea"] == "Strata")
            & df["typeOfSale"].isin(["2", "3"])]
    df = df.assign(
        area=pd.to_numeric(df["area"]),
        price=pd.to_numeric(df["price"]),
        units=pd.to_numeric(df["noOfUnits"]),
        month="20" + df["contractDate"].str[2:4] + "-" + df["contractDate"].str[0:2],  # contractDate is MMYY
        district=df["district"].str.zfill(2),
    )
    df = df[(df["units"] == 1) & (df["area"] > 0) & (df["price"] > 0)].copy()
    df["psf"] = df["price"] / (df["area"] * SQFT_PER_SQM)  # URA area is in square metres
    long_lease = df["tenure"].str.match(r"^(999|9999) yrs").fillna(False).astype(bool)  # behaves like freehold
    df["tenure_class"] = ((df["tenure"] == "Freehold") | long_lease).map({True: "freehold", False: "leasehold"})

    window = month_window(df["month"].max(), URA_WINDOW_MONTHS)
    df = df[df["month"].isin(window)]

    def stats(g):
        return {"n": len(g), "median_psf": int(round(g["psf"].median()))}

    districts = {}
    for district, g in df.groupby("district"):
        entry = {"all": stats(g)}
        for tenure_class, gc in g.groupby("tenure_class"):
            entry[tenure_class] = stats(gc)
        districts[district] = entry

    # PMI_Resi_Rental_Median gives rent per sq ft per month for each project and quarter ("2026Q2").
    rent_rows = [{"district": str(r["district"]).zfill(2), "period": r["refPeriod"], "median": float(r["median"])}
                 for p in rent_projects for r in p.get("rentalMedian", [])]
    periods = []
    if rent_rows:
        rdf = pd.DataFrame(rent_rows)
        periods = sorted(rdf["period"].unique())[-URA_RENT_PERIODS:]
        for district, g in rdf[rdf["period"].isin(periods)].groupby("district"):
            if district in districts:
                districts[district]["median_rent_psf"] = round(float(g["median"].median()), 2)
                districts[district]["rent_n"] = len(g)
    return districts, window, periods


def ura_get(path, access_key, token=None, params=None):
    headers = {"AccessKey": access_key}
    if token:
        headers["Token"] = token
    body = get_json(f"{URA_BASE}/{path}", headers=headers, params=params)
    if body.get("Status") != "Success":
        raise RuntimeError(f"URA {path} failed: {body.get('Message') or body.get('Status')!r}")
    return body["Result"]


def build_private(data_dir, accessed, access_key):
    token = ura_get("insertNewToken/v1", access_key)  # the token is valid for the day
    projects = []
    for batch in (1, 2, 3, 4):  # the transaction data is split into 4 batches of postal districts
        projects.extend(ura_get("invokeUraDS/v1", access_key, token,
                                {"service": "PMI_Resi_Transaction", "batch": batch}))
    rent_projects = ura_get("invokeUraDS/v1", access_key, token, {"service": "PMI_Resi_Rental_Median"})
    districts, window, periods = aggregate_private(projects, rent_projects)
    write_json(data_dir / "private_psf.json", {
        "meta": {
            "generated_on": accessed,
            "transactions": {"service": "PMI_Resi_Transaction", "months": [window[0], window[-1]],
                             "scope": "condominiums and apartments, strata, resale and sub sale, single-unit caveats"},
            "rentals": {"service": "PMI_Resi_Rental_Median", "periods": periods,
                        "note": "median of project-level quarterly medians, SGD per sq ft per month"},
            "attribution": attribution(
                ["URA Data Service API: Private Residential Properties Transactions and Median Rentals"],
                "the Urban Redevelopment Authority", accessed),
        },
        "sector_to_district": SECTOR_TO_DISTRICT,
        "districts": districts,
    })
    print(f"private_psf.json: {len(districts)} districts (transactions {window[0]}..{window[-1]})")


def write_site(data_dir, site_dir):
    """Stage the GitHub Pages site: the JSON files under data/ plus an index page with the licence notices."""
    out = site_dir / "data"
    out.mkdir(parents=True, exist_ok=True)
    links, notices = [], []
    for path in sorted(data_dir.glob("*.json")):
        shutil.copy2(path, out / path.name)
        links.append(f'<li><a href="data/{path.name}">{path.name}</a></li>')
        notice = json.loads(path.read_text(encoding="utf-8")).get("meta", {}).get("attribution")
        if notice:
            linked = html.escape(notice).replace(LICENCE_URL, f'<a href="{LICENCE_URL}">{LICENCE_URL}</a>')
            notices.append(f"<p>{linked}</p>")
    (site_dir / "index.html").write_text(
        '<!doctype html>\n<meta charset="utf-8">\n<title>PropSnap Investor data</title>\n'
        "<h1>PropSnap Investor data files</h1>\n"
        "<p>Static JSON read by the PropSnap Investor browser extension, regenerated monthly from "
        "Singapore Government open data.</p>\n"
        f"<ul>\n{chr(10).join(links)}\n</ul>\n{chr(10).join(notices)}\n"
        "<p>This site and the extension are not endorsed by, or affiliated with, any Singapore Government agency.</p>\n",
        encoding="utf-8")
    print(f"site staged in {site_dir}: {len(links)} data files")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the static data files for PropSnap Investor.")
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent.parent / "data")
    parser.add_argument("--site-dir", type=Path, help="also stage the GitHub Pages site in this folder")
    args = parser.parse_args(argv)
    args.data_dir.mkdir(parents=True, exist_ok=True)
    accessed = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    build_hdb(args.data_dir, accessed)
    build_mrt(args.data_dir, accessed)

    access_key = os.environ.get("URA_ACCESS_KEY", "").strip()
    if access_key:
        build_private(args.data_dir, accessed, access_key)
    else:
        print("URA_ACCESS_KEY is not set: skipping private_psf.json (any existing file is left untouched)")

    if args.site_dir:
        write_site(args.data_dir, args.site_dir)


if __name__ == "__main__":
    main()
