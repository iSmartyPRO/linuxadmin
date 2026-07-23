# Linux Admin — common operator commands
# Usage: make <target>
# Requires: Python 3.12+, Node.js 20+, PostgreSQL

ROOT        := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BACKEND     := $(ROOT)/src/backend
FRONTEND    := $(ROOT)/src/frontend
VENV        := $(BACKEND)/.venv
PYTHON      := $(VENV)/bin/python
PIP         := $(VENV)/bin/pip
UVICORN     := $(VENV)/bin/uvicorn
ENV_FILE    := $(ROOT)/.env
PID_FILE    := $(ROOT)/.run/lnxadmin.pid
LOG_DIR     := $(ROOT)/.run/logs

# Defaults (override on CLI: make start LNXADMIN_BIND_HOST=0.0.0.0)
# Application secrets are loaded by pydantic from .env — do not include .env here.
LNXADMIN_ENV        ?= development
LNXADMIN_BIND_HOST  ?= 127.0.0.1
LNXADMIN_BIND_PORT  ?= 8000

.PHONY: help env install install-backend install-frontend build migrate \
	dev dev-backend dev-frontend run start stop status restart check \
	systemd-install systemd-uninstall clean clean-all logs

help: ## Show this help
	@echo "Linux Admin — Make targets"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Typical production flow:"
	@echo "  1. cp .env.example .env   # or: make env"
	@echo "  2. edit .env              # secrets, LNXADMIN_ENV=production"
	@echo "  3. make install build"
	@echo "  4. make migrate"
	@echo "  5. make run               # or: make systemd-install"

env: ## Create .env from .env.example if missing
	@if [ -f "$(ENV_FILE)" ]; then \
	  echo ".env already exists: $(ENV_FILE)"; \
	else \
	  cp "$(ROOT)/.env.example" "$(ENV_FILE)"; \
	  echo "Created $(ENV_FILE) — edit secrets before production use"; \
	fi

install: install-backend install-frontend ## Install Python + Node dependencies

install-backend: ## Create venv and pip install
	@test -f "$(ENV_FILE)" || $(MAKE) env
	python3 -m venv "$(VENV)"
	"$(PIP)" install --upgrade pip
	"$(PIP)" install -r "$(BACKEND)/requirements.txt"
	@echo "Backend venv ready: $(VENV)"

install-frontend: ## npm ci
	cd "$(FRONTEND)" && npm ci
	@echo "Frontend deps ready"

build: ## Build production frontend into src/frontend/dist
	cd "$(FRONTEND)" && npm run build
	@echo "Frontend built → $(FRONTEND)/dist"

migrate: ## Apply Alembic migrations
	cd "$(BACKEND)" && PYTHONPATH=. "$(VENV)/bin/alembic" upgrade head

dev: ## Run API (reload) + Vite together (Ctrl+C stops both)
	@test -x "$(UVICORN)" || $(MAKE) install-backend
	@mkdir -p "$(LOG_DIR)"
	@echo "Starting backend :$(LNXADMIN_BIND_PORT) and Vite :5173 …"
	@cd "$(BACKEND)" && PYTHONPATH=. LNXADMIN_ENV=development \
	  "$(UVICORN)" app.main:app --host 127.0.0.1 --port "$(LNXADMIN_BIND_PORT)" --reload & echo $$! > "$(PID_FILE).api"
	@cd "$(FRONTEND)" && npm run dev -- --host 127.0.0.1 --port 5173 & echo $$! > "$(PID_FILE).vite"
	@echo "UI: http://127.0.0.1:5173  API: http://127.0.0.1:$(LNXADMIN_BIND_PORT)/api/health"
	@trap '$(MAKE) stop' INT TERM; wait

dev-backend: ## Backend only with auto-reload
	@test -x "$(UVICORN)" || $(MAKE) install-backend
	cd "$(BACKEND)" && PYTHONPATH=. LNXADMIN_ENV=development \
	  "$(UVICORN)" app.main:app --host 127.0.0.1 --port "$(LNXADMIN_BIND_PORT)" --reload

dev-frontend: ## Vite only (proxies /api to backend)
	cd "$(FRONTEND)" && npm run dev -- --host 127.0.0.1 --port 5173

run: start ## Alias for start (production-style single process)

start: ## Start production server (serves API + built UI)
	@test -f "$(ENV_FILE)" || (echo "Missing .env — run: make env"; exit 1)
	@test -x "$(UVICORN)" || $(MAKE) install-backend
	@test -f "$(FRONTEND)/dist/index.html" || $(MAKE) build
	@mkdir -p "$(LOG_DIR)" "$(ROOT)/.run"
	@if [ -f "$(PID_FILE)" ] && kill -0 $$(cat "$(PID_FILE)") 2>/dev/null; then \
	  echo "Already running (pid $$(cat $(PID_FILE)))"; exit 0; \
	fi
	@echo "Starting Linux Admin on $(LNXADMIN_BIND_HOST):$(LNXADMIN_BIND_PORT) (env=$(LNXADMIN_ENV))"
	@cd "$(BACKEND)" && PYTHONPATH=. \
	  "$(UVICORN)" app.main:app \
	    --host "$(LNXADMIN_BIND_HOST)" \
	    --port "$(LNXADMIN_BIND_PORT)" \
	    --workers 1 \
	    --proxy-headers \
	    --forwarded-allow-ips=127.0.0.1 \
	  >> "$(LOG_DIR)/app.log" 2>&1 & echo $$! > "$(PID_FILE)"
	@sleep 1
	@$(MAKE) --no-print-directory status

stop: ## Stop background start/dev processes
	@for f in "$(PID_FILE)" "$(PID_FILE).api" "$(PID_FILE).vite"; do \
	  if [ -f "$$f" ]; then \
	    pid=$$(cat "$$f"); \
	    if kill -0 "$$pid" 2>/dev/null; then \
	      kill "$$pid" 2>/dev/null || true; \
	      echo "Stopped $$pid ($$f)"; \
	    fi; \
	    rm -f "$$f"; \
	  fi; \
	done
	@echo "Stopped"

restart: stop start ## Restart production server

status: ## Show process / health
	@if [ -f "$(PID_FILE)" ] && kill -0 $$(cat "$(PID_FILE)") 2>/dev/null; then \
	  echo "Process: running (pid $$(cat $(PID_FILE)))"; \
	else \
	  echo "Process: not running (make start)"; \
	fi
	@curl -fsS "http://127.0.0.1:$(LNXADMIN_BIND_PORT)/api/health" 2>/dev/null \
	  && echo "" || echo "Health: unreachable on 127.0.0.1:$(LNXADMIN_BIND_PORT)"

check: ## Validate .env security + health endpoint
	@test -x "$(PYTHON)" || $(MAKE) install-backend
	@cd "$(BACKEND)" && PYTHONPATH=. "$(PYTHON)" "$(ROOT)/scripts/check_security.py"
	@$(MAKE) --no-print-directory status

logs: ## Tail application log
	@mkdir -p "$(LOG_DIR)"
	@touch "$(LOG_DIR)/app.log"
	tail -n 100 -f "$(LOG_DIR)/app.log"

systemd-install: ## Install systemd unit (requires root; paths baked for this checkout)
	@test -f "$(ENV_FILE)" || (echo "Missing .env"; exit 1)
	@test -f "$(FRONTEND)/dist/index.html" || $(MAKE) build
	sed -e "s|@ROOT@|$(ROOT)|g" \
	    -e "s|@BIND_HOST@|$(LNXADMIN_BIND_HOST)|g" \
	    -e "s|@BIND_PORT@|$(LNXADMIN_BIND_PORT)|g" \
	    "$(ROOT)/deploy/lnxadmin.service" > /tmp/lnxadmin.service
	sudo cp /tmp/lnxadmin.service /etc/systemd/system/lnxadmin.service
	sudo systemctl daemon-reload
	sudo systemctl enable --now lnxadmin.service
	@echo "Installed: systemctl status lnxadmin"

systemd-uninstall: ## Disable and remove systemd unit
	sudo systemctl disable --now lnxadmin.service 2>/dev/null || true
	sudo rm -f /etc/systemd/system/lnxadmin.service
	sudo systemctl daemon-reload
	@echo "Removed lnxadmin.service"

clean: ## Remove build artifacts and pid files
	rm -rf "$(FRONTEND)/dist" "$(ROOT)/.run"
	find "$(BACKEND)" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

clean-all: clean ## Also remove venv and node_modules
	rm -rf "$(VENV)" "$(FRONTEND)/node_modules"
