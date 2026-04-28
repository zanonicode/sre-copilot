# macOS Metal Serving

> **Purpose**: Why Ollama runs on the Mac host (not as a Pod) and how Metal acceleration shapes everything downstream
> **MCP Validated**: 2026-04-26

## The Hard Constraint

Apple Metal GPUs are NOT accessible from inside Docker containers on macOS. Docker Desktop runs containers in a Linux VM that has no path to the host's GPU. Therefore:

- **Ollama in a Pod = CPU-only inference** = ~10× slower (TTFT 30–60s instead of 3–5s)
- **Ollama on the host = Metal accelerated** = TTFT 1–3s after warm-load

For SRE Copilot we accept the architectural awkwardness (Pods talk to host) in exchange for usable demo latency.

## Architecture

```text
┌─────────────────────────────── macOS Host ────────────────────────────────┐
│                                                                            │
│  brew services start ollama                                                │
│  └─ ollama serve  (binds 0.0.0.0:11434, uses Metal)                        │
│      └─ qwen2.5:7b loaded in unified memory (~5 GB)                        │
│                                                                            │
│  Docker Desktop                                                            │
│  └─ kind cluster (Linux VM)                                                │
│      ├─ control-plane node                                                 │
│      ├─ worker-platform node                                               │
│      └─ worker-apps node                                                   │
│          └─ Pod: backend                                                   │
│              └─ HTTP POST → ollama.sre-copilot.svc:11434                   │
│                  └─ ExternalName → host.docker.internal:11434  ────────────┤
│                                                                            ↓
│                                              host loopback to ollama serve │
└────────────────────────────────────────────────────────────────────────────┘
```

## Why Not vLLM in a Pod?

vLLM gives state-of-the-art throughput, but:

- vLLM requires CUDA (or ROCm). Mac = no CUDA.
- Llama.cpp Pod variants are CPU-only on Mac.

We document vLLM in `docs/aws-migration.md` as the prod swap when moving to EKS with GPU nodes.

## RAM Budget on a 16 GB Mac

| Consumer | Typical | Peak |
|----------|---------|------|
| macOS + apps | 5 GB | 6 GB |
| Docker Desktop VM (4 vCPU, 8 GB) | 4 GB | 8 GB |
| Ollama runtime + Qwen 7B | 5 GB | 6 GB |
| Headroom | ~2 GB | 0 — stop! |

If you load BOTH Qwen 7B + Llama 8B simultaneously, you'll spill into swap and TTFT goes from 3s to 30s. See `concepts/keep-alive-and-cold-load.md` and `patterns/on-demand-model-load.md`.

## Tuning Docker Desktop

Settings → Resources → recommended for SRE Copilot demo:

| Setting | Value | Why |
|---------|-------|-----|
| CPUs | 4 | Plenty for kind + apps |
| Memory | 8 GB | Tight; raises OOMKilled risk if higher because Ollama on host needs RAM too |
| Swap | 1 GB | Default OK |
| Disk | 60 GB | Models are big |

If you have 32 GB Mac, raise Docker memory to 12 GB and you can afford a second loaded model.

## Health Check Pattern

```bash
# Is Ollama up on the host?
curl -fsS http://localhost:11434/api/tags

# From a Pod
kubectl exec -it deploy/backend -n sre-copilot -- \
  curl -fsS http://ollama.sre-copilot.svc.cluster.local:11434/api/tags
```

The backend should NOT do this on every request — instead, catch `httpx.ConnectError` / `openai.APIConnectionError` and surface a 503 with `{"error_code": "ollama_unreachable"}` (DESIGN AT-007).

## See Also

- concepts/kind-host-networking.md — the `host.docker.internal` routing
- concepts/model-selection.md — Qwen vs Llama tradeoffs
- concepts/keep-alive-and-cold-load.md — RAM rotation
