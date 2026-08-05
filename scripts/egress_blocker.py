import logging

from mitmproxy import http

ALLOWLIST = [
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


def _is_allowed(host: str) -> bool:
    host = (host or "").lower()
    return any(host == a or host.endswith("." + a) for a in ALLOWLIST)


def http_connect(flow: http.HTTPFlow) -> None:
    host = flow.request.host
    if not _is_allowed(host):
        logger.warning("blocked egress: %s", host)
        flow.response = http.Response.make(
            403, b"blocked by egress policy", {"Content-Type": "text/plain"}
        )


def request(flow: http.HTTPFlow) -> None:
    host = flow.request.pretty_host
    if not _is_allowed(host):
        logger.warning("blocked egress: %s", flow.request.pretty_url)
        flow.response = http.Response.make(
            403, b"blocked by egress policy", {"Content-Type": "text/plain"}
        )
