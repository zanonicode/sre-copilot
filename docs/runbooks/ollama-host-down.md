# Runbook: Ollama Host Process Down

**Symptom:** Backend pods return 503 with `{"code":"ollama_unreachable","message":"LLM backend is unavailable"}`. The Grafana "Live LLM Activity" panel shows zero active requests and no token throughput. Tempo traces show a failed `ollama.host_call` span.

**Root cause:** The Ollama process on the host machine stopped (crash, manual kill, or host sleep/hibernation).

---

## Immediate Triage

```bash
# 1. Confirm Ollama is not responding on the host
curl -sf http://localhost:11434/ || echo "Ollama not reachable"

# 2. Check if the process is running at all
pgrep -l ollama || echo "Ollama process not found"

# 3. Confirm the ExternalName Service resolves
kubectl exec -n sre-copilot deploy/backend -- \
  curl -sf http://ollama.sre-copilot.svc.cluster.local:11434/ \
  && echo "Service resolves" || echo "Service does not resolve"
```

---

## Resolution

### Step 1: Restart Ollama

```bash
ollama serve &
```

Wait 3–5 seconds for the process to bind to port 11434.

### Step 2: Verify the model is loaded

```bash
ollama list
# Expected output includes:
# qwen2.5:7b-instruct-q4_K_M   (primary model)
# llama3.1:8b-instruct-q4_K_M  (judge model — only needed for eval)
```

If the model is absent (silent pull failure — see [Known Environmental Gotchas §11.3](../.claude/sdd/features/DESIGN_sre-copilot.md)):

```bash
until ollama pull qwen2.5:7b-instruct-q4_K_M; do
  echo "pull incomplete — retrying in 5s"
  sleep 5
done
```

### Step 3: Warm the model

The first inference after a cold load can take 10–15s. Issue a warm-up request:

```bash
curl -sf http://localhost:11434/api/generate \
  -d '{"model":"qwen2.5:7b-instruct-q4_K_M","prompt":"ping","stream":false}' \
  | jq .done
# Expected: true
```

### Step 4: Verify backend recovery

```bash
kubectl exec -n sre-copilot deploy/backend -- \
  curl -sf http://ollama.sre-copilot.svc.cluster.local:11434/ \
  && echo "Backend → Ollama: OK"

# Then confirm a live request works
curl -sf -X POST http://localhost:8000/analyze/logs \
  -H 'Content-Type: application/json' \
  -d '{"log_payload":"ERROR DataNode blk_123 replication failed"}' \
  | head -c 200
```

---

## Prevention

Keep Ollama alive across sessions:

```bash
# In your .zshrc / .bashrc — start Ollama automatically on login
ollama serve &> /tmp/ollama.log &
```

Or use a launchd plist on macOS to manage the process lifecycle:

```xml
<!-- ~/Library/LaunchAgents/com.ollama.server.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.ollama.server</string>
  <key>ProgramArguments</key>
  <array><string>/usr/local/bin/ollama</string><string>serve</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/ollama.log</string>
  <key>StandardErrorPath</key><string>/tmp/ollama.err</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.ollama.server.plist
```

---

## Related

- [ADR-003: Ollama on host via ExternalName Service](../adr/0003-ollama-externalname.md)
- AT-007: Ollama unreachable → 503 + structured error + trace span
