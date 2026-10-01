# Roadmap — vibe-coding a modpack with this lab

Goal: an AI (or human) can **design progression** without memorizing every mod’s
JEI pages. Point the lab at a packwiz pack → snapshot real recipes/tags/loot →
ask “is this playable?”, “why does Verdant unlock crimson iron and Liminal
doesn’t?”, “what should the quest chapter look like?”

## Done now

| Capability | Command / artifact |
|---|---|
| Server-true recipes + tags | `make dump` → `out/<id>/recipe_data.json` |
| Loot tables + NeoForge GLMs | jar extract on `make convert` — [loot.md](loot.md) |
| World-aware reachability | `profiles/<id>.json` + `make report` |
| Pack vs mod recipe origin | `origin: pack\|mod` from recipe-id namespace (`cpverdant`, `kubejs`, …) |
| Pack-to-pack diff | `make compare A=verdant B=liminal [ITEM=…]` |
| Static web hub (multi-pack UI) | `make web` / `make serve` → `out/web/` |

Almost every snapshot recipe is either **parsed into a route** or **classified
non-route** (compost values, dye specials, enchant data, …). Remaining unparsed
types in a report are real coverage debt — open an issue / extend `recipe_parse.py`.

## Next layers (in order)

### 0. Web UI (human front-end) — done

CLI stays for agents/CI. Humans get one static site for **all** dumped packs:

- `make web` → `out/web/index.html` (hub) + `out/web/packs/<id>/`
- `make serve` → http://127.0.0.1:8765/ (pack switcher in the nav)
- `make web-compare A=verdant B=liminal` → under `out/web/compare/`

Overview, targets + craft paths, pack-authored recipes, coverage, economics /
progression when insights JSON exists. No Docker/Node — Python 3 only.

### 1. Deeper pack attribute (next)

`make compare` already flags pack-only recipes. Next high-value tool for
builders: **why pack A works and B doesn’t** at the file level —

- Mod-list diff (packwiz toml / installed jars)
- KubeJS + datapack tree diff (`kubejs/`, `kubejs/data/`, pack namespaces)
- Config toggle diff (disabled machines, JEI hide)

Surface that in the web compare view so “copy Verdant’s crimson sieve” is a
clickable path, not a CLI wall of text.

### 2. Config + jar economics — done (CLI)

`make insights PACK=verdant` → `out/<pack>/insights/economics.{json,md}`

Jar+config scrape (no Docker): generator clusters, machine tier ladders, config
blacklist/disable hits. Heuristics are naming-based and marked `verified: false`.

Later: RF/FE output tables, true side-grade vs upgrade scoring, pack-authored
config diffs between packs. Web UI surfaces the JSON when present.

### 3. Progression / quest charts — done (CLI)

`make progression PACK=verdant` → `out/<pack>/insights/progression.{json,md}`

Clusters reachable items by mod namespace, orders chapters by median target depth,
flags pack-only unlocks and blocked targets. Web UI surfaces the same JSON.

### 4. AI-assisted pack authoring loop

1. Propose a world profile + target list  
2. `make analyze` → blocked targets  
3. `make compare` against a known-good pack (Verdant) → missing KubeJS/datapack  
4. Agent drafts the sieve/script/config fix in the pack repo  
5. Re-dump → green report → lock a quest chapter  

## Profile fields

```json
{
  "pack_namespaces": ["cpverdant"]
}
```

Any recipe id under those namespaces (plus `kubejs` / `crafttweaker`) is tagged
`origin: "pack"` so reports and compares can say “this route is pack scripting,
not the mod.”
