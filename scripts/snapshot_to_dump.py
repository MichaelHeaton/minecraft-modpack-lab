#!/usr/bin/env python3
"""Convert a modpack-lab server snapshot into recipe_data.json (what series_reach.py reads).

Usage:
  python3 scripts/snapshot_to_dump.py --snapshot out/liminal/snapshot.json --out out/liminal/recipe_data.json

Server recipes replace jar-scraped ones. Loot tables are kept from an existing dump when present
(the snapshot does not carry loot yet). Server-resolved tags overlay jar tags.
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

UNPARSED_CAP = 400


def convert(snap: dict, old: dict) -> dict:
    recipes: dict[str, dict] = {}
    unparsed: dict[str, list] = {}
    skipped: dict[str, int] = {}
    for rid, data in sorted(snap["recipes"].items()):
        rtype = data.get("type", "")
        if not rtype:
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
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "source": "server snapshot",
        "item_count": len(recipes),
        "tags": dict(sorted(tags.items())),
        "loot": old.get("loot", {}),
        "unparsed": unparsed,
        "skipped_types": dict(sorted(skipped.items(), key=lambda kv: -kv[1])),
        "recipes": recipes,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    snap = json.loads(Path(a.snapshot).read_text(encoding="utf-8"))
    if not snap.get("done"):
        print("snapshot is incomplete (exporter never reported done); refusing to convert", file=sys.stderr)
        return 2
    out = Path(a.out)
    old = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    dump = convert(snap, old)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dump, indent=2), encoding="utf-8")
    n = sum(len(v["mod"]) for v in dump["recipes"].values())
    print(
        f"wrote {out}: {n} recipes for {dump['item_count']} items; "
        f"{sum(dump['skipped_types'].values())} with no readable output "
        f"in {len(dump['skipped_types'])} types"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
