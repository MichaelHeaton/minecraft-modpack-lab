# Loot tables & global loot modifiers

Reachability needs mob/chest/block drops, not just crafting recipes. After a server
snapshot, `make convert` (also part of `make dump`) scans the installed jars under
`out/<pack>/server/` and merges:

1. **Loot tables** — `data/*/loot_table/**` (and legacy `loot_tables/`)
2. **NeoForge GLMs** — `data/*/loot_modifiers/**` listed in
   `data/neoforge/loot_modifiers/global_loot_modifiers.json`

`neoforge:add_table` modifiers (Silent Gear mob silk, Farmer's Delight chest injects, …)
are folded into the targeted entity/chest keys so `series_reach` can use them when the
start file lists those mobs or `loot_sources`.

This is jar-based on purpose: more reliable across KubeJS versions than dumping loot from
inside the running server. Re-run after mod updates:

```bash
make convert PACK=verdant   # no Docker — uses existing snapshot + server/mods
make report PACK=verdant
```

Limits: chances/conditions are ignored (same as recipes). Code-only drops and some
custom GLM types may still be missing — they show up as false “no route” until covered.
