# Reachability examples

`series_reach.py` answers: from this pack's **starting resources**, can the player make X?

These files are **examples**. Real pack start/targets should live in each pack repo
(e.g. Liminal `docs/series/items/reach/`). Point at them with `START=` / `TARGETS=`.

```bash
make check PACK=liminal
make check PACK=liminal START=/path/to/pack/docs/series/items/reach/verdant.json
make why PACK=liminal ITEM=minecraft:iron_ingot
make blocked PACK=liminal ITEM=silentgear:crimson_iron_ingot
make tags PACK=liminal
```

| File | What |
|---|---|
| `verdant.json` | Example start: overworld surface, no ore worldgen, Ex Deorum sieve |
| `targets.json` | Example design goals (gear metals, Powah, AE2, Create, …) |

Needs a dump first: `make dump PACK=… EULA=1` → `out/<id>/recipe_data.json`.
