#!/usr/bin/env python3
"""Minimal recipe JSON helpers for server-snapshot → dump conversion.

Ported from the jar scraper's parsers so this repo does not need recipe_wiki_core.
Handles: item/tag/fluid/chemical results, Ex Deorum ore_chunk (4 chunks → '#ore tag'),
Mekanism main/secondary outputs, shaped grids.
"""
from __future__ import annotations

_FLUID_LIKE = ("fluid", "chemical", "gas", "infuse_type", "slurry", "pigment")
_RESULT_KEYS = {"result", "results", "output", "outputs", "fluid_output", "fluid_result", "byproducts"}


def _stack_id(val) -> str | None:
    """Item id of a result stack, or a pseudo id for fluids and chemicals."""
    if isinstance(val, str):
        return val
    if not isinstance(val, dict):
        return None
    for key in _FLUID_LIKE:
        ref = val.get(key)
        if isinstance(ref, dict):
            ref = ref.get("id") or ref.get("fluid") or ref.get("chemical")
        if isinstance(ref, str):
            return f"{key}:{ref}"
    ref = val.get("id") or val.get("item")
    if isinstance(ref, dict):
        ref = ref.get("id") or ref.get("item") or (ref.get("tag") and "#" + ref["tag"])
    if not ref and isinstance(val.get("tag"), str):
        return "#" + val["tag"]
    if isinstance(ref, str):
        if "amount" in val and "count" not in val and "item" not in val:
            return f"fluid:{ref}"
        return ref
    for key in ("ingredient", "stack"):
        if key in val:
            return _stack_id(val[key])
    return None


def get_result_ids(data: dict) -> list[str]:
    """Every output of a recipe (items, fluids, chemicals), in order, without repeats."""
    found: list[str] = []
    rtype = data.get("type", "")
    if rtype == "exdeorum:ore_chunk" and isinstance(data.get("ore"), str):
        return ["#" + data["ore"]]
    # Fluid-producing recipes where the fluid field is the product (not an ingredient)
    if rtype in ("exdeorum:water_crucible", "exdeorum:lava_crucible") and data.get("fluid"):
        rid = _stack_id(data["fluid"])
        return [rid] if rid else []
    for key in (
        "result", "results", "output", "outputs", "main_output", "secondary_output",
        "item_output", "chemical_output", "fluid_output", "fluid_result", "byproducts",
    ):
        val = data.get(key)
        if not val:
            continue
        for v in (val if isinstance(val, list) else [val]):
            rid = _stack_id(v)
            if rid and rid not in found:
                found.append(rid)
    return found


def get_result_count(data: dict) -> int:
    for key in ("result", "results", "output"):
        val = data.get(key)
        if not val:
            continue
        if isinstance(val, list):
            val = val[0] if val else None
        if isinstance(val, dict):
            return int(val.get("count", 1))
    return 1


def norm_ing(raw, _depth: int = 0) -> dict:
    """Normalise any ingredient shape to {type, value, count}."""
    if _depth > 4:
        return {"type": "item", "value": "", "count": 1}
    if isinstance(raw, list):
        for r in raw:
            if r:
                raw = r
                break
        else:
            return {"type": "item", "value": "", "count": 1}
    if isinstance(raw, str):
        return {"type": "item", "value": raw, "count": 1}
    if not isinstance(raw, dict):
        return {"type": "item", "value": "", "count": 1}
    count = int(raw.get("count", 1))
    if "tag" in raw:
        return {"type": "tag", "value": raw["tag"], "count": count}
    val = raw.get("id") or raw.get("item")
    if val:
        return {"type": "item", "value": str(val), "count": count}
    nested = raw.get("ingredient")
    if nested and isinstance(nested, (dict, list)):
        return norm_ing(nested, _depth + 1)
    return {"type": "item", "value": "", "count": count}


def _scan_refs(node, _top: bool = True, _depth: int = 0) -> list[dict]:
    found: list[dict] = []
    if _depth > 8:
        return found
    if isinstance(node, dict):
        if not _top:
            if "tag" in node and isinstance(node["tag"], str):
                found.append({"type": "tag", "value": node["tag"], "count": int(node.get("count", 1) or 1)})
                return found
            if isinstance(node.get("item"), str):
                found.append({"type": "item", "value": node["item"], "count": int(node.get("count", 1) or 1)})
                return found
            for key in _FLUID_LIKE:
                ref = node.get(key)
                if isinstance(ref, dict):
                    ref = ref.get("id") or ref.get(key)
                if isinstance(ref, str):
                    found.append({"type": "item", "value": f"{key}:{ref}", "count": 1})
                    return found
            for key in ("Name", "id"):
                val = node.get(key)
                if isinstance(val, str) and ":" in val:
                    if val not in ("minecraft:water", "minecraft:lava"):
                        found.append({"type": "item", "value": val, "count": int(node.get("count", 1) or 1)})
                    return found
        for key, val in node.items():
            if _top and key in _RESULT_KEYS:
                continue
            found.extend(_scan_refs(val, False, _depth + 1))
    elif isinstance(node, list):
        for val in node:
            found.extend(_scan_refs(val, False, _depth + 1))
    return found


def _fluid_ing(val) -> dict | None:
    """Turn a fluid/chemical stack or tag into a pseudo-item ingredient."""
    if not val:
        return None
    if isinstance(val, dict) and isinstance(val.get("tag"), str):
        # fluid tags are still tags — reach resolves fluid:<id> members when present
        return {"type": "tag", "value": val["tag"], "count": 1}
    rid = _stack_id(val)
    if rid:
        return {"type": "item", "value": rid, "count": 1}
    return None


def ingredients_from(data: dict) -> list[dict]:
    """Return flat ingredient list from any recipe type."""
    rtype = data.get("type", "")
    out: list[dict] = []

    if rtype == "exdeorum:ore_chunk":
        chunk = data.get("ore_chunk")
        chunk = chunk.get("item") if isinstance(chunk, dict) else chunk
        return [{"type": "item", "value": chunk, "count": 4}] if isinstance(chunk, str) else []

    if rtype in ("exdeorum:barrel_mixing", "exdeorum:barrel_fluid_mixing"):
        if data.get("ingredient"):
            out.append(norm_ing(data["ingredient"]))
        for key in ("fluid", "fluid1", "fluid2"):
            fi = _fluid_ing(data.get(key))
            if fi:
                out.append(fi)
        # barrel_fluid_mixing sometimes uses additive fluids only
        out = [i for i in out if i.get("value")]
        return out or [i for i in _scan_refs(data) if i.get("value")]

    if rtype in ("exdeorum:water_crucible", "exdeorum:lava_crucible"):
        return [norm_ing(data.get("ingredient", {}))] if data.get("ingredient") else []

    if rtype == "mekanism:reaction":
        for key in ("item_input", "fluid_input", "chemical_input"):
            val = data.get(key)
            if not val:
                continue
            if key == "item_input":
                out.append(norm_ing(val))
            else:
                fi = _fluid_ing(val)
                if fi:
                    out.append(fi)
        return [i for i in out if i.get("value")]

    if "crafting_shaped" in rtype:
        pattern = data.get("pattern", [])
        key = data.get("key", {})
        seen: set[str] = set()
        for row in pattern:
            for ch in row:
                if ch != " " and ch in key and ch not in seen:
                    seen.add(ch)
                    out.append(norm_ing(key[ch]))
    elif "crafting_shapeless" in rtype:
        for ing in data.get("ingredients", []):
            out.append(norm_ing(ing))
    elif rtype in (
        "minecraft:smelting", "minecraft:blasting", "minecraft:smoking",
        "minecraft:campfire_cooking", "minecraft:stonecutting",
    ):
        out.append(norm_ing(data.get("ingredient", {})))
    else:
        for field in ("ingredients", "ingredient", "inputs", "input", "item_input"):
            val = data.get(field)
            if not val:
                continue
            if isinstance(val, list):
                for v in val:
                    out.append(norm_ing(v))
            else:
                out.append(norm_ing(val))
            break
        # Common companion fluid/chemical inputs
        for key in ("fluid_input", "chemical_input", "fluid"):
            if key in data and rtype not in ("exdeorum:water_crucible", "exdeorum:lava_crucible"):
                # Skip fluid-as-output crucibles (handled above)
                if key == "fluid" and "result" in data:
                    fi = _fluid_ing(data[key])
                    if fi:
                        out.append(fi)

    mesh = data.get("mesh")
    if mesh:
        out.append(norm_ing(mesh))
    out = [i for i in out if i.get("value")]
    if not out:
        out = [i for i in _scan_refs(data) if i.get("value")]
    return out


def shaped_grid(data: dict) -> list[list[dict | None]]:
    """Return 3×3 grid of ingredient dicts (or None for empty cells)."""
    pattern = data.get("pattern", [])
    key = data.get("key", {})
    grid: list[list[dict | None]] = []
    for row_str in pattern[:3]:
        row: list[dict | None] = []
        for ch in (row_str + "   ")[:3]:
            if ch == " " or ch not in key:
                row.append(None)
            else:
                row.append(norm_ing(key[ch]))
        grid.append(row)
    while len(grid) < 3:
        grid.append([None, None, None])
    return grid
