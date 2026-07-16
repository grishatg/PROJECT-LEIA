# LEIA web control center — portable image (Render / Railway / Fly / any VPS).
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

# Install dependencies first (cached layer) using only the manifests.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy the rest of the project and install it.
COPY . .
RUN uv sync --frozen --no-dev

ENV PORT=8000
EXPOSE 8000

# Migrate (best-effort, with retry) then serve — in one process so a briefly
# paused/waking database can't stop the web server from starting. $PORT is
# provided by the host (Render sets it).
CMD ["sh", "-c", "uv run leia dashboard --migrate --host 0.0.0.0 --port ${PORT:-8000}"]
