# Agent notes — minecraft-modpack-lab

Pack-agnostic tooling. Point at a local packwiz NeoForge pack; snapshot recipes from a headless
Docker server; run reachability. Pack-specific start/targets files stay in the pack repos
(examples only under `examples/reach/`).

## Commands

```bash
make packs
make add DIR=/path/to/pack
make doctor PACK=<id>
make dump PACK=<id> EULA=1
make check PACK=<id>
make analyze PACK=<id> EULA=1
```

Outputs: `out/<pack-id>/`. Do not write analysis artifacts into pack repos from this tool.

## Do not

- Copy the jar-scrape pipeline here unless asked (stays in pack repos as fallback)
- Guess KubeJS / Docker results you cannot run — mark unverified
- Put model names in commits/PRs

## Source of the prototype

Ported from `minecraft-modpack-cp-liminal` `tools/modpack-lab/` + `scripts/series-reach.py`
(after PRs #103 / #104). Keep dump/snapshot schemas stable so packs keep working.
