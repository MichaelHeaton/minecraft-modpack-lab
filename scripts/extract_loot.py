#!/usr/bin/env python3
"""Extract loot tables and NeoForge global loot modifiers from installed mod/Minecraft jars.

Merges into the dump format series_reach expects:
  loot["entities/minecraft:zombie"] = {"items": [...], "tags": [...], "tables": [...]}

GLMs of type neoforge:add_table fold extra tables into the targeted loot keys so mob/chest
drops from modifiers (Silent Gear silk, Farmer's Delight chest injects, …) become reachable.

Usage:
  python3 scripts/extract_loot.py --mods-dir out/verdant/server/mods \\
      [--vanilla-jar out/verdant/server/libraries/.../server-*-extra.jar] \\
      --out out/verdant/loot.json
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

# Primary kinds reach cares about; other folders (drops/, equipment/, …) are still indexed
# so GLM-added tables resolve.
PRIMARY_KINDS = ("blocks", "entities", "gameplay", "chests", "archaeology", "pots", "shearing")


def _loot_refs(node, out: dict) -> None:
    if isinstance(node, dict):
        et = node.get("type", "")
        if et == "minecraft:item" and isinstance(node.get("name"), str):
            out["items"].add(node["name"])
        elif et == "minecraft:tag" and isinstance(node.get("name"), str):
            out["tags"].add(node["name"])
        elif et == "minecraft:loot_table":
            ref = node.get("value") or node.get("name")
            if isinstance(ref, str):
                out["tables"].add(ref)
        for key, val in node.items():
            if key in ("conditions", "functions"):
                continue
            _loot_refs(val, out)
    elif isinstance(node, list):
        for val in node:
            _loot_refs(val, out)


def _table_id_to_key(table_id: str) -> str | None:
    """minecraft:entities/zombie → entities/minecraft:zombie"""
    if ":" not in table_id:
        return None
    ns, _, path = table_id.partition(":")
    kind, _, rest = path.partition("/")
    if not kind or not rest:
        return f"other/{ns}:{path}"
    return f"{kind}/{ns}:{rest}"


def _path_to_key(parts: list[str]) -> str | None:
    """data/ns/loot_table/kind/rest.json → kind/ns:rest"""
    # parts: data, ns, loot_table|loot_tables, ...
    if len(parts) < 5 or parts[0] != "data" or not parts[-1].endswith(".json"):
        return None
    if parts[2] not in ("loot_table", "loot_tables"):
        return None
    ns = parts[1]
    kind = parts[3]
    rest = "/".join(parts[4:])[:-5]
    return f"{kind}/{ns}:{rest}"


def _merge_entry(loot: dict, key: str, found: dict) -> None:
    entry = loot.setdefault(key, {"items": set(), "tags": set(), "tables": set()})
    for k in ("items", "tags", "tables"):
        entry[k] |= found[k]


def extract_loot_tables(jars: list[Path]) -> dict[str, dict]:
    loot: dict[str, dict] = {}
    for jar_path in jars:
        try:
            with zipfile.ZipFile(jar_path) as zf:
                for name in zf.namelist():
                    parts = name.split("/")
                    key = _path_to_key(parts)
                    if not key:
                        continue
                    try:
                        data = json.loads(zf.read(name).decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        continue
                    found = {"items": set(), "tags": set(), "tables": set()}
                    _loot_refs(data.get("pools", data), found)
                    if not any(found.values()):
                        continue
                    _merge_entry(loot, key, found)
        except (zipfile.BadZipFile, OSError):
            continue
    return loot


def _collect_loot_table_ids(node, out: set[str]) -> None:
    if isinstance(node, dict):
        if isinstance(node.get("loot_table_id"), str):
            out.add(node["loot_table_id"])
        for val in node.values():
            _collect_loot_table_ids(val, out)
    elif isinstance(node, list):
        for val in node:
            _collect_loot_table_ids(val, out)


def _glm_items(data: dict) -> set[str]:
    """Item ids listed directly on a modifier (common add_item shapes)."""
    found: set[str] = set()
    for key in ("item", "addition", "additions"):
        val = data.get(key)
        if isinstance(val, str) and ":" in val:
            found.add(val)
        elif isinstance(val, dict):
            iid = val.get("id") or val.get("item")
            if isinstance(iid, str):
                found.add(iid)
        elif isinstance(val, list):
            for v in val:
                if isinstance(v, str) and ":" in v:
                    found.add(v)
                elif isinstance(v, dict):
                    iid = v.get("id") or v.get("item")
                    if isinstance(iid, str):
                        found.add(iid)
    return found


def extract_glms(jars: list[Path], loot: dict[str, dict]) -> dict:
    """Apply NeoForge global loot modifiers into the loot map. Returns stats."""
    active: set[str] = set()
    modifiers: dict[str, dict] = {}  # id → json
    stats = {"glm_files": 0, "glm_applied": 0, "glm_skipped": 0}

    for jar_path in jars:
        try:
            with zipfile.ZipFile(jar_path) as zf:
                for name in zf.namelist():
                    if name.endswith("neoforge/loot_modifiers/global_loot_modifiers.json"):
                        try:
                            g = json.loads(zf.read(name).decode("utf-8"))
                        except (ValueError, UnicodeDecodeError):
                            continue
                        for entry in g.get("entries") or []:
                            if isinstance(entry, str):
                                active.add(entry)
                    if "/loot_modifiers/" in name and name.endswith(".json") and not name.endswith(
                        "global_loot_modifiers.json"
                    ):
                        parts = name.split("/")
                        # data/ns/loot_modifiers/rest.json → ns:rest
                        if len(parts) < 4 or parts[0] != "data":
                            continue
                        ns = parts[1]
                        rest = "/".join(parts[3:])[:-5]
                        mid = f"{ns}:{rest}"
                        try:
                            modifiers[mid] = json.loads(zf.read(name).decode("utf-8"))
                        except (ValueError, UnicodeDecodeError):
                            continue
                        stats["glm_files"] += 1
        except (zipfile.BadZipFile, OSError):
            continue

    # If no global list found, treat every discovered modifier as active
    if not active:
        active = set(modifiers)

    for mid in sorted(active):
        data = modifiers.get(mid)
        if not data:
            stats["glm_skipped"] += 1
            continue
        targets: set[str] = set()
        _collect_loot_table_ids(data.get("conditions"), targets)
        added_table = data.get("table")
        direct_items = _glm_items(data)
        if not targets and not added_table and not direct_items:
            stats["glm_skipped"] += 1
            continue
        for tid in targets:
            key = _table_id_to_key(tid)
            if not key:
                continue
            entry = loot.setdefault(key, {"items": set(), "tags": set(), "tables": set()})
            if isinstance(added_table, str):
                entry["tables"].add(added_table)
                # Also fold resolved items if we already extracted that table
                ref_key = _table_id_to_key(added_table)
                # added tables often live under drops/ — try multiple key shapes
                candidates = []
                if ref_key:
                    candidates.append(ref_key)
                ns, _, path = added_table.partition(":")
                candidates.append(f"drops/{ns}:{path}")
                candidates.append(f"gameplay/{ns}:{path}")
                for ck in candidates:
                    if ck in loot:
                        entry["items"] |= set(loot[ck].get("items", []))
                        entry["tags"] |= set(loot[ck].get("tags", []))
                        entry["tables"] |= set(loot[ck].get("tables", []))
            entry["items"] |= direct_items
            stats["glm_applied"] += 1
        if not targets and direct_items:
            # Untargeted add — stash under gameplay/glm:<id>
            key = f"gameplay/glm:{mid}"
            entry = loot.setdefault(key, {"items": set(), "tags": set(), "tables": set()})
            entry["items"] |= direct_items
            stats["glm_applied"] += 1

    return stats


def freeze(loot: dict) -> dict:
    return {
        k: {f: sorted(v) for f, v in e.items() if v}
        for k, e in sorted(loot.items())
        if any(e.values())
    }


def find_vanilla_jars(server_dir: Path) -> list[Path]:
    libs = server_dir / "libraries" / "net" / "minecraft" / "server"
    found: list[Path] = []
    if libs.is_dir():
        for p in libs.rglob("*-extra.jar"):
            found.append(p)
        for p in libs.rglob("server-1.21*.jar"):
            if "slim" not in p.name and "srg" not in p.name and "unpacked" not in p.name:
                found.append(p)
    return found


def extract(mods_dir: Path, extra_jars: list[Path] | None = None) -> tuple[dict, dict]:
    jars = sorted(mods_dir.glob("*.jar"))
    if extra_jars:
        jars = list(extra_jars) + jars
    loot = extract_loot_tables(jars)
    stats = extract_glms(jars, loot)
    # Resolve one level of table refs into items for primary entity/chest keys
    for key, entry in list(loot.items()):
        kind = key.split("/", 1)[0]
        if kind not in PRIMARY_KINDS:
            continue
        for ref in list(entry.get("tables", [])):
            rk = _table_id_to_key(ref)
            candidates = [rk, f"drops/{ref.replace(':', ':', 1)}"]
            ns, _, path = ref.partition(":")
            candidates += [f"drops/{ns}:{path}", f"gameplay/{ns}:{path}", f"chests/{ns}:{path}"]
            for ck in candidates:
                if ck and ck in loot:
                    entry["items"] = set(entry.get("items", [])) | set(loot[ck].get("items", []))
                    entry["tags"] = set(entry.get("tags", [])) | set(loot[ck].get("tags", []))
    stats["loot_tables"] = len(loot)
    return freeze(loot), stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mods-dir", required=True)
    ap.add_argument("--server-dir", default="", help="server root (finds vanilla *-extra.jar)")
    ap.add_argument("--vanilla-jar", action="append", default=[])
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    mods = Path(a.mods_dir)
    extras = [Path(p) for p in a.vanilla_jar]
    if a.server_dir:
        extras.extend(find_vanilla_jars(Path(a.server_dir)))
    loot, stats = extract(mods, extras or None)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(loot, indent=2), encoding="utf-8")
    print(
        f"wrote {a.out}: {stats.get('loot_tables', 0)} loot keys; "
        f"GLMs applied={stats.get('glm_applied', 0)} skipped={stats.get('glm_skipped', 0)} "
        f"files={stats.get('glm_files', 0)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
