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

.PHONY: help packs add remove pick doctor snapshot dump check why blocked tags analyze

help:  ## show targets
	@echo "modpack-lab — analyze packwiz NeoForge packs (recipes the server really loads)"
	@echo ""
	@echo "Setup"
	@echo "  make packs                         list registered packs"
	@echo "  make add DIR=/path/to/pack         register a pack (saved in packs.local.toml)"
	@echo "  make remove ID=liminal             unregister a local pack"
	@echo "  make pick                          choose current pack (1/2/3…)"
	@echo ""
	@echo "Analyze  (add PACK=id|N|/path  or omit to pick)"
	@echo "  make doctor                        check Docker / pack / RAM / port"
	@echo "  make snapshot EULA=1               boot headless server → out/<id>/snapshot.json"
	@echo "  make dump EULA=1                   snapshot + write out/<id>/recipe_data.json"
	@echo "  make check                         reachability from start/targets files"
	@echo "  make analyze EULA=1                dump + check (full pass)"
	@echo "  make why ITEM=mod:item             cheapest craft chain"
	@echo "  make blocked ITEM=mod:item         per-recipe missing ingredients"
	@echo "  make tags                          ingredient tags with no members"
	@echo ""
	@echo "Examples"
	@echo "  make add DIR=~/Projects/…/minecraft-modpack-cp-liminal"
	@echo "  make doctor PACK=liminal"
	@echo "  make dump PACK=1 EULA=1"
	@echo "  make check PACK=liminal START=examples/reach/verdant.json"
	@echo "  make why PACK=liminal ITEM=mekanism:ingot_osmium"
	@echo ""
	@echo "Outputs land in out/<pack-id>/ (gitignored). Pack repos are never modified."

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

analyze:  ## dump + check (needs EULA=1)
	@$(RUN) analyze $(RUN_FLAGS)
