#!/usr/bin/env python3
"""Cross-pack mod frequency — which mods are core vs rare / overused.

Scans mods/ in every registered pack (build + reference) that has a local path.
Uses packwiz *.pw.toml stems when present, else jar name heuristics.

Usage:
  python3 scripts/mod_corpus.py
  make corpus

Writes:
  out/corpus/mods.json
  out/corpus/mods.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from packs import load_packs  # noqa: E402

# Library / platform noise — still counted, but tagged
PLATFORMISH = frozenset(
    {
        "minecraft",
        "neoforge",
        "forge",
        "fabric-api",
        "fabric",
        "quilt",
        "kotlinforforge",
        "architectury",
        "cloth-config",
        "cloth_config",
        "jei",
        "emi",
        "rei",
        "jade",
        "theoneprobe",
        "appleskin",
        "controlling",
        "searchables",
        "catalogue",
        "configured",
        "fancymenu",
        "konkrete",
        "modernfix",
    }
)


def _mod_ids(pack_path: Path) -> set[str]:
    mods_dir = pack_path / "mods"
    ids: set[str] = set()
    if not mods_dir.is_dir():
        return ids
    for p in mods_dir.glob("*.pw.toml"):
        # file is often name.pw.toml → stem "name.pw"
        stem = p.name[: -len(".pw.toml")] if p.name.endswith(".pw.toml") else p.stem
        if stem.endswith(".pw"):
            stem = stem[: -len(".pw")]
        ids.add(stem.lower())
    if ids:
        return ids
    for p in mods_dir.glob("*.jar"):
        stem = p.stem.lower()
        stem = re.sub(r"[-_](\d+\.)+\d+.*$", "", stem)
        stem = re.sub(r"[-_]mc\d.*$", "", stem)
        stem = re.sub(r"[-_]neoforge.*$", "", stem)
        stem = re.sub(r"[-_]forge.*$", "", stem)
        ids.add(stem.strip("-_") or p.stem.lower())
    return ids


def build_corpus() -> dict:
    packs = load_packs()
    by_mod: dict[str, list[dict]] = defaultdict(list)
    pack_rows = []
    for pid, entry in packs.items():
        path = Path(entry["path"])
        if not path.is_dir():
            continue
        mods = sorted(_mod_ids(path))
        if not mods:
            continue
        role = entry.get("role") or "build"
        pack_rows.append(
            {
                "id": pid,
                "label": entry.get("label") or pid,
                "role": role,
                "mod_count": len(mods),
                "path": str(path),
            }
        )
        for mid in mods:
            by_mod[mid].append({"pack": pid, "role": role})

    n_packs = len(pack_rows)
    rows = []
    for mid, appearances in sorted(by_mod.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        pack_ids = sorted({a["pack"] for a in appearances})
        roles = {a["role"] for a in appearances}
        count = len(pack_ids)
        frac = count / n_packs if n_packs else 0.0
        if count >= max(2, int(0.6 * n_packs + 0.999)):
            band = "core"
        elif count == 1:
            band = "unique"
        elif frac >= 0.4:
            band = "common"
        else:
            band = "occasional"
        rows.append(
            {
                "mod": mid,
                "pack_count": count,
                "fraction": round(frac, 3),
                "band": band,
                "packs": pack_ids,
                "roles": sorted(roles),
                "platformish": mid in PLATFORMISH or any(
                    mid.startswith(p + "-") or mid.startswith(p + "_") for p in PLATFORMISH
                ),
            }
        )

    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "pack_count": n_packs,
        "unique_mods": len(rows),
        "packs": pack_rows,
        "mods": rows,
    }


def render_md(data: dict) -> str:
    lines = [
        "# Mod corpus",
        "",
        f"Packs scanned: **{data['pack_count']}** · unique mods: **{data['unique_mods']}**",
        "",
        "## Packs",
        "",
    ]
    for p in data["packs"]:
        lines.append(
            f"- `{p['id']}` [{p['role']}] — {p['mod_count']} mods — {p['label']}"
        )
    lines += ["", "## Core (in most packs)", ""]
    core = [m for m in data["mods"] if m["band"] == "core" and not m["platformish"]]
    plat = [m for m in data["mods"] if m["band"] == "core" and m["platformish"]]
    for m in core[:40]:
        lines.append(
            f"- `{m['mod']}` — {m['pack_count']}/{data['pack_count']} "
            f"({', '.join(m['packs'])})"
        )
    if not core:
        lines.append("- (need more packs for a stable core set)")
    if plat:
        lines += ["", "### Platform / QoL (core but expected)", ""]
        for m in plat[:25]:
            lines.append(f"- `{m['mod']}` — {m['pack_count']}/{data['pack_count']}")

    lines += ["", "## Unique to one pack", ""]
    unique = [m for m in data["mods"] if m["band"] == "unique"]
    # Group by pack
    by_pack: dict[str, list[str]] = defaultdict(list)
    for m in unique:
        by_pack[m["packs"][0]].append(m["mod"])
    for pid, mods in sorted(by_pack.items()):
        lines.append(f"### {pid} ({len(mods)})")
        for mid in mods[:30]:
            lines.append(f"- `{mid}`")
        if len(mods) > 30:
            lines.append(f"- … +{len(mods) - 30} more")
        lines.append("")

    lines += ["## Occasional / common (2+ but not core)", ""]
    mid = [m for m in data["mods"] if m["band"] in ("occasional", "common") and not m["platformish"]]
    for m in mid[:50]:
        lines.append(
            f"- `{m['mod']}` — {m['pack_count']}/{data['pack_count']} [{m['band']}]"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.parse_args()
    data = build_corpus()
    out = ROOT / "out" / "corpus"
    out.mkdir(parents=True, exist_ok=True)
    (out / "mods.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    (out / "mods.md").write_text(render_md(data), encoding="utf-8")
    print(f"wrote {out / 'mods.json'}")
    print(f"wrote {out / 'mods.md'}")
    print(
        f"packs={data['pack_count']} unique_mods={data['unique_mods']} "
        f"core={sum(1 for m in data['mods'] if m['band']=='core')} "
        f"unique={sum(1 for m in data['mods'] if m['band']=='unique')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
