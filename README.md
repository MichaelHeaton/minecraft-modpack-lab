# minecraft-modpack-lab

Point this at a **packwiz NeoForge** pack and ask: after you change the world
(no ore veins, no Nether, skyblock, …), can the player still craft what the pack needs?

Default mods assume a full vanilla world. Pack tweaks create chicken-and-egg gaps.
This tool boots a headless server, snapshots real recipes/tags, then checks reachability
against a **pack profile** (world flags + start resources + design targets).

## Quick start

```bash
make add DIR=~/path/to/your-pack
make dump PACK=my-pack EULA=1      # Docker: snapshot recipes the server really loaded
make report PACK=my-pack           # playability under profiles/my-pack.json
make why PACK=my-pack ITEM=minecraft:iron_ingot
```

## Pack profiles (`profiles/<id>.json`)

World assumptions matter:

| Flag | Example |
|---|---|
| `ore_veins: false` | Skyblock-esque / stripped overworld ores |
| `nether: false` | No Nether progression — blaze/netherite need substitutes |
| `terrain: void` | Classic void skyblock start |

See [docs/profiles.md](docs/profiles.md). Examples: `profiles/verdant.json`, `profiles/liminal.json`.

## Everyday commands

| Command | What |
|---|---|
| `make dump EULA=1` | Headless Docker snapshot → `out/<id>/recipe_data.json` |
| `make convert` | Re-parse snapshot + extract loot/GLMs from jars (no Docker) |
| `make report` | Playability report (targets + chicken-egg signals) |
| `make analyze EULA=1` | Dump + report |
| `make why ITEM=…` | Cheapest craft chain |
| `make knowledge` | Local learnings (client-only / CF-blocked mods) |

Outputs: `out/` and `.cache/` (gitignored). Pack repos are never modified.

## Layout

```
lab/                 headless snapshot (Docker + KubeJS exporter)
scripts/             registry, dump convert, reach, report, profiles
profiles/            world flags + start/targets per pack
examples/reach/      example start sets and target lists
docs/                profiles, knowledge, loot/GLM extract
```

Loot tables and NeoForge GLMs are jar-scanned on convert — see [docs/loot.md](docs/loot.md).
