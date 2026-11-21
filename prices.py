#!/usr/bin/env python3
"""Checks and summarises ChargeAhead's per-operator price tables.

Each country has one file, `<cc>.json` (`tr.json`): the operators'
published per-kWh prices, the page each came from and when it was checked.
The ChargeAhead backend reads these files from this repo's main branch
every 10 minutes, so a merged change shows in the app without a release.

    python3 prices.py validate [files...]   check every table (CI runs this)
    python3 prices.py summary [BASE]        what changed against BASE (default origin/main), as Markdown
    python3 prices.py due [--days N]        rows not checked for N days (default 7)
    python3 prices.py by-hand               rows whose price is only in the operator's app

Standard library only.
"""

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAX_PER_KWH = 1000.0   # the backend drops anything above it as a typo
CHECKS = ("page", "app")


def tables(paths=None):
    files = [Path(p) for p in paths] if paths else sorted(ROOT.glob("[a-z][a-z].json"))
    return [(f, json.loads(f.read_text())) for f in files]


def price_range(v):
    """A price or [min, max] as (min, max); None for null; raises for junk."""
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        lo = hi = float(v)
    elif isinstance(v, list) and len(v) == 2 and all(
        isinstance(x, (int, float)) and not isinstance(x, bool) for x in v
    ):
        lo, hi = float(v[0]), float(v[1])
    else:
        raise ValueError(f"{v!r} is not a price or [min, max]")
    if not (0 < lo <= hi < MAX_PER_KWH):
        raise ValueError(f"{v!r} is out of range (0 < min <= max < {MAX_PER_KWH:g})")
    return lo, hi


def day(v, what):
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d\d-\d\d", v):
        raise ValueError(f"{what} must be YYYY-MM-DD")
    return dt.date.fromisoformat(v)


def fold(name):
    """Close to the backend's operatorKeyFor: lower case, letters and digits
    only, Turkish and accented letters folded."""
    table = str.maketrans("çğıöşüâêîôûàáäéèëíìïñóòúùÿ", "cgiosuaeiouaaaeeeiiinoouuy")
    return re.sub(r"[^a-z0-9]", "", name.lower().translate(table))


def problems(path, table, today=None):
    today = today or dt.date.today()
    out = []
    where = path.name
    if path.stem.upper() != str(table.get("country", "")).upper():
        out.append(f"{where}: country must be {path.stem.upper()}")
    if not re.fullmatch(r"[A-Z]{3}", str(table.get("currency", ""))):
        out.append(f"{where}: currency must be ISO 4217 in capitals")
    rows = table.get("operators")
    if not isinstance(rows, list) or not rows:
        return out + [f"{where}: no operators"]
    seen = {}
    for i, row in enumerate(rows, 1):
        name = row.get("name") if isinstance(row, dict) else None
        at = f"{where} row {i} ({name or '?'})"
        if not isinstance(name, str) or not name.strip():
            out.append(f"{at}: needs a name")
            continue
        keys = row.get("keys", [])
        if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
            out.append(f"{at}: keys must be a list of names")
            keys = []
        for key in {fold(name), *(fold(k) for k in keys)} - {""}:
            if key in seen and seen[key] != name:
                out.append(f"{at}: key {key!r} is also {seen[key]}'s")
            seen[key] = name
        try:
            ac, dc = price_range(row.get("ac")), price_range(row.get("dc"))
            if ac is None and dc is None and row.get("check") != "app":
                out.append(f"{at}: no AC or DC price (set check: app if it's only in the app)")
        except ValueError as e:
            out.append(f"{at}: {e}")
        if row.get("check") not in CHECKS:
            out.append(f"{at}: check must be page or app")
        src = row.get("source")
        if not isinstance(src, str) or not src.startswith("https://"):
            out.append(f"{at}: source must be the operator's https page")
        try:
            checked = day(row.get("checked"), "checked")
            if checked > today:
                out.append(f"{at}: checked is in the future")
            if row.get("changed") is not None:
                changed = day(row.get("changed"), "changed")
                if changed > checked:
                    out.append(f"{at}: changed is after checked")
        except ValueError as e:
            out.append(f"{at}: {e}")
    return out


def show(v):
    r = price_range(v)
    if r is None:
        return "–"
    lo, hi = r
    return f"{lo:g}" if lo == hi else f"{lo:g}–{hi:g}"


def summary(base="origin/main", paths=None):
    """What changed in the tables against `base`, as Markdown lines."""
    lines = []
    for path, now in tables(paths):
        try:
            old = json.loads(subprocess.run(
                ["git", "show", f"{base}:{path.name}"], cwd=ROOT,
                capture_output=True, text=True, check=True).stdout)
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            old = {"operators": []}
        before = {r["name"]: r for r in old.get("operators", []) if isinstance(r, dict) and "name" in r}
        after = {r["name"]: r for r in now.get("operators", []) if isinstance(r, dict) and "name" in r}
        cc, cur = path.stem.upper(), now.get("currency", "")
        rechecked = []
        for name, r in after.items():
            b = before.get(name)
            if b is None:
                lines.append(f"- {cc} **{name}** added: AC {show(r.get('ac'))}, DC {show(r.get('dc'))} {cur}/kWh ({r.get('source')})")
                continue
            moves = [f"{k.upper()} {show(b.get(k))} → {show(r.get(k))}"
                     for k in ("ac", "dc") if show(b.get(k)) != show(r.get(k))]
            if moves:
                lines.append(f"- {cc} **{name}**: {', '.join(moves)} {cur}/kWh ({r.get('source')})")
            elif r.get("checked") != b.get("checked"):
                rechecked.append(name)
        for name in before.keys() - after.keys():
            lines.append(f"- {cc} **{name}** removed")
        if rechecked:
            lines.append(f"- {cc} unchanged, checked again: {', '.join(sorted(rechecked))}")
    return lines


def due(days, paths=None, today=None):
    today = today or dt.date.today()
    out = []
    for path, t in tables(paths):
        for r in t.get("operators", []):
            checked = dt.date.fromisoformat(r["checked"])
            if (today - checked).days >= days:
                out.append(f"{path.stem.upper()} {r['name']}: checked {r['checked']}")
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("files", nargs="*")
    s = sub.add_parser("summary")
    s.add_argument("base", nargs="?", default="origin/main")
    d = sub.add_parser("due")
    d.add_argument("--days", type=int, default=7)
    sub.add_parser("by-hand")
    args = p.parse_args(argv)
    if args.cmd == "validate":
        errors = [e for path, t in tables(args.files) for e in problems(path, t)]
        for e in errors:
            print(f"✗ {e}")
        n = sum(len(t.get("operators", [])) for _, t in tables(args.files))
        print(f"{'ok' if not errors else f'{len(errors)} problem(s)'} · {n} operator rows")
        return 1 if errors else 0
    if args.cmd == "summary":
        print("\n".join(summary(args.base)) or "No changes.")
    elif args.cmd == "due":
        print("\n".join(due(args.days)) or "Nothing due.")
    else:
        for path, t in tables():
            for r in t.get("operators", []):
                if r.get("check") == "app":
                    print(f"{path.stem.upper()} {r['name']}: {r.get('source')} ({r.get('note', '')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
