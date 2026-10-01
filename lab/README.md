# lab/ — headless server snapshot

Boots a packwiz pack on a NeoForge dedicated server in Docker and writes `snapshot.json`
(schema 1: recipes by id, resolved tags, done counts).

Prefer the repo root Makefile (`make doctor`, `make dump EULA=1`). Direct use:

```bash
./lab/lab.sh doctor   --pack /path/to/pack --out ./out/my-pack
./lab/lab.sh snapshot --pack /path/to/pack --out ./out/my-pack --accept-eula
```

| File | Role |
|---|---|
| `lab.sh` | doctor + snapshot (+ client-only prune retry) |
| `packtool.py` | prune served pack copy; detect client-only crash mods |
| `parse_log.py` | `[LABDUMP]` log lines → `snapshot.json` |
| `export/zz_lab_export.js` | KubeJS exporter (read-only; name sorts last) |

See the root [README.md](../README.md) for registry UX and reachability.
