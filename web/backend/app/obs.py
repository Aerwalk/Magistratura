"""Backend observability helpers.

Adds manual OTel spans to business logic, W3C traceparent propagation over
the websocket protocols (agent <-> backend, so robot/uav agents and backend
share one distributed trace), a python-logging -> Loki mirror for error
records, and current-trace-id capture so Loki lines can link to Tempo.

Everything is best-effort: when OpenTelemetry is unavailable, span() becomes
a no-op and the propagators return None.
"""

import logging
from contextlib import contextmanager

try:
    from opentelemetry import trace as _otrace
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator as _TraceContextPropagator
except Exception:
    _otrace = None
    _TraceContextPropagator = None

from otel import get_tracer as _get_tracer


def tracing_available() -> bool:
    return _otrace is not None and _get_tracer() is not None


@contextmanager
def span(name, robot_id=None, parent_ctx=None, **attrs):
    """Start a span as current; yields it (or None when tracing is off)."""
    tracer = _get_tracer()
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(name, context=parent_ctx) as sp:
        if sp is not None:
            _decorate(sp, robot_id, attrs)
        yield sp


def begin_span(name, robot_id=None, parent_ctx=None, **attrs):
    """Manually open a span (no-with-block variant). Call end_span() later.

    Returns a handle or None when tracing is unavailable/throws.
    """
    tracer = _get_tracer()
    if tracer is None:
        return None
    try:
        sp = tracer.start_span(name, context=parent_ctx)
        if sp is None:
            return None
        _decorate(sp, robot_id, attrs)
        token_cm = _otrace.use_span(sp, end_on_exit=False)
        token_cm.__enter__()
        return (sp, token_cm)
    except Exception:
        return None


def end_span(handle, error=None):
    """Close a span previously opened with begin_span(). Tolerates None."""
    if not handle:
        return
    sp, token_cm = handle
    try:
        if error is not None and sp is not None:
            try:
                from opentelemetry import trace as ot
                sp.set_status(ot.Status(ot.StatusCode.ERROR, str(error)))
                sp.record_exception(error)
            except Exception:
                pass
        token_cm.__exit__(None, None, None)
        sp.end()
    except Exception:
        pass


@contextmanager
def null():
    """No-op context manager (same 'with' shape as span())."""
    yield None


def _decorate(sp, robot_id, attrs):
    try:
        if robot_id is not None:
            sp.set_attribute("robot.id", int(robot_id))
        for k, v in attrs.items():
            if v is not None:
                sp.set_attribute(k, v)
    except Exception:
        pass


def w3c_traceparent():
    """W3C traceparent of the current span (for embedding into messages)."""
    if _otrace is None:
        return None
    try:
        span = _otrace.get_current_span()
        ctx = span.get_span_context()
        if not ctx.is_valid:
            return None
        return "00-{:032x}-{:016x}-{:02x}".format(
            ctx.trace_id, ctx.span_id, ctx.trace_flags & 0xff
        )
    except Exception:
        return None


def current_trace_id():
    """Trace id (32-hex) of the current span, or None."""
    if _otrace is None:
        return None
    try:
        span = _otrace.get_current_span()
        ctx = span.get_span_context()
        if not ctx.is_valid:
            return None
        return "{:032x}".format(ctx.trace_id)
    except Exception:
        return None


def extract_traceparent(msg):
    """Extract a parent Context from a 'traceparent' key in a message dict."""
    if _otrace is None or _TraceContextPropagator is None:
        return None
    try:
        tp = msg.get("traceparent") if isinstance(msg, dict) else None
        if not tp:
            return None
        return _TraceContextPropagator().extract({"traceparent": tp})
    except Exception:
        return None


class LokiLogHandler(logging.Handler):
    """Mirror WARNING+ python log records into Loki under magsim-backend."""

    def emit(self, record):
        try:
            from db import push_log
            text = self.format(record)
            level = getattr(record, "levelname", "info").lower()
            push_log(getattr(record, "robot_id", None), level, text, None)
        except Exception:
            pass


_ATTACHED = False


def init():
    """Wire LokiLogHandler into the root logger (idempotent)."""
    global _ATTACHED
    if _ATTACHED:
        return
    _ATTACHED = True
    try:
        handler = LokiLogHandler(level=logging.WARNING)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s"
        ))
        logging.getLogger().addHandler(handler)
        print("[obs] info: python logging -> Loki (WARNING+)")
    except Exception as exc:
        print(f"[obs] error: log handler failed: {exc}")