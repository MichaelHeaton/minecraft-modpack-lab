# minecraft-modpack-lab

Reusable tooling for **packwiz NeoForge** modpack design. Point it at a pack on your machine;
one `make` command boots that pack on a **headless server in Docker** and saves what the server
really loaded (recipes + resolved tags). Later: reachability checks, variant diffs, gap analysis.

Jar scraping misses recipes mods build at runtime (for example Ex Deorum's 4 ore chunks → ore).
JEI/EMI read the server's final set — so we snapshot a dedicated server instead.

## Quick start

```bash
# 1. Register packs you work on (paths stay on this machine)
make add DIR=~/Projects/specterrealm/esport/minecraft-modpack-cp-liminal
make packs                         # numbered list

# 2. Check the machine is ready (Docker Desktop running, etc.)
make doctor PACK=liminal

# 3. Snapshot + dump (accepts the Minecraft EULA for the container)
make dump PACK=liminal EULA=1

# 4. Reachability (example start/targets under examples/reach/)
make check PACK=liminal
make why PACK=liminal ITEM=mekanism:ingot_osmium
```

Omit `PACK=` to reuse the last pick, or get a `1) 2) 3)` prompt.

Outputs go under `out/<pack-id>/` (gitignored). Your pack repo is **not** modified.

## Everyday make targets

| Command | What it does |
|---|---|
| `make packs` | List registered packs |
| `make add DIR=…` | Register a packwiz pack (`packs.local.toml`) |
| `make pick` | Choose current pack |
| `make doctor` | Docker / python / pack / RAM / port checks |
| `make snapshot EULA=1` | Headless boot → `out/<id>/snapshot.json` |
| `make dump EULA=1` | Snapshot + `out/<id>/recipe_data.json` |
| `make check` | Reachability vs start + targets files |
| `make analyze EULA=1` | Dump + check |
| `make why ITEM=…` | Cheapest craft chain |
| `make blocked ITEM=…` | Per-recipe missing ingredients |

Pack selector: `PACK=liminal` · `PACK=2` · `PACK=/abs/path` · omit to pick.

## Layout

```
lab/                 headless snapshot (lab.sh, packtool, parse_log, KubeJS exporter)
scripts/             packs registry, snapshot→dump, reachability
examples/reach/      example start + targets (pack-specific files stay in pack repos)
packs.toml           optional shared defaults (Colony Protocol paths)
packs.local.toml     your machine registry (gitignored)
out/<pack-id>/       snapshots, dumps, server dirs (gitignored)
```

## Requirements

- Docker (Desktop on macOS) with enough RAM for the pack (Liminal-sized ≈ 8G+ for the container)
- Python 3.11+
- A packwiz pack that includes **KubeJS** (the exporter is a server script)
- `packwiz refresh` already run in the pack if you changed files (`index.toml` is served as-is)

## How the snapshot works

1. Serves a copy of the pack over HTTP (no packwiz CLI needed on the host).
2. Runs `itzg/minecraft-server` (NeoForge versions from `pack.toml`) with `PACKWIZ_URL`.
3. Client-only mods that crash the dedicated server are pruned from the served copy and the run retries (list in `out/<id>/exclude-mods.txt`).
4. `lab/export/zz_lab_export.js` prints `[LABDUMP]` recipe/tag lines; `parse_log.py` writes `snapshot.json`.
5. `snapshot_to_dump.py` converts to the dump format `series_reach.py` reads.

## Not verified yet (first real Mac run)

Written and unit-tested without relying on a live Docker daemon in every environment. Still to confirm on your machine:

- KubeJS exporter APIs on the pack's KubeJS version
- Packwiz installer removing jars after prune + retry
- How many extra client-only mods turn up beyond the first crash

If a CurseForge mod blocks download, drop its jar in `out/<id>/extra-mods/` and re-run.

## Roadmap

1. Clean snapshot on Liminal; compare to jar dumps
2. Loot / worldgen / global loot modifiers in the exporter
3. Static dependency map from `neoforge.mods.toml` (no Docker)
4. Parallel variant containers + snapshot diffs (hidden deps, wasted mods)
5. Mod recommendations from cross-pack history (ore routes, known gaps)

## License

See [LICENSE](LICENSE).
