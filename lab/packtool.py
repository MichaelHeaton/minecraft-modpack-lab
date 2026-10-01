#!/usr/bin/env python3
"""Pack helpers for modpack-lab.

  packtool.py prune  --src PACK --dst DIR --exclude-file FILE
      Copy a packwiz pack to DIR without the mods listed in FILE (one pw.toml name per line, no extension),
      removing them from index.toml and updating the index hash in pack.toml. The original pack is untouched.

  packtool.py detect --log FILE [--log FILE] --mods-dir DIR --pack MODS_PW_DIR
      Find mods to leave out of the next server attempt:
        - client-only (invalid dist / client class on dedicated server)
        - CurseForge API exclusions ("must be downloaded manually")
      Prints one pw.toml name (slug) per line. Exit 0 whether or not any were found.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
import zipfile
from pathlib import Path

SKIP_DIRS = {".git", ".lab", "dist", "node_modules", ".packwiz-cache", "out", ".cache"}
CLIENT_ONLY = ("invalid dist", "DEDICATED_SERVER", "net/minecraft/client", "net.minecraft.client")
FAILED = re.compile(r"\(([A-Za-z0-9_\-.]+)\) has failed to load correctly\s*\n\s*(.+)")
# packwiz: "save this file to /data/mods/<jar>" or curseforge.com/minecraft/mc-mods/<slug>/files/
CF_JAR = re.compile(r"save this file to /data/mods/([^\s]+\.jar)", re.I)
CF_SLUG = re.compile(r"curseforge\.com/minecraft/mc-mods/([A-Za-z0-9_\-]+)/files/", re.I)


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


def _pw_index(pack_mods: Path) -> tuple[dict[str, str], dict[str, str]]:
    """filename→slug and slug→slug for pack mods/*.pw.toml."""
    by_file: dict[str, str] = {}
    by_slug: dict[str, str] = {}
    for pw in pack_mods.glob("*.pw.toml"):
        slug = pw.name[: -len(".pw.toml")]
        by_slug[slug] = slug
        text = pw.read_text(encoding="utf-8", errors="replace")
        fm = re.search(r'^filename = "([^"]+)"', text, re.M)
        if fm:
            by_file[fm.group(1)] = slug
    return by_file, by_slug


def detect_client_only(logs: list[str], mods_dir: Path, pack_mods: Path) -> list[str]:
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
    by_file, _ = _pw_index(pack_mods)
    return sorted({by_file[j] for j in jars if j in by_file})


def detect_cf_excluded(logs: list[str], pack_mods: Path) -> list[str]:
    """Mods packwiz could not download because CurseForge blocked the API."""
    by_file, by_slug = _pw_index(pack_mods)
    found: set[str] = set()
    for path in logs:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "excluded from the CurseForge API" not in text and "must be downloaded manually" not in text:
            continue
        for m in CF_JAR.finditer(text):
            jar = m.group(1)
            if jar in by_file:
                found.add(by_file[jar])
        for m in CF_SLUG.finditer(text):
            slug = m.group(1)
            if slug in by_slug:
                found.add(slug)
    return sorted(found)


def detect(logs: list[str], mods_dir: Path, pack_mods: Path) -> list[str]:
    return sorted(set(detect_client_only(logs, mods_dir, pack_mods)) | set(detect_cf_excluded(logs, pack_mods)))


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
