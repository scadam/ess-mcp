FROM mcr.microsoft.com/devcontainers/python:3.12-bookworm
ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN pip install httpx==0.28.1 azure-identity==1.25.3
COPY provision_evidence.py /app/provision_evidence.py
USER vscode
CMD ["python", "/app/provision_evidence.py"]
