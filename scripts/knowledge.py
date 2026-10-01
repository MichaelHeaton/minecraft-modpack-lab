#!/usr/bin/env python3
"""Local (gitignored) knowledge store for modpack-lab.

Learnings about packs and mods live under .cache/ on this machine — not in git,
not in pack repos. Re-run dumps when mod lists change; keep exclusions and notes
so the next snapshot skips known client-only mods on round 1.

Layout:
  .cache/mods/client-only.json     global slugs we have seen fail on dedicated server
  .cache/packs/<id>/exclude-mods.txt   last excludes for that pack
  .cache/packs/<id>/meta.json          last successful dump metadata

Commands:
  seed --pack-id ID --exclude-file PATH   merge global+pack excludes into PATH
  learn --pack-id ID --exclude-file PATH [--meta JSON]
  show [--pack-id ID]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache"
MODS = CACHE / "mods"
PACKS = CACHE / "packs"
CLIENT = MODS / "client-only.json"


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{x}\n" for x in sorted(set(lines))), encoding="utf-8")


def load_client_only() -> dict:
    if not CLIENT.exists():
        return {"mods": {}}
    return json.loads(CLIENT.read_text(encoding="utf-8"))


def save_client_only(data: dict) -> None:
    CLIENT.parent.mkdir(parents=True, exist_ok=True)
    CLIENT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def pack_dir(pack_id: str) -> Path:
    return PACKS / pack_id


def known_excludes(pack_id: str) -> list[str]:
    data = load_client_only()
    global_slugs = sorted(data.get("mods", {}).keys())
    pack_slugs = _read_lines(pack_dir(pack_id) / "exclude-mods.txt")
    return sorted(set(global_slugs) | set(pack_slugs))


def cmd_seed(a: argparse.Namespace) -> int:
    dest = Path(a.exclude_file)
    existing = _read_lines(dest)
    merged = sorted(set(existing) | set(known_excludes(a.pack_id)))
    _write_lines(dest, merged)
    print(f"seeded {len(merged)} exclude(s) for {a.pack_id} → {dest}", file=sys.stderr)
    return 0


def cmd_learn(a: argparse.Namespace) -> int:
    pack_id = a.pack_id
    slugs = _read_lines(Path(a.exclude_file))
    # Pack-local copy
    _write_lines(pack_dir(pack_id) / "exclude-mods.txt", slugs)
    # Global client-only registry
    data = load_client_only()
    mods = data.setdefault("mods", {})
    now = datetime.now(timezone.utc).isoformat()
    for slug in slugs:
        entry = mods.setdefault(
            slug,
            {"first_seen": now, "packs": [], "reason": "excluded from dedicated-server snapshot"},
        )
        if pack_id not in entry["packs"]:
            entry["packs"].append(pack_id)
        entry["last_seen"] = now
        entry["last_pack"] = pack_id
    save_client_only(data)
    if a.meta:
        meta = json.loads(a.meta) if a.meta.startswith("{") else json.loads(Path(a.meta).read_text())
        meta["updated"] = now
        meta_path = pack_dir(pack_id) / "meta.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"learned {len(slugs)} client-only mod(s) for {pack_id}", file=sys.stderr)
    return 0


def cmd_show(a: argparse.Namespace) -> int:
    data = load_client_only()
    mods = data.get("mods", {})
    print(f"global client-only mods: {len(mods)}")
    for slug, info in sorted(mods.items()):
        packs = ",".join(info.get("packs", []))
        print(f"  {slug:<40} packs=[{packs}]  {info.get('reason', '')}")
    if a.pack_id:
        p = pack_dir(a.pack_id)
        print(f"\npack {a.pack_id}:")
        print(f"  excludes: {', '.join(_read_lines(p / 'exclude-mods.txt')) or '(none)'}")
        meta = p / "meta.json"
        if meta.exists():
            print(f"  meta: {meta.read_text(encoding='utf-8').strip()}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed")
    s.add_argument("--pack-id", required=True)
    s.add_argument("--exclude-file", required=True)
    s.set_defaults(f=cmd_seed)
    l = sub.add_parser("learn")
    l.add_argument("--pack-id", required=True)
    l.add_argument("--exclude-file", required=True)
    l.add_argument("--meta", default="")
    l.set_defaults(f=cmd_learn)
    sh = sub.add_parser("show")
    sh.add_argument("--pack-id", default="")
    sh.set_defaults(f=cmd_show)
    a = ap.parse_args()
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
