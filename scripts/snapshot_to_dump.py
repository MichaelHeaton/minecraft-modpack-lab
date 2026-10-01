#!/usr/bin/env python3
"""Convert a modpack-lab server snapshot into recipe_data.json (what series_reach.py reads).

Usage:
  python3 scripts/snapshot_to_dump.py --snapshot out/liminal/snapshot.json --out out/liminal/recipe_data.json
      [--mods-dir out/liminal/server/mods] [--server-dir out/liminal/server]

When --mods-dir is set, loot tables + NeoForge GLMs are extracted from jars and merged in
(so mob/chest drops work in reach without a second Docker API).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from recipe_parse import get_result_count, get_result_ids, ingredients_from, shaped_grid  # noqa: E402
from extract_loot import extract, find_vanilla_jars  # noqa: E402

UNPARSED_CAP = 400

# Recipe types that are not item routes (heat values, compost volume, enchant data, …)
NON_ROUTE_TYPES = {
    "exdeorum:barrel_compost",
    "exdeorum:crucible_heat_source",
    "replication:matter_value",
    "minecraft:smithing_trim",
    "silentgear:smithing/upgrade",
    "silentgear:smithing/coating",
    "silentgear:salvaging/gear",
    "ars_nouveau:enchantment",
    "mysticalagriculture:enchanter",
    "mysticalagriculture:soul_extraction",
    "botanypotsmystical:mystical_crop",
    "botanypots:block_derived_crop",
    "botanypots:block_derived_soil",
    "productivebees:bee_breeding",
}


def convert(snap: dict, old: dict, loot: dict | None = None) -> dict:
    recipes: dict[str, dict] = {}
    unparsed: dict[str, list] = {}
    skipped: dict[str, int] = {}
    non_route: dict[str, int] = {}
    for rid, data in sorted(snap["recipes"].items()):
        rtype = data.get("type", "")
        if not rtype:
            continue
        if rtype in NON_ROUTE_TYPES:
            non_route[rtype] = non_route.get(rtype, 0) + 1
            continue
        outs = get_result_ids(data)
        if not outs:
            skipped[rtype] = skipped.get(rtype, 0) + 1
            if skipped[rtype] <= UNPARSED_CAP:
                unparsed.setdefault(rtype, []).append({"jar": "(server)", "file": rid, "data": data})
            continue
        entry = {
            "type": rtype,
            "jar": "(server)",
            "id": rid,
            "ings": ingredients_from(data),
            "count": get_result_count(data),
            "removed": False,
        }
        if "crafting_shaped" in rtype:
            entry["grid"] = shaped_grid(data)
        for out in outs:
            recipes.setdefault(out, {"mod": [], "rm": [], "kj": []})["mod"].append(entry)
    tags = dict(old.get("tags", {}))
    tags.update({k: v for k, v in snap.get("tags", {}).items() if v})
    merged_loot = dict(old.get("loot", {}))
    if loot:
        merged_loot.update(loot)
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "source": "server snapshot",
        "item_count": len(recipes),
        "tags": dict(sorted(tags.items())),
        "loot": merged_loot,
        "unparsed": unparsed,
        "skipped_types": dict(sorted(skipped.items(), key=lambda kv: -kv[1])),
        "non_route_types": dict(sorted(non_route.items(), key=lambda kv: -kv[1])),
        "recipes": recipes,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mods-dir", default="")
    ap.add_argument("--server-dir", default="")
    a = ap.parse_args()
    snap = json.loads(Path(a.snapshot).read_text(encoding="utf-8"))
    if not snap.get("done"):
        print("snapshot is incomplete (exporter never reported done); refusing to convert", file=sys.stderr)
        return 2
    out = Path(a.out)
    old = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}

    loot = None
    if a.mods_dir:
        mods = Path(a.mods_dir)
        extras = find_vanilla_jars(Path(a.server_dir)) if a.server_dir else []
        loot, stats = extract(mods, extras or None)
        print(
            f"loot: {stats.get('loot_tables', 0)} tables; "
            f"GLMs applied={stats.get('glm_applied', 0)}",
            file=sys.stderr,
        )
        loot_path = out.parent / "loot.json"
        loot_path.write_text(json.dumps(loot, indent=2), encoding="utf-8")

    dump = convert(snap, old, loot)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dump, indent=2), encoding="utf-8")
    n = sum(len(v["mod"]) for v in dump["recipes"].values())
    print(
        f"wrote {out}: {n} recipes for {dump['item_count']} items; "
        f"{sum(dump['skipped_types'].values())} unparsed in {len(dump['skipped_types'])} types; "
        f"{sum(dump.get('non_route_types', {}).values())} non-route; "
        f"{len(dump.get('loot') or {})} loot keys"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
