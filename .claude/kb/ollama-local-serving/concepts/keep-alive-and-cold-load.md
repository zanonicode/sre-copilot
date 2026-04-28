# keep_alive + Cold Load Behavior

> **Purpose**: How Ollama decides when a model lives in RAM, when it gets evicted, and how to control that with `keep_alive`
> **MCP Validated**: 2026-04-26

## Lifecycle States

```text
on disk (~5 GB)            → not loaded, no RAM cost
loaded into RAM (~5–6 GB)  → ready, Metal-resident, instant TTFT
evicted (after keep_alive) → freed, next request triggers cold-load
```

## Cold-Load Cost (M1/M2 Mac)

| Phase | Time |
|-------|------|
| Read model file from disk | 1–3s (SSD, partly cached) |
| Allocate Metal buffers | 1–2s |
| First-token compute | 0.5–2s |
| **TOTAL cold TTFT** | **5–15s** |
| Warm TTFT (already loaded) | 0.5–2s |

So cold-load is roughly 10× warm. Demo and AT-001 (TTFT < 2s) require warm.

## `keep_alive` Parameter

Per-request hint to Ollama: "after I'm done, hold this model in RAM for X."

| Value | Meaning |
|-------|---------|
| `"5m"` (default) | Keep loaded for 5 minutes after last request |
| `"30m"`, `"1h"` | Long warm hold — good for demo |
| `0` or `"0"` | Unload immediately on completion |
| `-1` or `"-1"` | Keep forever (until process exits) |

```python
await client.chat.completions.create(
    model="qwen2.5:7b-instruct-q4_K_M",
    messages=[...],
    extra_body={"keep_alive": "30m"},
)
```

## Global Default

Set `OLLAMA_KEEP_ALIVE` env var on the host:

```bash
launchctl setenv OLLAMA_KEEP_ALIVE 30m
brew services restart ollama
```

For SRE Copilot demo: set to `30m` host-wide so the analyzer model stays warm between user clicks during the screencast.

## Unload Semantics

To free a model immediately:

```bash
# Empty messages + keep_alive: 0 → triggers unload
curl http://localhost:11434/api/generate \
  -d '{"model":"qwen2.5:7b-instruct-q4_K_M","keep_alive":0}'
```

Note: there is NO explicit `/api/unload` endpoint. The `keep_alive: 0` trick is the documented way.

## Concurrent Loaded Models

| Setting | Default | Effect |
|---------|---------|--------|
| `OLLAMA_MAX_LOADED_MODELS` | 1 (Mac) | Hard cap; loading a 2nd evicts oldest |
| `OLLAMA_NUM_PARALLEL` | 4 | Concurrent requests against ONE loaded model |

Mac default is intentionally 1 to protect RAM. If you set it to 2 and try to hold Qwen + Llama, you swap-thrash.

## Detecting Loaded Models

```bash
curl -s http://localhost:11434/api/ps | jq
```

```json
{
  "models": [
    {
      "name": "qwen2.5:7b-instruct-q4_K_M",
      "size": 4683073536,
      "size_vram": 5897330688,
      "expires_at": "2026-04-26T01:09:30Z"
    }
  ]
}
```

`expires_at` is when keep_alive will fire. `models` empty → nothing loaded → next call is cold.

## Smoke-Test Wall-Clock Timer

Required for AT-004 (cold start ≤ 10 min) and `make smoke`:

```bash
# Warm the model before assertions
curl -s http://localhost:11434/v1/chat/completions \
  -d '{"model":"qwen2.5:7b-instruct-q4_K_M","messages":[{"role":"user","content":"warmup"}]}' > /dev/null

# Now run latency assertions
time curl -s http://localhost:11434/v1/chat/completions ...
```

## Failure Modes

| Symptom | Cause |
|---------|-------|
| TTFT 30s every call | `keep_alive` too short OR something else is being loaded between calls (`/api/ps` will show evictions) |
| RAM pressure / swap | Two models loaded; reduce `OLLAMA_MAX_LOADED_MODELS=1` |
| First call after `make demo` slow | Expected cold-load; pre-warm in Makefile |
| Model evicted mid-request | Should not happen; if it does check `OLLAMA_NUM_PARALLEL` |

## Recommended Defaults for SRE Copilot

```bash
launchctl setenv OLLAMA_KEEP_ALIVE 30m
launchctl setenv OLLAMA_MAX_LOADED_MODELS 1
launchctl setenv OLLAMA_NUM_PARALLEL 2          # 2 concurrent backend requests OK
launchctl setenv OLLAMA_HOST 0.0.0.0:11434
brew services restart ollama
```

## See Also

- patterns/on-demand-model-load.md — explicit unload before judge run
- patterns/model-rotation-debugging.md — what eviction storms look like
- concepts/macos-metal-serving.md — RAM budget context
