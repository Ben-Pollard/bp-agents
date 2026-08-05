import logging
from urllib.parse import urlparse

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
    """Controls outbound network access from sandbox containers.

    EgressPolicy blocks network-level egress to destinations not in the
    allowlist. Local git commands (git status, git add, etc.) do NOT
    require network and are NOT blocked by this policy. Git command
    execution inside sandboxes is prevented at the container image level
    — the sandbox images used in production must not include git.
    """

    def __init__(self, allowlist: list[str] | None = None) -> None:
        self.allowlist = allowlist or list(DEFAULT_ALLOWLIST)
        self.log_allowlist()

    def log_allowlist(self) -> None:
        logger.info("egress allowlist: %s", self.allowlist)

    def is_allowed(self, destination: str) -> bool:
        hostname = urlparse(destination).hostname
        if hostname is None:
            return False
        return any(
            hostname == allowed or hostname.endswith(f".{allowed}")
            for allowed in self.allowlist
        )

    def check(self, destination: str, ticket_id: str = "") -> None:
        if not self.is_allowed(destination):
            if ticket_id:
                logger.warning(
                    "blocked egress: %s from ticket %s", destination, ticket_id
                )
            else:
                logger.warning("blocked egress: %s", destination)
            raise EgressBlockedError(destination)


class EgressBlockedError(Exception):
    def __init__(self, destination: str) -> None:
        self.destination = destination
        super().__init__(f"blocked egress: {destination}")
