# Build context is the REPO ROOT: docker build -f webapp/Dockerfile .
FROM node:22-alpine AS frontend
WORKDIR /build
COPY webapp/frontend/package.json webapp/frontend/package-lock.json ./
RUN npm ci
COPY webapp/frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
# Library first (its own layer), then the backend package.
COPY pyproject.toml poetry.lock README.md LICENSE ./library/
COPY src ./library/src
RUN pip install --no-cache-dir ./library
COPY webapp/backend ./backend
RUN pip install --no-cache-dir ./backend
COPY --from=frontend /build/dist /app/static
ENV STUDIO_STATIC_DIR=/app/static
EXPOSE 8000
CMD ["uvicorn", "--factory", "experiment_studio.app:create_app", "--host", "0.0.0.0", "--port", "8000"]
