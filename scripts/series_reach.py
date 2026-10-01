#!/usr/bin/env python3
"""Reachability over the recipe dump: what can a player make from a pack's starting resources?

Reads docs/recipe_data.json (from make recipe-pr / recipe-sync) and a start file, then repeatedly
marks an item reachable when some recipe has every ingredient reachable. Reports which target
items (gear tiers, machine inputs, crop seeds) have no route, and why.

Start file (docs/series/items/reach/<name>.json):
    {"name": "...", "start_items": ["minecraft:cobblestone", ...],
     "start_tags": ["minecraft:logs", ...], "mobs": ["minecraft:zombie", ...],
     "loot_sources": ["gameplay/minecraft:fishing", "chests/minecraft:village/*"],
     "disable_types": ["..."], "notes": "..."}
Targets file (docs/series/items/reach/targets.json): {"targets": [{"id": "minecraft:diamond", "why": "..."}]}

Usage:
    python3 scripts/series-reach.py check <start.json> [--targets targets.json] [--dump docs/recipe_data.json]
    python3 scripts/series-reach.py why <start.json> <item>        # cheapest recipe chain
    python3 scripts/series-reach.py blocked <start.json> <item>    # per recipe: which ingredients are missing
    python3 scripts/series-reach.py tags <start.json>              # tags nothing resolves (fix with aliases)

Assumptions, stated so the output is read correctly:
- Only recipes the dump could read ingredients for are used. Recipes with no readable item ingredients
  (fluid-only casting, loot, worldgen, mob drops, villager trades) are not routes, so list those
  sources in the start file.
- A recipe's own result used as an ingredient is treated as a catalyst, not consumed (Theurgy's
  reformation target, tool upgrades). Pass --strict to treat it as a real ingredient.
- Tags come from the mods' own tag files when the dump has them (newer dumps), otherwise from the
  name rules below. Vanilla tags are resolved by name rules. Items the rules cannot place are listed
  by `tags`, and can be added in the start file under "tag_aliases": {"tag": ["item", ...]}.
- Loot tables (from the dump's `loot`): a mob listed in the start file's `mobs` drops its table; a block drops its table when the block item is reachable (any tool, no silk-touch or fortune detail); tables named in `loot_sources` (exact key, or a prefix ending in `*`, such as `chests/minecraft:village/*`) count as found, including tables they reference. Spawn rates, chances and conditions are not modelled.
- Fluids and chemicals are pseudo items (`fluid:<id>`, `chemical:<id>`): a recipe that melts an ingot makes `fluid:...`, casting uses it. Put world sources (`fluid:minecraft:water`, `fluid:minecraft:lava`) in the start file. A filled bucket and its fluid are linked.
- Machines, fuel, power, tank capacity and recipe speed are not modelled; this answers "is there any route", not "how fast".
"""
import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
DUMP = os.path.join(ROOT, "out", "recipe_data.json")  # override with --dump; prefer out/<pack>/recipe_data.json
REACH = os.path.join(ROOT, "examples", "reach")

SINGULAR = {
    "ingots": "ingot", "nuggets": "nugget", "dusts": "dust", "gems": "gem", "plates": "plate", "rods": "rod",
    "gears": "gear", "wires": "wire", "ores": "ore", "raw_materials": "raw", "storage_blocks": "block",
    "crystals": "crystal", "shards": "shard", "seeds": "seeds", "dyes": "dye", "foods": "", "buckets": "bucket",
}

# Recipe results that are placeholders / debug blocks — never treat as a craft route.
JUNK_ITEMS = {
    "minecraft:barrier",
    "minecraft:air",
    "minecraft:light",
    "minecraft:structure_void",
    "minecraft:structure_block",
    "minecraft:jigsaw",
    "minecraft:command_block",
    "minecraft:repeating_command_block",
    "minecraft:chain_command_block",
    "minecraft:debug_stick",
    "minecraft:knowledge_book",
}


# Vanilla tags are not in any mod jar. Item ids (or name suffixes starting with "*") for the ones recipes use most.
VANILLA_TAGS = {
    "minecraft:stone_crafting_materials": ["minecraft:cobblestone", "minecraft:cobbled_deepslate", "minecraft:blackstone"],
    "minecraft:stone_tool_materials": ["minecraft:cobblestone", "minecraft:cobbled_deepslate", "minecraft:blackstone"],
    "minecraft:coals": ["minecraft:coal", "minecraft:charcoal"],
    "minecraft:smelts_to_glass": ["minecraft:sand", "minecraft:red_sand"],
    "minecraft:sand": ["minecraft:sand", "minecraft:red_sand"],
    "minecraft:soul_fire_base_blocks": ["minecraft:soul_sand", "minecraft:soul_soil"],
    "minecraft:iron_ores": ["minecraft:iron_ore", "minecraft:deepslate_iron_ore"],
    "minecraft:gold_ores": ["minecraft:gold_ore", "minecraft:deepslate_gold_ore", "minecraft:nether_gold_ore"],
    "minecraft:copper_ores": ["minecraft:copper_ore", "minecraft:deepslate_copper_ore"],
    "minecraft:diamond_ores": ["minecraft:diamond_ore", "minecraft:deepslate_diamond_ore"],
    "minecraft:redstone_ores": ["minecraft:redstone_ore", "minecraft:deepslate_redstone_ore"],
    "minecraft:lapis_ores": ["minecraft:lapis_ore", "minecraft:deepslate_lapis_ore"],
    "minecraft:coal_ores": ["minecraft:coal_ore", "minecraft:deepslate_coal_ore"],
    "minecraft:emerald_ores": ["minecraft:emerald_ore", "minecraft:deepslate_emerald_ore"],
    "minecraft:anvil": ["minecraft:anvil", "minecraft:chipped_anvil", "minecraft:damaged_anvil"],
    "minecraft:wooden_slabs": ["*_slab:planks"],
    "minecraft:wooden_stairs": ["*_stairs:planks"],
    "minecraft:wooden_fences": ["*_fence:planks"],
    "minecraft:wooden_buttons": ["*_button:planks"],
    "minecraft:wooden_pressure_plates": ["*_pressure_plate:planks"],
    "minecraft:trapdoors": ["*_trapdoor"],
    "minecraft:doors": ["*_door"],
    "minecraft:fences": ["*_fence"],
    "minecraft:fence_gates": ["*_fence_gate"],
    "minecraft:logs": ["*_log", "*_stem", "*_wood", "*_hyphae"],
    "minecraft:logs_that_burn": ["*_log", "*_wood"],
    "minecraft:planks": ["*_planks"],
    "minecraft:leaves": ["*_leaves"],
    "minecraft:saplings": ["*_sapling"],
    "minecraft:wool": ["*_wool"],
    "minecraft:flowers": ["*_tulip", "dandelion", "poppy", "blue_orchid", "allium", "azure_bluet", "oxeye_daisy", "cornflower", "lily_of_the_valley", "sunflower", "lilac", "rose_bush", "peony"],
    "minecraft:dirt": ["minecraft:dirt", "minecraft:grass_block", "minecraft:podzol", "minecraft:coarse_dirt", "minecraft:mycelium", "minecraft:rooted_dirt", "minecraft:moss_block", "minecraft:mud"],
    "minecraft:terracotta": ["*_terracotta", "minecraft:terracotta"],
    "minecraft:beds": ["*_bed"],
    "minecraft:boats": ["*_boat"],
    "minecraft:fishes": ["minecraft:cod", "minecraft:salmon", "minecraft:tropical_fish", "minecraft:pufferfish"],
    "minecraft:wool_carpets": ["*_carpet"],
}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class World:
    def __init__(self, dump, start, strict=False):
        self.recipes = dump["recipes"]
        self.dump_tags = dump.get("tags", {})
        self.aliases = {k: set(v) for k, v in start.get("tag_aliases", {}).items()}
        self.disabled = set(start.get("disable_types", []))
        self.loot = dump.get("loot", {})
        self.mobs = set(start.get("mobs", []))
        self.loot_sources = self._expand_sources(start.get("loot_sources", []))
        self.strict = strict
        self._expand_tag_outputs()
        self.known = set(self.recipes)
        for entry in self.loot.values():
            self.known.update(entry.get("items", []))
        for entry in self.recipes.values():
            for r in entry["mod"]:
                for ing in r["ings"]:
                    if ing["type"] == "item":
                        self.known.add(ing["value"])
        self._tag_cache = {}
        self.items = {k: 0 for k in start.get("start_items", [])}  # item -> depth
        self.via = {}  # item -> (recipe type, jar, [ingredients as text])
        for tag in start.get("start_tags", []):
            for m in self.tag_members(tag):
                self.items.setdefault(m, 0)

    def _expand_tag_outputs(self):
        """A recipe that outputs a tag ('#c:ores/osmium': Ex Deorum chunks, Occultism miners, bee combs) makes any one
        member. Modelled as making every member (slightly optimistic when a tag has several members)."""
        merged = {k: v for k, v in self.recipes.items() if not k.startswith("#")}
        for key, entry in self.recipes.items():
            if not key.startswith("#"):
                continue
            tag = key[1:]
            members = set(self.dump_tags.get(tag, [])) | self.aliases.get(tag, set())
            for m in members:
                tgt = merged.setdefault(m, {"mod": [], "rm": [], "kj": []})
                tgt = dict(tgt, mod=list(tgt["mod"]) + entry["mod"])
                merged[m] = tgt
        self.recipes = merged

    # ----- loot -----
    def _expand_sources(self, patterns):
        """Loot table keys the pack can reach: exact keys or prefixes ending in *, plus the tables they reference."""
        keys = set()
        for pat in patterns:
            if pat.endswith("*"):
                keys |= {k for k in self.loot if k.startswith(pat[:-1])}
            elif pat in self.loot:
                keys.add(pat)
        todo = list(keys)
        while todo:
            for ref in self.loot[todo.pop()].get("tables", []):
                ns, _, path = ref.partition(":")          # "minecraft:gameplay/fishing/fish"
                kind, _, rest = path.partition("/")       # -> key "gameplay/minecraft:fishing/fish"
                cand = f"{kind}/{ns}:{rest}"
                if cand in self.loot and cand not in keys:
                    keys.add(cand)
                    todo.append(cand)
        return keys

    def _loot_pass(self):
        """Items dropped by sources the pack can reach: mobs in the world, blocks the player can hold, listed tables."""
        changed = False
        for key, entry in self.loot.items():
            kind, _, ident = key.partition("/")
            if kind == "entities":
                depth = 1 if ident in self.mobs else None
            elif kind == "blocks":
                d = self.items.get(ident)  # the block item: the player can place it and break it again
                depth = None if d is None else d + 1
            else:
                depth = 1 if key in self.loot_sources else None
            if depth is None:
                continue
            drops = list(entry.get("items", []))
            for tag in entry.get("tags", []):
                drops += sorted(self.tag_members(tag))[:50]
            for item in drops:
                if item not in self.items or depth < self.items[item]:
                    self.items[item] = depth
                    self.via[item] = ("loot", key, [])
                    changed = True
        return changed

    # ----- tags -----
    def tag_members(self, tag):
        if tag in self._tag_cache:
            return self._tag_cache[tag]
        members = set(self.dump_tags.get(tag, [])) | self.aliases.get(tag, set())
        members |= set(self.dump_tags.get("fluid:" + tag, []))  # fluid tags (#c:molten_*) hold fluid:<id> pseudo items
        if not members and tag in VANILLA_TAGS:
            members = self._vanilla(tag)
        if not members:
            members = self._by_name(tag)
        self._tag_cache[tag] = members
        return members

    def _vanilla(self, tag):
        out = set()
        for rule in VANILLA_TAGS[tag]:
            if "*" in rule:
                pat, _, _kind = rule.partition(":")
                suffix = pat.lstrip("*")
                out |= {i for i in self.known if i.split(":", 1)[-1].endswith(suffix) and i.startswith("minecraft:")}
            elif ":" in rule:
                out.add(rule)
            else:
                out.add("minecraft:" + rule)
        return out

    def _by_name(self, tag):
        ns, _, path = tag.partition(":")
        out = set()
        leafs = {i: i.split(":", 1)[-1] for i in self.known}
        if "/" in path:
            cat, _, mat = path.partition("/")
            word = SINGULAR.get(cat, cat.rstrip("s"))
            mat_leaf = mat.replace("/", "_")
            pats = {f"{mat_leaf}_{word}", f"{word}_{mat_leaf}"} if word else {mat_leaf}
            if cat == "gems":
                pats |= {mat_leaf}
            if cat == "storage_blocks":
                pats |= {f"{mat_leaf}_block", f"block_{mat_leaf}", f"{mat_leaf}_storage_block"}
            if cat == "raw_materials":
                pats |= {f"raw_{mat_leaf}", f"{mat_leaf}_raw", f"raw_{mat_leaf}_ore"}
            if cat == "ores":
                pats |= {f"{mat_leaf}_ore", f"deepslate_{mat_leaf}_ore", f"ore_{mat_leaf}"}
            for item, leaf in leafs.items():
                if leaf in pats:
                    out.add(item)
            return out
        # plain tags such as minecraft:logs, minecraft:planks, c:cobblestones
        base = path
        stems = {base, base.rstrip("s"), base[:-3] + "y" if base.endswith("ies") else base}
        for item, leaf in leafs.items():
            for st in stems:
                if st and (leaf == st or leaf.endswith("_" + st)):
                    out.add(item)
                    break
        return out

    # ----- closure -----
    def usable(self, recipe, result):
        need = []
        for ing in recipe["ings"]:
            if not self.strict and ing["type"] == "item" and ing["value"] == result:
                continue
            need.append(ing)
        if not need:
            return None
        depth = 0
        for ing in need:
            if ing["type"] == "item":
                d = self.items.get(ing["value"])
            else:
                ds = [self.items[m] for m in self.tag_members(ing["value"]) if m in self.items]
                d = min(ds) if ds else None
            if d is None:
                return None
            depth = max(depth, d)
        return depth + 1

    def _bucket_links(self):
        """A filled bucket stands for its fluid (ns:x_bucket <-> fluid:ns:x): pseudo items for fluids connect to items."""
        links = []
        for item in self.known:
            ns, _, name = item.partition(":")
            if name.endswith("_bucket") and name != "bucket":
                links.append((item, f"fluid:{ns}:{name[:-7]}"))
        return links

    def close(self):
        changed = True
        passes = 0
        links = self._bucket_links()
        while changed and passes < 60:
            changed = False
            passes += 1
            if self._loot_pass():
                changed = True
            for bucket, fluid in links:
                if bucket in self.items and fluid not in self.items:
                    self.items[fluid] = self.items[bucket]
                    self.via[fluid] = ("(bucket)", "", [bucket])
                    changed = True
                elif fluid in self.items and bucket not in self.items and "minecraft:bucket" in self.items:
                    self.items[bucket] = max(self.items[fluid], self.items["minecraft:bucket"]) + 1
                    self.via[bucket] = ("(fill bucket)", "", [fluid, "minecraft:bucket"])
                    changed = True
            for item, entry in self.recipes.items():
                if item in JUNK_ITEMS:
                    continue
                for r in entry["mod"]:
                    if r.get("removed") or r.get("inactive") or r["type"] in self.disabled or not r["ings"]:
                        continue
                    # Skip recipes that need a junk placeholder as an ingredient
                    if any(ing["type"] == "item" and ing["value"] in JUNK_ITEMS for ing in r["ings"]):
                        continue
                    d = self.usable(r, item)
                    if d is not None and (item not in self.items or d < self.items[item]):
                        self.items[item] = d
                        self.via[item] = (r["type"], r["jar"], [i["value"] for i in r["ings"]])
                        changed = True
        return passes

    def chain(self, item, seen=None, depth=0, lines=None):
        seen = seen if seen is not None else set()
        lines = lines if lines is not None else []
        if item in seen:
            return lines
        seen.add(item)
        if item in self.via:
            rtype, jar, ings = self.via[item]
            lines.append("  " * depth + f"{item}  <- {rtype} [{jar}]: " + ", ".join(ings))
            for ing in ings:
                if ing in self.items:
                    self.chain(ing, seen, depth + 1, lines)
                else:
                    best = next((m for m in sorted(self.tag_members(ing)) if m in self.items), None)
                    if best:
                        self.chain(best, seen, depth + 1, lines)
        else:
            lines.append("  " * depth + f"{item}  (start)")
        return lines


def targets_from(path):
    return load(path)["targets"]


def cmd_check(a):
    start, dump = load(a.start), load(a.dump)
    w = World(dump, start, a.strict)
    passes = w.close()
    ok, bad = [], []
    for t in targets_from(a.targets):
        (ok if t["id"] in w.items else bad).append(t)
    print(f"{start.get('name', a.start)}: {len(w.items)} reachable items after {passes} passes; "
          f"{len(w.known)} items known; dump has {'tag data' if w.dump_tags else 'NO tag data (name rules only)'}")
    print(f"\nREACHABLE ({len(ok)}):")
    for t in ok:
        print(f"  {t['id']:<44} depth {w.items[t['id']]:>2}  {t.get('why', '')}")
    print(f"\nNO ROUTE ({len(bad)}):")
    for t in bad:
        known = "known" if t["id"] in w.known else "NOT IN DUMP"
        print(f"  {t['id']:<44} {known:<12} {t.get('why', '')}")
    unreadable = sum(1 for e in w.recipes.values() for r in e["mod"] if not r["ings"] and not r.get("inactive"))
    inactive = sum(1 for e in w.recipes.values() for r in e["mod"] if r.get("inactive"))
    total = sum(len(e["mod"]) for e in w.recipes.values())
    print(f"\nNote: {inactive} of {total} recipes are inactive (load conditions not met) and ignored; "
          f"{unreadable} active ones have no readable ingredients and are not used as routes.")
    return 0


def cmd_why(a):
    w = World(load(a.dump), load(a.start), a.strict)
    w.close()
    if a.item not in w.items:
        print(f"{a.item}: no route from this start")
        return 1
    print(f"{a.item}: depth {w.items[a.item]}")
    print("\n".join(w.chain(a.item)))
    return 0


def cmd_blocked(a):
    w = World(load(a.dump), load(a.start), a.strict)
    w.close()
    entry = w.recipes.get(a.item)
    if not entry:
        print(f"{a.item}: not a recipe result in the dump" + (" (but reachable from the start)" if a.item in w.items else ""))
        return 1
    for r in entry["mod"]:
        if r.get("removed"):
            print(f"- {r['type']} [{r['jar']}]: removed by KubeJS")
            continue
        if r.get("inactive"):
            print(f"- {r['type']} [{r['jar']}]: inactive (load condition not met in this pack)")
            continue
        miss = []
        for ing in r["ings"]:
            if ing["type"] == "item":
                if ing["value"] not in w.items and not (not a.strict and ing["value"] == a.item):
                    miss.append(ing["value"])
            elif not any(m in w.items for m in w.tag_members(ing["value"])):
                miss.append("#" + ing["value"] + ("" if w.tag_members(ing["value"]) else " (tag has no members)"))
        state = "no readable ingredients" if not r["ings"] else ("OK" if not miss else "missing " + ", ".join(miss))
        print(f"- {r['type']} [{r['jar']}]: {state}")
    return 0


def cmd_tags(a):
    w = World(load(a.dump), load(a.start), a.strict)
    seen = collections.Counter()
    for e in w.recipes.values():
        for r in e["mod"]:
            for ing in r["ings"]:
                if ing["type"] == "tag" and not w.tag_members(ing["value"]):
                    seen[ing["value"]] += 1
    print(f"{len(seen)} ingredient tags have no members (recipes using them cannot be routes):")
    for tag, n in seen.most_common(60):
        print(f"  {n:>4}  {tag}")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dump", default=DUMP)
    p.add_argument("--strict", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("start"); c.add_argument("--targets", default=os.path.join(REACH, "targets.json")); c.set_defaults(f=cmd_check)
    y = sub.add_parser("why"); y.add_argument("start"); y.add_argument("item"); y.set_defaults(f=cmd_why)
    b = sub.add_parser("blocked"); b.add_argument("start"); b.add_argument("item"); b.set_defaults(f=cmd_blocked)
    t = sub.add_parser("tags"); t.add_argument("start"); t.set_defaults(f=cmd_tags)
    a = p.parse_args()
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
