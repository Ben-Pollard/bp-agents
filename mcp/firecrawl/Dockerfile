FROM python:3.13-slim
WORKDIR /app
RUN pip install uv --quiet
COPY . .
RUN uv sync --no-dev --no-cache
CMD ["uv", "run", "--no-sync", "python", "-m", "firecrawl_mcp"]