#!/usr/bin/env python3
"""Turn the "[LABDUMP]" lines the exporter script printed into a snapshot file.

Usage: parse_log.py --log <log file> [--log <another>] --out snapshot.json [--pack-name NAME]

Snapshot format (schema 1): {"schema", "generated", "source": "server", "pack", "recipes": {id: recipe json},
"tags": {tag: [item ids]}, "done": {"recipes", "tags", "errors"} or null, "bad_lines": n}
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone

MARK = "[LABDUMP] "
DONE = re.compile(r"(\w+)=(\d+)")


def parse(paths: list[str]) -> dict:
    recipes: dict[str, dict] = {}
    tags: dict[str, list[str]] = {}
    done = None
    bad = 0
    for path in paths:
        try:
            fh = open(path, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                at = line.find(MARK)
                if at < 0:
                    continue
                kind, _, rest = line[at + len(MARK):].rstrip("\n").partition(" ")
                if kind == "recipe":
                    rid, _, blob = rest.partition(" ")
                    try:
                        recipes[rid] = json.loads(blob)
                    except ValueError:
                        bad += 1
                elif kind == "tag":
                    name, _, blob = rest.partition(" ")
                    try:
                        tags[name] = sorted(set(json.loads(blob)))
                    except ValueError:
                        bad += 1
                elif kind == "done":
                    done = {k: int(v) for k, v in DONE.findall(rest)}
    return {"recipes": recipes, "tags": tags, "done": done, "bad_lines": bad}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", action="append", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pack-name", default="")
    a = ap.parse_args()
    snap = parse(a.log)
    snap.update({"schema": 1, "source": "server", "pack": a.pack_name,
                 "generated": datetime.now(timezone.utc).isoformat()})
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(snap, fh, indent=1, sort_keys=True)
    done = snap["done"]
    print(f"{len(snap['recipes'])} recipes, {len(snap['tags'])} tags, "
          f"{snap['bad_lines']} unreadable lines; exporter finished: {done if done else 'NO (incomplete)'}")
    return 0 if done else 2


if __name__ == "__main__":
    sys.exit(main())
