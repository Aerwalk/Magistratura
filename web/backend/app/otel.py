"""OpenTelemetry tracing: FastAPI instrumentation exported via OTLP to Tempo.

Best-effort: if Tempo is unreachable the exporter drops spans and the
simulation keeps running (traces are optional, like TimescaleDB/Loki).
"""

import os

TEMPO_OTLP = os.getenv("TEMPO_OTLP_URL", "http://tempo:4318")

_tracer = None
_enabled = False


def get_tracer():
    return _tracer


def is_enabled() -> bool:
    return _enabled


def init_tracing(app):
    global _tracer, _enabled
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": "magsim-backend"})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{TEMPO_OTLP}/v1/traces"))
        )
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)
        _tracer = trace.get_tracer("magsim")
        _enabled = True
        print(f"[otel] info: tracing enabled -> {TEMPO_OTLP}")
    except Exception as exc:
        print(f"[otel] warn: tracing disabled: {exc}")