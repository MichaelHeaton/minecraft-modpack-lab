#!/usr/bin/env python3
"""Thin orchestrator for make targets: resolve a pack, then run lab / dump / reach."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAB_SH = ROOT / "lab" / "lab.sh"
PACKS = ROOT / "scripts" / "packs.py"
SNAP2DUMP = ROOT / "scripts" / "snapshot_to_dump.py"
REACH = ROOT / "scripts" / "series_reach.py"
EXAMPLES = ROOT / "examples" / "reach"
RESULT = ROOT / "out" / ".resolve"


def resolve_pack(selector: str | None) -> tuple[str, Path, Path]:
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(PACKS), "resolve", "--write", str(RESULT)]
    if selector:
        cmd += [selector, "--remember"]
    rc = subprocess.call(cmd, cwd=ROOT)
    if rc != 0:
        sys.exit(rc)
    if not RESULT.exists():
        sys.exit("resolve did not write a result")
    pid, path, out = RESULT.read_text(encoding="utf-8").strip().split("\t", 2)
    return pid, Path(path), Path(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "command",
        choices=("doctor", "snapshot", "dump", "check", "why", "blocked", "tags", "analyze"),
    )
    ap.add_argument("--pack", default="", help="pack id, number, or path (omit to pick / use last)")
    ap.add_argument("--accept-eula", action="store_true")
    ap.add_argument("--memory", default="")
    ap.add_argument("--port", default="")
    ap.add_argument("--timeout", default="")
    ap.add_argument("--start", default="", help="reach start file")
    ap.add_argument("--targets", default="", help="reach targets file")
    ap.add_argument("--item", default="", help="item id for why/blocked")
    a = ap.parse_args()

    pid, pack_path, out_dir = resolve_pack(a.pack.strip() or None)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"pack: {pid}\n  path: {pack_path}\n  out:  {out_dir}", file=sys.stderr)

    lab_args = ["--pack", str(pack_path), "--out", str(out_dir)]
    if a.memory:
        lab_args += ["--memory", a.memory]
    if a.port:
        lab_args += ["--port", a.port]
    if a.timeout:
        lab_args += ["--timeout", a.timeout]
    if a.accept_eula or os.environ.get("EULA") == "1" or os.environ.get("MC_EULA") == "true":
        lab_args.append("--accept-eula")

    if a.command == "doctor":
        return subprocess.call([str(LAB_SH), "doctor", *lab_args], cwd=ROOT)

    if a.command == "snapshot":
        return subprocess.call([str(LAB_SH), "snapshot", *lab_args], cwd=ROOT)

    if a.command in ("dump", "analyze"):
        rc = subprocess.call([str(LAB_SH), "snapshot", *lab_args], cwd=ROOT)
        if rc != 0:
            return rc
        snap = out_dir / "snapshot.json"
        dump = out_dir / "recipe_data.json"
        rc = subprocess.call(
            [sys.executable, str(SNAP2DUMP), "--snapshot", str(snap), "--out", str(dump)],
            cwd=ROOT,
        )
        if rc != 0 or a.command == "dump":
            return rc
        a.command = "check"

    if a.command in ("check", "why", "blocked", "tags"):
        dump = out_dir / "recipe_data.json"
        if not dump.exists():
            print(f"no dump yet at {dump}; run: make dump PACK={pid} EULA=1", file=sys.stderr)
            return 1
        start = Path(a.start) if a.start else EXAMPLES / "verdant.json"
        if not start.is_file():
            print(f"start file not found: {start}", file=sys.stderr)
            return 1
        targets = Path(a.targets) if a.targets else EXAMPLES / "targets.json"
        cmd = [sys.executable, str(REACH), "--dump", str(dump), a.command, str(start)]
        if a.command == "check":
            cmd += ["--targets", str(targets)]
        elif a.command in ("why", "blocked"):
            if not a.item:
                print(f"usage: make {a.command} PACK={pid} ITEM=mod:item", file=sys.stderr)
                return 2
            cmd.append(a.item)
        return subprocess.call(cmd, cwd=ROOT)

    return 2


if __name__ == "__main__":
    sys.exit(main())
