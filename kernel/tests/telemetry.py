"""In-memory OpenTelemetry providers for asserting on spans and metrics."""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    HistogramDataPoint,
    InMemoryMetricReader,
    NumberDataPoint,
)
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

type Point = tuple[dict[str, Any], float]


@dataclass(frozen=True)
class Telemetry:
    exporter: InMemorySpanExporter
    reader: InMemoryMetricReader

    def spans(self, trace_id: str) -> list[ReadableSpan]:
        return [
            span
            for span in self.exporter.get_finished_spans()
            if span.context is not None and format(span.context.trace_id, "032x") == trace_id
        ]

    def points(self, name: str) -> list[Point]:
        """Histogram points report their count, counters and gauges their value."""
        data = self.reader.get_metrics_data()
        found: list[Point] = []
        if data is None:
            return found
        for resource in data.resource_metrics:
            for scope in resource.scope_metrics:
                for metric in scope.metrics:
                    if metric.name != name:
                        continue
                    for point in metric.data.data_points:
                        attributes = dict(point.attributes or {})
                        if isinstance(point, HistogramDataPoint):
                            found.append((attributes, point.count))
                        elif isinstance(point, NumberDataPoint):
                            found.append((attributes, point.value))
        return found

    def total(self, name: str, **attributes: Any) -> float:
        return sum(
            value
            for point_attributes, value in self.points(name)
            if all(point_attributes.get(k) == v for k, v in attributes.items())
        )


def install() -> Telemetry:
    exporter = InMemorySpanExporter()
    reader = InMemoryMetricReader()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(MeterProvider(metric_readers=[reader]))
    return Telemetry(exporter, reader)


@contextmanager
def span_trace_id(name: str = "test") -> Generator[str]:
    with trace.get_tracer("tests").start_as_current_span(name) as span:
        yield format(span.get_span_context().trace_id, "032x")
