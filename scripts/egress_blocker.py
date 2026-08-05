import logging
import os

from mitmproxy import http

DEFAULT_ALLOWLIST = [
    "api.openai.com",
    "api.anthropic.com",
    "api.openrouter.ai",
    "pypi.org",
    "files.pythonhosted.org",
    "pypi.python.org",
    "registry.npmjs.org",
    "context7.com",
    "api.context7.com",
]

logger = logging.getLogger(__name__)

_env_allowlist = os.environ.get("MITMPROXY_ALLOWLIST")
if _env_allowlist:
    ALLOWLIST = [h.strip() for h in _env_allowlist.split(",") if h.strip()]
else:
    ALLOWLIST = list(DEFAULT_ALLOWLIST)

logger.info("egress allowlist: %s", ALLOWLIST)


def _is_allowed(host: str) -> bool:
    host = (host or "").lower()
    return any(host == a or host.endswith("." + a) for a in ALLOWLIST)


def http_connect(flow: http.HTTPFlow) -> None:
    host = flow.request.host
    if not _is_allowed(host):
        logger.warning("blocked egress: %s from ticket <unknown>", host)
        flow.response = http.Response.make(
            403, b"blocked by egress policy", {"Content-Type": "text/plain"}
        )


def request(flow: http.HTTPFlow) -> None:
    host = flow.request.pretty_host
    if not _is_allowed(host):
        logger.warning(
            "blocked egress: %s from ticket <unknown>", flow.request.pretty_url
        )
        flow.response = http.Response.make(
            403, b"blocked by egress policy", {"Content-Type": "text/plain"}
        )
