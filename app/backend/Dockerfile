FROM python:3.13-slim

# Node is needed for the `claude` CLI; curl for the uv/elan installers; git for
# lake to fetch Mathlib; libgmp10 is a runtime dep of the Lean toolchain.
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs npm curl ca-certificates git libgmp10 \
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

# Lean 4 + Mathlib: elan (toolchain manager) + a prebuilt `lake` project used
# by scripts/lean.py to formally check hypotheses against Mathlib. This is
# heavy — several GB and a long first build downloading Mathlib's precompiled
# cache — because Mathlib was requested in full rather than a bare Lean setup.
# Lives at /opt/lean, NOT /workspace, since docker-compose bind-mounts the
# host repo over /workspace at runtime and would shadow anything built there.
ENV ELAN_HOME="/root/.elan"
ENV PATH="${ELAN_HOME}/bin:${PATH}"
ENV LEAN_PROJECT_DIR="/opt/lean/research"
RUN curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf \
      | sh -s -- -y --default-toolchain none \
 && LEAN_VERSION=$(curl -fsSL https://raw.githubusercontent.com/leanprover-community/mathlib4/master/lean-toolchain | sed 's#leanprover/lean4:##') \
 && mkdir -p /opt/lean && cd /opt/lean \
 && lake "+${LEAN_VERSION}" new research math \
 && cd research && lake exe cache get

WORKDIR /app

# Cache deps separately from source.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .

EXPOSE 4003
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "4003"]
