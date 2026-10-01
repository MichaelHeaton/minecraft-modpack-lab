#!/usr/bin/env python3
"""Config + jar economics insights for pack designers.

Scans installed mod jars (recipe filenames / light JSON) and generated server
configs to flag possible redundant generators, machine tier ladders, and
disabled / blacklisted content. No Docker required.

Usage:
  python3 scripts/insights_economics.py --pack-out out/verdant
  python3 scripts/insights_economics.py --pack-out out/verdant \\
      --mods-dir out/verdant/server/mods --config-dir out/verdant/server/config

Writes:
  out/<pack>/insights/economics.json
  out/<pack>/insights/economics.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

# --- Heuristic keywords (unverified; naming-based) --------------------------------

GENERATOR_TOKENS = (
    "generator",
    "dynamo",
    "furnator",
    "magmator",
    "solar",
    "reactor",
    "thermoelectric",
    "thermo_generator",
    "stirling",
    "alternator",
    "wind_turbine",
    "gas_burning",
    "heat_generator",
    "bio_generator",
)

# Filename / result-id patterns that look like energy producers but are usually
# parts, upgrades, or non-generators — still listed under assumptions.
GENERATOR_EXCLUDE = re.compile(
    r"(solar_panel$|"  # Mekanism solar_panel component (not the generator)
    r"solar_neutron|stone_generator|cobble.?gen|"
    r"module_.*generator|module_.*solar|upgrade/|"
    r"_casing$|_port$|_frame$|_glass$|_controller$|_valve$|_vent$|_blade$|_rotor$|"
    r"logic_adapter|fuel_assembly|control_rod|hohlraum|"
    r"electromagnetic_coil|laser_focus|saturating_condenser|"
    r"rotational_complex|chemical_infusing|activating/|rotary/|"
    r"fission_reactor|fusion_reactor|"
    r"generator_fuel|generator_base|particle_generator|"
    r"_prt_|reactor_glass|reactor_injector|reactor_stabilizer|"
    r"thermoelectric_plate|"
    r"heavy_water|turbine_|"
    r"/reactors/|extremereactors|bee_breeding|bee_conversion|bee_produce|"
    r"honeycomb_|spawn_egg|cyanite_ingot|yellorium_ingot)",
    re.I,
)

TIER_SUFFIXES = (
    ("_ultimate", "ultimate"),
    ("_elite", "elite"),
    ("_advanced", "advanced"),
    ("_basic", "basic"),
    ("_starter", "starter"),
    ("_creative", "creative"),
    ("_nitro", "nitro"),
    ("_niotic", "niotic"),
    ("_spirited", "spirited"),
    ("_blazing", "blazing"),
    ("_hardened", "hardened"),
    ("_reinforced", "reinforced"),
    ("_resonant", "resonant"),
    ("_t4", "t4"),
    ("_t3", "t3"),
    ("_t2", "t2"),
    ("_t1", "t1"),
    ("_tier4", "tier4"),
    ("_tier3", "tier3"),
    ("_tier2", "tier2"),
    ("_tier1", "tier1"),
)

CONFIG_EXTS = {".toml", ".json", ".json5", ".cfg", ".conf", ".hocon", ".properties", ".ini", ".snbt"}

# Config line heuristics — preference for JEI hide / recipe removal / machine disable.
CONFIG_INTEREST = re.compile(
    r"(?i)("
    r"jei.?hide|hide.?item|hidden.?item|ingredient.?blacklist|"
    r"recipe.?remov|remove.?recipe|disabled.?recipe|disable.?recipe|"
    r"disabled.?machine|disable.?machine|machines?.?disabled|"
    r"blacklist|black.?list|"
    r"\benabled\b.*=.*false|\bdisabled\b.*=.*true|"
    r"hideFromJEI|removeRecipes|disabledItems"
    r")"
)

# Skip noisy false-positives in comments / generic UI settings.
CONFIG_SKIP = re.compile(
    r"(?i)(display_disabled_waypoints|advancements_disabled|"
    r"itemDisplayDisabled|tickDedupeLogicDisabled|"
    r"Optimized DFU|sparkles around the multiblock|"
    r"Allowed Values:.*HIDDEN|"
    r"Replace objects used to detect)"
)

KIND_RE = re.compile(
    r"(solar|furnator|magmator|thermo|heat|bio|wind|gas.?burn|"
    r"dynamo|reactor|stirling|alternator|generator)",
    re.I,
)


def _assumptions() -> list[str]:
    return [
        "Generator detection is filename/result-id keyword based; not validated against RF/FE output.",
        "Craft-cost clustering uses ingredient slot count and shared item/tag ids only — not recursive recipe trees.",
        "Tier sibling groups are naming heuristics (_basic/_advanced/…, _t1/_t2); side-grades may be mislabeled as tiers.",
        "Config findings are regex hits on generated configs; empty blacklists and unrelated 'disabled' flags may appear.",
        "Does not require Docker; jar datapack recipes may differ from runtime KubeJS / datapack overrides.",
    ]


def _norm_stem(path_or_id: str) -> str:
    """Last path segment without .json, or item path after ns:."""
    s = path_or_id.replace("\\", "/")
    if s.endswith(".json"):
        s = s[:-5]
    if ":" in s and "/" not in s.split(":", 1)[1]:
        s = s.split(":", 1)[1]
    return s.rsplit("/", 1)[-1].lower()


def _looks_like_generator(stem: str, full_path: str = "") -> bool:
    stem_l = stem.lower()
    path_l = full_path.lower()
    if GENERATOR_EXCLUDE.search(stem_l) or (path_l and GENERATOR_EXCLUDE.search(path_l)):
        return False
    # Require a generator-ish token on the stem itself (avoids path-only hits).
    return any(tok in stem_l for tok in GENERATOR_TOKENS)


def _generator_kind(stem: str) -> str:
    m = KIND_RE.search(stem)
    if not m:
        return "other"
    raw = m.group(1).lower().replace(" ", "_")
    if "gas" in raw:
        return "gas"
    if raw in ("thermo", "thermoelectric"):
        return "thermo"
    if raw == "generator":
        # e.g. heat_generator already matched heat; plain "generator" alone
        return "generic"
    return raw


def _strip_tier(stem: str) -> tuple[str, str | None]:
    for suffix, label in TIER_SUFFIXES:
        if stem.endswith(suffix):
            return stem[: -len(suffix)], label
    return stem, None


def _ingredient_refs(node, out: set[str]) -> None:
    if isinstance(node, dict):
        if isinstance(node.get("item"), str):
            out.add("item:" + node["item"])
        if isinstance(node.get("tag"), str):
            out.add("tag:" + node["tag"])
        if isinstance(node.get("id"), str) and "result" not in node:
            # NeoForge ingredient form
            pass
        for k, v in node.items():
            if k in ("result", "results", "output", "outputs"):
                continue
            _ingredient_refs(v, out)
    elif isinstance(node, list):
        for v in node:
            _ingredient_refs(v, out)


def _result_id(data: dict) -> str | None:
    result = data.get("result")
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("id", "item"):
            if isinstance(result.get(key), str):
                return result[key]
    results = data.get("results")
    if isinstance(results, list) and results:
        first = results[0]
        if isinstance(first, dict):
            for key in ("id", "item"):
                if isinstance(first.get(key), str):
                    return first[key]
    return None


def _craft_cost(data: dict) -> dict:
    """Lightweight craft-cost fingerprint from a recipe JSON."""
    refs: set[str] = set()
    key = data.get("key")
    if isinstance(key, dict):
        _ingredient_refs(key, refs)
        pattern = data.get("pattern") or []
        cells = sum(len(row) for row in pattern if isinstance(row, str)) if isinstance(pattern, list) else 0
        # Count non-space pattern cells when possible
        filled = 0
        if isinstance(pattern, list):
            for row in pattern:
                if isinstance(row, str):
                    filled += sum(1 for ch in row if ch != " ")
        slot_count = filled or len(key)
    else:
        ings = data.get("ingredients") or data.get("ingredient")
        if ings is not None:
            _ingredient_refs(ings, refs)
        slot_count = len(refs) if refs else 0
        if isinstance(ings, list):
            slot_count = max(slot_count, len(ings))
    return {
        "ingredient_slots": slot_count,
        "unique_refs": sorted(refs),
        "ref_count": len(refs),
    }


def _is_recipe_path(name: str) -> bool:
    parts = name.replace("\\", "/").split("/")
    if len(parts) < 4 or parts[0] != "data":
        return False
    if parts[2] not in ("recipe", "recipes"):
        return False
    return name.endswith(".json") and not name.endswith(".mcmeta")


def scan_jars(mods_dir: Path) -> tuple[list[dict], list[dict], dict]:
    """Return (generators, all_tiered_items, stats)."""
    generators: list[dict] = []
    tiered: list[dict] = []
    stats = {
        "jars_scanned": 0,
        "jars_failed": 0,
        "recipe_files": 0,
        "recipes_parsed": 0,
        "recipes_parse_failed": 0,
    }

    if not mods_dir.is_dir():
        return generators, tiered, stats

    for jar_path in sorted(mods_dir.glob("*.jar")):
        stats["jars_scanned"] += 1
        try:
            zf = zipfile.ZipFile(jar_path)
        except (zipfile.BadZipFile, OSError):
            stats["jars_failed"] += 1
            continue
        with zf:
            for name in zf.namelist():
                if not _is_recipe_path(name):
                    continue
                stats["recipe_files"] += 1
                stem = _norm_stem(name)
                parts = name.split("/")
                ns = parts[1] if len(parts) > 1 else "?"
                recipe_id = f"{ns}:{'/'.join(parts[3:])[:-5]}"

                is_gen = _looks_like_generator(stem, name)
                base, tier = _strip_tier(stem)
                want_parse = is_gen or tier is not None
                cost = None
                result = None
                rtype = None
                if want_parse:
                    try:
                        raw = zf.read(name)
                        data = json.loads(raw.decode("utf-8"))
                        stats["recipes_parsed"] += 1
                        cost = _craft_cost(data)
                        result = _result_id(data)
                        rtype = data.get("type")
                    except (ValueError, UnicodeDecodeError, KeyError, OSError):
                        stats["recipes_parse_failed"] += 1

                entry = {
                    "recipe_id": recipe_id,
                    "stem": stem,
                    "namespace": ns,
                    "jar": jar_path.name,
                    "path": name,
                    "result": result,
                    "type": rtype,
                    "craft": cost,
                }
                if is_gen:
                    entry["kind"] = _generator_kind(stem)
                    generators.append(entry)
                if tier is not None:
                    tiered.append(
                        {
                            **entry,
                            "family": base,
                            "tier": tier,
                        }
                    )

    return generators, tiered, stats


def cluster_generators(generators: list[dict], min_size: int = 3) -> list[dict]:
    """Cluster generators by kind + similar craft cost; flag groups of min_size+.

    A cluster is only flagged as possible redundancy when it spans more than one
    namespace or more than one stem-family (same-mod tier ladders alone are not
    treated as redundant).
    """
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for g in generators:
        by_kind[g.get("kind") or "other"].append(g)

    clusters: list[dict] = []
    for kind, items in sorted(by_kind.items()):
        seen: set[str] = set()
        uniq: list[dict] = []
        for g in items:
            key = (g.get("result") or g["stem"]).lower()
            if key in seen:
                continue
            seen.add(key)
            uniq.append(g)

        used = [False] * len(uniq)
        for i, a in enumerate(uniq):
            if used[i]:
                continue
            group = [a]
            used[i] = True
            a_slots = (a.get("craft") or {}).get("ingredient_slots") or 0
            a_refs = set((a.get("craft") or {}).get("unique_refs") or [])
            a_family, _ = _strip_tier(a["stem"])
            for j in range(i + 1, len(uniq)):
                if used[j]:
                    continue
                b = uniq[j]
                b_slots = (b.get("craft") or {}).get("ingredient_slots") or 0
                b_refs = set((b.get("craft") or {}).get("unique_refs") or [])
                b_family, _ = _strip_tier(b["stem"])
                slot_ok = abs(a_slots - b_slots) <= 2
                shared = len(a_refs & b_refs)
                ma, mb = KIND_RE.search(a["stem"]), KIND_RE.search(b["stem"])
                name_ok = a_family == b_family or (
                    bool(ma and mb) and ma.group(1).lower() == mb.group(1).lower()
                )
                cross_mod = a.get("namespace") != b.get("namespace")
                if slot_ok and (shared >= 1 or name_ok or (cross_mod and a_slots > 0)):
                    group.append(b)
                    used[j] = True
            if len(group) < min_size:
                continue
            namespaces = sorted({g.get("namespace") or "?" for g in group})
            families = sorted({_strip_tier(g["stem"])[0] for g in group})
            # Same-mod single family = tier ladder, not redundancy.
            if len(namespaces) < 2 and len(families) < 2:
                continue
            clusters.append(
                {
                    "kind": kind,
                    "reason": "similar craft cost and/or naming within generator kind",
                    "size": len(group),
                    "namespaces": namespaces,
                    "families": families,
                    "members": [
                        {
                            "result": g.get("result") or g["stem"],
                            "recipe_id": g["recipe_id"],
                            "namespace": g.get("namespace"),
                            "ingredient_slots": (g.get("craft") or {}).get("ingredient_slots"),
                            "ref_count": (g.get("craft") or {}).get("ref_count"),
                            "jar": g.get("jar"),
                        }
                        for g in group
                    ],
                    "flag": "possible_redundant_generators",
                    "verified": False,
                }
            )
    clusters.sort(key=lambda c: (-c["size"], c["kind"]))
    return clusters


def detect_tier_groups(tiered: list[dict], min_tiers: int = 2) -> list[dict]:
    """Group items that share a stem family with different tier suffixes."""
    by_family: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
    for t in tiered:
        ns = t.get("namespace") or "?"
        family = t["family"]
        # Prefer result id for display; key by family within namespace
        key = (ns, family)
        tier = t["tier"]
        # Keep one recipe per tier (first wins)
        if tier not in by_family[key]:
            by_family[key][tier] = t

    groups: list[dict] = []
    for (ns, family), tiers in sorted(by_family.items()):
        if len(tiers) < min_tiers:
            continue
        members = []
        for tier, t in sorted(tiers.items(), key=lambda kv: kv[0]):
            members.append(
                {
                    "tier": tier,
                    "stem": t["stem"],
                    "result": t.get("result"),
                    "recipe_id": t["recipe_id"],
                    "ingredient_slots": (t.get("craft") or {}).get("ingredient_slots"),
                }
            )
        groups.append(
            {
                "namespace": ns,
                "family": family,
                "tier_count": len(members),
                "tiers": [m["tier"] for m in members],
                "members": members,
                "verified": False,
            }
        )
    groups.sort(key=lambda g: (-g["tier_count"], g["namespace"], g["family"]))
    return groups


def _config_snippet(line: str, max_len: int = 160) -> str:
    s = line.strip()
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def scan_configs(config_dir: Path, max_hits: int = 200) -> list[dict]:
    findings: list[dict] = []
    if not config_dir.is_dir():
        return findings

    for path in sorted(config_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in CONFIG_EXTS and path.suffix != "":
            # allow extensionless rarely; skip binaries
            if path.suffix.lower() in {".jar", ".png", ".jpg", ".zip", ".nbt", ".dat"}:
                continue
            if path.suffix and path.suffix.lower() not in CONFIG_EXTS:
                continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(path.relative_to(config_dir))
        for i, line in enumerate(text.splitlines(), start=1):
            if not CONFIG_INTEREST.search(line):
                continue
            if CONFIG_SKIP.search(line):
                continue
            # Prefer non-empty / non-default-looking hits but keep empties with note
            snippet = _config_snippet(line)
            category = "blacklist"
            low = line.lower()
            if any(x in low for x in ("jei", "hide", "hidden")):
                category = "jei_hide"
            elif any(x in low for x in ("recipe", "removerecipe")):
                category = "recipe_removal"
            elif any(x in low for x in ("machine", "enabled", "disabled")):
                category = "disabled_flag"
            findings.append(
                {
                    "file": rel,
                    "line": i,
                    "category": category,
                    "snippet": snippet,
                    "verified": False,
                }
            )
            if len(findings) >= max_hits:
                return findings
    return findings


def build_report(
    pack_out: Path,
    mods_dir: Path,
    config_dir: Path,
) -> dict:
    generators, tiered, jar_stats = scan_jars(mods_dir)
    clusters = cluster_generators(generators, min_size=3)
    tier_groups = detect_tier_groups(tiered, min_tiers=2)
    config_hits = scan_configs(config_dir)

    # Summary counts
    gen_by_kind: dict[str, int] = defaultdict(int)
    for g in generators:
        gen_by_kind[g.get("kind") or "other"] += 1

    return {
        "schema": "modpack-lab.insights.economics/v1",
        "pack_out": str(pack_out),
        "mods_dir": str(mods_dir),
        "config_dir": str(config_dir),
        "assumptions": _assumptions(),
        "verified": False,
        "stats": {
            **jar_stats,
            "generators_found": len(generators),
            "generator_kinds": dict(sorted(gen_by_kind.items(), key=lambda kv: -kv[1])),
            "redundant_generator_clusters": len(clusters),
            "tier_groups": len(tier_groups),
            "config_hits": len(config_hits),
            "mods_dir_exists": mods_dir.is_dir(),
            "config_dir_exists": config_dir.is_dir(),
        },
        "generators": [
            {
                "result": g.get("result") or g["stem"],
                "kind": g.get("kind"),
                "recipe_id": g["recipe_id"],
                "namespace": g.get("namespace"),
                "ingredient_slots": (g.get("craft") or {}).get("ingredient_slots"),
                "ref_count": (g.get("craft") or {}).get("ref_count"),
                "shared_tags_sample": [
                    r for r in ((g.get("craft") or {}).get("unique_refs") or []) if r.startswith("tag:")
                ][:6],
                "jar": g.get("jar"),
            }
            for g in generators
        ],
        "redundant_generator_clusters": clusters,
        "machine_tier_groups": tier_groups,
        "config_disabled_or_blacklist": config_hits,
    }


def render_markdown(report: dict) -> str:
    s = report["stats"]
    lines = [
        "# Economics insights",
        "",
        f"Pack out: `{report['pack_out']}`",
        "",
        "## Summary",
        "",
        f"- Jars scanned: **{s.get('jars_scanned', 0)}** ({s.get('recipe_files', 0)} recipe files)",
        f"- Generators (heuristic): **{s.get('generators_found', 0)}**",
        f"- Possible redundant generator clusters (3+): **{s.get('redundant_generator_clusters', 0)}**",
        f"- Machine tier groups: **{s.get('tier_groups', 0)}**",
        f"- Config blacklist / disable hits: **{s.get('config_hits', 0)}**",
        "",
        "> Unverified naming/config heuristics — see `assumptions` in economics.json.",
        "",
    ]
    kinds = s.get("generator_kinds") or {}
    if kinds:
        lines.append("### Generator kinds")
        lines.append("")
        for k, n in kinds.items():
            lines.append(f"- `{k}`: {n}")
        lines.append("")

    clusters = report.get("redundant_generator_clusters") or []
    if clusters:
        lines.append("## Possible redundant generators")
        lines.append("")
        for c in clusters[:20]:
            lines.append(
                f"- **{c['kind']}** ×{c['size']} across {', '.join('`'+n+'`' for n in c['namespaces'])}"
            )
            for m in c["members"][:8]:
                slots = m.get("ingredient_slots")
                lines.append(
                    f"  - `{m['result']}` (slots={slots}, ns=`{m.get('namespace')}`)"
                )
            if len(c["members"]) > 8:
                lines.append(f"  - … +{len(c['members']) - 8} more")
        lines.append("")

    tiers = report.get("machine_tier_groups") or []
    if tiers:
        lines.append("## Machine tier ladders (sample)")
        lines.append("")
        for g in tiers[:25]:
            lines.append(
                f"- `{g['namespace']}:{g['family']}` → {', '.join(g['tiers'])}"
            )
        if len(tiers) > 25:
            lines.append(f"- … +{len(tiers) - 25} more families")
        lines.append("")

    hits = report.get("config_disabled_or_blacklist") or []
    if hits:
        lines.append("## Config: disabled / blacklist / JEI (sample)")
        lines.append("")
        for h in hits[:30]:
            lines.append(f"- `{h['file']}:{h['line']}` [{h['category']}] {h['snippet']}")
        if len(hits) > 30:
            lines.append(f"- … +{len(hits) - 30} more")
        lines.append("")

    if not s.get("mods_dir_exists"):
        lines.append("**Note:** mods dir missing — re-run after `make dump`.")
        lines.append("")
    if not s.get("config_dir_exists"):
        lines.append("**Note:** config dir missing — configs appear after a server dump.")
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--pack-out",
        required=True,
        help="Pack output directory, e.g. out/verdant",
    )
    ap.add_argument("--mods-dir", default="", help="Override mods dir (default: <pack-out>/server/mods)")
    ap.add_argument(
        "--config-dir",
        default="",
        help="Override config dir (default: <pack-out>/server/config)",
    )
    ap.add_argument(
        "--out-dir",
        default="",
        help="Insights output dir (default: <pack-out>/insights)",
    )
    args = ap.parse_args()

    pack_out = Path(args.pack_out)
    mods_dir = Path(args.mods_dir) if args.mods_dir else pack_out / "server" / "mods"
    config_dir = Path(args.config_dir) if args.config_dir else pack_out / "server" / "config"
    out_dir = Path(args.out_dir) if args.out_dir else pack_out / "insights"
    out_dir.mkdir(parents=True, exist_ok=True)

    report = build_report(pack_out, mods_dir, config_dir)
    json_path = out_dir / "economics.json"
    md_path = out_dir / "economics.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")

    s = report["stats"]
    print(
        f"economics → {json_path}  "
        f"gens={s.get('generators_found', 0)} "
        f"clusters={s.get('redundant_generator_clusters', 0)} "
        f"tiers={s.get('tier_groups', 0)} "
        f"config={s.get('config_hits', 0)}",
        file=sys.stderr,
    )
    print(md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
