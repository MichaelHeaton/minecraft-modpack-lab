#!/usr/bin/env python3
"""Pack registry for modpack-lab.

Keeps a numbered list of packwiz packs on this machine so make targets can pick
by id, number, path, or interactive prompt.

Files (merged, local wins):
  packs.toml         — shared / committed defaults (optional)
  packs.local.toml   — machine-specific paths (gitignored; preferred for real work)
  .current-pack      — last interactively chosen id (gitignored)

Schema:
  [packs.<id>]
  path = "/absolute/or~/expanded/path"
  label = "optional display name"

Commands:
  list
  add --path DIR [--id ID] [--label TEXT]
  remove --id ID
  resolve [SELECTOR]     print: id\\tpath\\tout_dir  (SELECTOR = id | number | path)
  pick                   interactive resolve; remembers choice in .current-pack
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    sys.exit("Python 3.11+ required (tomllib)")

ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / "packs.toml"
LOCAL = ROOT / "packs.local.toml"
CURRENT = ROOT / ".current-pack"
OUT_ROOT = ROOT / "out"


def _expand(path: str) -> Path:
    return Path(os.path.expanduser(path)).resolve()


def _read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def load_packs() -> dict[str, dict]:
    """Merge shared + local; local overrides same id."""
    merged: dict[str, dict] = {}
    for src in (_read_toml(SHARED), _read_toml(LOCAL)):
        for pid, entry in (src.get("packs") or {}).items():
            if not isinstance(entry, dict) or "path" not in entry:
                continue
            merged[pid] = {
                "id": pid,
                "path": str(_expand(str(entry["path"]))),
                "label": str(entry.get("label") or pid),
            }
    return dict(sorted(merged.items()))


def _write_local(packs: dict[str, dict]) -> None:
    lines = [
        "# Machine-local pack registry for modpack-lab (gitignored).",
        "# Add with: make add DIR=/path/to/pack",
        "# Or edit this file. Shared defaults live in packs.toml.",
        "",
    ]
    for pid, entry in sorted(packs.items()):
        lines.append(f"[packs.{pid}]")
        lines.append(f'path = "{entry["path"]}"')
        if entry.get("label") and entry["label"] != pid:
            lines.append(f'label = "{entry["label"]}"')
        lines.append("")
    LOCAL.write_text("\n".join(lines), encoding="utf-8")


def _slug_from_path(path: Path) -> str:
    name = path.name
    name = re.sub(r"^minecraft-modpack-", "", name)
    name = re.sub(r"^cp-", "", name)
    name = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return name or "pack"


def _pack_label(path: Path) -> str:
    pt = path / "pack.toml"
    if pt.exists():
        m = re.search(r'(?m)^name\s*=\s*"([^"]+)"', pt.read_text(encoding="utf-8", errors="replace"))
        if m:
            return m.group(1)
    return path.name


def _validate_pack(path: Path) -> None:
    if not (path / "pack.toml").is_file() or not (path / "index.toml").is_file():
        sys.exit(f"not a packwiz pack (need pack.toml + index.toml): {path}")


def cmd_list(_a: argparse.Namespace) -> int:
    packs = load_packs()
    if not packs:
        print("No packs registered yet.")
        print("  make add DIR=/path/to/packwiz-pack")
        print("  or copy packs.example.toml → packs.local.toml and edit paths")
        return 0
    print(f"{'#':>3}  {'id':<16}  path")
    for i, (pid, e) in enumerate(packs.items(), 1):
        exists = "✓" if Path(e["path"]).is_dir() else "✗"
        print(f"{i:>3}  {pid:<16}  {exists}  {e['path']}")
        if e["label"] != pid:
            print(f"{'':>3}  {'':<16}     ({e['label']})")
    if CURRENT.exists():
        print(f"\ncurrent: {CURRENT.read_text(encoding='utf-8').strip()}")
    return 0


def cmd_add(a: argparse.Namespace) -> int:
    path = _expand(a.path)
    _validate_pack(path)
    pid = a.id or _slug_from_path(path)
    label = a.label or _pack_label(path)
    # Prefer writing only to local registry
    local = _read_toml(LOCAL)
    packs = dict(local.get("packs") or {})
    packs[pid] = {"path": str(path), "label": label}
    # Also keep any shared-only packs that aren't being overwritten? No — local file
    # should only contain local entries. Shared stays in packs.toml.
    _write_local({k: {"path": str(_expand(str(v["path"]))), "label": str(v.get("label") or k)}
                  for k, v in packs.items()})
    print(f"registered [{pid}] → {path}")
    print(f"  (saved in {LOCAL.name})")
    return 0


def cmd_remove(a: argparse.Namespace) -> int:
    local = _read_toml(LOCAL)
    packs = dict(local.get("packs") or {})
    if a.id not in packs:
        # If only in shared, tell user to edit packs.toml
        shared = _read_toml(SHARED).get("packs") or {}
        if a.id in shared:
            sys.exit(f"'{a.id}' is in packs.toml (shared). Remove it there, or override in packs.local.toml.")
        sys.exit(f"unknown pack id: {a.id}")
    del packs[a.id]
    _write_local({k: {"path": str(_expand(str(v["path"]))), "label": str(v.get("label") or k)}
                  for k, v in packs.items()})
    if CURRENT.exists() and CURRENT.read_text().strip() == a.id:
        CURRENT.unlink()
    print(f"removed [{a.id}] from {LOCAL.name}")
    return 0


def _resolve_selector(selector: str | None, packs: dict[str, dict]) -> dict:
    # Explicit path
    if selector and (selector.startswith("/") or selector.startswith("~") or selector.startswith(".")):
        path = _expand(selector)
        _validate_pack(path)
        pid = _slug_from_path(path)
        return {"id": pid, "path": str(path), "label": _pack_label(path)}

    # Number
    if selector and selector.isdigit():
        items = list(packs.values())
        n = int(selector)
        if not 1 <= n <= len(items):
            sys.exit(f"pack number out of range (1–{len(items)})")
        return items[n - 1]

    # Id
    if selector and selector in packs:
        return packs[selector]

    # .current-pack
    if not selector and CURRENT.exists():
        cur = CURRENT.read_text(encoding="utf-8").strip()
        if cur in packs:
            return packs[cur]

    # Interactive
    if not packs:
        sys.exit("No packs registered. Run: make add DIR=/path/to/pack")
    if selector:
        sys.exit(f"unknown pack '{selector}'. Run: make packs")

    print("Registered packs:", file=sys.stderr)
    items = list(packs.values())
    for i, e in enumerate(items, 1):
        print(f"  {i}) {e['id']:<16} {e['label']}", file=sys.stderr)
        print(f"      {e['path']}", file=sys.stderr)
    try:
        choice = input(f"Pick [1–{len(items)}] (or id): ").strip()
    except EOFError:
        sys.exit("no pack selected")
    if not choice:
        sys.exit("no pack selected")
    return _resolve_selector(choice, packs)


def cmd_resolve(a: argparse.Namespace) -> int:
    packs = load_packs()
    entry = _resolve_selector(a.selector, packs)
    path = Path(entry["path"])
    if not path.is_dir():
        sys.exit(f"pack path missing on disk: {path}")
    _validate_pack(path)
    out = OUT_ROOT / entry["id"]
    if a.remember or (a.selector is None):
        CURRENT.write_text(entry["id"] + "\n", encoding="utf-8")
    line = f"{entry['id']}\t{path}\t{out}"
    if a.write:
        Path(a.write).parent.mkdir(parents=True, exist_ok=True)
        Path(a.write).write_text(line + "\n", encoding="utf-8")
        print(f"→ {entry['id']}  ({entry['label']})", file=sys.stderr)
    else:
        print(line)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list registered packs").set_defaults(f=cmd_list)

    add = sub.add_parser("add", help="register a packwiz pack path")
    add.add_argument("--path", required=True)
    add.add_argument("--id")
    add.add_argument("--label")
    add.set_defaults(f=cmd_add)

    rem = sub.add_parser("remove", help="remove a pack from the local registry")
    rem.add_argument("--id", required=True)
    rem.set_defaults(f=cmd_remove)

    res = sub.add_parser("resolve", help="resolve selector → id, path, out dir")
    res.add_argument("selector", nargs="?", default=None)
    res.add_argument("--remember", action="store_true")
    res.add_argument("--write", default="", help="also write id\\tpath\\tout to this file")
    res.set_defaults(f=cmd_resolve)

    pick = sub.add_parser("pick", help="interactive resolve and remember")
    pick.set_defaults(
        f=lambda _a: cmd_resolve(argparse.Namespace(selector=None, remember=True, write=""))
    )

    a = ap.parse_args()
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
