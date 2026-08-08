"""OTLP/HTTP receiver that logs spans to stdout.

Best-effort: failures are logged and swallowed, never propagate to caller.
Log level filtering: info=session_status + session_error events only;
debug=all spans including llm_message and tool_call.
"""

import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer

logger = logging.getLogger(__name__)


class _OtlpHandler(BaseHTTPRequestHandler):
    receiver: "OtelReceiver | None" = None

    def log_message(self, format: str, *args: object) -> None:
        logger.debug("OTLP server: " + format, *args)

    def do_POST(self) -> None:
        if self.path != "/v1/traces":
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()
            return
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        if self.receiver is not None:
            self.receiver._handle_traces(body)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"healthy": true}')
        else:
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()


class OtelReceiver:
    def __init__(self, log_level: str = "info") -> None:
        self._log_level = log_level
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._server_port: int = 4318

    async def start(self, port: int = 4318) -> None:
        _OtlpHandler.receiver = self
        self._server = HTTPServer(("0.0.0.0", port), _OtlpHandler)
        self._server_port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.debug("OTLP receiver started on port %d", self._server_port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.debug("OTLP receiver stopped")

    def _handle_traces(self, body: bytes) -> None:
        if not body:
            return
        try:
            self._process_otlp(body)
        except Exception:
            logger.exception("failed to process OTLP traces")

    def _process_otlp(self, body: bytes) -> None:
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )

        request = ExportTraceServiceRequest()
        request.ParseFromString(body)

        for resource_spans in request.resource_spans:
            for scope_spans in resource_spans.scope_spans:
                for span in scope_spans.spans:
                    self._process_span(span)

    def _process_span(self, span: object) -> None:
        span_type = self._get_span_type(span)
        span_name = getattr(span, "name", "")
        span_id = getattr(span, "span_id", b"").hex()

        if self._log_level == "info":
            if span_type not in ("session_status", "session_error"):
                return

        record = {
            "span_id": span_id,
            "name": span_name,
            "type": span_type or "unknown",
        }

        attrs = self._get_attributes(span)
        if attrs:
            record["attributes"] = attrs

        events = self._get_events(span)
        if events:
            record["events"] = events

        logger.log(
            logging.DEBUG if self._log_level == "debug" else logging.INFO,
            "OTEL span: %s",
            json.dumps(record),
        )

    @staticmethod
    def _get_span_type(span: object) -> str | None:
        for attr in getattr(span, "attributes", []):
            key = attr.key if hasattr(attr, "key") else ""
            if key in ("event.type", "type", "gen_ai.event.type"):
                value = attr.value
                if hasattr(value, "string_value") and value.string_value:
                    return value.string_value
                if hasattr(value, "string_value"):
                    return str(value)
        for attr in getattr(span, "attributes", []):
            if hasattr(attr, "key") and attr.key == "type":
                val = attr.value
                if hasattr(val, "string_value"):
                    return val.string_value
        return None

    @staticmethod
    def _get_attributes(span: object) -> dict:
        result = {}
        for attr in getattr(span, "attributes", []):
            key = attr.key if hasattr(attr, "key") else ""
            val = attr.value
            if hasattr(val, "string_value") and val.string_value:
                result[key] = val.string_value
            elif hasattr(val, "int_value"):
                result[key] = val.int_value
            elif hasattr(val, "double_value"):
                result[key] = val.double_value
            elif hasattr(val, "bool_value"):
                result[key] = val.bool_value
        return result

    @staticmethod
    def _get_events(span: object) -> list:
        events = []
        for event in getattr(span, "events", []):
            ev = {"name": event.name if hasattr(event, "name") else ""}
            attrs = {}
            for attr in getattr(event, "attributes", []):
                key = attr.key if hasattr(attr, "key") else ""
                val = attr.value
                if hasattr(val, "string_value") and val.string_value:
                    attrs[key] = val.string_value
            if attrs:
                ev["attributes"] = attrs
            events.append(ev)
        return events
