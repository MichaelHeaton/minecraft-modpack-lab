#!/usr/bin/env bash
# modpack-lab: boot a packwiz modpack on a headless server in Docker and snapshot what the server really loaded.
#
#   lab.sh doctor   [--pack DIR] [--out DIR]
#   lab.sh snapshot [--pack DIR] [--out DIR] [--memory 8G] [--timeout 1200] [--port 8099] [--accept-eula]
#
# Prefer the repo-root Makefile (make doctor / make dump EULA=1) so pack registry + out/<id>/ are used.
# Needs: docker (running), python3, a packwiz pack (pack.toml + index.toml) that includes KubeJS.
# Writes: <out>/snapshot.json (recipes + resolved tags), <out>/server/ (server files, logs), <out>/lab.log
# Not needed: Prism, the game client, packwiz.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CMD="${1:-}"; [[ $# -gt 0 ]] && shift || true

PACK="$PWD"; OUT=""; MEMORY="8G"; TIMEOUT=1200; PORT=8099
ACCEPT_EULA="${MC_EULA:-}"
IMAGE="${LAB_IMAGE:-itzg/minecraft-server:java21}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pack) PACK="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --memory) MEMORY="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --accept-eula) ACCEPT_EULA=true; shift ;;
    -h|--help) sed -n 2,12p "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
PACK="$(cd "$PACK" 2>/dev/null && pwd || echo "$PACK")"
OUT="${OUT:-$PACK/.lab}"

FAILS=0
ok()   { printf '  ok    %s\n' "$*"; }
warn() { printf '  WARN  %s\n' "$*"; }
bad()  { printf '  FAIL  %s\n' "$*"; FAILS=$((FAILS + 1)); }
toml_get() { sed -n "s/^$1 *= *\"\(.*\)\"/\1/p" "$PACK/pack.toml" | head -1; }

doctor() {
  echo "modpack-lab doctor (pack: $PACK, out: $OUT)"
  if command -v docker >/dev/null 2>&1; then
    ok "docker installed"
    if docker info >/dev/null 2>&1; then ok "docker daemon running"
    else bad "docker is installed but not running (start Docker Desktop / the docker service)"; fi
  else bad "docker not found (install Docker: https://docs.docker.com/get-docker/)"; fi
  command -v python3 >/dev/null 2>&1 && ok "python3 installed" || bad "python3 not found"
  if [[ -f "$PACK/pack.toml" && -f "$PACK/index.toml" ]]; then
    ok "packwiz pack found ($(toml_get name))"
    [[ -n "$(toml_get minecraft)" && -n "$(toml_get neoforge)" ]] \
      && ok "versions: minecraft $(toml_get minecraft), neoforge $(toml_get neoforge)" \
      || bad "pack.toml has no [versions] minecraft/neoforge (this prototype supports NeoForge packs only)"
    if ls "$PACK"/mods/kubejs.pw.toml >/dev/null 2>&1; then ok "KubeJS is in the pack (the exporter needs it)"
    else bad "mods/kubejs.pw.toml not found: the exporter is a KubeJS script, so the pack must include KubeJS"; fi
    warn "index.toml is served as-is: run 'packwiz refresh' first if you changed files"
  else bad "no pack.toml and index.toml in $PACK (use --pack DIR)"; fi
  if mkdir -p "$OUT" 2>/dev/null && [[ -w "$OUT" ]]; then ok "output folder writable: $OUT"
  else bad "cannot write to the output folder $OUT (use --out DIR)"; fi
  local mem_gb=""
  if [[ -r /proc/meminfo ]]; then mem_gb=$(awk '/MemTotal/ {printf "%d", $2/1048576}' /proc/meminfo)
  elif command -v sysctl >/dev/null 2>&1; then mem_gb=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1073741824 )); fi
  if [[ -n "$mem_gb" && "$mem_gb" -gt 0 ]]; then
    [[ "$mem_gb" -ge 12 ]] && ok "${mem_gb} GB RAM on this machine (server asks for $MEMORY)" \
      || warn "only ${mem_gb} GB RAM here; the server asks for $MEMORY (Docker Desktop also caps its own memory)"
  fi
  if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    bad "port $PORT is already in use (use --port N)"; else ok "port $PORT free"; fi
  [[ "$ACCEPT_EULA" == "true" ]] && ok "Minecraft EULA accepted (--accept-eula / MC_EULA=true)" \
    || warn "EULA not accepted yet: snapshot needs --accept-eula (https://aka.ms/MinecraftEULA)"
  echo
  [[ $FAILS -eq 0 ]] && echo "ready." || { echo "$FAILS problem(s) to fix."; return 1; }
}

snapshot() {
  doctor
  [[ "$ACCEPT_EULA" == "true" ]] || { echo "Pass --accept-eula to accept the Minecraft EULA (https://aka.ms/MinecraftEULA)." >&2; exit 1; }
  name="modpack-lab-$$"; srv="$OUT/server"; served="$OUT/pack-served"; excl="$OUT/exclude-mods.txt"
  local round=0 max_rounds=10 status=""
  http_pid=""
  stop_all() {
    [[ -n "${http_pid:-}" ]] && kill "$http_pid" 2>/dev/null || true
    http_pid=""
    docker rm -f "$name" >/dev/null 2>&1 || true
  }
  trap stop_all EXIT

  rm -rf "$srv"; mkdir -p "$srv/kubejs/server_scripts" "$OUT/extra-mods"; touch "$excl"
  cp "$HERE/export/zz_lab_export.js" "$srv/kubejs/server_scripts/zz_lab_export.js"

  while :; do
    round=$((round + 1))
    # Serve a copy of the pack without the mods known to be client-only (the original pack is not touched).
    python3 "$HERE/packtool.py" prune --src "$PACK" --dst "$served" --exclude-file "$excl"
    echo "round $round: serving the pack on port $PORT and starting the server (first run downloads the image and mods)"
    python3 -m http.server "$PORT" --bind 0.0.0.0 --directory "$served" >"$OUT/http.log" 2>&1 &
    http_pid=$!
    docker rm -f "$name" >/dev/null 2>&1 || true
    docker run -d --name "$name" \
      --add-host=host.docker.internal:host-gateway \
      -e EULA=TRUE -e TYPE=NEOFORGE \
      -e VERSION="$(toml_get minecraft)" -e NEOFORGE_VERSION="$(toml_get neoforge)" \
      -e PACKWIZ_URL="http://host.docker.internal:$PORT/pack.toml" \
      -e MEMORY="$MEMORY" -e ONLINE_MODE=FALSE -e LEVEL_TYPE=minecraft:flat \
      -e VIEW_DISTANCE=2 -e SIMULATION_DISTANCE=2 -e SPAWN_PROTECTION=0 -e ENABLE_RCON=false \
      -e UID="$(id -u)" -e GID="$(id -g)" \
      -v "$srv:/data" -v "$OUT/extra-mods:/mods:ro" \
      "$IMAGE" >/dev/null

    local waited=0; status=timeout
    while [[ $waited -lt $TIMEOUT ]]; do
      if grep -qs '\[LABDUMP\] done' "$srv/logs/kubejs/server.log" "$srv/logs/latest.log" 2>/dev/null; then status=done; break; fi
      if [[ "$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null)" != "true" ]]; then status=exited; break; fi
      sleep 5; waited=$((waited + 5))
    done
    docker logs "$name" >"$OUT/lab.log" 2>&1 || true
    [[ -n "$http_pid" ]] && kill "$http_pid" 2>/dev/null || true; http_pid=""
    [[ "$status" == "done" ]] && break

    if [[ "$status" == "exited" && $round -lt $max_rounds ]]; then
      local found
      found="$(python3 "$HERE/packtool.py" detect --log "$OUT/lab.log" --mods-dir "$srv/mods" --pack "$PACK/mods" || true)"
      found="$(comm -13 <(sort -u "$excl") <(printf '%s\n' "$found" | sort -u) | sed '/^$/d')"
      if [[ -n "$found" ]]; then
        echo "client-only mods the server cannot load; leaving them out and trying again:"
        printf '  %s\n' $found
        printf '%s\n' $found >>"$excl"
        continue
      fi
    fi
    echo "the server $( [[ $status == exited ]] && echo stopped || echo "timed out after ${TIMEOUT}s" ) before the dump finished. Last log lines:" >&2
    tail -60 "$OUT/lab.log" >&2
    echo "(full log: $OUT/lab.log; if a mod could not be downloaded, put its jar in $OUT/extra-mods/ and run again)" >&2
    exit 1
  done

  echo "dump finished; stopping the server"
  docker stop -t 60 "$name" >/dev/null 2>&1 || true
  python3 "$HERE/parse_log.py" --pack-name "$(toml_get name)" --out "$OUT/snapshot.json" \
    --log "$srv/logs/kubejs/server.log" --log "$srv/logs/latest.log"
  if [[ -s "$excl" ]]; then
    echo "left out as client-only ($(wc -l <"$excl" | tr -d ' ')); consider 'side = \"client\"' in their pw.toml files:"
    sed 's/^/  /' "$excl"
  fi
  echo "snapshot: $OUT/snapshot.json"
}

case "$CMD" in
  doctor) doctor ;;
  snapshot) snapshot ;;
  *) sed -n 2,12p "$0"; exit 2 ;;
esac
