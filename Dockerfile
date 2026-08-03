FROM python:3.13-slim

WORKDIR /app

COPY . .

RUN pip install uv && uv sync --no-dev --no-cache

RUN ln -s /usr/local/bin/python3 /usr/bin/python3

CMD [".venv/bin/python", "-m", "bp_agents.orchestrator.main"]