#!/usr/bin/env python3
"""Single-pack playability report: can the player reach the design targets under this world?

Uses the pack profile (world flags + start/targets) and out/<id>/recipe_data.json.
Answers the chicken-and-egg question: after you strip ores / Nether / End, what breaks?
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from profile import NETHER_HINTS, format_world, load_profile, world_warnings  # noqa: E402
from series_reach import World, targets_from  # noqa: E402


def report(pack_id: str, dump_path: Path) -> int:
    profile = load_profile(pack_id)
    if profile.get("_missing_profile"):
        print(f"NOTE: no profiles/{pack_id}.json — using defaults (vanilla-like world). "
              f"Add a profile so ore/nether/end flags match the pack.\n", file=sys.stderr)

    start = json.loads(Path(profile["start"]).read_text(encoding="utf-8"))
    targets = targets_from(profile["targets"])
    dump = json.loads(dump_path.read_text(encoding="utf-8"))

    print(f"# Playability — {profile.get('label', pack_id)}")
    print(f"world: {format_world(profile['world'])}")
    if profile.get("notes"):
        print(f"notes: {profile['notes']}")
    print(f"dump:  {dump_path} ({dump.get('item_count')} items, source={dump.get('source')})")
    print(f"start: {profile['start']}")
    print(f"targets: {profile['targets']} ({len(targets)} items)")
    print()

    for wmsg in world_warnings(profile, start):
        print(f"WARN  profile/start mismatch: {wmsg}")
    if world_warnings(profile, start):
        print()

    w = World(dump, start)
    passes = w.close()
    ok, bad = [], []
    for t in targets:
        (ok if t["id"] in w.items else bad).append(t)

    print(f"## Reachability")
    print(f"{len(w.items)} items reachable after {passes} passes; "
          f"{len(w.known)} known in dump; "
          f"{'tag data present' if w.dump_tags else 'NO tag data'}")
    print()
    print(f"REACHABLE ({len(ok)}/{len(targets)}):")
    for t in ok:
        print(f"  OK   {t['id']:<44} depth {w.items[t['id']]:>2}  {t.get('why', '')}")
    print()
    print(f"NO ROUTE ({len(bad)}/{len(targets)}):")
    world = profile["world"]
    for t in bad:
        known = "known" if t["id"] in w.known else "NOT IN DUMP"
        hint = ""
        if t["id"] in NETHER_HINTS and not world.get("nether"):
            hint = "  [nether=false — need overworld substitute]"
        if world.get("ore_veins") is False and "_ore" in t["id"]:
            hint = "  [ore_veins=false]"
        print(f"  FAIL {t['id']:<44} {known:<12} {t.get('why', '')}{hint}")

    # Chicken-egg: powder without rod, chunk metals without ore_chunk, etc.
    print()
    print("## Chicken-and-egg signals")
    signals = []
    if "minecraft:blaze_powder" in w.items and "minecraft:blaze_rod" not in w.items:
        signals.append("blaze_powder reachable but blaze_rod is not — compacting/casting gap")
    if "minecraft:netherite_scrap" in w.items and "minecraft:netherite_ingot" not in w.items:
        signals.append("netherite_scrap reachable but netherite_ingot is not")
    for metal, label in (
        ("silentgear:crimson_iron_ingot", "crimson iron"),
        ("silentgear:azure_silver_ingot", "azure silver"),
        ("silentgear:tyrian_steel_ingot", "tyrian steel"),
    ):
        if metal in w.known and metal not in w.items:
            signals.append(f"{label} known in dump but no route from this start")
    if not signals:
        print("  (none detected from simple heuristics)")
    else:
        for s in signals:
            print(f"  • {s}")

    # Skipped recipe types — coverage debt
    skipped = dump.get("skipped_types") or {}
    non_route = dump.get("non_route_types") or {}
    loot = dump.get("loot") or {}
    print()
    print(f"## Loot / GLM coverage")
    print(f"  {len(loot)} loot keys in dump "
          f"(entities={sum(1 for k in loot if k.startswith('entities/'))}, "
          f"chests={sum(1 for k in loot if k.startswith('chests/'))}, "
          f"blocks={sum(1 for k in loot if k.startswith('blocks/'))})")
    if skipped:
        print()
        print("## Unparsed recipe types (coverage debt — may hide real routes)")
        for rtype, n in sorted(skipped.items(), key=lambda kv: -kv[1])[:12]:
            print(f"  {n:>5}  {rtype}")
        if len(skipped) > 12:
            print(f"  ... {len(skipped) - 12} more types")
    if non_route:
        print()
        print("## Non-route types (intentionally ignored — no item craft path)")
        for rtype, n in sorted(non_route.items(), key=lambda kv: -kv[1])[:8]:
            print(f"  {n:>5}  {rtype}")
        if len(non_route) > 8:
            print(f"  ... {len(non_route) - 8} more types")

    print()
    rc = 0 if not bad else 1
    print(f"## Verdict: {'PLAYABLE targets OK' if rc == 0 else f'{len(bad)} target(s) blocked'}")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pack-id", required=True)
    ap.add_argument("--dump", required=True)
    a = ap.parse_args()
    dump = Path(a.dump)
    if not dump.exists():
        print(f"no dump at {dump}; run: make dump PACK={a.pack_id} EULA=1", file=sys.stderr)
        return 1
    return report(a.pack_id, dump)


if __name__ == "__main__":
    sys.exit(main())
