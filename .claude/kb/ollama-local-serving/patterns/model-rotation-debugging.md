# Model Rotation Debugging

> **Purpose**: Recognize the symptoms of model swap-thrash on a 16 GB Mac and have a runbook to fix it
> **MCP Validated**: 2026-04-26

## When to Use

- TTFT regression mid-demo
- After running the eval judge while the serving model is also active
- After raising `OLLAMA_MAX_LOADED_MODELS` above 1 on a 16 GB host

## Symptoms

| Observation | Likely cause |
|-------------|--------------|
| TTFT jumps from 1s → 15s for one request, then back to 1s | Cold-load: serving model was evicted |
| Sustained 8–20s TTFT for several minutes | Both models in RAM → swap thrash |
| `ollama serve` process eating CPU at idle | swap-related I/O |
| macOS Activity Monitor shows "memory pressure" yellow/red | Approaching/in swap |
| `kubectl logs backend` shows `request timeout` | Underlying inference is slow enough that 60s timeout fires |
| `/api/ps` shows two models | Either wrong env or judge run forgot to unload |

## Diagnostic Commands

```bash
# 1. What is loaded?
curl -s http://localhost:11434/api/ps | jq

# 2. Are we swapping? (macOS)
sysctl vm.swapusage
# vm.swapusage: total = 1024.00M used = 850.00M free = 174.00M (encrypted)
# > 100M used = bad sign on a 16 GB Mac

# 3. Memory pressure (macOS)
memory_pressure -l                          # output: warn, critical, normal

# 4. Ollama logs (which models are loading/unloading)
tail -f ~/.ollama/logs/server.log
# or via brew:
log show --predicate 'process == "ollama"' --last 5m

# 5. RAM-by-process
ps -A -o pid,rss,comm | sort -nr -k2 | head -10
# RSS in KB; ollama serve typically 5–8 GB when warm
```

## Diagnostic Test

```bash
# Baseline: nothing loaded
curl -s http://localhost:11434/api/generate \
  -d '{"model":"qwen2.5:7b","keep_alive":0}' > /dev/null
sleep 2

# Cold call — record TTFT
time curl -s http://localhost:11434/v1/chat/completions \
  -d '{"model":"qwen2.5:7b-instruct-q4_K_M",
       "messages":[{"role":"user","content":"hi"}],
       "stream":false}' > /dev/null
# Expect 5–15s on first hit

# Warm call
time curl -s http://localhost:11434/v1/chat/completions \
  -d '{"model":"qwen2.5:7b-instruct-q4_K_M",
       "messages":[{"role":"user","content":"hi"}],
       "stream":false}' > /dev/null
# Expect 0.5–2s

# Force load 2nd model
curl -s http://localhost:11434/v1/chat/completions \
  -d '{"model":"llama3.1:8b-instruct-q4_K_M",
       "messages":[{"role":"user","content":"hi"}]}' > /dev/null

# Both loaded?
curl -s http://localhost:11434/api/ps | jq '.models[].name'
# If only one shows up → MAX_LOADED_MODELS=1 evicted Qwen → that's a cold-load next call

# Now Qwen call again
time curl -s http://localhost:11434/v1/chat/completions \
  -d '{"model":"qwen2.5:7b-instruct-q4_K_M","messages":[{"role":"user","content":"hi"}]}' > /dev/null
# If 5–15s → eviction happened. Expected behavior with MAX_LOADED_MODELS=1.
```

## Root Causes + Fixes

### A. Eval judge left Llama loaded

```bash
# Symptom: /api/ps shows llama3.1; serving is slow
curl -X POST http://localhost:11434/api/generate \
  -d '{"model":"llama3.1:8b-instruct-q4_K_M","keep_alive":0}'
# Then warm Qwen
curl -X POST http://localhost:11434/v1/chat/completions \
  -d '{"model":"qwen2.5:7b-instruct-q4_K_M","messages":[{"role":"user","content":"warmup"}]}'
```

Long-term fix: ensure judge runner ALWAYS unloads (see patterns/on-demand-model-load.md). Wrap in `try/finally`.

### B. `OLLAMA_MAX_LOADED_MODELS` set too high

```bash
launchctl getenv OLLAMA_MAX_LOADED_MODELS
# If > 1 on a 16 GB Mac:
launchctl setenv OLLAMA_MAX_LOADED_MODELS 1
brew services restart ollama
```

### C. `OLLAMA_KEEP_ALIVE` too long across model swaps

If demo and eval interleave, a long keep_alive on Llama prevents Qwen from re-loading promptly. Use per-request override (`extra_body={"keep_alive": "0"}` in eval).

### D. Docker Desktop memory too high

Docker Desktop allocating 12 GB on a 16 GB Mac leaves only 4 GB for macOS + Ollama. Lower to 8 GB.

```text
Docker Desktop → Settings → Resources → Memory: 8 GB
```

### E. Background apps eating RAM

Browser, Slack, IDEs each take 2–5 GB. For demo runs, close non-essentials. Verify:

```bash
top -o mem
```

## Prevention Checklist

```text
[ ] OLLAMA_MAX_LOADED_MODELS=1
[ ] OLLAMA_KEEP_ALIVE=30m for serving
[ ] Eval scripts always end with explicit unload
[ ] Docker Desktop memory ≤ 8 GB on a 16 GB Mac
[ ] Pre-warm script in `make seed-models` followed by `make demo`
[ ] Monitoring panel "loaded models" via /api/ps in cluster-health dashboard (v1.1)
```

## Recovery Recipe (panic mode mid-demo)

```bash
# Nuke everything from RAM
for m in $(curl -s http://localhost:11434/api/ps | jq -r '.models[].name'); do
  curl -X POST http://localhost:11434/api/generate -d "{\"model\":\"$m\",\"keep_alive\":0}"
done

# Restart Ollama (last resort)
brew services restart ollama
sleep 5

# Pre-warm
curl -s http://localhost:11434/v1/chat/completions \
  -d '{"model":"qwen2.5:7b-instruct-q4_K_M","messages":[{"role":"user","content":"warmup"}]}' > /dev/null
```

## See Also

- concepts/keep-alive-and-cold-load.md — `keep_alive` + `/api/ps` reference
- concepts/macos-metal-serving.md — RAM math
- patterns/on-demand-model-load.md — judge rotation pattern
