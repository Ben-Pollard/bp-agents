// OTEL Observability Plugin for opencode
// Hooks session lifecycle events and tool calls, emits OTLP spans
// to the orchestrator's OtelReceiver at $OTEL_EXPORTER_OTLP_ENDPOINT.

const OTEL_ENDPOINT = (process.env.OTEL_EXPORTER_OTLP_ENDPOINT || "http://orchestrator:4318") + "/v1/traces";
const SERVICE_NAME = "opencode-sandbox";

function hexId(len) {
  return Array.from({ length: len }, () => Math.floor(Math.random() * 16).toString(16)).join("");
}

function makeSpan(name, attributes) {
  const now = Date.now() * 1_000_000;
  return {
    name: name,
    spanId: hexId(16),
    traceId: hexId(32),
    startTimeUnixNano: String(now),
    endTimeUnixNano: String(now + 1_000_000),
    kind: 1,
    attributes: Object.entries(attributes || {}).map(([k, v]) => ({
      key: k,
      value: { stringValue: String(v) },
    })),
  };
}

function makeOtlpBody(spans) {
  return {
    resourceSpans: [{
      resource: {
        attributes: [{ key: "service.name", value: { stringValue: SERVICE_NAME } }],
      },
      scopeSpans: [{
        scope: { name: "opencode-observability" },
        spans: spans,
      }],
    }],
  };
}

async function emit(spans) {
  try {
    const body = JSON.stringify(makeOtlpBody(spans));
    await fetch(OTEL_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body,
    });
  } catch (e) {
    console.error("[otel] emit failed:", e.message);
  }
}

const plugin = async (ctx) => {
  console.log("[otel] loaded endpoint=" + OTEL_ENDPOINT);
  return {
    event: async ({ event }) => {
      if (event.type === "session.status" || event.type === "session.idle" || event.type === "session.busy") {
        const props = event.properties || {};
        await emit([makeSpan("session.status", {
          "event.type": "session_status",
          "session.id": String(props.sessionID || ""),
          "session.status": String(props.status?.type || props.type || event.type),
        })]);
      }
      if (event.type === "session.error") {
        const props = event.properties || {};
        await emit([makeSpan("session.error", {
          "event.type": "session_error",
          "session.id": String(props.sessionID || ""),
          "error.message": String(props.error?.message || props.error || ""),
        })]);
      }
    },
    "tool.execute.before": async (input, output) => {
      await emit([makeSpan("tool.execute", {
        "event.type": "tool_call",
        "llm.message.type": "tool_call",
        "tool.name": String(input.tool || ""),
        "session.id": String(input.sessionID || ""),
        "call.id": String(input.callID || ""),
      })]);
    },
    "tool.execute.after": async (input, output) => {
      await emit([makeSpan("tool.execute.result", {
        "event.type": "tool_call",
        "tool.name": String(input.tool || ""),
        "session.id": String(input.sessionID || ""),
        "tool.result": String((output?.output || "").slice(0, 200)),
      })]);
    },
    "chat.message": async (input, output) => {
      const text = output?.message?.content?.[0]?.text || "";
      await emit([makeSpan("chat.message", {
        "event.type": "llm_message",
        "llm.message.type": "user",
        "session.id": String(input.sessionID || ""),
        "model.provider": String(input.model?.providerID || ""),
        "model.id": String(input.model?.modelID || ""),
        "message.id": String(input.messageID || ""),
        "llm.message.text": String(text.slice(0, 500)),
      })]);
    },
  };
};

export default plugin;