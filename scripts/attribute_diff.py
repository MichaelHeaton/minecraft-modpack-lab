#!/usr/bin/env python3
"""Attribute why pack A unlocks what B does not — at the *source file* level.

Diffs registered packwiz trees (mods, kubejs scripts/datapacks) and optional
server configs from dumps. Complements recipe-id compare: this points at files
to copy (e.g. kubejs/data/cpverdant/recipe/sieve_*.json).

Usage:
  python3 scripts/attribute_diff.py --a verdant --b liminal
  make attribute A=verdant B=liminal

Writes:
  out/diffs/<a>-vs-<b>/attribute.json
  out/diffs/<a>-vs-<b>/attribute.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from packs import load_packs  # noqa: E402

SKIP_DIR_NAMES = {".git", ".cache", "node_modules", "__pycache__", ".DS_Store"}
SKIP_FILE_NAMES = {".DS_Store", "README.md", "thumbs.db"}
CONFIG_HINT = re.compile(
    r"(disable|enabled\s*=\s*false|blacklist|hidden|jei\.|emi\.|remov)",
    re.I,
)


def _pack_entry(pack_id: str) -> dict:
    packs = load_packs()
    if pack_id not in packs:
        raise SystemExit(
            f"unknown pack id '{pack_id}'. Register with: make add DIR=/path/to/pack"
        )
    path = Path(packs[pack_id]["path"])
    if not path.is_dir():
        raise SystemExit(f"pack path missing: {path}")
    return {"id": pack_id, "path": path, "label": packs[pack_id].get("label") or pack_id}


def _rel_files(root: Path, sub: str) -> dict[str, str]:
    """Map relative posix path → sha256 hex (empty string if unreadable)."""
    base = root / sub
    out: dict[str, str] = {}
    if not base.is_dir():
        return out
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in p.parts):
            continue
        if p.name in SKIP_FILE_NAMES or p.name.startswith("."):
            continue
        rel = p.relative_to(root).as_posix()
        try:
            digest = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        except OSError:
            digest = ""
        out[rel] = digest
    return out


def _mod_ids(pack_path: Path) -> set[str]:
    mods = pack_path / "mods"
    ids: set[str] = set()
    if not mods.is_dir():
        return ids
    for p in mods.glob("*.pw.toml"):
        ids.add(p.stem.lower())
    for p in mods.glob("*.jar"):
        # fallback if unpacked without packwiz
        ids.add(re.sub(r"[-_]?\d.*$", "", p.stem).lower())
    return ids


def _diff_maps(a: dict[str, str], b: dict[str, str]) -> dict:
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    changed = sorted(k for k in set(a) & set(b) if a[k] != b[k] and a[k] and b[k])
    return {
        "only_a": only_a,
        "only_b": only_b,
        "changed": changed,
        "count_a": len(a),
        "count_b": len(b),
    }


def _pack_recipe_hints(only_a_files: list[str]) -> list[dict]:
    """Call out datapack recipe JSON only in A — usual progression fixes."""
    hints = []
    for rel in only_a_files:
        if not rel.endswith(".json"):
            continue
        if "/data/" not in rel:
            continue
        if "/recipe/" not in rel and "/recipes/" not in rel:
            continue
        hints.append({"file": rel, "kind": "datapack_recipe"})
    return hints


def _config_hits(config_root: Path, limit: int = 40) -> list[dict]:
    hits: list[dict] = []
    if not config_root.is_dir():
        return hits
    for p in sorted(config_root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in {".toml", ".json", ".cfg", ".txt", ".properties"}:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not CONFIG_HINT.search(text):
            continue
        # first matching line
        line = ""
        for raw in text.splitlines():
            if CONFIG_HINT.search(raw):
                line = raw.strip()[:160]
                break
        hits.append(
            {
                "file": p.relative_to(config_root).as_posix(),
                "snippet": line,
            }
        )
        if len(hits) >= limit:
            break
    return hits


def _dump_pack_recipes(pack_id: str) -> list[dict]:
    dump_path = ROOT / "out" / pack_id / "recipe_data.json"
    if not dump_path.is_file():
        return []
    try:
        dump = json.loads(dump_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = []
    for item, bucket in (dump.get("recipes") or {}).items():
        for e in bucket.get("mod") or []:
            if e.get("origin") == "pack":
                rows.append(
                    {
                        "item": item,
                        "id": e.get("id"),
                        "type": e.get("type"),
                    }
                )
    rows.sort(key=lambda r: (r.get("id") or "", r.get("item") or ""))
    return rows


def attribute(pack_a: str, pack_b: str) -> dict:
    ea, eb = _pack_entry(pack_a), _pack_entry(pack_b)
    mods_a, mods_b = _mod_ids(ea["path"]), _mod_ids(eb["path"])
    kube_a = _rel_files(ea["path"], "kubejs")
    kube_b = _rel_files(eb["path"], "kubejs")
    # openloader / global datapacks if present
    for extra in ("openloader", "global_packs", "datapacks"):
        kube_a.update({f"{extra}/{k}": v for k, v in _rel_files(ea["path"], extra).items()})
        kube_b.update({f"{extra}/{k}": v for k, v in _rel_files(eb["path"], extra).items()})

    kube_diff = _diff_maps(kube_a, kube_b)
    recipe_hints = _pack_recipe_hints(kube_diff["only_a"])

    cfg_a = ROOT / "out" / pack_a / "server" / "config"
    cfg_b = ROOT / "out" / pack_b / "server" / "config"
    cfg_files_a: dict[str, str] = {}
    cfg_files_b: dict[str, str] = {}
    if cfg_a.is_dir():
        for p in cfg_a.rglob("*"):
            if p.is_file() and p.name not in SKIP_FILE_NAMES:
                try:
                    cfg_files_a[p.relative_to(cfg_a).as_posix()] = hashlib.sha256(
                        p.read_bytes()
                    ).hexdigest()[:16]
                except OSError:
                    cfg_files_a[p.relative_to(cfg_a).as_posix()] = ""
    if cfg_b.is_dir():
        for p in cfg_b.rglob("*"):
            if p.is_file() and p.name not in SKIP_FILE_NAMES:
                try:
                    cfg_files_b[p.relative_to(cfg_b).as_posix()] = hashlib.sha256(
                        p.read_bytes()
                    ).hexdigest()[:16]
                except OSError:
                    cfg_files_b[p.relative_to(cfg_b).as_posix()] = ""
    cfg_diff = _diff_maps(cfg_files_a, cfg_files_b)

    pack_recipes_a = _dump_pack_recipes(pack_a)
    pack_recipes_b = _dump_pack_recipes(pack_b)
    ids_b = {r["id"] for r in pack_recipes_b}
    ids_a = {r["id"] for r in pack_recipes_a}
    recipes_only_a = [r for r in pack_recipes_a if r["id"] not in ids_b]
    recipes_only_b = [r for r in pack_recipes_b if r["id"] not in ids_a]

    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "a": {"id": pack_a, "label": ea["label"], "path": str(ea["path"])},
        "b": {"id": pack_b, "label": eb["label"], "path": str(eb["path"])},
        "mods": {
            "only_a": sorted(mods_a - mods_b),
            "only_b": sorted(mods_b - mods_a),
            "shared": len(mods_a & mods_b),
            "count_a": len(mods_a),
            "count_b": len(mods_b),
        },
        "kubejs_and_datapacks": kube_diff,
        "datapack_recipes_only_in_a": recipe_hints,
        "pack_origin_recipes": {
            "only_a": recipes_only_a,
            "only_b": recipes_only_b,
            "count_a": len(pack_recipes_a),
            "count_b": len(pack_recipes_b),
        },
        "server_config": {
            **cfg_diff,
            "available_a": cfg_a.is_dir(),
            "available_b": cfg_b.is_dir(),
            "disable_hints_a": _config_hits(cfg_a) if cfg_a.is_dir() else [],
            "disable_hints_b": _config_hits(cfg_b) if cfg_b.is_dir() else [],
        },
    }


def render_md(data: dict) -> str:
    a, b = data["a"]["id"], data["b"]["id"]
    lines = [
        f"# Attribute diff — {a} vs {b}",
        "",
        f"**{data['a']['label']}** (`{data['a']['path']}`)",
        f"**{data['b']['label']}** (`{data['b']['path']}`)",
        "",
        "## Mods (packwiz)",
        "",
        f"- {a}: {data['mods']['count_a']} · {b}: {data['mods']['count_b']} · shared {data['mods']['shared']}",
    ]
    if data["mods"]["only_a"]:
        lines.append(f"- Only in {a} ({len(data['mods']['only_a'])}):")
        for m in data["mods"]["only_a"][:40]:
            lines.append(f"  - `{m}`")
        if len(data["mods"]["only_a"]) > 40:
            lines.append(f"  - … +{len(data['mods']['only_a']) - 40} more")
    if data["mods"]["only_b"]:
        lines.append(f"- Only in {b} ({len(data['mods']['only_b'])}):")
        for m in data["mods"]["only_b"][:40]:
            lines.append(f"  - `{m}`")
        if len(data["mods"]["only_b"]) > 40:
            lines.append(f"  - … +{len(data['mods']['only_b']) - 40} more")
    if not data["mods"]["only_a"] and not data["mods"]["only_b"]:
        lines.append("- (same mod id set)")

    kd = data["kubejs_and_datapacks"]
    lines += [
        "",
        "## KubeJS / datapacks",
        "",
        f"- {a}: {kd['count_a']} files · {b}: {kd['count_b']} files",
        f"- Only in {a}: {len(kd['only_a'])} · only in {b}: {len(kd['only_b'])} · changed: {len(kd['changed'])}",
        "",
    ]
    hints = data.get("datapack_recipes_only_in_a") or []
    if hints:
        lines.append(f"### Datapack recipes only in {a} (copy candidates)")
        lines.append("")
        for h in hints[:50]:
            lines.append(f"- `{h['file']}`")
        if len(hints) > 50:
            lines.append(f"- … +{len(hints) - 50} more")
        lines.append("")

    if kd["only_a"]:
        lines.append(f"### All files only in {a}")
        lines.append("")
        for rel in kd["only_a"][:60]:
            lines.append(f"- `{rel}`")
        if len(kd["only_a"]) > 60:
            lines.append(f"- … +{len(kd['only_a']) - 60} more")
        lines.append("")

    if kd["only_b"]:
        lines.append(f"### Files only in {b}")
        lines.append("")
        for rel in kd["only_b"][:40]:
            lines.append(f"- `{rel}`")
        if len(kd["only_b"]) > 40:
            lines.append(f"- … +{len(kd['only_b']) - 40} more")
        lines.append("")

    pr = data["pack_origin_recipes"]
    lines += [
        "## Pack-origin recipes (from dumps)",
        "",
        f"- {a}: {pr['count_a']} · {b}: {pr['count_b']}",
    ]
    if pr["only_a"]:
        lines.append(f"- Recipe ids only in {a}:")
        for r in pr["only_a"][:40]:
            lines.append(f"  - `{r['id']}` → `{r['item']}` ({r['type']})")
        if len(pr["only_a"]) > 40:
            lines.append(f"  - … +{len(pr['only_a']) - 40} more")
    if pr["only_b"]:
        lines.append(f"- Recipe ids only in {b}:")
        for r in pr["only_b"][:20]:
            lines.append(f"  - `{r['id']}` → `{r['item']}`")

    sc = data["server_config"]
    lines += [
        "",
        "## Server config (from dumps)",
        "",
    ]
    if not sc["available_a"] and not sc["available_b"]:
        lines.append("- No `out/<pack>/server/config` yet — run `make dump` on both packs.")
    else:
        lines.append(
            f"- available: {a}={sc['available_a']} · {b}={sc['available_b']}"
        )
        lines.append(
            f"- only in {a}: {len(sc['only_a'])} · only in {b}: {len(sc['only_b'])} · changed: {len(sc['changed'])}"
        )
        for label, key in ((a, "disable_hints_a"), (b, "disable_hints_b")):
            hits = sc.get(key) or []
            if hits:
                lines.append(f"- Disable/blacklist hints in {label}:")
                for h in hits[:15]:
                    lines.append(f"  - `{h['file']}`: `{h['snippet']}`")

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--a", required=True, help="pack id A (known-good / reference)")
    ap.add_argument("--b", required=True, help="pack id B (under test)")
    a = ap.parse_args()

    data = attribute(a.a, a.b)
    out_dir = ROOT / "out" / "diffs" / f"{a.a}-vs-{a.b}"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "attribute.json"
    md_path = out_dir / "attribute.md"
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_md(data), encoding="utf-8")

    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    hints = data.get("datapack_recipes_only_in_a") or []
    print(
        f"mods only_a={len(data['mods']['only_a'])} only_b={len(data['mods']['only_b'])}; "
        f"kubejs only_a={len(data['kubejs_and_datapacks']['only_a'])}; "
        f"datapack recipes only in {a.a}={len(hints)}; "
        f"pack recipes only_a={len(data['pack_origin_recipes']['only_a'])}"
    )
    if hints:
        print("copy candidates (first 8):")
        for h in hints[:8]:
            print(f"  {h['file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
