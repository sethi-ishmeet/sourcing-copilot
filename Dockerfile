# Build the UI, then package the API with the built UI inside. One container, one port.
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY sample_data ./sample_data
COPY --from=ui /ui/dist ./frontend/dist
RUN uv sync --frozen --no-dev
ENV DB_PATH=/data/sourcing_copilot.sqlite
VOLUME /data
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "sourcing_copilot.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
