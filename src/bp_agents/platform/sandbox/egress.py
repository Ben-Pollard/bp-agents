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
