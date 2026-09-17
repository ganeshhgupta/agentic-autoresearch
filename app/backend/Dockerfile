FROM python:3.13-slim

# Node is needed for the `claude` CLI; curl for the uv installer.
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs npm curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

# Install uv (matches the host workflow).
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Tectonic: self-contained LaTeX engine for the editor's Compile endpoint and
# for the agent's scripts/latex.py tool. Downloads packages on demand instead
# of shipping a multi-GB texlive image.
RUN curl --proto '=https' -fsSL https://drop-sh.fullyjustified.net | sh \
 && mv tectonic /usr/local/bin/tectonic

# Lean 4 + Mathlib runs as its own service (see lean-service/) — it needs
# more RAM than this container has any business carrying just to typecheck
# a claim occasionally. scripts/lean.py calls it over HTTP; see LEAN_SERVICE_URL.

WORKDIR /app

# Cache deps separately from source.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .

EXPOSE 4003
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "4003"]
