#!/usr/bin/env python3
"""Compare two pack dumps: why does A unlock X while B does not?

Usage:
  python3 scripts/compare.py --a out/verdant/recipe_data.json --b out/liminal/recipe_data.json
  python3 scripts/compare.py ... --item silentgear:crimson_iron_ingot
  python3 scripts/compare.py ... --targets examples/reach/targets-liminal.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _routes(dump: dict, item: str) -> list[dict]:
    bucket = (dump.get("recipes") or {}).get(item) or {}
    return list(bucket.get("mod") or [])


def _label(entry: dict) -> str:
    origin = entry.get("origin") or "?"
    return f"{entry.get('type')}  {entry.get('id')}  [{origin}]"


def compare_item(a: dict, b: dict, item: str, name_a: str, name_b: str) -> None:
    ra, rb = _routes(a, item), _routes(b, item)
    ids_a = {e.get("id") for e in ra}
    ids_b = {e.get("id") for e in rb}
    only_a = [e for e in ra if e.get("id") not in ids_b]
    only_b = [e for e in rb if e.get("id") not in ids_a]
    print(f"\n## {item}")
    print(f"  {name_a}: {len(ra)} route(s); {name_b}: {len(rb)} route(s)")
    if only_a:
        print(f"  only in {name_a}:")
        for e in only_a:
            print(f"    + {_label(e)}")
            ings = e.get("ings") or []
            if ings:
                bits = [f"{i.get('value')}×{i.get('count', 1)}" for i in ings[:6]]
                print(f"      ings: {', '.join(bits)}")
    if only_b:
        print(f"  only in {name_b}:")
        for e in only_b:
            print(f"    + {_label(e)}")
    if not only_a and not only_b:
        if not ra and not rb:
            print("  (no recipes for this item in either dump)")
        else:
            print("  (same recipe ids in both)")


def pack_recipe_namespaces(dump: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for bucket in (dump.get("recipes") or {}).values():
        for e in bucket.get("mod") or []:
            rid = e.get("id") or ""
            ns = rid.split(":", 1)[0] if ":" in rid else "?"
            if e.get("origin") == "pack" or ns.startswith("cp"):
                counts[ns] = counts.get(ns, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--a", required=True, help="recipe_data.json for pack A")
    ap.add_argument("--b", required=True, help="recipe_data.json for pack B")
    ap.add_argument("--name-a", default="A")
    ap.add_argument("--name-b", default="B")
    ap.add_argument("--item", action="append", default=[], help="item id to diff (repeatable)")
    ap.add_argument("--targets", default="", help="targets JSON {items:[{id,...}]} or [id,...]")
    a = ap.parse_args()

    da = json.loads(Path(a.a).read_text(encoding="utf-8"))
    db = json.loads(Path(a.b).read_text(encoding="utf-8"))

    print(f"# Pack compare: {a.name_a} vs {a.name_b}")
    print(f"  {a.name_a}: {da.get('item_count')} items, origins={da.get('origins')}, "
          f"pack_ns={da.get('pack_namespaces')}")
    print(f"  {a.name_b}: {db.get('item_count')} items, origins={db.get('origins')}, "
          f"pack_ns={db.get('pack_namespaces')}")

    pa, pb = pack_recipe_namespaces(da), pack_recipe_namespaces(db)
    if pa or pb:
        print("\n## Pack-authored recipe namespaces")
        print(f"  {a.name_a}: {pa or '(none)'}")
        print(f"  {a.name_b}: {pb or '(none)'}")

    items = list(a.item)
    if a.targets:
        raw = json.loads(Path(a.targets).read_text(encoding="utf-8"))
        if isinstance(raw, list):
            items.extend(raw if all(isinstance(x, str) for x in raw) else [x["id"] for x in raw])
        elif isinstance(raw, dict):
            for x in raw.get("items") or raw.get("targets") or []:
                items.append(x if isinstance(x, str) else x["id"])
    if not items:
        # Default: highlight pack-only recipes that unlock items missing routes in B
        print("\n## Pack-only recipes in A (sample)")
        shown = 0
        for item, bucket in sorted((da.get("recipes") or {}).items()):
            pack_routes = [e for e in (bucket.get("mod") or []) if e.get("origin") == "pack"]
            if not pack_routes:
                continue
            b_routes = _routes(db, item)
            if b_routes:
                # still show if B lacks those pack ids
                if all(e.get("id") in {x.get("id") for x in b_routes} for e in pack_routes):
                    continue
            print(f"  {item}")
            for e in pack_routes:
                in_b = e.get("id") in {x.get("id") for x in b_routes}
                mark = "also in B" if in_b else f"MISSING from {a.name_b}"
                print(f"    {_label(e)}  — {mark}")
            shown += 1
            if shown >= 40:
                print("  … truncated")
                break
        if not shown:
            print("  (none)")
        return 0

    for item in items:
        compare_item(da, db, item, a.name_a, a.name_b)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
