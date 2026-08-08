"""Integration tests for OtelReceiver — real HTTP I/O, log level filtering."""

import importlib
import json
import logging
import os
import socket

import httpx
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

from bp_agents.platform.observability.otel_receiver import OtelReceiver


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_otlp_body(spans: list[Span]) -> bytes:
    request = ExportTraceServiceRequest(
        resource_spans=[ResourceSpans(scope_spans=[ScopeSpans(spans=spans)])]
    )
    return request.SerializeToString()


def _make_span(
    name: str,
    span_type: str,
    attributes: dict[str, str] | None = None,
    span_id: bytes | None = None,
) -> Span:
    attrs = [
        KeyValue(key="type", value=AnyValue(string_value=span_type)),
    ]
    if attributes:
        for k, v in attributes.items():
            attrs.append(KeyValue(key=k, value=AnyValue(string_value=v)))
    return Span(
        name=name,
        span_id=span_id or b"\x01" * 8,
        attributes=attrs,
    )


@pytest.mark.asyncio
async def test_otel_receiver_starts_on_configurable_port() -> None:
    port = _free_port()
    receiver = OtelReceiver(log_level="info")
    await receiver.start(port=port)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"http://127.0.0.1:{port}/health")
        assert resp.status_code == 200
        assert resp.json() == {"healthy": True}
    finally:
        await receiver.stop()


@pytest.mark.asyncio
async def test_otel_receiver_accepts_v1_traces(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    receiver = OtelReceiver(log_level="debug")
    port = _free_port()
    await receiver.start(port=port)
    try:
        body = _make_otlp_body(
            [_make_span("session_start", "session_status", span_id=b"\xaa" * 8)]
        )
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"http://127.0.0.1:{port}/v1/traces",
                content=body,
                headers={"Content-Type": "application/x-protobuf"},
            )
        assert resp.status_code in (200, 202)
    finally:
        await receiver.stop()


@pytest.mark.asyncio
async def test_debug_level_logs_all_spans(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    receiver = OtelReceiver(log_level="debug")
    port = _free_port()
    await receiver.start(port=port)
    try:
        body = _make_otlp_body(
            [
                _make_span("llm_call", "llm_message", span_id=b"\x01" * 8),
                _make_span("tool_use", "tool_call", span_id=b"\x02" * 8),
                _make_span("session_done", "session_status", span_id=b"\x03" * 8),
                _make_span("session_err", "session_error", span_id=b"\x04" * 8),
            ]
        )
        async with httpx.AsyncClient() as client:
            await client.post(
                f"http://127.0.0.1:{port}/v1/traces",
                content=body,
                headers={"Content-Type": "application/x-protobuf"},
            )
        import time

        time.sleep(0.3)
    finally:
        await receiver.stop()

    otel_logs = [r for r in caplog.records if "OTEL span" in r.getMessage()]
    types_in_logs: set[str] = set()
    for record in otel_logs:
        data = json.loads(record.getMessage().replace("OTEL span: ", "", 1))
        types_in_logs.add(data["type"])

    assert types_in_logs == {
        "llm_message",
        "tool_call",
        "session_status",
        "session_error",
    }


@pytest.mark.asyncio
async def test_info_level_filters_to_session_events(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    receiver = OtelReceiver(log_level="info")
    port = _free_port()
    await receiver.start(port=port)
    try:
        body = _make_otlp_body(
            [
                _make_span("llm_call", "llm_message", span_id=b"\x01" * 8),
                _make_span("tool_use", "tool_call", span_id=b"\x02" * 8),
                _make_span("session_error", "session_error", span_id=b"\x03" * 8),
                _make_span("session_done", "session_status", span_id=b"\x04" * 8),
            ]
        )
        async with httpx.AsyncClient() as client:
            await client.post(
                f"http://127.0.0.1:{port}/v1/traces",
                content=body,
                headers={"Content-Type": "application/x-protobuf"},
            )
        import time

        time.sleep(0.3)
    finally:
        await receiver.stop()

    otel_logs = [r for r in caplog.records if "OTEL span" in r.getMessage()]
    types_in_logs: set[str] = set()
    for record in otel_logs:
        data = json.loads(record.getMessage().replace("OTEL span: ", "", 1))
        types_in_logs.add(data["type"])

    assert types_in_logs == {"session_error", "session_status"}
    assert "llm_message" not in types_in_logs
    assert "tool_call" not in types_in_logs


@pytest.mark.asyncio
async def test_invalid_payload_does_not_crash_receiver(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    receiver = OtelReceiver(log_level="debug")
    port = _free_port()
    await receiver.start(port=port)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"http://127.0.0.1:{port}/v1/traces",
                content=b"this is not valid protobuf",
                headers={"Content-Type": "application/x-protobuf"},
            )
        assert resp.status_code in (200, 202)
        import time

        time.sleep(0.3)
    finally:
        await receiver.stop()

    error_logs = [r for r in caplog.records if r.levelno >= logging.ERROR]
    otel_error = any(
        "OTLP" in r.getMessage() or "traces" in r.getMessage() for r in error_logs
    )
    assert otel_error, "should log the deserialization error"


@pytest.mark.asyncio
async def test_empty_body_returns_ok(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    receiver = OtelReceiver(log_level="debug")
    port = _free_port()
    await receiver.start(port=port)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"http://127.0.0.1:{port}/v1/traces",
                content=b"",
                headers={"Content-Type": "application/x-protobuf"},
            )
        assert resp.status_code in (200, 202)
    finally:
        await receiver.stop()


@pytest.mark.asyncio
async def test_receiver_start_stop_no_crash() -> None:
    receiver = OtelReceiver(log_level="info")
    port = _free_port()
    await receiver.start(port=port)
    await receiver.stop()
    await receiver.start(port=port)
    await receiver.stop()


@pytest.mark.asyncio
async def test_post_to_wrong_path_returns_404(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    receiver = OtelReceiver(log_level="debug")
    port = _free_port()
    await receiver.start(port=port)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"http://127.0.0.1:{port}/v1/wrong",
                content=b"data",
            )
        assert resp.status_code == 404
    finally:
        await receiver.stop()


@pytest.mark.asyncio
async def test_otel_receiver_default_port_in_docker_compose_wiring() -> None:
    """Verify that BP_LOG_LEVEL and BP_OTEL_PORT are read from env and wired correctly."""
    import bp_agents.main as main_mod

    os.environ["BP_LOG_LEVEL"] = "debug"
    os.environ["BP_OTEL_PORT"] = "9999"
    importlib.reload(main_mod)

    try:
        assert main_mod.BP_LOG_LEVEL == "debug"
        assert main_mod.BP_OTEL_PORT == 9999
    finally:
        os.environ.pop("BP_LOG_LEVEL", None)
        os.environ.pop("BP_OTEL_PORT", None)
        importlib.reload(main_mod)
