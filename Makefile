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

.PHONY: help packs add remove pick doctor snapshot dump check why blocked tags analyze knowledge report convert

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
	@echo "  make convert PACK=id               re-parse snapshot + extract loot (no Docker)"
	@echo "  make analyze EULA=1                dump + report"
	@echo "  make check                         reachability only"
	@echo "  make why ITEM=mod:item             cheapest craft chain"
	@echo "  make blocked ITEM=mod:item         per-recipe missing ingredients"
	@echo "  make tags                          unresolved ingredient tags"
	@echo ""
	@echo "Profiles: profiles/<id>.json (world: ores/nether/end/…). See docs/profiles.md"
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

convert:  ## re-parse snapshot → recipe_data (+ loot) without Docker
	@test -n "$(PACK)" || (echo "usage: make convert PACK=verdant"; exit 2)
	@$(PY) scripts/snapshot_to_dump.py \
		--snapshot out/$(PACK)/snapshot.json \
		--out out/$(PACK)/recipe_data.json \
		--mods-dir out/$(PACK)/server/mods \
		--server-dir out/$(PACK)/server

knowledge:  ## show local .cache learnings (client-only mods, pack meta)
	@$(PY) scripts/knowledge.py show $(if $(PACK),--pack-id $(PACK),)
