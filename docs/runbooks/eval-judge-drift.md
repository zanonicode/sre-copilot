# Runbook: Eval Judge Drift (Layer-2 Pass Rate Falling)

**Symptom:** The nightly eval job (`.github/workflows/nightly-eval.yml`) reports `root_cause_match_rate < 0.80`. The latest `datasets/eval/judge_runs/<timestamp>.json` shows the rate falling below the 80% threshold (AT-011).

**Root causes:**
- Prompt template changed without updating ground-truth records.
- Qwen model version changed (different default behavior under the same tag).
- Ground-truth labels are too narrow (the judge scores correct-but-different analyses as misses).
- Llama judge model version changed (different scoring behavior).
- A new batch of ground-truth records was added with systematically harder cases.

---

## Immediate Triage

### Step 1: Read the latest judge run

```bash
# Find the latest run
LATEST=$(ls -t datasets/eval/judge_runs/*.json | head -1)
cat "$LATEST" | python3 -m json.tool

# Summary fields to check:
# - root_cause_match_rate  (must be >= 0.80)
# - evaluated              (should equal number of .json files in ground_truth/)
# - skipped                (non-zero means backend or payload issues)
# - results[]              (per-incident breakdown with rationale)
```

### Step 2: Identify the failing incidents

```bash
cat "$LATEST" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for r in data['results']:
    if r['root_cause_match'] == 0:
        print(f\"FAIL: {r['id']} — {r['rationale']}\")
"
```

### Step 3: Manually re-evaluate the failing incidents

Run the failing incidents through the analyzer manually and compare against ground truth:

```bash
# Pull the ground truth for a failing incident
cat datasets/eval/ground_truth/<incident-id>.json | python3 -m json.tool

# Run the analyzer on its log_payload
LOG=$(cat datasets/eval/ground_truth/<incident-id>.json | python3 -c \
  "import json,sys; print(json.load(sys.stdin)['log_payload'])")

curl -sf -X POST http://localhost:8000/analyze/logs \
  -H 'Content-Type: application/json' \
  -d "{\"log_payload\": $(echo $LOG | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" \
  | python3 -c "
import json,sys
acc=''
for line in sys.stdin:
    if line.startswith('data: '):
        e=json.loads(line[6:])
        if e.get('type')=='delta': acc+=e.get('token','')
        elif e.get('type')=='done': break
print(json.dumps(json.loads(acc), indent=2))
"
```

---

## Resolution

### Case 1: Prompt template changed (most common)

If the prompt template (`src/backend/prompts/log_analyzer.j2`) was updated, the model's output format may have shifted. The ground-truth `root_cause` field may now be expressed differently than the candidate produces.

**Fix:** Update the ground-truth records to reflect the new canonical output shape, or tighten the rubric to be more lenient on paraphrase.

```bash
# Update a ground truth record
vi datasets/eval/ground_truth/<incident-id>.json
```

### Case 2: Ground-truth labels are too narrow

The judge scores a factually correct analysis as a miss because the candidate uses different words than the ground truth.

**Fix:** Loosen the ground-truth `root_cause` field to describe the causal mechanism rather than a specific phrase. The rubric says "paraphrase is acceptable; the causal mechanism must match."

### Case 3: Judge model behavior changed

If `llama3.1:8b-instruct-q4_K_M` was updated via `ollama pull`, its scoring behavior may have shifted. Check:

```bash
# What version of Llama is installed?
ollama show llama3.1:8b-instruct-q4_K_M | grep -i digest
```

**Fix:** If the new judge is systematically stricter, run a Layer-3 manual spot-check (5 cases from the failing set) to calibrate. If the human manual pass rate is above 80% for the same incidents the judge fails, the judge has drifted — open an issue to consider updating the rubric or pinning the judge model tag.

### Case 4: Qwen model version changed

```bash
ollama show qwen2.5:7b-instruct-q4_K_M | grep -i digest
```

If the model was updated, run a fresh candidate batch and compare with historical judge runs. If the pass rate dropped suddenly coinciding with a model update, the new model may produce different output structure. Check `hallucination` scores — if they increased, the new model may be hallucinating more.

---

## Escalation: API Judge Waiver

Per ADR-004, if Llama-judge agreement with humans falls below 80% over **2 consecutive nightly runs**, escalate to the project owner for an API-judge waiver. The waiver allows temporarily using an external LLM (Claude or GPT-4) as the judge, breaking NFR6 but restoring eval signal.

```bash
# Check last 2 run results
ls -t datasets/eval/judge_runs/*.json | head -2 | xargs -I{} \
  python3 -c "
import json, sys
data = json.load(open('{}'))
print(f\"{data['timestamp'][:10]}: {data['root_cause_match_rate']:.0%} ({'PASS' if data['passed'] else 'FAIL'})\")
"
```

---

## Verification After Fix

Re-run the judge locally:

```bash
# Start the backend if not running
OLLAMA_BASE_URL=http://localhost:11434/v1 \
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
PYTHONPATH=src python -m uvicorn backend.main:app --port 8000 &

# Run the judge
BACKEND_URL=http://localhost:8000 \
PYTHONPATH=src python tests/eval/judge/run_judge.py

# Check the result
ls -t datasets/eval/judge_runs/*.json | head -1 | xargs python3 -m json.tool | grep root_cause_match_rate
```

---

## Related

- AT-011: Layer-2 Llama judge ≥80% root-cause match on held-out set
- [ADR-004: Hybrid eval strategy](../adr/0004-hybrid-eval-strategy.md)
- [docs/eval/manual_checklist.md](../eval/manual_checklist.md)
- `.github/workflows/nightly-eval.yml`
