@echo off
set SERVICE=%1
if "%SERVICE%"=="" set SERVICE=backend

set COMPOSE_CMD=docker compose
if "%SERVICE%"=="postgres" set COMPOSE_CMD=docker compose -f db/compose.yaml
if "%SERVICE%"=="neo4j" set COMPOSE_CMD=docker compose -f db/compose.yaml

%COMPOSE_CMD% exec -it %SERVICE% sh

