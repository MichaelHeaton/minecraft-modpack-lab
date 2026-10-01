# modpack-lab — headless packwiz / NeoForge analysis tooling
#
# Point this repo at any packwiz pack on your machine. One make command boots the
# pack on a headless server in Docker and snapshots real recipes + tags.
#
# Pack selection (any target that needs a pack):
#   PACK=liminal          by id
#   PACK=1                by number from `make packs`
#   PACK=/path/to/pack    by path (also registers nothing; just uses it)
#   (omit PACK)           uses last pick, or prompts 1/2/3/…

PACK    ?=
EULA    ?=
START   ?=
TARGETS ?=
ITEM    ?=
MEMORY  ?=
PORT    ?=
TIMEOUT ?=

PY      := python3
RUN     := $(PY) scripts/run.py
PACKS   := $(PY) scripts/packs.py

RUN_FLAGS := $(if $(PACK),--pack $(PACK),)
RUN_FLAGS += $(if $(filter 1 true TRUE yes YES,$(EULA)),--accept-eula,)
RUN_FLAGS += $(if $(MEMORY),--memory $(MEMORY),)
RUN_FLAGS += $(if $(PORT),--port $(PORT),)
RUN_FLAGS += $(if $(TIMEOUT),--timeout $(TIMEOUT),)
RUN_FLAGS += $(if $(START),--start $(START),)
RUN_FLAGS += $(if $(TARGETS),--targets $(TARGETS),)
RUN_FLAGS += $(if $(ITEM),--item $(ITEM),)

.DEFAULT_GOAL := help

.PHONY: help packs add remove pick doctor snapshot dump check why blocked tags analyze knowledge report convert compare web serve web-compare progression insights

help:  ## show targets
	@echo "modpack-lab — is this pack playable after world tweaks?"
	@echo ""
	@echo "Setup"
	@echo "  make packs                         list registered packs"
	@echo "  make add DIR=/path/to/pack         register a pack (saved in packs.local.toml)"
	@echo "  make remove ID=liminal             unregister a local pack"
	@echo "  make pick                          choose current pack (1/2/3…)"
	@echo "  make knowledge                     show local learnings (.cache/, gitignored)"
	@echo ""
	@echo "Analyze  (PACK=id|N|/path  or omit to pick)"
	@echo "  make doctor                        check Docker / pack / RAM / port"
	@echo "  make dump EULA=1                   headless snapshot → recipe_data.json"
	@echo "  make report                        playability report (profile world flags + targets)"
	@echo "  make web                            rebuild hub + all dumped packs → out/web/"
	@echo "  make web PACK=id                   rebuild one pack + hub"
	@echo "  make serve                         generate hub + python http.server :8765"
	@echo "  make web-compare A=id B=id         compare into out/web/compare/"
	@echo "  make convert PACK=id               re-parse snapshot + extract loot (no Docker)"
	@echo "  make compare A=id B=id [ITEM=…]    why pack A unlocks what B does not"
	@echo "  make insights PACK=id              jar+config economics → out/<id>/insights/"
	@echo "  make progression PACK=id           quest-chapter draft from reach depths"
	@echo "  make analyze EULA=1                dump + report"
	@echo "  make check                         reachability only"
	@echo "  make why ITEM=mod:item             cheapest craft chain"
	@echo "  make blocked ITEM=mod:item         per-recipe missing ingredients"
	@echo "  make tags                          unresolved ingredient tags"
	@echo ""
	@echo "Profiles: profiles/<id>.json (world + pack_namespaces). See docs/profiles.md + docs/roadmap.md"
	@echo "Web UI: make web / make serve (human front-end). CLI remains for agents/CI."
	@echo "Outputs: out/<id>/  Learnings: .cache/  (both gitignored)"

packs:  ## list registered packs
	@$(PACKS) list

add:  ## register DIR=/path/to/pack [ID=name]
	@test -n "$(DIR)" || (echo "usage: make add DIR=/path/to/packwiz-pack [ID=name]"; exit 2)
	@$(PACKS) add --path "$(DIR)" $(if $(ID),--id $(ID),) $(if $(LABEL),--label "$(LABEL)",)

remove:  ## unregister ID=name
	@test -n "$(ID)" || (echo "usage: make remove ID=liminal"; exit 2)
	@$(PACKS) remove --id "$(ID)"

pick:  ## interactively choose current pack
	@$(PACKS) pick

doctor:  ## check Docker and the selected pack are ready
	@$(RUN) doctor $(RUN_FLAGS)

snapshot:  ## headless server snapshot (needs EULA=1)
	@$(RUN) snapshot $(RUN_FLAGS)

dump:  ## snapshot + recipe_data.json (needs EULA=1)
	@$(RUN) dump $(RUN_FLAGS)

check:  ## reachability report (needs a prior dump)
	@$(RUN) check $(RUN_FLAGS)

why:  ## craft chain for ITEM=…
	@$(RUN) why $(RUN_FLAGS)

blocked:  ## missing ingredients for ITEM=…
	@$(RUN) blocked $(RUN_FLAGS)

tags:  ## unresolved ingredient tags
	@$(RUN) tags $(RUN_FLAGS)

analyze:  ## dump + report (needs EULA=1)
	@$(RUN) analyze $(RUN_FLAGS)

report:  ## playability report from profile + dump
	@$(RUN) report $(RUN_FLAGS)
	@echo ""
	@echo "Web: make web && make serve  →  http://127.0.0.1:8765/"

web:  ## static HTML hub → out/web/ (all dumps, or PACK=id)
	@$(PY) scripts/web_report.py $(if $(PACK),--pack "$(PACK)",--all)

serve:  ## generate hub and serve at http://127.0.0.1:8765/
	@$(PY) scripts/web_report.py $(if $(PACK),--pack "$(PACK)",--all)
	@echo ""
	@echo "Serving out/web/ at http://127.0.0.1:8765/"
	@echo "Open http://127.0.0.1:8765/  (pack switcher in the nav)"
	@cd out/web && $(PY) -m http.server 8765 --bind 127.0.0.1

web-compare:  ## compare two packs into the hub
	@test -n "$(A)" -a -n "$(B)" || (echo "usage: make web-compare A=verdant B=liminal"; exit 2)
	@$(PY) scripts/web_report.py --compare "$(A)" "$(B)"

convert:  ## re-parse snapshot → recipe_data (+ loot) without Docker
	@test -n "$(PACK)" || (echo "usage: make convert PACK=verdant"; exit 2)
	@$(PY) -c "import json,sys; from pathlib import Path; p=Path('profiles')/('$(PACK)'+'.json');\
 ns=','.join(json.loads(p.read_text()).get('pack_namespaces') or []) if p.exists() else '';\
 print(ns)" > /tmp/mplab-ns-$(PACK).txt
	@$(PY) scripts/snapshot_to_dump.py \
		--snapshot out/$(PACK)/snapshot.json \
		--out out/$(PACK)/recipe_data.json \
		--mods-dir out/$(PACK)/server/mods \
		--server-dir out/$(PACK)/server \
		--pack-namespaces "$$(cat /tmp/mplab-ns-$(PACK).txt)"

compare:  ## why pack A unlocks what B does not (A=verdant B=liminal [ITEM=…])
	@test -n "$(A)" -a -n "$(B)" || (echo "usage: make compare A=verdant B=liminal [ITEM=mod:item]"; exit 2)
	@$(PY) scripts/compare.py \
		--a out/$(A)/recipe_data.json --name-a $(A) \
		--b out/$(B)/recipe_data.json --name-b $(B) \
		$(if $(ITEM),--item $(ITEM),) \
		$(if $(TARGETS),--targets $(TARGETS),)

insights:  ## jar+config economics insights (PACK=id; needs prior dump)
	@test -n "$(PACK)" || (echo "usage: make insights PACK=verdant"; exit 2)
	@$(PY) scripts/insights_economics.py --pack-out out/$(PACK)

progression:  ## quest-chapter draft from reach depths (PACK=verdant)
	@test -n "$(PACK)" || (echo "usage: make progression PACK=verdant"; exit 2)
	@$(PY) scripts/progression.py --pack $(PACK)

knowledge:  ## show local .cache learnings (client-only mods, pack meta)
	@$(PY) scripts/knowledge.py show $(if $(PACK),--pack-id $(PACK),)
