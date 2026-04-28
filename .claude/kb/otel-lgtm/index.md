# OpenTelemetry + LGTM Knowledge Base

> **Purpose**: End-to-end observability stack for SRE Copilot — OTel SDK in Python/JS app code, OTel Collector as the routing hub, LGTM (Loki + Grafana + Tempo + Prometheus*) as the storage/UI backend, plus SLO burn-rate alerting math
> **MCP Validated**: 2026-04-26
>
> *Mimir replaced by Prometheus single-binary for the local 16 GB Mac kind cluster (RAM-friendly). LGTM acronym retained.

## Quick Navigation

### Concepts (< 150 lines each)

| File | Purpose |
|------|---------|
| [concepts/otel-sdk-init.md](concepts/otel-sdk-init.md) | TracerProvider + MeterProvider + LoggerProvider + Resource attributes |
| [concepts/collector-architecture.md](concepts/collector-architecture.md) | Receivers, processors, exporters, pipelines, deployment vs daemonset |
| [concepts/lgtm-stack-roles.md](concepts/lgtm-stack-roles.md) | What Loki/Grafana/Tempo/Prometheus each store + query model |
| [concepts/slo-burn-rate-math.md](concepts/slo-burn-rate-math.md) | Multi-window multi-burn-rate (MWMBR) — why 14.4 + 6 + 1 + 1 |

### Patterns (< 200 lines each)

| File | Purpose |
|------|---------|
| [patterns/python-fastapi-instrumentation.md](patterns/python-fastapi-instrumentation.md) | FastAPI auto-instrumentation + manual Ollama span (DESIGN §4.3) |
| [patterns/browser-otel-traceparent.md](patterns/browser-otel-traceparent.md) | Next.js fetch interceptor propagating W3C traceparent |
| [patterns/otel-collector-config.md](patterns/otel-collector-config.md) | OTLP in → Loki/Tempo/Prometheus out |
| [patterns/loki-single-binary-recipe.md](patterns/loki-single-binary-recipe.md) | Loki monolithic mode for kind (no S3, ephemeral) |
| [patterns/tempo-monolithic-recipe.md](patterns/tempo-monolithic-recipe.md) | Tempo monolithic single-binary, OTLP receiver |
| [patterns/prometheus-servicemonitor.md](patterns/prometheus-servicemonitor.md) | ServiceMonitor scrape config + relabeling |
| [patterns/grafana-sidecar-dashboards.md](patterns/grafana-sidecar-dashboards.md) | ConfigMap + sidecar auto-load of 4 dashboards |
| [patterns/mwmbr-slo-alerts.md](patterns/mwmbr-slo-alerts.md) | Prometheus rules for the 3 SLOs (availability, TTFT, full-response) |

---

## Quick Reference

- [quick-reference.md](quick-reference.md) — env vars, OTLP ports, PromQL/LogQL/TraceQL cheats

---

## Key Concepts

| Concept | Description |
|---------|-------------|
| **OTLP** | OpenTelemetry Protocol — gRPC (4317) or HTTP (4318); the wire format |
| **Resource** | Identity attributes attached to every signal (service.name, deployment.environment) |
| **Trace context** | W3C `traceparent` header propagating trace_id + span_id across hops |
| **Synthetic span** | Locally-emitted span representing work done by an opaque external system (Ollama) |
| **MWMBR** | Multi-Window Multi-Burn-Rate — Google SRE pattern for SLO alerts that catch fast and slow burns |

---

## Learning Path

| Level | Files |
|-------|-------|
| **Beginner** | concepts/lgtm-stack-roles.md, concepts/otel-sdk-init.md |
| **Intermediate** | patterns/python-fastapi-instrumentation.md, patterns/otel-collector-config.md, patterns/prometheus-servicemonitor.md |
| **Advanced** | concepts/slo-burn-rate-math.md, patterns/mwmbr-slo-alerts.md, patterns/browser-otel-traceparent.md |

---

## Agent Usage

| Agent | Primary Files | Use Case |
|-------|---------------|----------|
| observability-engineer | All patterns | Sprint 3 LGTM rollout, dashboards, alerts |
| python-developer | patterns/python-fastapi-instrumentation.md | Add OTel to FastAPI handlers |
| frontend-architect | patterns/browser-otel-traceparent.md | Browser OTel SDK + traceparent propagation |
| k8s-platform-engineer | patterns/loki/tempo/prometheus recipes | Render LGTM Helm releases |

---

## Project Context

This KB supports DESIGN §4.3 (OTel init), §4.4 (JSON logs with trace_id), §4.5 (Prom AnalysisTemplate), §9.2 (synthetic ollama.inference span), §9.3 (NetworkPolicy allow-list), §5.3 (log schema), and Sprint 3 entries #30–36.

| Component | Pattern |
|-----------|---------|
| OTLP collector deployment | patterns/otel-collector-config.md |
| Loki single-binary | patterns/loki-single-binary-recipe.md |
| Tempo monolithic | patterns/tempo-monolithic-recipe.md |
| Prometheus + ServiceMonitor | patterns/prometheus-servicemonitor.md |
| 4 Grafana dashboards | patterns/grafana-sidecar-dashboards.md |
| 3 SLO alert rules | patterns/mwmbr-slo-alerts.md |
| Backend instrumentation | patterns/python-fastapi-instrumentation.md |
| Frontend instrumentation | patterns/browser-otel-traceparent.md |

---

## External Resources

- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/)
- [OTel Collector](https://opentelemetry.io/docs/collector/)
- [Grafana Loki](https://grafana.com/docs/loki/latest/)
- [Grafana Tempo](https://grafana.com/docs/tempo/latest/)
- [Google SRE Workbook — Alerting on SLOs](https://sre.google/workbook/alerting-on-slos/)
