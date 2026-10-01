#!/usr/bin/env python3
"""Thin orchestrator for make targets: resolve a pack, then run lab / dump / reach."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAB_SH = ROOT / "lab" / "lab.sh"
PACKS = ROOT / "scripts" / "packs.py"
KNOWLEDGE = ROOT / "scripts" / "knowledge.py"
SNAP2DUMP = ROOT / "scripts" / "snapshot_to_dump.py"
REACH = ROOT / "scripts" / "series_reach.py"
REPORT = ROOT / "scripts" / "report.py"
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


def toml_get(pack: Path, key: str) -> str:
    text = (pack / "pack.toml").read_text(encoding="utf-8", errors="replace")
    m = re.search(rf'(?m)^{re.escape(key)}\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else ""


def seed_excludes(pack_id: str, out_dir: Path) -> None:
    excl = out_dir / "exclude-mods.txt"
    excl.parent.mkdir(parents=True, exist_ok=True)
    if not excl.exists():
        excl.write_text("", encoding="utf-8")
    subprocess.call(
        [sys.executable, str(KNOWLEDGE), "seed", "--pack-id", pack_id, "--exclude-file", str(excl)],
        cwd=ROOT,
    )


def learn_excludes(pack_id: str, pack_path: Path, out_dir: Path, snap: Path) -> None:
    excl = out_dir / "exclude-mods.txt"
    meta = {
        "pack": pack_id,
        "path": str(pack_path),
        "minecraft": toml_get(pack_path, "minecraft"),
        "neoforge": toml_get(pack_path, "neoforge"),
        "snapshot": str(snap) if snap.exists() else "",
    }
    if snap.exists():
        try:
            data = json.loads(snap.read_text(encoding="utf-8"))
            meta["recipes"] = len(data.get("recipes", {}))
            meta["tags"] = len(data.get("tags", {}))
            meta["done"] = data.get("done")
        except (OSError, ValueError):
            pass
    dump = out_dir / "recipe_data.json"
    if dump.exists():
        try:
            d = json.loads(dump.read_text(encoding="utf-8"))
            meta["dump_items"] = d.get("item_count")
            meta["dump_source"] = d.get("source")
        except (OSError, ValueError):
            pass
    subprocess.call(
        [
            sys.executable,
            str(KNOWLEDGE),
            "learn",
            "--pack-id",
            pack_id,
            "--exclude-file",
            str(excl),
            "--meta",
            json.dumps(meta),
        ],
        cwd=ROOT,
    )


def run_snapshot(pack_id: str, pack_path: Path, out_dir: Path, lab_args: list[str]) -> int:
    seed_excludes(pack_id, out_dir)
    rc = subprocess.call([str(LAB_SH), "snapshot", *lab_args], cwd=ROOT)
    if rc == 0:
        learn_excludes(pack_id, pack_path, out_dir, out_dir / "snapshot.json")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "command",
        choices=("doctor", "snapshot", "dump", "check", "why", "blocked", "tags", "analyze", "report"),
    )
    ap.add_argument("--pack", default="", help="pack id, number, or path (omit to pick / use last)")
    ap.add_argument("--accept-eula", action="store_true")
    ap.add_argument("--memory", default="")
    ap.add_argument("--port", default="")
    ap.add_argument("--timeout", default="")
    ap.add_argument("--start", default="", help="reach start file (overrides profile)")
    ap.add_argument("--targets", default="", help="reach targets file (overrides profile)")
    ap.add_argument("--item", default="", help="item id for why/blocked")
    a = ap.parse_args()

    pid, pack_path, out_dir = resolve_pack(a.pack.strip() or None)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"pack: {pid}\n  path: {pack_path}\n  out:  {out_dir}", file=sys.stderr)

    # Profile supplies default start/targets for this pack
    sys.path.insert(0, str(ROOT / "scripts"))
    from profile import load_profile  # local import after path setup

    profile = load_profile(pid)
    default_start = profile["start"]
    default_targets = profile["targets"]

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
        return run_snapshot(pid, pack_path, out_dir, lab_args)

    if a.command in ("dump", "analyze"):
        rc = run_snapshot(pid, pack_path, out_dir, lab_args)
        if rc != 0:
            return rc
        snap = out_dir / "snapshot.json"
        dump = out_dir / "recipe_data.json"
        convert_cmd = [
            sys.executable,
            str(SNAP2DUMP),
            "--snapshot",
            str(snap),
            "--out",
            str(dump),
            "--mods-dir",
            str(out_dir / "server" / "mods"),
            "--server-dir",
            str(out_dir / "server"),
        ]
        rc = subprocess.call(convert_cmd, cwd=ROOT)
        if rc == 0:
            learn_excludes(pid, pack_path, out_dir, snap)
        if rc != 0:
            return rc
        if a.command == "dump":
            return 0
        a.command = "report"

    if a.command == "report":
        dump = out_dir / "recipe_data.json"
        return subprocess.call(
            [sys.executable, str(REPORT), "--pack-id", pid, "--dump", str(dump)],
            cwd=ROOT,
        )

    if a.command in ("check", "why", "blocked", "tags"):
        dump = out_dir / "recipe_data.json"
        if not dump.exists():
            print(f"no dump yet at {dump}; run: make dump PACK={pid} EULA=1", file=sys.stderr)
            return 1
        start = Path(a.start) if a.start else Path(default_start)
        if not start.is_file():
            print(f"start file not found: {start}", file=sys.stderr)
            return 1
        targets = Path(a.targets) if a.targets else Path(default_targets)
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
