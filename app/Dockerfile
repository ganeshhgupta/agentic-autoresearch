# Single-image build for Dokploy.
#
# IMPORTANT: build context must be the REPO ROOT, not app/.
# In Dokploy:  Build Context = .   Dockerfile = app/Dockerfile
#
# Stage 1 — build the Vite SPA. `VITE_BASE` is baked into asset URLs.
# Stage 2 — Python + Node + `claude` CLI + uv. Bakes:
#             /app    backend source + built SPA under /app/static
#             /shared system_prompt.md, docs/, scripts/, root pyproject
#                     (the workspace claude runs from)

FROM node:22-slim AS frontend-build
WORKDIR /build
COPY app/frontend/package.json app/frontend/package-lock.json* ./
RUN npm ci
COPY app/frontend/ ./
ARG VITE_BASE=/
ENV VITE_BASE=${VITE_BASE}
RUN npm run build


FROM python:3.13-slim AS prod

RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs npm curl ca-certificates git libgmp10 \
 && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Tectonic: self-contained LaTeX engine for the editor's Compile endpoint and
# for the agent's own `tectonic latex/<name>.tex` calls.
RUN curl --proto '=https' -fsSL https://drop-sh.fullyjustified.net | sh \
 && mv tectonic /usr/local/bin/tectonic

# Lean 4 + Mathlib for scripts/lean.py — see app/backend/Dockerfile for why
# this lives outside /shared (nothing here is bind-mounted in prod, but we
# keep the same layout so the two Dockerfiles stay interchangeable).
ENV ELAN_HOME="/root/.elan"
ENV PATH="${ELAN_HOME}/bin:${PATH}"
ENV LEAN_PROJECT_DIR="/opt/lean/research"
RUN curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf \
      | sh -s -- -y --default-toolchain none \
 && LEAN_VERSION=$(curl -fsSL https://raw.githubusercontent.com/leanprover-community/mathlib4/master/lean-toolchain | sed 's#leanprover/lean4:##') \
 && mkdir -p /opt/lean && cd /opt/lean \
 && lake "+${LEAN_VERSION}" new research math \
 && cd research && lake exe cache get

# --- /shared: cwd claude runs from, holds prompt + docs + scripts ---
WORKDIR /shared
COPY system_prompt.md ./
COPY docs/ ./docs/
COPY scripts/ ./scripts/
COPY pyproject.toml uv.lock .python-version ./
# Pre-install the connector deps (httpx, ddgs, python-dotenv) into
# /shared/.venv so `uv run scripts/<name>.py` starts instantly.
RUN uv sync --frozen

# --- /app: the FastAPI backend ---
WORKDIR /app

COPY app/backend/pyproject.toml app/backend/uv.lock ./
RUN uv sync --frozen --no-install-project

COPY app/backend/ ./

COPY --from=frontend-build /build/dist ./static

ENV APP_PREFIX=
ENV SHARED_ROOT=/shared

EXPOSE 4003
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "4003"]
