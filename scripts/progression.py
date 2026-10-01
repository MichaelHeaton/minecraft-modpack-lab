#!/usr/bin/env python3
"""Progression / quest-chart export from reach depths + mod namespaces.

Clusters reachable items into mod “chapters”, orders chapters by how early their
design targets unlock, and flags pack-authored-only unlocks.

Usage:
  python3 scripts/progression.py --pack verdant
  # uses profiles/verdant.json + out/verdant/recipe_data.json
  # writes out/verdant/insights/progression.{json,md}
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from profile import format_world, load_profile  # noqa: E402
from series_reach import World, targets_from  # noqa: E402


def _ns(item_id: str) -> str:
    if item_id.startswith(("fluid:", "chemical:")):
        # fluid:minecraft:water → minecraft; chemical:mekanism:oxygen → mekanism
        rest = item_id.split(":", 1)[1]
        return rest.split(":", 1)[0] if ":" in rest else rest
    return item_id.split(":", 1)[0] if ":" in item_id else item_id


def _active_routes(dump: dict, item: str) -> list[dict]:
    bucket = (dump.get("recipes") or {}).get(item) or {}
    out = []
    for e in bucket.get("mod") or []:
        if e.get("removed") or e.get("inactive") or not e.get("ings"):
            continue
        out.append(e)
    return out


def _pack_only(dump: dict, item: str) -> bool:
    """True when every active recipe route for this item is pack-authored."""
    routes = _active_routes(dump, item)
    if not routes:
        return False
    return all(e.get("origin") == "pack" for e in routes)


def _median(depths: list[int]) -> float | None:
    if not depths:
        return None
    return float(statistics.median(depths))


def build_progression(pack_id: str, dump_path: Path) -> dict:
    profile = load_profile(pack_id)
    start = json.loads(Path(profile["start"]).read_text(encoding="utf-8"))
    targets = targets_from(profile["targets"])
    dump = json.loads(dump_path.read_text(encoding="utf-8"))

    w = World(dump, start)
    passes = w.close()

    target_by_id = {t["id"]: t for t in targets}
    target_ids = set(target_by_id)

    reachable_ok = [t for t in targets if t["id"] in w.items]
    blocked = [t for t in targets if t["id"] not in w.items]

    # Cluster every reachable item by mod namespace
    by_ns: dict[str, list[str]] = defaultdict(list)
    for item in w.items:
        by_ns[_ns(item)].append(item)

    chapters = []
    for ns, items in by_ns.items():
        items_sorted = sorted(items, key=lambda i: (w.items[i], i))
        chapter_targets = [i for i in items_sorted if i in target_ids]
        # Design targets first, then other items by depth
        other = [i for i in items_sorted if i not in target_ids]
        ordered = chapter_targets + other

        target_depths = [w.items[i] for i in chapter_targets]
        all_depths = [w.items[i] for i in items_sorted]
        pack_flagged = [i for i in ordered if _pack_only(dump, i)]

        entry_items = []
        for item in ordered:
            via = w.via.get(item)
            entry_items.append({
                "id": item,
                "depth": w.items[item],
                "via_type": via[0] if via else None,
                "is_target": item in target_ids,
                "why": (target_by_id[item].get("why") or "") if item in target_ids else "",
                "pack_authored_only": item in pack_flagged,
            })

        chapters.append({
            "mod": ns,
            "item_count": len(items_sorted),
            "target_count": len(chapter_targets),
            "min_depth": min(all_depths) if all_depths else None,
            "median_target_depth": _median(target_depths),
            "median_item_depth": _median(all_depths),
            "pack_authored_only_count": len(pack_flagged),
            "targets": [
                {
                    "id": i,
                    "depth": w.items[i],
                    "via_type": (w.via[i][0] if i in w.via else None),
                    "why": target_by_id[i].get("why", ""),
                    "pack_authored_only": _pack_only(dump, i),
                }
                for i in chapter_targets
            ],
            # Cap bulk item list in JSON so files stay usable; full order still in md summary
            "items": entry_items[:80],
            "items_truncated": max(0, len(entry_items) - 80),
        })

    # Quest chapter order: mods with design targets first (low median target depth → late),
    # then remaining mods by median item depth.
    def chapter_sort_key(ch: dict):
        has_targets = 0 if ch["target_count"] else 1
        med_t = ch["median_target_depth"]
        med_i = ch["median_item_depth"]
        # Chapters with targets: sort by median target depth; without: after, by item median
        primary = med_t if med_t is not None else (med_i if med_i is not None else 9999.0)
        return (has_targets, primary, ch["mod"])

    chapters.sort(key=chapter_sort_key)

    suggested_order = [
        {
            "rank": i + 1,
            "mod": ch["mod"],
            "median_target_depth": ch["median_target_depth"],
            "median_item_depth": ch["median_item_depth"],
            "target_count": ch["target_count"],
            "item_count": ch["item_count"],
        }
        for i, ch in enumerate(chapters)
        if ch["target_count"] > 0 or ch["item_count"] >= 5
    ]

    blocked_out = []
    for t in blocked:
        routes = _active_routes(dump, t["id"])
        blocked_out.append({
            "id": t["id"],
            "why": t.get("why", ""),
            "known_in_dump": t["id"] in w.known,
            "recipe_count": len(routes),
            "origins": sorted({e.get("origin") or "?" for e in routes}),
            "note": "blocked / needs pack script",
        })

    return {
        "pack": pack_id,
        "label": profile.get("label", pack_id),
        "world": format_world(profile["world"]),
        "notes": profile.get("notes") or "",
        "dump": str(dump_path),
        "passes": passes,
        "reachable_items": len(w.items),
        "targets_ok": len(reachable_ok),
        "targets_blocked": len(blocked),
        "chapter_count": len(chapters),
        "suggested_quest_order": suggested_order,
        "chapters": chapters,
        "blocked_targets": blocked_out,
    }


def render_markdown(data: dict) -> str:
    lines: list[str] = []
    lines.append(f"# Progression — {data['label']}")
    lines.append("")
    lines.append(f"world: {data['world']}")
    if data.get("notes"):
        lines.append(f"notes: {data['notes']}")
    lines.append(
        f"reachable: {data['reachable_items']} items after {data['passes']} passes; "
        f"targets {data['targets_ok']} ok / {data['targets_blocked']} blocked; "
        f"{data['chapter_count']} mod chapters"
    )
    lines.append("")

    lines.append("## Suggested quest chapter order")
    lines.append("")
    lines.append("Early → late by median depth of design targets (mods without targets omitted unless large).")
    lines.append("")
    for entry in data["suggested_quest_order"]:
        if entry["target_count"]:
            med = entry["median_target_depth"]
            med_s = f"{med:.1f}" if med is not None else "?"
            lines.append(
                f"{entry['rank']:>3}. **{entry['mod']}** — "
                f"median target depth {med_s}, "
                f"{entry['target_count']} target(s), {entry['item_count']} items"
            )
        else:
            med = entry["median_item_depth"]
            med_s = f"{med:.1f}" if med is not None else "?"
            lines.append(
                f"{entry['rank']:>3}. {entry['mod']} — "
                f"median item depth {med_s}, {entry['item_count']} items (no design targets)"
            )
    lines.append("")

    lines.append("## Chapters (targets first within each mod)")
    lines.append("")
    for ch in data["chapters"]:
        if not ch["target_count"] and ch["item_count"] < 5:
            continue
        med_t = ch["median_target_depth"]
        med_s = f"{med_t:.1f}" if med_t is not None else "—"
        lines.append(f"### {ch['mod']}")
        lines.append(
            f"items={ch['item_count']}, targets={ch['target_count']}, "
            f"min_depth={ch['min_depth']}, median_target_depth={med_s}"
        )
        if ch["pack_authored_only_count"]:
            lines.append(
                f"pack-authored-only unlocks: {ch['pack_authored_only_count']}"
            )
        lines.append("")
        if ch["targets"]:
            lines.append("Design targets:")
            for t in ch["targets"]:
                via = t["via_type"] or "start"
                pack = "  [pack-authored only]" if t.get("pack_authored_only") else ""
                why = f"  — {t['why']}" if t.get("why") else ""
                lines.append(
                    f"  - `{t['id']}` depth {t['depth']} via {via}{pack}{why}"
                )
            lines.append("")
        # Sample early items beyond targets
        extras = [it for it in ch["items"] if not it["is_target"]][:12]
        if extras:
            lines.append("Early unlocks (sample):")
            for it in extras:
                via = it["via_type"] or "start"
                pack = "  [pack-authored only]" if it.get("pack_authored_only") else ""
                lines.append(f"  - `{it['id']}` depth {it['depth']} via {via}{pack}")
            if ch.get("items_truncated") or len([i for i in ch["items"] if not i["is_target"]]) > 12:
                more = ch.get("items_truncated", 0) + max(
                    0, len([i for i in ch["items"] if not i["is_target"]]) - 12
                )
                if more:
                    lines.append(f"  - … +{more} more")
            lines.append("")

    lines.append("## Blocked / needs pack script")
    lines.append("")
    if not data["blocked_targets"]:
        lines.append("(none — all design targets reachable)")
    else:
        for t in data["blocked_targets"]:
            known = "known" if t["known_in_dump"] else "NOT IN DUMP"
            origins = ",".join(t["origins"]) if t["origins"] else "no recipes"
            why = f" — {t['why']}" if t.get("why") else ""
            lines.append(f"- `{t['id']}` ({known}; routes={t['recipe_count']} [{origins}]){why}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pack", required=True, help="pack id (profiles/<id>.json)")
    ap.add_argument(
        "--dump",
        default="",
        help="recipe_data.json (default: out/<pack>/recipe_data.json)",
    )
    ap.add_argument(
        "--out-dir",
        default="",
        help="insights dir (default: out/<pack>/insights)",
    )
    a = ap.parse_args()

    dump_path = Path(a.dump) if a.dump else ROOT / "out" / a.pack / "recipe_data.json"
    if not dump_path.exists():
        print(
            f"no dump at {dump_path}; run: make dump PACK={a.pack} EULA=1",
            file=sys.stderr,
        )
        return 1

    out_dir = Path(a.out_dir) if a.out_dir else ROOT / "out" / a.pack / "insights"
    out_dir.mkdir(parents=True, exist_ok=True)

    data = build_progression(a.pack, dump_path)
    json_path = out_dir / "progression.json"
    md_path = out_dir / "progression.md"
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(data), encoding="utf-8")

    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(
        f"chapters={data['chapter_count']} "
        f"targets_ok={data['targets_ok']}/{data['targets_ok'] + data['targets_blocked']} "
        f"blocked={data['targets_blocked']}"
    )
    # Top chapters with design targets
    top = [e for e in data["suggested_quest_order"] if e["target_count"]][:8]
    if top:
        print("top chapters (by target depth):")
        for e in top:
            med = e["median_target_depth"]
            med_s = f"{med:.1f}" if med is not None else "?"
            print(f"  {e['rank']}. {e['mod']}  median_target={med_s}  targets={e['target_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
