import logging

logger = logging.getLogger(__name__)

DEFAULT_ALLOWLIST: list[str] = [
    # LLM API endpoints
    "api.openai.com",
    "api.anthropic.com",
    "api.openrouter.ai",
    # Package registries
    "pypi.org",
    "files.pythonhosted.org",
    "pypi.python.org",
    "registry.npmjs.org",
    # MCP endpoints
    "context7.com",
    "api.context7.com",
]


class EgressPolicy:
    def __init__(self, allowlist: list[str] | None = None) -> None:
        self.allowlist = allowlist or list(DEFAULT_ALLOWLIST)
        logger.info("egress allowlist: %s", self.allowlist)

    def is_allowed(self, destination: str) -> bool:
        return any(allowed in destination for allowed in self.allowlist)

    def check(self, destination: str) -> None:
        if not self.is_allowed(destination):
            logger.warning("blocked egress: %s", destination)
            raise EgressBlockedError(destination)


class EgressBlockedError(Exception):
    def __init__(self, destination: str) -> None:
        self.destination = destination
        super().__init__(f"blocked egress: {destination}")
