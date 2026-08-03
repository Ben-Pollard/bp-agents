FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --no-dev --no-cache

COPY . .

CMD ["python", "-m", "bp_agents.orchestrator.main"]