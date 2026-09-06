"""Agent-side OpenTelemetry tracing (best-effort -> Tempo via OTLP HTTP).

Also exposes W3C traceparent helpers so messages sent back to the backend
carry the agent's span context, joining agent and backend into one
distributed trace.
"""

import os
from contextlib import contextmanager

try:
    from opentelemetry import trace as _otrace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    _OTEL_OK = True
except Exception:
    _OTEL_OK = False

SERVICE = os.getenv("OTEL_SERVICE_NAME", "magsim-robot-agent")
TEMPO_OTLP = os.getenv("TEMPO_OTLP_URL", "http://tempo:4318")

_tracer = None
_inited = False


def init():
    global _tracer, _inited
    if _inited:
        return
    _inited = True
    if not _OTEL_OK:
        print("[observe] opentelemetry unavailable, tracing off")
        return
    try:
        resource = Resource.create({"service.name": SERVICE})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{TEMPO_OTLP}/v1/traces"))
        )
        _otrace.set_tracer_provider(provider)
        _tracer = _otrace.get_tracer("magsim-agent")
        print(f"[observe] tracing enabled -> {TEMPO_OTLP} ({SERVICE})")
    except Exception as exc:
        _tracer = None
        print(f"[observe] tracing disabled: {exc}")


@contextmanager
def span(name, robot_id=None, parent_ctx=None, **attrs):
    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name, context=parent_ctx) as sp:
        if sp is not None:
            try:
                if robot_id is not None:
                    sp.set_attribute("robot.id", int(robot_id))
                for k, v in attrs.items():
                    if v is not None:
                        sp.set_attribute(k, v)
            except Exception:
                pass
        yield sp


def w3c_traceparent():
    if _otrace is None or _tracer is None:
        return None
    try:
        ctx = _otrace.get_current_span().get_span_context()
        if not ctx.is_valid:
            return None
        return "00-{:032x}-{:016x}-{:02x}".format(
            ctx.trace_id, ctx.span_id, ctx.trace_flags & 0xff
        )
    except Exception:
        return None


def extract_traceparent(msg):
    if _otrace is None:
        return None
    try:
        tp = msg.get("traceparent") if isinstance(msg, dict) else None
        if not tp:
            return None
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
        return TraceContextTextMapPropagator().extract({"traceparent": tp})
    except Exception:
        return None