"""E2E canary tests for OTEL observability pipeline.

RED when infrastructure needs rebuilding. PASS when instructions in README
have been followed correctly. These are the first tests to check when the
pipeline appears broken.
"""

from __future__ import annotations

import json
import subprocess
import time

import pytest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import (
    ResourceSpans,
    ScopeSpans,
    Span,
)

pytestmark = [pytest.mark.e2e]

_RECEIVER_PORT = 4318
_ORCHESTRATOR_SERVICE = "bp-agents-orchestrator-1"
_SANDBOX_IMAGE = "symphony-agent:latest"
_OTEL_NPM_PACKAGES = [
    "@opentelemetry/sdk-node",
    "@opentelemetry/exporter-trace-otlp-proto",
    "@opentelemetry/resources",
    "@opentelemetry/semantic-conventions",
]


def _docker_available() -> bool:
    try:
        subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return True
    except Exception:
        return False


def _compose_service_running(name: str) -> bool:
    try:
        r = subprocess.run(
            [
                "docker",
                "inspect",
                name,
                "--format",
                "{{.State.Status}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.returncode == 0 and r.stdout.strip() == "running"
    except Exception:
        return False


def _docker_exec(container: str, cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "exec", container] + cmd,
        capture_output=True,
        timeout=30,
    )


def _image_exists(name: str) -> bool:
    try:
        r = subprocess.run(
            ["docker", "image", "inspect", name],
            capture_output=True,
            timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


def _make_otlp_body(spans: list[Span]) -> bytes:
    request = ExportTraceServiceRequest(
        resource_spans=[ResourceSpans(scope_spans=[ScopeSpans(spans=spans)])]
    )
    return request.SerializeToString()


def _make_span(name: str, span_type: str) -> Span:
    return Span(
        name=name,
        span_id=b"\x01" * 8,
        attributes=[
            KeyValue(key="type", value=AnyValue(string_value=span_type)),
        ],
    )


# ── Canary 1: Orchestrator container running ──────────────────────────


@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
def test_orchestrator_container_is_running() -> None:
    """Orchestrator container must be up before OTEL pipeline can work."""
    assert _compose_service_running(_ORCHESTRATOR_SERVICE), (
        f"{_ORCHESTRATOR_SERVICE} not running. "
        f"Run `docker compose up -d orchestrator` first."
    )


# ── Canary 2: Sandbox image exists with OTEL npm packages ─────────────


@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
def test_sandbox_image_exists() -> None:
    """Sandbox image must be built before agent sessions can emit spans."""
    assert _image_exists(_SANDBOX_IMAGE), (
        f"Sandbox image '{_SANDBOX_IMAGE}' not found. "
        f"Run `docker build -t {_SANDBOX_IMAGE} -f Dockerfile.sandbox .`"
    )


@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
@pytest.mark.skipif(
    not _image_exists(_SANDBOX_IMAGE), reason=f"{_SANDBOX_IMAGE} not built"
)
def test_sandbox_has_otel_npm_packages() -> None:
    """Sandbox image must have @opentelemetry/* packages for span export.

    RED when the sandbox image was built before OTEL packages were added
    to Dockerfile.sandbox:11. Rebuild with `docker build -t symphony-agent:latest
    -f Dockerfile.sandbox .`.
    """
    missing: list[str] = []
    for pkg in _OTEL_NPM_PACKAGES:
        r = _docker_exec(
            _ORCHESTRATOR_SERVICE
            if _compose_service_running(_ORCHESTRATOR_SERVICE)
            else "unreachable",
            ["node", "-e", f"require('{pkg}'); console.log('ok')"],
        )
        # Can't test npm in sandbox directly; check orchestrator's node_modules
        # as a proxy or test via docker run --rm
    # Actually test inside sandbox via docker run
    for pkg in _OTEL_NPM_PACKAGES:
        r = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                _SANDBOX_IMAGE,
                "node",
                "-e",
                f"require('{pkg}'); console.log('ok')",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode != 0:
            missing.append(pkg)

    assert not missing, (
        f"OTEL npm packages missing from {_SANDBOX_IMAGE}: {missing}. "
        f"Rebuild image: `docker build -t {_SANDBOX_IMAGE} -f Dockerfile.sandbox .`"
    )


# ── Canary 3: OtelReceiver in orchestrator accepts OTLP spans ─────────


@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
@pytest.mark.skipif(
    not _compose_service_running(_ORCHESTRATOR_SERVICE),
    reason=f"{_ORCHESTRATOR_SERVICE} not running",
)
def test_orchestrator_otel_receiver_accepts_spans() -> None:
    """OtelReceiver in the orchestrator container must process OTLP spans.

    Sends a real OTLP protobuf payload to http://localhost:{_RECEIVER_PORT}/v1/traces
    inside the orchestrator container. Checks HTTP 200 response.

    RED when the orchestrator image was built before OtelReceiver was wired
    into main.py. Rebuild with `docker compose build orchestrator && docker compose up -d`.
    """
    body = _make_otlp_body([_make_span("test_span", "session_status")])
    r = _docker_exec(
        _ORCHESTRATOR_SERVICE,
        [
            "python3",
            "-c",
            f"""
import httpx
body = {json.dumps(body.hex())}
resp = httpx.post(
    'http://localhost:{_RECEIVER_PORT}/v1/traces',
    content=bytes.fromhex(body),
    headers={{"Content-Type": "application/x-protobuf"}},
    timeout=5,
)
print(resp.status_code, resp.text)
""",
        ],
    )
    if r.returncode != 0:
        pytest.fail(f"docker exec failed: {r.stderr.decode()}")
    output = r.stdout.decode().strip()
    assert "200" in output, (
        f"OtelReceiver returned non-200: {output}. "
        f"OtelReceiver may not be running in orchestrator. "
        f"Rebuild orchestrator image with `docker compose build orchestrator`."
    )


# ── Canary 4: Span data appears in orchestrator docker logs ───────────


@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
@pytest.mark.skipif(
    not _compose_service_running(_ORCHESTRATOR_SERVICE),
    reason=f"{_ORCHESTRATOR_SERVICE} not running",
)
def test_otel_span_appears_in_orchestrator_logs() -> None:
    """OTEL span JSON must appear in orchestrator docker logs after submission.

    Sends an OTLP span with a unique marker, reads docker logs, and asserts the
    marker appears. Proves the full OtelReceiver→print→stdout→docker_logs path.

    RED when:
    - Orchestrator image has old code (no OtelReceiver)
    - OtelReceiver uses logging instead of print() (suppressed by uvicorn)
    - Container not rebuilt after code changes
    """
    marker = f"canary-{time.monotonic_ns()}"
    body = _make_otlp_body([_make_span(marker, "session_status")])

    # Capture logs BEFORE sending
    before = subprocess.run(
        ["docker", "logs", _ORCHESTRATOR_SERVICE],
        capture_output=True,
        text=True,
        timeout=10,
    )

    # Send span
    send = _docker_exec(
        _ORCHESTRATOR_SERVICE,
        [
            "python3",
            "-c",
            f"""
import httpx
import json
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Span, ResourceSpans, ScopeSpans

span = Span(name="{marker}", span_id=b"\\x01" * 8, attributes=[KeyValue(key="type", value=AnyValue(string_value="session_status"))])
req = ExportTraceServiceRequest(resource_spans=[ResourceSpans(scope_spans=[ScopeSpans(spans=[span])])])
body = req.SerializeToString()
resp = httpx.post('http://localhost:{_RECEIVER_PORT}/v1/traces', content=body, headers={{"Content-Type": "application/x-protobuf"}}, timeout=5)
print(resp.status_code, resp.text)
""",
        ],
    )
    assert send.returncode == 0, f"send failed: {send.stderr.decode()}"
    time.sleep(1)

    # Capture logs AFTER
    after = subprocess.run(
        ["docker", "logs", _ORCHESTRATOR_SERVICE],
        capture_output=True,
        text=True,
        timeout=10,
    )

    new_output = after.stdout[len(before.stdout) :]
    assert marker in new_output, (
        f"Marker '{marker}' not found in orchestrator logs after submitting span.\n"
        f"docker exec response: {send.stdout.decode()}\n"
        f"New log lines:\n{new_output[:2000]}\n\n"
        f"Likely causes (in order):\n"
        f"1. Orchestrator image not rebuilt after code changes — "
        f"run `docker compose build orchestrator && docker compose up -d orchestrator`\n"
        f"2. OtelReceiver not wired into this image — check main.py has "
        f"OtelReceiver(log_level=...) and otel_receiver.start(port=...)\n"
        f"3. Span output uses logging (old code) instead of print() — "
        f"check otel_receiver.py uses print(json.dumps(record), file=sys.stdout, flush=True)\n"
        f"4. OtelReceiver not started — check main.py TaskGroup includes "
        f"await otel_receiver.start(port=BP_OTEL_PORT)"
    )


# ── Canary 5: Info level suppresses debug spans ───────────────────────


@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
@pytest.mark.skipif(
    not _compose_service_running(_ORCHESTRATOR_SERVICE),
    reason=f"{_ORCHESTRATOR_SERVICE} not running",
)
def test_info_level_suppresses_llm_spans_in_logs() -> None:
    """At BP_LOG_LEVEL=info, llm_message and tool_call spans must NOT appear.

    Verifies both that session_status DOES appear and llm_message does NOT.
    """
    status_marker = f"status-{time.monotonic_ns()}"
    llm_marker = f"llm-{time.monotonic_ns()}"

    body = _make_otlp_body(
        [
            _make_span(status_marker, "session_status"),
            _make_span(llm_marker, "llm_message"),
        ]
    )

    before = subprocess.run(
        ["docker", "logs", _ORCHESTRATOR_SERVICE],
        capture_output=True,
        text=True,
        timeout=10,
    )

    send = _docker_exec(
        _ORCHESTRATOR_SERVICE,
        [
            "python3",
            "-c",
            f"""
import httpx
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Span, ResourceSpans, ScopeSpans

s1 = Span(name="{status_marker}", span_id=b"\\x01" * 8, attributes=[KeyValue(key="type", value=AnyValue(string_value="session_status"))])
s2 = Span(name="{llm_marker}", span_id=b"\\x02" * 8, attributes=[KeyValue(key="type", value=AnyValue(string_value="llm_message"))])
req = ExportTraceServiceRequest(resource_spans=[ResourceSpans(scope_spans=[ScopeSpans(spans=[s1, s2])])])
resp = httpx.post('http://localhost:{_RECEIVER_PORT}/v1/traces', content=req.SerializeToString(), headers={{"Content-Type": "application/x-protobuf"}}, timeout=5)
print(resp.status_code)
""",
        ],
    )
    assert send.returncode == 0
    time.sleep(1)

    after = subprocess.run(
        ["docker", "logs", _ORCHESTRATOR_SERVICE],
        capture_output=True,
        text=True,
        timeout=10,
    )
    new_output = after.stdout[len(before.stdout) :]

    assert status_marker in new_output, (
        f"session_status span not found in logs at info level. "
        f"OtelReceiver filtering may be wrong.\n"
        f"New log lines:\n{new_output[:1000]}"
    )
    assert llm_marker not in new_output, (
        "llm_message span appeared in logs at info level. "
        "OtelReceiver filtering is broken — _process_span should return early "
        "for non-session types when self._log_level == 'info'."
    )
