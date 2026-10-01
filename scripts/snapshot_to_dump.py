#!/usr/bin/env python3
"""Convert a modpack-lab server snapshot into recipe_data.json (what series_reach.py reads).

Usage:
  python3 scripts/snapshot_to_dump.py --snapshot out/liminal/snapshot.json --out out/liminal/recipe_data.json
      [--mods-dir out/liminal/server/mods] [--server-dir out/liminal/server]
      [--pack-namespaces cpverdant,kubejs]

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

# Built-in datapack / script namespaces (always "pack" origin)
DEFAULT_PACK_NAMESPACES = frozenset({"kubejs", "crafttweaker", "almostunified"})

# Recipe types that are not item routes (heat values, compost, specials, NBT upgrades, …)
# Keep sorted for readability; expand when convert still reports coverage debt.
NON_ROUTE_TYPES = frozenset({
    # Explicit data / values
    "exdeorum:barrel_compost",
    "exdeorum:crucible_heat_source",
    "replication:matter_value",
    "mekanism:energy_conversion",
    "createaddition:liquid_burning",
    "azurum_miner:generator_recipe",
    "theurgy:catalysation",
    "nep:module_status",
    # Smithing / salvage / dye / repair specials (no new unlock item)
    "minecraft:smithing_trim",
    "silentgear:smithing/upgrade",
    "silentgear:smithing/coating",
    "silentgear:salvaging/gear",
    "silentgear:salvaging/compound_part",
    "silentgear:fill_repair_kit",
    "silentgear:mod_kit_paint_part",
    "silentgear:mod_kit_remove_part",
    "silentgear:quick_paint",
    "silentgear:quick_repair",
    "silentgear:swap_gear_part",
    "sophisticatedbackpacks:backpack_dye",
    "sophisticatedcore:upgrade_clear",
    "sophisticatedstorage:barrel_material",
    "sophisticatedstorage:flat_top_barrel_toggle",
    "sophisticatedstorage:storage_dye",
    "create:item_copying",
    "create:toolbox_dyeing",
    "farmersdelight:food_serving",
    "farmersdelight:dough",
    "mekanism:bin_extract",
    "mekanism:bin_insert",
    "mekanism:clear_configuration",
    "cb_microblock:microblock",
    "agricraft:magnifyinghelmet",
    "projecte:covalence_repair",
    "projecte:philo_stone_smelting",
    "occultism:crafting_special_book_binding",
    "occultism:crafting_special_repairitem",
    # Vanilla specials
    "minecraft:crafting_decorated_pot",
    "minecraft:crafting_special_armordye",
    "minecraft:crafting_special_bannerduplicate",
    "minecraft:crafting_special_bookcloning",
    "minecraft:crafting_special_firework_rocket",
    "minecraft:crafting_special_firework_star",
    "minecraft:crafting_special_firework_star_fade",
    "minecraft:crafting_special_mapcloning",
    "minecraft:crafting_special_mapextending",
    "minecraft:crafting_special_repairitem",
    "minecraft:crafting_special_shielddecoration",
    "minecraft:crafting_special_shulkerboxcoloring",
    "minecraft:crafting_special_suspiciousstew",
    "minecraft:crafting_special_tippedarrow",
    # Enchant / tome / ritual / NBT upgrade (identity transforms)
    "ars_nouveau:enchantment",
    "ars_nouveau:caster_tome",
    "ars_nouveau:scry_ritual",
    "ars_nouveau:summon_ritual",
    "ars_nouveau:prestidigitation",
    "ars_nouveau:reactive_enchantment",
    "ars_nouveau:spell_write",
    "ars_nouveau:armor_upgrade",
    "ars_nouveau:dispel_entity",
    "ars_nouveau:alakarkinos_conversion",
    "ars_additions:locate_structure",
    "ars_additions:charm_charging",
    "ars_additions:bulk_scribing",
    "ars_additions:imbue_scroll",
    "ars_additions:source_spawner",
    "ars_elemental:netherite_upgrade",
    "ars_zero:staff_filial",
    "ars_zero:protection_upgrade",
    "mysticalagriculture:enchanter",
    "mysticalagriculture:soul_extraction",
    "mysticalagriculture:soul_jar_empty",
    "mysticalagriculture:soulium_spawner",
    "apothic_spawners:spawner_modifier",
    "apotheosis:reforging",
    "apotheosis:purity_upgrade",
    "apotheosis:potion_charm_infusion",
    "apotheosis:add_sockets",
    "apotheosis:socketing",
    "apotheosis:supremacy",
    "apotheosis:unnaming",
    "apotheosis:withdrawal",
    "apotheosis:malice",
    # AE2 / wireless tooling (ammo weight, dual terminals without static result)
    "ae2:matter_cannon",
    "ae2:facade",
    "ae2:add_item_upgrade",
    "ae2:remove_item_upgrade",
    "ae2wtlib:combine",
    "ae2wtlib:upgrade",
    "akashictome:attachment",
    "morphtool:attachment",
    "nep:processing_pattern_conversion",
    # Botany pots registration / fertilizer (not craft outputs)
    "botanypots:soil",
    "botanypots:fertilizer",
    "botanypots:block_derived_crop",
    "botanypots:block_derived_soil",
    "botanypotsmystical:mystical_crop",
    # Bees meta
    "productivebees:bee_breeding",
    "productivebees:bee_nbt_changer",
    "productivebees:bee_fishing",
    "productivebees:bee_cage_bomb",
    "productivebees:configurable_comb_block",
    "productivebees:configurable_honeycomb",
    "productivebees:gene_gene",
    "productivebees:gene_treat",
    # Twilight Forest gear modifiers / repairs
    "twilightforest:travellers_gear_modifier_shaped_recipe",
    "twilightforest:travellers_gear_modifier_shapeless_recipe",
    "twilightforest:travellers_vest_gloves_merge_recipe",
    "twilightforest:no_template_smithing",
    "twilightforest:casket_repair_recipe",
    "twilightforest:emperors_cloth_recipe",
    "twilightforest:essence_repair_recipe",
    "twilightforest:magic_map_cloning_recipe",
    "twilightforest:maze_map_cloning_recipe",
    "twilightforest:moonworm_queen_repair_recipe",
    "twilightforest:scepter_repair",
})


def _is_non_route(rtype: str) -> bool:
    if rtype in NON_ROUTE_TYPES:
        return True
    if "crafting_special" in rtype:
        return True
    return False


def recipe_origin(recipe_id: str, pack_namespaces: set[str]) -> str:
    """mod = shipped in a mod jar; pack = KubeJS / pack datapack namespace."""
    ns = recipe_id.split(":", 1)[0] if ":" in recipe_id else ""
    if ns in pack_namespaces or ns in DEFAULT_PACK_NAMESPACES:
        return "pack"
    return "mod"


def convert(
    snap: dict,
    old: dict,
    loot: dict | None = None,
    pack_namespaces: set[str] | None = None,
) -> dict:
    pack_ns = set(pack_namespaces or ())
    recipes: dict[str, dict] = {}
    unparsed: dict[str, list] = {}
    skipped: dict[str, int] = {}
    non_route: dict[str, int] = {}
    origins: dict[str, int] = {"mod": 0, "pack": 0}
    for rid, data in sorted(snap["recipes"].items()):
        rtype = data.get("type", "")
        if not rtype:
            continue
        if _is_non_route(rtype):
            non_route[rtype] = non_route.get(rtype, 0) + 1
            continue
        outs = get_result_ids(data)
        if not outs:
            # Some types intentionally produce nothing (block destroy → air)
            if rtype == "productivebees:block_conversion":
                non_route[rtype] = non_route.get(rtype, 0) + 1
                continue
            skipped[rtype] = skipped.get(rtype, 0) + 1
            if skipped[rtype] <= UNPARSED_CAP:
                unparsed.setdefault(rtype, []).append({"jar": "(server)", "file": rid, "data": data})
            continue
        origin = recipe_origin(rid, pack_ns)
        origins[origin] = origins.get(origin, 0) + 1
        entry = {
            "type": rtype,
            "jar": "(server)",
            "id": rid,
            "origin": origin,
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
        "origins": origins,
        "pack_namespaces": sorted(pack_ns | DEFAULT_PACK_NAMESPACES),
        "recipes": recipes,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mods-dir", default="")
    ap.add_argument("--server-dir", default="")
    ap.add_argument(
        "--pack-namespaces",
        default="",
        help="comma-separated recipe-id namespaces that count as pack/KubeJS (e.g. cpverdant)",
    )
    a = ap.parse_args()
    snap = json.loads(Path(a.snapshot).read_text(encoding="utf-8"))
    if not snap.get("done"):
        print("snapshot is incomplete (exporter never reported done); refusing to convert", file=sys.stderr)
        return 2
    out = Path(a.out)
    old = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    pack_ns = {n.strip() for n in a.pack_namespaces.split(",") if n.strip()}

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

    dump = convert(snap, old, loot, pack_ns)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dump, indent=2), encoding="utf-8")
    n = sum(len(v["mod"]) for v in dump["recipes"].values())
    print(
        f"wrote {out}: {n} recipes for {dump['item_count']} items; "
        f"{sum(dump['skipped_types'].values())} unparsed in {len(dump['skipped_types'])} types; "
        f"{sum(dump.get('non_route_types', {}).values())} non-route; "
        f"origins={dump.get('origins')}; "
        f"{len(dump.get('loot') or {})} loot keys"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
