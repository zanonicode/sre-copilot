import { WebTracerProvider } from "@opentelemetry/sdk-trace-web";
import { BatchSpanProcessor } from "@opentelemetry/sdk-trace-base";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { Resource } from "@opentelemetry/resources";
import { SemanticResourceAttributes } from "@opentelemetry/semantic-conventions";
import { registerInstrumentations } from "@opentelemetry/instrumentation";
import { FetchInstrumentation } from "@opentelemetry/instrumentation-fetch";
import { DocumentLoadInstrumentation } from "@opentelemetry/instrumentation-document-load";
import { W3CTraceContextPropagator } from "@opentelemetry/core";
import { propagation, context, trace } from "@opentelemetry/api";

const COLLECTOR_ENDPOINT =
  process.env.NEXT_PUBLIC_OTEL_COLLECTOR_URL ||
  "http://otel-collector.observability.svc.cluster.local:4318";

let initialized = false;

export function initBrowserOtel(): void {
  if (initialized || typeof window === "undefined") {
    return;
  }
  initialized = true;

  const resource = new Resource({
    [SemanticResourceAttributes.SERVICE_NAME]: "sre-copilot-frontend",
    [SemanticResourceAttributes.DEPLOYMENT_ENVIRONMENT]: "kind-local",
  });

  const exporter = new OTLPTraceExporter({
    url: `${COLLECTOR_ENDPOINT}/v1/traces`,
    headers: {},
  });

  const provider = new WebTracerProvider({ resource });
  provider.addSpanProcessor(new BatchSpanProcessor(exporter));

  propagation.setGlobalPropagator(new W3CTraceContextPropagator());
  provider.register();

  registerInstrumentations({
    instrumentations: [
      new FetchInstrumentation({
        propagateTraceHeaderCorsUrls: [/.*/],
        clearTimingResources: true,
      }),
      new DocumentLoadInstrumentation(),
    ],
  });
}

export function getTracer() {
  return trace.getTracer("sre-copilot-frontend");
}

export { context, trace, propagation };
