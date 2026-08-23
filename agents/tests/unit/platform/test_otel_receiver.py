"""Tests for OtelReceiver — OTLP/HTTP span ingestion."""

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
async def test_debug_level_logs_all_spans(capsys: pytest.CaptureFixture[str]) -> None:
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

    captured = capsys.readouterr()
    otel_lines = [
        line
        for line in captured.out.splitlines()
        if "llm_message" in line or "tool_call" in line or "session_status" in line
    ]
    assert any("llm_message" in line for line in otel_lines)
    assert any("tool_call" in line for line in otel_lines)
    assert any("session_status" in line for line in otel_lines)


@pytest.mark.asyncio
async def test_info_level_filters_to_session_events(
    capsys: pytest.CaptureFixture[str],
) -> None:
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

    captured = capsys.readouterr()
    assert "session_error" in captured.out or "session_status" in captured.out
    assert "llm_message" not in captured.out
    assert "tool_call" not in captured.out


@pytest.mark.asyncio
async def test_invalid_payload_does_not_crash(
    capsys: pytest.CaptureFixture[str],
) -> None:
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

    captured = capsys.readouterr()
    assert "failed to process OTLP traces" in captured.err


@pytest.mark.asyncio
async def test_empty_body_does_not_crash(capsys: pytest.CaptureFixture[str]) -> None:
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
