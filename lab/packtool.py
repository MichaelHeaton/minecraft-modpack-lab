#!/usr/bin/env python3
"""Pack helpers for modpack-lab.

  packtool.py prune  --src PACK --dst DIR --exclude-file FILE
      Copy a packwiz pack to DIR without the mods listed in FILE (one pw.toml name per line, no extension),
      removing them from index.toml and updating the index hash in pack.toml. The original pack is untouched.

  packtool.py detect --log FILE [--log FILE] --mods-dir DIR --pack MODS_PW_DIR
      Find mods the server could not load because they are client-only (class loaded on the wrong dist).
      Prints one pw.toml name per line. Exit 0 whether or not any were found.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
import zipfile
from pathlib import Path

SKIP_DIRS = {".git", ".lab", "dist", "node_modules", ".packwiz-cache"}
CLIENT_ONLY = ("invalid dist", "DEDICATED_SERVER", "net/minecraft/client", "net.minecraft.client")
FAILED = re.compile(r"\(([A-Za-z0-9_\-.]+)\) has failed to load correctly\s*\n\s*(.+)")


def prune(src: Path, dst: Path, exclude: set[str]) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=lambda _d, names: [n for n in names if n in SKIP_DIRS or n.endswith(".jar")])
    if not exclude:
        return
    index = dst / "index.toml"
    text = index.read_text(encoding="utf-8")
    head, *blocks = re.split(r"(?m)^\[\[files\]\]\n", text)
    kept = []
    for block in blocks:
        m = re.search(r'^file = "mods/([^"/]+)\.pw\.toml"', block, re.M)
        if m and m.group(1) in exclude:
            (dst / "mods" / f"{m.group(1)}.pw.toml").unlink(missing_ok=True)
            continue
        kept.append(block)
    index.write_text(head + "".join("[[files]]\n" + b for b in kept), encoding="utf-8")
    pack = dst / "pack.toml"
    ptxt = pack.read_text(encoding="utf-8")
    if 'hash-format = "sha256"' not in ptxt.split("[versions]")[0]:
        sys.exit("pack.toml index hash-format is not sha256; cannot rewrite the index hash")
    digest = hashlib.sha256(index.read_bytes()).hexdigest()
    ptxt, n = re.subn(r'(\[index\][^\[]*?\bhash = ")[0-9a-f]+(")', rf"\g<1>{digest}\g<2>", ptxt, count=1)
    if n != 1:
        sys.exit("could not update the index hash in pack.toml")
    pack.write_text(ptxt, encoding="utf-8")


def jar_mod_ids(jar: Path) -> set[str]:
    try:
        with zipfile.ZipFile(jar) as zf:
            for name in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml"):
                if name in zf.namelist():
                    return set(re.findall(r'(?m)^\s*modId\s*=\s*"([^"]+)"', zf.read(name).decode("utf-8", "replace")))
    except (zipfile.BadZipFile, OSError):
        pass
    return set()


def detect(logs: list[str], mods_dir: Path, pack_mods: Path) -> list[str]:
    bad_ids: set[str] = set()
    for path in logs:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in FAILED.finditer(text):
            if any(tok in m.group(2) for tok in CLIENT_ONLY):
                bad_ids.add(m.group(1))
    jars = {j.name for j in mods_dir.glob("*.jar") if jar_mod_ids(j) & bad_ids}
    slugs = []
    for pw in sorted(pack_mods.glob("*.pw.toml")):
        fm = re.search(r'^filename = "([^"]+)"', pw.read_text(encoding="utf-8", errors="replace"), re.M)
        if fm and fm.group(1) in jars:
            slugs.append(pw.name[: -len(".pw.toml")])
    return slugs


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prune")
    p.add_argument("--src", required=True)
    p.add_argument("--dst", required=True)
    p.add_argument("--exclude-file", required=True)
    d = sub.add_parser("detect")
    d.add_argument("--log", action="append", required=True)
    d.add_argument("--mods-dir", required=True)
    d.add_argument("--pack", required=True)
    a = ap.parse_args()
    if a.cmd == "prune":
        ex = Path(a.exclude_file)
        names = {ln.strip() for ln in ex.read_text().splitlines() if ln.strip()} if ex.exists() else set()
        prune(Path(a.src), Path(a.dst), names)
        print(f"pack copy ready ({len(names)} mod(s) excluded)", file=sys.stderr)
    else:
        for s in detect(a.log, Path(a.mods_dir), Path(a.pack)):
            print(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
