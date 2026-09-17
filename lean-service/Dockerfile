FROM python:3.13-slim

# git: lake needs it to fetch Mathlib. curl: uv + elan installers.
# libgmp10: runtime dep of the Lean toolchain.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates git libgmp10 \
 && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Lean 4 + Mathlib. Heavy (several GB, long first build) — that's the whole
# reason this lives on its own host instead of inside the main app's image.
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
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen
COPY main.py ./

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
