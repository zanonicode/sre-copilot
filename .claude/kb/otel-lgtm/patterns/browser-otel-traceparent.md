# Browser OTel + Traceparent Propagation

> **Purpose**: Next.js frontend emits its own spans (web vitals + fetch) and propagates W3C `traceparent` into backend requests so a single trace covers click → SSE done
> **MCP Validated**: 2026-04-26

## When to Use

- Sprint 3 entry #34 (`src/frontend/observability/`)
- Required for AT-001 trace continuity

## Implementation

### Install (Next.js 14 App Router)

```bash
npm i @opentelemetry/api \
      @opentelemetry/sdk-trace-web \
      @opentelemetry/exporter-trace-otlp-http \
      @opentelemetry/instrumentation-fetch \
      @opentelemetry/instrumentation-document-load \
      @opentelemetry/context-zone \
      @opentelemetry/resources \
      @opentelemetry/semantic-conventions
```

### `src/frontend/src/observability/otel.ts`

```typescript
import { WebTracerProvider } from "@opentelemetry/sdk-trace-web";
import { BatchSpanProcessor } from "@opentelemetry/sdk-trace-base";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { ZoneContextManager } from "@opentelemetry/context-zone";
import { registerInstrumentations } from "@opentelemetry/instrumentation";
import { FetchInstrumentation } from "@opentelemetry/instrumentation-fetch";
import { DocumentLoadInstrumentation } from "@opentelemetry/instrumentation-document-load";
import { Resource } from "@opentelemetry/resources";
import { SemanticResourceAttributes } from "@opentelemetry/semantic-conventions";
import { W3CTraceContextPropagator } from "@opentelemetry/core";
import { propagation } from "@opentelemetry/api";

export function initBrowserOtel() {
  const provider = new WebTracerProvider({
    resource: new Resource({
      [SemanticResourceAttributes.SERVICE_NAME]: "sre-copilot-frontend",
      [SemanticResourceAttributes.DEPLOYMENT_ENVIRONMENT]: "kind-local",
    }),
  });

  // Browser → Collector OTLP/HTTP (gRPC not viable from browser)
  provider.addSpanProcessor(new BatchSpanProcessor(new OTLPTraceExporter({
    url: "/otel/v1/traces",                     // proxied through Next.js to collector :4318
  })));

  provider.register({ contextManager: new ZoneContextManager() });
  propagation.setGlobalPropagator(new W3CTraceContextPropagator());

  registerInstrumentations({
    instrumentations: [
      new DocumentLoadInstrumentation(),
      new FetchInstrumentation({
        // CRITICAL: tells the SDK to inject traceparent on these origins
        propagateTraceHeaderCorsUrls: [
          /\/api\/.*/,
          /^http:\/\/backend\.sre-copilot\.svc\.cluster\.local.*/,
        ],
        clearTimingResources: true,
      }),
    ],
  });
}
```

### Hook into `app/layout.tsx`

```typescript
"use client";
import { useEffect } from "react";
import { initBrowserOtel } from "@/observability/otel";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  useEffect(() => { initBrowserOtel(); }, []);
  return <html lang="en"><body>{children}</body></html>;
}
```

### Backend CORS — must expose `traceparent`

```python
# src/backend/main.py
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://frontend.sre-copilot.svc.cluster.local"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "traceparent", "tracestate"],
    expose_headers=["traceparent"],
)
```

## Configuration

### Next.js proxy for OTLP/HTTP

Browser cannot hit cluster DNS directly. Proxy via Next.js API route:

```typescript
// src/frontend/src/app/otel/v1/[...path]/route.ts
export async function POST(req: Request, { params }: { params: { path: string[] } }) {
  const url = `http://otel-collector.observability:4318/v1/${params.path.join("/")}`;
  const r = await fetch(url, { method: "POST", body: req.body, headers: req.headers,
                               // @ts-ignore Node 18 stream
                               duplex: "half" });
  return new Response(r.body, { status: r.status });
}
```

Or expose OTLP/HTTP via Traefik IngressRoute and point `OTLPTraceExporter` at that public URL.

## Verification

In Chrome DevTools → Network → click a `/api/analyze/logs` request → check Request Headers:

```text
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
```

In Tempo, search by trace_id `4bf92f3577b34da6a3ce929d0e0e4736` — you should see:

```text
[frontend] documentLoad
  └─ [frontend] HTTP POST /api/analyze/logs
      └─ [backend] POST /analyze/logs
          ├─ [backend] ollama.host_call
          └─ [backend] ollama.inference (synthetic)
```

## Common Issues

| Symptom | Fix |
|---------|-----|
| Backend trace and frontend trace are separate | `propagateTraceHeaderCorsUrls` regex doesn't match the API URL |
| `traceparent` header rejected by browser | Backend must list it in `allow_headers` |
| 405 on `/otel/v1/traces` | Next.js route handler missing — use proxy snippet |
| No spans in collector | Wrong URL (HTTP vs gRPC: browser uses :4318 NOT :4317) |

## See Also

- patterns/python-fastapi-instrumentation.md — backend side of the trace
- concepts/otel-sdk-init.md — context propagation theory
