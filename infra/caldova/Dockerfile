# Build only from an isolated context containing pyproject.toml, README.md, src/,
# this Dockerfile, and the accompanying .dockerignore. Never stage the repo or env/.
FROM mcr.microsoft.com/devcontainers/python:3.12-bookworm AS builder

USER root
WORKDIR /build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml README.md constraints.txt ./
# Preserve the selected local environment's key versions instead of upgrading FastMCP's major release.
RUN python -c "import subprocess, sys, tomllib; deps = tomllib.loads(open('pyproject.toml', encoding='utf-8').read())['project']['dependencies']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--prefix=/install', '--constraint=constraints.txt', *deps])"
COPY src/ ./src/
RUN python -m pip install --no-deps --prefix=/install .

FROM mcr.microsoft.com/devcontainers/python:3.12-bookworm AS runtime

USER root
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

COPY --from=builder /install/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=builder /install/bin/ /usr/local/bin/
COPY --from=builder --chown=vscode:vscode /build/src/ ./src/

# The selected MCR devcontainers base provides the non-root vscode account.
USER vscode
EXPOSE 8080
ENTRYPOINT ["python", "-m", "mcp_servers.cli"]
CMD ["all", "--transport", "both", "--host", "0.0.0.0", "--port", "8080"]