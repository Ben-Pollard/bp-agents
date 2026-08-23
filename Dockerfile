FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

COPY agents/ .
COPY scripts/ scripts/

RUN pip install uv && uv sync --no-dev --no-cache

RUN ln -s /usr/local/bin/python3 /usr/bin/python3

CMD [".venv/bin/python", "-u", "-m", "bp_agents.main"]