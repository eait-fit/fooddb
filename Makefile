# Operator interface for a self-hosted fooddb. Run `make` for the list of targets.
# Developers use ./dev instead. Runbook: docs/deploy.md.
COMPOSE_FILES ?= -f deploy/docker-compose.yml
COMPOSE = docker compose --project-directory deploy $(COMPOSE_FILES)
limit ?= 1
TIMEOUT = 900

HEX = hex() { if command -v openssl >/dev/null 2>&1; then openssl rand -hex "$$1"; else od -An -N"$$1" -tx1 /dev/urandom | tr -d ' \n'; fi; }
FILL = fill() { if grep -q "^$$1=$$" deploy/.env; then sed -i.bak "s/^$$1=$$/$$1=$$(hex "$$2")/" deploy/.env && rm -f deploy/.env.bak; fi; }
PORT = p=$${FOODDB__DEPLOY__PORT:-$$(sed -n 's/^FOODDB__DEPLOY__PORT=//p' deploy/.env 2>/dev/null | tail -1)}; PORT=$${p:-8000}

.DEFAULT_GOAL := help
.PHONY: help install search cli status logs stop update uninstall

help: ## Show this list
	@echo "fooddb: make <target>"
	@awk -F':.*## ' '/^[a-z-]+:.*## /{printf "  %-10s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Build and start the stack, then wait until the API answers
	@die() { echo "make install: $$*" >&2; exit 1; }; \
	command -v docker >/dev/null 2>&1 || die "docker is missing. Install Docker: https://docs.docker.com/engine/install/"; \
	docker compose version >/dev/null 2>&1 || die "docker compose v2 is missing. Install the Compose plugin: https://docs.docker.com/compose/install/"; \
	docker info >/dev/null 2>&1 || die "the Docker daemon is not reachable. Start Docker, or add your user to the docker group."; \
	command -v curl >/dev/null 2>&1 || die "curl is missing. Install curl with your package manager."; \
	[ -f deploy/.env ] || cp deploy/.env.example deploy/.env; \
	$(HEX); $(FILL); \
	fill FOODDB__BACKEND__POSTGRES_PASSWORD 24; \
	fill FOODDB__BACKEND__SECRET_KEY 32; \
	echo "Building and starting the stack. The first build takes a few minutes."; \
	$(COMPOSE) up -d --build || exit 1; \
	$(PORT); url=http://127.0.0.1:$$PORT; waited=0; \
	printf 'Waiting for %s/healthz. The worker downloads the first data, which takes a few minutes.' "$$url"; \
	until [ "$$(curl -s -o /dev/null -w '%{http_code}' "$$url/healthz" || true)" = 200 ]; do \
		if [ "$$waited" -ge $(TIMEOUT) ]; then printf '\n'; die "no answer after $$(($(TIMEOUT) / 60)) minutes. Run: make logs"; fi; \
		printf '.'; sleep 5; waited=$$((waited + 5)); \
	done; \
	printf '\nfooddb is up after %s s.\n\nTry it:\n\n  curl "%s/v1/foods?q=apple+pie&limit=1"\n  make search q="apple pie"\n' "$$waited" "$$url"

search: ## Look up a food: make search q="apple pie" [limit=1]
	@[ -n "$$q" ] || { echo 'usage: make search q="apple pie" [limit=1]' >&2; exit 2; }
	@$(COMPOSE) exec -T api fooddb search "$$q" --limit $(limit)

cli: ## Run any fooddb command: make cli args='status'
	@$(COMPOSE) exec -T api fooddb $(args)

status: ## Show row counts, recent fetch runs and the job queue
	@$(COMPOSE) exec -T api fooddb status

logs: ## Follow the API and worker logs
	@$(COMPOSE) logs -f api worker

stop: ## Stop the stack and keep the data
	@$(COMPOSE) down

update: ## Pull the latest code, rebuild and restart
	git pull --ff-only
	$(COMPOSE) up -d --build

uninstall: ## Stop the stack and DELETE the data (asks first; yes=1 skips)
	@if [ "$(yes)" != 1 ]; then printf 'This deletes the fooddb database and all its data. Type yes to continue: '; read a; [ "$$a" = yes ] || { echo Aborted.; exit 1; }; fi
	@$(COMPOSE) down -v
