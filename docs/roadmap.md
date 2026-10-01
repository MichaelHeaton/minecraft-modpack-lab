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

Almost every snapshot recipe is either **parsed into a route** or **classified
non-route** (compost values, dye specials, enchant data, …). Remaining unparsed
types in a report are real coverage debt — open an issue / extend `recipe_parse.py`.

## Next layers (in order)

### 1. Compare + attribute (started)

- `make compare` already flags pack-only recipes (e.g. Verdant’s
  `cpverdant:sieve_*` Silent Gear metals missing from Liminal).
- Later: diff **mod lists**, **KubeJS script trees**, and **config toggles** so
  “why doesn’t this work?” points at a file, not just a missing recipe id.

### 2. Config + jar economics

Use installed jars + generated configs to answer design questions:

- Generators with similar recipes / similar RF — hide or gate duplicates?
- Machines that are side-grades vs true upgrades
- Disabled recipes / JEI blacklists already in config

This is jar+config scrape, not another Docker boot. Keep findings under
`out/<id>/insights/` (gitignored).

### 3. Progression / quest charts

From reach depths + mod “chapters”:

- Cluster items by mod and depth → draft **tech-tree chapters**
- Suggest FTB Quests / HermitQuest chapter order from target lists
- Mark **in-game intended** lines (mod’s own quest book / patchouli) vs kitchen-sink noise

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
