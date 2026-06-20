#!/bin/sh
SERVICE=${1:-backend}

COMPOSE_CMD="docker compose"
if [ "$SERVICE" = "postgres" ] || [ "$SERVICE" = "neo4j" ]; then
    COMPOSE_CMD="docker compose -f db/compose.yaml"
fi

$COMPOSE_CMD exec -it "$SERVICE" sh

