SERVICE ?= backend

ifeq ($(SERVICE),$(filter $(SERVICE),postgres neo4j))
  COMPOSE_CMD := docker compose -f db/compose.yaml
else
  COMPOSE_CMD := docker compose
endif

.PHONY: shell
shell:
	$(COMPOSE_CMD) exec -it $(SERVICE) sh

