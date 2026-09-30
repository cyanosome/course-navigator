SERVICE ?= backend

ifeq ($(SERVICE),$(filter $(SERVICE),postgres neo4j))
  COMPOSE_CMD := docker compose -f db/compose.yaml
else
  COMPOSE_CMD := docker compose
endif

.PHONY: shell adk-web
shell:
	$(COMPOSE_CMD) exec -it $(SERVICE) sh

adk-web:
	docker compose run --rm -p 8085:8085 backend uv run adk web src/agent --host 0.0.0.0 --port 8085 --reload_agents

