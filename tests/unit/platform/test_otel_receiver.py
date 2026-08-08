"""Tests for OtelReceiver — OTLP/HTTP span ingestion."""

import logging
import time

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
async def test_otel_receiver_accepts_post_v1_traces() -> None:
    receiver = OtelReceiver()
    await receiver.start(port=0)
    try:
        url = f"http://localhost:{receiver._server_port}/v1/traces"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                content=b"",
                headers={"Content-Type": "application/x-protobuf"},
            )
        assert resp.status_code in (200, 202)
    finally:
        await receiver.stop()


@pytest.mark.asyncio
async def test_debug_level_logs_all_spans(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    receiver = OtelReceiver(log_level="debug")
    await receiver.start(port=0)
    try:
        body = _make_otlp_body(
            [
                _make_span("llm_call", "llm_message"),
                _make_span("tool_use", "tool_call"),
                _make_span("session_done", "session_status"),
            ]
        )
        url = f"http://localhost:{receiver._server_port}/v1/traces"
        async with httpx.AsyncClient() as client:
            await client.post(
                url,
                content=body,
                headers={"Content-Type": "application/x-protobuf"},
            )
        time.sleep(0.3)
    finally:
        await receiver.stop()

    otel_logs = [r for r in caplog.records if "OTEL span" in r.getMessage()]
    types_in_logs = set()
    for record in otel_logs:
        import json

        data = json.loads(record.getMessage().replace("OTEL span: ", "", 1))
        types_in_logs.add(data["type"])

    assert types_in_logs == {"llm_message", "tool_call", "session_status"}


@pytest.mark.asyncio
async def test_info_level_filters_to_session_events(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    receiver = OtelReceiver(log_level="info")
    await receiver.start(port=0)
    try:
        body = _make_otlp_body(
            [
                _make_span("llm_call", "llm_message"),
                _make_span("tool_use", "tool_call"),
                _make_span("session_error", "session_error"),
                _make_span("session_done", "session_status"),
            ]
        )
        url = f"http://localhost:{receiver._server_port}/v1/traces"
        async with httpx.AsyncClient() as client:
            await client.post(
                url,
                content=body,
                headers={"Content-Type": "application/x-protobuf"},
            )
        time.sleep(0.3)
    finally:
        await receiver.stop()

    otel_logs = [r for r in caplog.records if "OTEL span" in r.getMessage()]
    types_in_logs = set()
    for record in otel_logs:
        import json

        data = json.loads(record.getMessage().replace("OTEL span: ", "", 1))
        types_in_logs.add(data["type"])

    assert types_in_logs == {"session_error", "session_status"}
    assert "llm_message" not in types_in_logs
    assert "tool_call" not in types_in_logs


@pytest.mark.asyncio
async def test_invalid_payload_does_not_crash(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    receiver = OtelReceiver(log_level="debug")
    await receiver.start(port=0)
    try:
        url = f"http://localhost:{receiver._server_port}/v1/traces"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                content=b"this is not valid protobuf data here",
                headers={"Content-Type": "application/x-protobuf"},
            )
        assert resp.status_code in (200, 202)
        time.sleep(0.3)
    finally:
        await receiver.stop()

    error_logs = [r for r in caplog.records if r.levelno >= logging.ERROR]
    otel_error = any(
        "OTLP" in r.getMessage() or "traces" in r.getMessage() for r in error_logs
    )
    assert otel_error, "should log the deserialization error"


@pytest.mark.asyncio
async def test_empty_body_does_not_crash(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    receiver = OtelReceiver(log_level="debug")
    await receiver.start(port=0)
    try:
        url = f"http://localhost:{receiver._server_port}/v1/traces"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                content=b"",
                headers={"Content-Type": "application/x-protobuf"},
            )
        assert resp.status_code in (200, 202)
    finally:
        await receiver.stop()
