# Pack profiles — world assumptions for playability checks

A **profile** describes how a pack changes the default Minecraft world. Vanilla mods
assume ores, the Nether, End, villages, etc. When a pack strips those, recipes can
silently become unreachable (chicken-and-egg). The lab uses the profile to:

1. Pick the right **start** set (what the player can gather without crafting)
2. Pick **targets** (items that must be craftable for the pack to be "playable")
3. Warn when the start/targets disagree with world flags (e.g. netherite target with `nether: false` and no substitute route)

## Schema (`profiles/<id>.json`)

```json
{
  "id": "verdant",
  "label": "Colony Protocol: Verdant",
  "world": {
    "spawn": "overworld",
    "terrain": "full",
    "ore_veins": false,
    "nether": false,
    "end": false,
    "villages": true,
    "wandering_traders": false
  },
  "start": "examples/reach/verdant.json",
  "targets": "examples/reach/targets-verdant.json",
  "notes": "optional"
}
```

| `world` field | Meaning |
|---|---|
| `spawn` | `overworld` \| `void` \| `nether` \| `custom` |
| `terrain` | `full` (normal generation) \| `island` \| `void` |
| `ore_veins` | Whether overworld ore veins exist |
| `nether` / `end` | Whether those dimensions are part of progression |
| `villages` | Village structures / chests available |
| `wandering_traders` | Traders spawn |

Profiles are **pack design docs**, not dumps — commit them. Dumps stay under `out/` (local).

```bash
make report PACK=verdant    # playability report using profiles/verdant.json
make check PACK=verdant     # same start/targets as the profile
```
