# Open work — modpack-lab

Living checklist. Update this when priorities shift. Session todos mirror it.

## Now / next

- [ ] **Archetype scoring** — teaching vs kitchen-sink from measurable signals (`make archetype`)
- [ ] **Mod-fit probe** — “what if I add mod X?” adds / conflicts / holes
- [ ] **Download remaining wishlist refs** not yet on disk (ATM10 base, Direwolf20, Regrowth, Crash Landing, …)
- [ ] Re-run `make corpus` after more references land

## Done recently

- [x] Recipe coverage + loot/GLM extract
- [x] Pack-origin tagging + `make compare` / `make attribute`
- [x] Multi-pack web hub + pack switcher (`make serve`)
- [x] Progression + economics insights
- [x] Reference wishlist + mod corpus tooling
- [x] **Launcher discover** — `make discover APPLY=1` scans Prism + CurseForge and auto-registers
- [x] Hub Builds vs References grouping

## Deferred

- [ ] Pack **family** narrative (Verdant → Elysian → Influx → Liminal) — soft labels only until that content strategy proves out
- [ ] Click-to-run dump from the web UI
- [ ] Interactive tech-tree graphs
- [ ] Auto-fetch CurseForge / Modrinth when not installed (discover covers already-installed)

## Reference pack wishlist

| Id | Pack | CurseForge | Local? |
|---|---|---|---|
| atm10 | All the Mods 10 | [link](https://www.curseforge.com/minecraft/modpacks/all-the-mods-10) | wishlist |
| atm10-sky | All the Mods 10 Sky | [link](https://www.curseforge.com/minecraft/modpacks/all-the-mods-10-sky) | wishlist |
| direwolf20-s14 | FTB Presents Direwolf20 S14 | [link](https://www.curseforge.com/minecraft/modpacks/ftb-presents-direwolf20-s14) | wishlist |
| regrowth | Regrowth (newer) | [link](https://www.curseforge.com/minecraft/modpacks/regrowth) | wishlist |
| regrowth-hqm | Regrowth: An HQM Pack (classic) | [link](https://www.curseforge.com/minecraft/modpacks/regrowth-an-hqm-pack) | wishlist |
| minecolonies-official | MineColonies Official | [link](https://www.curseforge.com/minecraft/modpacks/minecolonies-official) | wishlist |
| ftb-evolution | FTB Evolution | [link](https://www.curseforge.com/minecraft/modpacks/ftb-evolution) | wishlist |
| minecolonies-dimensional | MineColonies Dimensional Adventure | [link](https://www.curseforge.com/minecraft/modpacks/minecolonies-dimensional-adventure) | wishlist |
| crash-landing | Crash Landing | [link](https://www.curseforge.com/minecraft/modpacks/crash-landing) | wishlist |
| rlcraft | RLCraft | [link](https://www.curseforge.com/minecraft/modpacks/rlcraft) | wishlist |
| homestead-cozy | Homestead Cozy | [link](https://www.curseforge.com/minecraft/modpacks/homestead-cozy) | wishlist |
| skyfactory-4 | SkyFactory 4 | [link](https://www.curseforge.com/minecraft/modpacks/skyfactory-4) | wishlist |
| ciscos-adventure-rpg | Cisco's Adventure RPG Ultimate | [link](https://www.curseforge.com/minecraft/modpacks/ciscos-adventure-rpg-ultimate) | wishlist |
| society-sunlit-valley | Society: Sunlit Valley | [link](https://www.curseforge.com/minecraft/modpacks/society-sunlit-valley) | wishlist |
| dungeon-heroes | Dungeon Heroes | [link](https://www.curseforge.com/minecraft/modpacks/dungeon-heroes) | wishlist |

After download (Curse/Modrinth zip or packwiz checkout):

```bash
make add DIR=~/Downloads/All\ the\ Mods\ 10 ID=atm10 ROLE=reference LABEL="All the Mods 10"
make dump PACK=atm10 EULA=1   # if NeoForge + KubeJS capable; else corpus still reads mods/
make corpus                   # mod frequency across builds + local references
make web && make serve
```

## Build packs (Colony Protocol)

| Id | Intent (hypothesis — prove with archetype later) |
|---|---|
| verdant | Teaching / focused |
| elysian | Teaching / focused |
| influx | Teaching / focused |
| liminal | Kitchen-sink inherit (until quests/integrations catch up) |
| ltm | Separate product |

See also [roadmap.md](roadmap.md) and the living checklist [backlog.md](backlog.md).
