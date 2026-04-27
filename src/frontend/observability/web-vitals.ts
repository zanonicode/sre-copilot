import { onCLS, onFCP, onFID, onLCP, onTTFB, type Metric } from "web-vitals";
import { getTracer } from "./otel";

function recordVital(metric: Metric): void {
  const tracer = getTracer();
  const span = tracer.startSpan(`web-vital.${metric.name.toLowerCase()}`);
  span.setAttributes({
    "web_vital.name": metric.name,
    "web_vital.value": metric.value,
    "web_vital.rating": metric.rating,
    "web_vital.id": metric.id,
  });
  span.end();
}

export function measureWebVitals(): void {
  if (typeof window === "undefined") {
    return;
  }
  onCLS(recordVital);
  onFCP(recordVital);
  onFID(recordVital);
  onLCP(recordVital);
  onTTFB(recordVital);
}
