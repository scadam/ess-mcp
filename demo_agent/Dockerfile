FROM mcr.microsoft.com/devcontainers/python:3.12-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8091

WORKDIR /app

COPY demo_agent/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY demo_agent ./demo_agent

EXPOSE 8091
CMD ["python", "-m", "demo_agent.web"]