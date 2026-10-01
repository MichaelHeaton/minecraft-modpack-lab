# Local knowledge cache (this machine only)

`.cache/` stores what we learn from snapshot runs so the next dump can skip known
client-only mods on round 1, and so notes about packs stay out of pack repos and
out of git.

| Path | Contents |
|---|---|
| `.cache/mods/client-only.json` | Global map of mod slugs that failed on a dedicated server |
| `.cache/packs/<id>/exclude-mods.txt` | Last exclude list for that pack |
| `.cache/packs/<id>/meta.json` | Last successful dump metadata (MC/NeoForge versions, recipe counts) |
| `out/<id>/` | Full snapshot + server dir (large; also gitignored) |

Regenerate dumps when you change the mod list or update major mods. The cache is a
hint for faster retries, not a substitute for a fresh snapshot.

```bash
make knowledge                    # show what we have learned
make dump PACK=liminal EULA=1     # seeds excludes from cache, learns after success
```

Do **not** commit `.cache/` or `out/`. Pack-repo cleanup (removing old recipe dumps /
lab prototypes) is a separate follow-up once this tool is the source of analysis.
