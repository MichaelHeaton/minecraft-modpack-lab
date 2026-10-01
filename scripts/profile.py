#!/usr/bin/env python3
"""Load pack profiles (world flags + start/targets paths)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "profiles"

WORLD_DEFAULTS = {
    "spawn": "overworld",
    "terrain": "full",
    "ore_veins": True,
    "nether": True,
    "end": True,
    "villages": True,
    "wandering_traders": True,
}

# Items that usually require the Nether unless the pack adds an overworld substitute.
NETHER_HINTS = {
    "minecraft:netherrack",
    "minecraft:soul_sand",
    "minecraft:soul_soil",
    "minecraft:glowstone",
    "minecraft:nether_quartz_ore",
    "minecraft:ancient_debris",
    "minecraft:blaze_rod",
    "minecraft:ghast_tear",
    "minecraft:magma_cream",
    "minecraft:nether_star",
    "minecraft:netherite_ingot",
    "minecraft:netherite_scrap",
}


def resolve_path(p: str | Path) -> Path:
    path = Path(p)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def load_profile(pack_id: str) -> dict:
    path = PROFILES / f"{pack_id}.json"
    if not path.exists():
        # Minimal fallback so packs without a profile still work
        return {
            "id": pack_id,
            "label": pack_id,
            "world": dict(WORLD_DEFAULTS),
            "start": str(ROOT / "examples/reach/verdant.json"),
            "targets": str(ROOT / "examples/reach/targets.json"),
            "_missing_profile": True,
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    world = dict(WORLD_DEFAULTS)
    world.update(data.get("world") or {})
    data["world"] = world
    data["start"] = str(resolve_path(data["start"]))
    data["targets"] = str(resolve_path(data["targets"]))
    return data


def world_warnings(profile: dict, start: dict) -> list[str]:
    """Flag mismatches between world flags and the start file."""
    w = profile["world"]
    warns: list[str] = []
    start_items = set(start.get("start_items", []))
    if w.get("ore_veins") is False:
        ore_like = [i for i in start_items if "_ore" in i.split(":")[-1] and "nether" not in i]
        if ore_like:
            warns.append(f"ore_veins=false but start lists ore blocks: {', '.join(sorted(ore_like)[:8])}")
    if w.get("nether") is False:
        nether_mobs = [m for m in start.get("mobs", []) if any(x in m for x in ("blaze", "ghast", "piglin", "hoglin", "wither_skeleton", "zombified_piglin", "magma_cube"))]
        if nether_mobs:
            warns.append(f"nether=false but start lists Nether mobs: {', '.join(nether_mobs[:8])}")
    if w.get("wandering_traders") is False and "minecraft:wandering_trader" in start.get("mobs", []):
        warns.append("wandering_traders=false but start lists wandering_trader")
    if w.get("villages") is False:
        loot = start.get("loot_sources", [])
        if any("village" in x for x in loot):
            warns.append("villages=false but start loot_sources mention villages")
    return warns


def format_world(world: dict) -> str:
    bits = [
        f"spawn={world.get('spawn')}",
        f"terrain={world.get('terrain')}",
        f"ores={'yes' if world.get('ore_veins') else 'NO'}",
        f"nether={'yes' if world.get('nether') else 'NO'}",
        f"end={'yes' if world.get('end') else 'NO'}",
        f"villages={'yes' if world.get('villages') else 'NO'}",
    ]
    return ", ".join(bits)


if __name__ == "__main__":
    pid = sys.argv[1] if len(sys.argv) > 1 else ""
    if not pid:
        for p in sorted(PROFILES.glob("*.json")):
            print(p.stem)
        sys.exit(0)
    print(json.dumps(load_profile(pid), indent=2))
