#!/usr/bin/env python3
"""Discover Prism + CurseForge instances and register them in packs.local.toml.

Defaults (macOS):
  Prism:      ~/Library/Application Support/PrismLauncher/instances
  CurseForge: ~/Documents/curseforge/minecraft/Instances

Colony Protocol / CP-* Prism instances map to role=build when not already
registered via packwiz. Everything else (and all CurseForge instances) maps to
role=reference.

Usage:
  python3 scripts/discover_launchers.py              # dry-run
  python3 scripts/discover_launchers.py --apply      # write packs.local.toml
  make discover
  make discover APPLY=1
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from packs import (  # noqa: E402
    LOCAL,
    load_packs,
    load_references,
    _expand,
    _norm_role,
    _read_toml,
    _write_local,
)

HOME = Path.home()

DEFAULT_PRISM = HOME / "Library/Application Support/PrismLauncher/instances"
DEFAULT_CURSE = HOME / "Documents/curseforge/minecraft/Instances"

# Prism/Curse names → preferred registry id (+ role hint)
KNOWN_ALIASES = {
    "cp-verdant-dev": ("verdant", "build"),
    "cp-verdant-vanilla": ("verdant-vanilla", "build"),
    "cp-verdant-dev-canvas": ("verdant-canvas", "build"),
    "cp-liminal-dev": ("liminal", "build"),
    "cp-elysian-dev": ("elysian", "build"),
    "cp-influx-dev": ("influx", "build"),
    "colony-protocol-verdant": ("verdant-curse", "reference"),
    "all-the-mods-10-atm10": ("atm10", "reference"),
    "all-the-mods-10-to-the-sky-atm10sky": ("atm10-sky", "reference"),
    "all-the-mods-10_-to-the-sky-atm10sky": ("atm10-sky", "reference"),
    "homestead-a-cozy-survival-experience": ("homestead-cozy", "reference"),
    "society-sunlit-valley": ("society-sunlit-valley", "reference"),
    "rlcraft": ("rlcraft", "reference"),
}


def _slug(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "pack"


def _find_game_dir(instance: Path) -> Path | None:
    """Directory that contains mods/ (Prism uses minecraft/, Curse often root)."""
    for cand in (instance / "minecraft", instance):
        mods = cand / "mods"
        if mods.is_dir():
            return cand
    return None


def _mod_count(game: Path) -> int:
    mods = game / "mods"
    if not mods.is_dir():
        return 0
    n = sum(1 for _ in mods.glob("*.jar"))
    n += sum(1 for _ in mods.glob("*.pw.toml"))
    return n


def _alias(name: str) -> tuple[str, str] | None:
    key = _slug(name)
    if key in KNOWN_ALIASES:
        return KNOWN_ALIASES[key]
    # fuzzy ATM10 sky
    if "atm10" in key and "sky" in key:
        return ("atm10-sky", "reference")
    if key.startswith("all-the-mods-10") and "sky" not in key:
        return ("atm10", "reference")
    if key.startswith("cp-") or "colony-protocol" in key:
        # build family
        short = key.replace("colony-protocol-", "").replace("cp-", "")
        short = re.sub(r"-dev$", "", short)
        short = re.sub(r"-vanilla$", "-vanilla", short)
        return (short, "build")
    return None


def scan_prism(root: Path) -> list[dict]:
    found = []
    if not root.is_dir():
        return found
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        game = _find_game_dir(child)
        if not game:
            continue
        alias = _alias(child.name)
        pid, role = alias if alias else (_slug(child.name), "reference")
        found.append(
            {
                "id": pid,
                "label": child.name,
                "path": str(game),
                "role": role,
                "source": "prism",
                "instance": str(child),
                "mod_count": _mod_count(game),
            }
        )
    return found


def scan_curse(root: Path) -> list[dict]:
    found = []
    if not root.is_dir():
        return found
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        game = _find_game_dir(child)
        if not game:
            continue
        alias = _alias(child.name)
        # CurseForge installs default to reference (even Colony Protocol copies)
        if alias:
            pid, role = alias
            if role == "build" and "colony" in child.name.lower():
                # keep curse copy as reference so packwiz path stays the build source
                pid = pid if pid.endswith("-curse") else f"{pid}-curse"
                role = "reference"
        else:
            pid, role = _slug(child.name), "reference"
        found.append(
            {
                "id": pid,
                "label": child.name,
                "path": str(game),
                "role": role,
                "source": "curseforge",
                "instance": str(child),
                "mod_count": _mod_count(game),
            }
        )
    return found


def merge_plan(discovered: list[dict], existing: dict[str, dict]) -> list[dict]:
    """Decide add / skip / conflict for each discovery."""
    plan = []
    for d in discovered:
        pid = d["id"]
        ex = existing.get(pid)
        row = dict(d)
        if not ex:
            row["action"] = "add"
            if d["mod_count"] == 0:
                row["action"] = "skip"
                row["reason"] = "no mods/ jars (incomplete install?)"
        else:
            ex_path = Path(ex["path"]).resolve()
            new_path = Path(d["path"]).resolve()
            if ex_path == new_path:
                row["action"] = "skip"
                row["reason"] = "already registered (same path)"
            elif "packwiz" in str(ex_path) or "minecraft-modpack" in str(ex_path):
                # Prefer packwiz/source tree for builds; keep discovery as note
                row["action"] = "skip"
                row["reason"] = f"keep existing packwiz/source path: {ex_path}"
            else:
                row["action"] = "skip"
                row["reason"] = f"id already used → {ex_path}"
        plan.append(row)
    return plan


def apply_plan(plan: list[dict]) -> int:
    local = _read_toml(LOCAL)
    packs = dict(local.get("packs") or {})
    # seed from merged view so we don't drop shared-only entries that were
    # copied into local earlier — only write local file additions
    added = 0
    for row in plan:
        if row["action"] != "add":
            continue
        packs[row["id"]] = {
            "path": row["path"],
            "label": row["label"],
            "role": _norm_role(row["role"]),
        }
        added += 1
    # Preserve any existing local entries not touched
    existing_local = dict(local.get("packs") or {})
    for pid, entry in existing_local.items():
        if pid not in packs:
            packs[pid] = entry
    _write_local(
        {
            k: {
                "path": str(_expand(str(v["path"]))),
                "label": str(v.get("label") or k),
                "role": _norm_role(v.get("role")),
            }
            for k, v in packs.items()
        }
    )
    return added


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write packs.local.toml")
    ap.add_argument("--prism", default=str(DEFAULT_PRISM))
    ap.add_argument("--curseforge", default=str(DEFAULT_CURSE))
    a = ap.parse_args()

    prism = Path(os.path.expanduser(a.prism))
    curse = Path(os.path.expanduser(a.curseforge))
    discovered = scan_prism(prism) + scan_curse(curse)
    existing = load_packs()
    plan = merge_plan(discovered, existing)

    print(f"Prism:      {prism}  ({'ok' if prism.is_dir() else 'MISSING'})")
    print(f"CurseForge: {curse}  ({'ok' if curse.is_dir() else 'MISSING'})")
    print()

    adds = [r for r in plan if r["action"] == "add"]
    skips = [r for r in plan if r["action"] != "add"]

    print(f"Would add ({len(adds)}):" if not a.apply else f"Adding ({len(adds)}):")
    for r in adds:
        print(
            f"  + [{r['role']:<9}] {r['id']:<24}  mods={r['mod_count']:<4}  "
            f"{r['source']}: {r['label']}"
        )
        print(f"      {r['path']}")
    if skips:
        print(f"\nSkipped ({len(skips)}):")
        for r in skips:
            print(
                f"  · {r['id']:<24}  mods={r['mod_count']:<4}  "
                f"{r.get('reason', r['action'])}"
            )

    # Wishlist overlap
    refs = load_references()
    matched = [r for r in plan if r["id"] in refs]
    if matched:
        print(f"\nWishlist hits ({len(matched)}): " + ", ".join(r["id"] for r in matched))

    if a.apply:
        n = apply_plan(plan)
        print(f"\nWrote {LOCAL.name}: {n} new pack(s). Run: make corpus && make packs")
    else:
        print("\nDry-run only. Apply with: make discover APPLY=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
