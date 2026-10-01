# Roadmap — vibe-coding a modpack with this lab

Goal: an AI (or human) can **design progression** without memorizing every mod’s
JEI pages. Point the lab at a packwiz pack → snapshot real recipes/tags/loot →
ask “is this playable?”, “why does Verdant unlock crimson iron and Liminal
doesn’t?”, “what should the quest chapter look like?”

Living checklist: **[docs/backlog.md](backlog.md)** (open work + reference wishlist).

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

### 1. Deeper pack attribute — done (CLI + web)

`make attribute A=verdant B=liminal` → `out/diffs/<a>-vs-<b>/attribute.{json,md}`

Diffs packwiz mod ids, KubeJS/datapack trees, pack-origin recipe ids from dumps,
and optional server configs. Surfaces **copy candidates** (datapack recipes only
in A — e.g. `kubejs/data/cpverdant/recipe/sieve_*`). Web compare includes an
Attribute tab when packs are registered via `make add`.

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

### 4. Reference packs + archetype scoring (next product layer)

**Build packs** (Verdant, Liminal, …) vs **reference packs** (ATM10, Direwolf20,
Regrowth, skyblocks you’ve played): same dump/compare/attribute pipeline, tagged
`role = "reference"` in the registry so the hub groups them separately. References
are idea mines and baselines, not “must be playable under our world flags.”

**Archetype score** (quantify teaching vs kitchen-sink — don’t trust vibes):

| Signal | Teaching / focused ↑ | Kitchen sink ↑ |
|---|---|---|
| Pack-origin recipe count / mod count | high | low |
| KubeJS + datapack file density | high | low |
| Quest book / FTB Quests present + chapter count | high | low/absent |
| Unique mods with ≥1 design target | few, deep | many, shallow |
| Redundant generator clusters (economics) | gated/hidden | many open |
| Median depth of design targets | ordered ladder | flat / missing |

Outputs something like `teaching_score` / `kitchensink_score` with evidence rows
in `insights/archetype.json` and a hub badge. Verdant should score teaching;
current Liminal should score kitchen-sink until integrations/quests land.

**Mod-fit probe** (separate command later): given a candidate mod (+ optional
reference pack that uses it), report what item namespaces it adds, which of your
targets it unlocks, conflicts with existing generators/ores, and new holes
(items in its recipes not reachable from your start) — the Liminal Silent Gear
problem generalized.

### 5. Pack families (defer)

Grouping Verdant/Elysian/Influx as a teaching trilogy that “graduates” into Liminal
is a content strategy, not a tool requirement yet. Soft labels on profiles
(`family`, `tier`) are enough if you want them later; don’t build family-specific
pipelines until that narrative proves it ships.

### 6. AI-assisted pack authoring loop

1. Propose a world profile + target list (+ optional reference pack)
2. `make analyze` → blocked targets + archetype score
3. `make attribute` / compare against reference or sibling build pack
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
