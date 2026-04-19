# syntax=docker/dockerfile:1.7

FROM mcr.microsoft.com/devcontainers/python:3.11 AS builder

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install --no-cache-dir .

FROM mcr.microsoft.com/devcontainers/python:3.11 AS runtime

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Copy installed dependencies and source code
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src ./src
COPY env ./src/env

ENTRYPOINT ["python", "-m", "mcp_servers.cli", "all", "--transport", "both", "--host", "0.0.0.0", "--port", "8080"]
