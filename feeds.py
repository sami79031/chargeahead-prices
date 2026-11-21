#!/usr/bin/env python3
"""Builds per-area price files from open OCPI feeds, for the ChargeAhead
backend to match to its stations.

    python3 feeds.py build OUT_DIR [--only nl|de] [--from-files NDW_DIR]

Sources (checked 2026-11-21):

- Netherlands: NDW open data, CC0 (attribution not required):
  https://opendata.ndw.nu/charging_point_{locations,tariffs}_ocpi.json.gz
- Germany: MobiData BW OCPDB, which merges the Mobilithek AFIR feeds:
  https://api.mobidata-bw.de/ocpdb/api/public/ocpi/2.2/{locations,tariffs}
  Dataset licence Datenlizenz Deutschland BY 2.0; each source has its own
  (`/v1/sources`): CC BY 4.0 sources are credited by name, a source with no
  licence is left out.

Output, one file per 0.2° x 0.2° area (`ocpi/<row>_<col>.json`, row =
floor(lat / 0.2), col = floor(lon / 0.2)) plus `ocpi/index.json`:

    {"cell": "261_24", "importedAt": "...",
     "sources": ["NDW"],                     # credit shown with a price
     "operators": ["EFL"],
     "rates": [[dc, minKw, maxKw, kwhMin, kwhMax, perMin, perSession]],
     "rateSets": [[0, 1]],
     "sites": [[lat, lon, operator, rateSet, source, "2026-11-09", "EUR"]]}

`dc` is 1, 0 or null (any plug); prices include VAT; perMin and perSession
are null when nothing is charged for them. Only prices for paying at the
charger count: OCPI tariffs typed AD_HOC_PAYMENT, or untyped (OCPI: for
every payment). Blocking fees (time charged only after a duration) and
parking are left out. Standard library only.
"""

import argparse
import datetime as dt
import gzip
import json
import math
import sys
import time
import urllib.request
from pathlib import Path

CELL = 0.2
NDW = "https://opendata.ndw.nu/"
OCPDB = "https://api.mobidata-bw.de/ocpdb/api/public/"
UA = {"User-Agent": "chargeahead-prices/1.0 (+https://github.com/sami79031/chargeahead-prices)"}
MAX_PER_KWH = 5.0   # euros: above this a feed has a unit error, not a price


def get(url, tries=4):
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                data = r.read()
            return gzip.decompress(data) if url.endswith(".gz") else data
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(5 * (attempt + 1))


def ocpdb_all(path):
    items, offset = [], 0
    while True:
        page = json.loads(get(f"{OCPDB}{path}{'&' if '?' in path else '?'}limit=1000&offset={offset}"))
        items += page.get("items", [])
        nxt = page.get("next_offset")
        if not nxt or nxt <= offset or not page.get("items"):
            return items
        offset = nxt


# ---------------------------------------------------------------- tariffs

def with_vat(component):
    """A price component's price with VAT, or None when the feed doesn't say
    what VAT applies: OCPI 2.2 says a missing `vat` means none, but most of
    NDW's components leave it out on prices that look like they exclude
    it, and a price 21% too low is worse than none. Reads OCPI 2.2 `vat`
    (percent; 0.21 read as 21%) and OCPDB's `taxes` with `tax_included`."""
    price = float(component.get("price") or 0)
    if price == 0:
        return 0.0
    if "taxes" in component:
        if component.get("tax_included"):
            return price
        taxes = [t for t in component.get("taxes") or []
                 if str(t.get("name", "VAT")).upper() in ("VAT", "BTW", "MWST", "UST", "USTR", "TVA")]
        if not taxes:
            return None
        return price * (1 + sum(float(t.get("percentage") or 0) for t in taxes) / 100)
    vat = component.get("vat")
    if not isinstance(vat, (int, float)) or isinstance(vat, bool):
        return None
    pct = vat * 100 if 0 < vat < 1 else vat
    return price * (1 + pct / 100)


def conditional(restrictions):
    """Whether an element only applies after a duration, or to parking,
    reservations: blocking fees and the like, not the price of charging."""
    r = restrictions or {}
    return any(r.get(k) for k in ("min_duration", "reservation", "min_kwh"))


def tariff_rate(tariff):
    """(kwh_min, kwh_max, per_min, per_session, min_kw, max_kw) for a
    tariff, or None when it isn't a pay-at-the-charger energy price."""
    if tariff.get("type") not in (None, "AD_HOC_PAYMENT"):
        return None
    energy, minutes, flats, bands = [], [], [], set()
    for el in tariff.get("elements") or []:
        r = el.get("restrictions") or {}
        if conditional(r):
            continue
        for c in el.get("price_components") or []:
            kind = c.get("type")
            if kind not in ("ENERGY", "TIME", "FLAT"):
                continue
            price = with_vat(c)
            if price is None:
                return None   # VAT unknown: no price rather than a wrong one
            if kind == "ENERGY":
                energy.append(price)
                bands.add(power_band(r))
            elif kind == "TIME":
                minutes.append(price / 60)   # OCPI TIME is per hour
            else:
                flats.append(price)
    energy = [e for e in energy if 0 < e < MAX_PER_KWH]
    if not energy:
        return None
    # One band only when every energy price has the same one; prices for
    # several bands become one range over all plugs.
    lo_kw, hi_kw = bands.pop() if len(bands) == 1 else (None, None)
    per_min = max(minutes) if minutes and max(minutes) > 0 else None
    per_session = max(flats) if flats and max(flats) > 0 else None
    return (round(min(energy), 4), round(max(energy), 4),
            None if per_min is None else round(per_min, 4),
            None if per_session is None else round(per_session, 2), lo_kw, hi_kw)


def power_band(restrictions):
    """(min_kw, max_kw) from an element's restrictions; a 0 or a band that
    is upside down counts as none."""
    def kw(v):
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None
    lo, hi = kw(restrictions.get("min_power")), kw(restrictions.get("max_power"))
    if lo is not None and hi is not None and lo > hi:
        return (None, None)
    return (lo, hi)


def is_dc(connector):
    pt = str(connector.get("power_type") or "")
    return None if not pt else pt == "DC"


def day(stamp):
    try:
        return dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------- sites

# Each feed's country, roughly: a site outside it is a bad coordinate (or
# a foreign site the feed lists) and is left out.
BOXES = {"NL": (50.7, 53.7, 3.2, 7.3), "DE": (47.2, 55.1, 5.8, 15.1)}


def in_box(lat, lon, box):
    s, n, w, e = box
    return s <= lat <= n and w <= lon <= e


def sites_of(locations, tariffs, source_of, skip_sources=(), evse_tariffs=None, box=None):
    """One site per location with at least one priced connector:
    (lat, lon, operator, rates, source, checked, currency). A connector's
    tariff is found through [evse_tariffs] (EVSE uid -> tariff, OCPI 3.0
    tariff associations) when given, else through its `tariff_ids`."""
    out = []
    for loc in locations:
        src = source_of(loc)
        if src is None or loc.get("source") in skip_sources:
            continue
        coords = loc.get("coordinates") or {}
        try:
            lat, lon = float(coords["latitude"]), float(coords["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if box and not in_box(lat, lon, box):
            continue
        groups = set()   # (dc, rate)
        checked, currency = None, None
        for evse in loc.get("evses") or []:
            by_evse = (evse_tariffs or {}).get(evse.get("uid"))
            for con in evse.get("connectors") or []:
                for tid in ([None] if by_evse else con.get("tariff_ids") or []):
                    t = by_evse or tariffs.get(tid)
                    rate = t and tariff_rate(t)
                    if not rate:
                        continue
                    currency = currency or t.get("currency")
                    d = day(t.get("last_updated"))
                    checked = max(filter(None, [checked, d]), default=None)
                    groups.add((is_dc(con), rate))
                    break
        if not groups or not checked or not currency:
            continue
        rates = []
        for dc, (lo, hi, per_min, per_session, min_kw, max_kw) in groups:
            # The band is the tariff's own power restriction only: a plug's
            # rating differs between feeds and TomTom (11 vs 22 kW).
            rates.append([None if dc is None else int(dc), min_kw, max_kw, lo, hi, per_min, per_session])
        operator = ((loc.get("operator") or {}).get("name") or loc.get("party_id") or "").strip()
        out.append((round(lat, 5), round(lon, 5), operator, sorted(rates, key=str), src, checked, currency))
    return out


def ndw(from_dir=None):
    def load(name):
        if from_dir:
            return json.loads(gzip.decompress((Path(from_dir) / name).read_bytes()))
        return json.loads(get(NDW + name))
    tariffs = {t["id"]: t for t in load("charging_point_tariffs_ocpi.json.gz") if "id" in t}
    locations = load("charging_point_locations_ocpi.json.gz")
    return sites_of(locations, tariffs, lambda loc: "NDW", box=BOXES["NL"])


def ocpdb():
    sources = {s["uid"]: s for s in json.loads(get(OCPDB + "v1/sources?limit=1000")).get("items", [])}

    def label(uid):
        s = sources.get(uid)
        if not s or not s.get("attribution_license"):
            return None   # no licence: not ours to use
        name = s.get("attribution_contributor") or s.get("name") or uid
        lic = s.get("attribution_license")
        own = "" if lic in ("cc-zero", "cc0", "cc0/1.0") else f" ({lic.upper().replace('/', ' ')})"
        return f"MobiData BW (dl-de/by-2-0) · {name}{own}"

    # OCPI 3.0: tariffs, and associations saying which EVSEs each applies
    # to and for whom (the 2.2 view's connector tariff_ids don't resolve).
    tariffs = {t["id"]: t for t in ocpdb_all("ocpi/3.0/tariffs") if "id" in t}
    evse_tariffs = {}
    for a in ocpdb_all("ocpi/3.0/tariff-associations"):
        t = tariffs.get(a.get("tariff_id"))
        if not t or a.get("audience") not in (None, "AD_HOC_PAYMENT"):
            continue
        for e in a.get("evses") or []:
            if e.get("evse_uid"):
                evse_tariffs[e["evse_uid"]] = {**t, "type": "AD_HOC_PAYMENT"}
    # Only the sources that have tariffs, and that we may use: a fraction of
    # the 110,000 locations.
    priced = sorted({t.get("source") for t in tariffs.values()} - {None})
    locations = []
    for uid in priced:
        if label(uid) is None:
            print(f"DE: {uid} has no licence, left out", file=sys.stderr)
            continue
        found = ocpdb_all(f"ocpi/2.2/locations?source_uid={uid}")
        print(f"DE: {uid} {len(found)} locations", file=sys.stderr)
        locations += found
    return sites_of(locations, tariffs, lambda loc: label(loc.get("source")),
                    evse_tariffs=evse_tariffs, box=BOXES["DE"])


# ---------------------------------------------------------------- cells

def cell_of(lat, lon):
    return f"{math.floor(lat / CELL)}_{math.floor(lon / CELL)}"


def shrunk(counts, previous, floor=1000, keep=0.5):
    """Countries whose priced sites fell below [keep] of the last publish:
    a feed that failed or changed shape, not a market that halved
    overnight. Publishing then would wipe the country's prices."""
    before = (previous or {}).get("countries") or {}
    return sorted(cc for cc, n in before.items()
                  if isinstance(n, int) and n >= floor and counts.get(cc, 0) < n * keep)


def write_cells(sites, out_dir, now=None, counts=None):
    now = now or dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    out = Path(out_dir) / "ocpi"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.json"):
        old.unlink()
    by_cell = {}
    for s in sites:
        by_cell.setdefault(cell_of(s[0], s[1]), []).append(s)
    sizes = {}
    for key, cell_sites in sorted(by_cell.items()):
        sources, operators, rates, rate_sets = [], [], [], []

        def index(seq, item):
            try:
                return seq.index(item)
            except ValueError:
                seq.append(item)
                return len(seq) - 1

        rows = []
        for lat, lon, op, site_rates, src, checked, cur in cell_sites:
            ids = sorted(index(rates, r) for r in site_rates)
            rows.append([lat, lon, index(operators, op), index(rate_sets, ids),
                         index(sources, src), checked, cur])
        body = json.dumps({"cell": key, "importedAt": now.isoformat().replace("+00:00", "Z"),
                           "sources": sources, "operators": operators, "rates": rates,
                           "rateSets": rate_sets, "sites": rows},
                          ensure_ascii=False, separators=(",", ":"))
        (out / f"{key}.json").write_text(body)
        sizes[key] = len(body)
    (out / "index.json").write_text(json.dumps({
        "importedAt": now.isoformat().replace("+00:00", "Z"),
        "cellDegrees": CELL, "sites": len(sites), "countries": counts or {},
        "cells": sorted(sizes)}, separators=(",", ":")))
    return sizes


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("out")
    b.add_argument("--only", choices=["nl", "de"])
    b.add_argument("--from-files", help="read the NDW files from this folder instead")
    b.add_argument("--previous", help="the last published index.json: refuse to publish a country that shrank by half")
    args = p.parse_args(argv)
    sites, counts = [], {}
    if args.only in (None, "nl"):
        nl = ndw(args.from_files)
        print(f"NL: {len(nl)} priced sites", file=sys.stderr)
        sites += nl
        counts["NL"] = len(nl)
    if args.only in (None, "de"):
        de = ocpdb()
        print(f"DE: {len(de)} priced sites", file=sys.stderr)
        sites += de
        counts["DE"] = len(de)
    if args.previous and Path(args.previous).is_file():
        try:
            previous = json.loads(Path(args.previous).read_text())
        except json.JSONDecodeError:
            previous = None
        if bad := shrunk(counts, previous):
            print(f"refusing to publish: {', '.join(bad)} fell below half of the last import "
                  f"({previous.get('countries')} -> {counts}); yesterday's files stay", file=sys.stderr)
            return 1
    sizes = write_cells(sites, args.out, counts=counts)
    big = max(sizes.values(), default=0)
    print(f"{len(sites)} sites in {len(sizes)} cells, largest {big // 1024} KiB", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
