import os
from opentelemetry import trace


def configure():
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not endpoint:
        return
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    provider = TracerProvider(
        resource=Resource.create(
            {"service.name": "telesales-platform", "service.version": "0.2.0"}
        )
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")
        )
    )
    trace.set_tracer_provider(provider)


tracer = trace.get_tracer("telesales.harness")
