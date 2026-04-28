# On-Demand Model Load (Eval Judge)

> **Purpose**: Load Llama 3.1 8B only for the eval-judge run, then unload immediately so the serving model (Qwen 2.5 7B) doesn't get evicted from RAM
> **MCP Validated**: 2026-04-26

## When to Use

- DESIGN §4.12 / Sprint 4 entry #45 (`tests/eval/judge/`)
- Any time a transient large-model task runs alongside the steady serving model

## The Problem

- 16 GB Mac, both models loaded = swap thrash (concepts/macos-metal-serving.md).
- Default `OLLAMA_KEEP_ALIVE=5m` means a single judge call leaves Llama in RAM for 5 minutes — long enough to evict Qwen on the next request.

## The Pattern

```text
1. Snapshot what's currently loaded
2. Pre-call: ensure judge model is on disk (pull if missing)
3. Run all judge calls back-to-back, with keep_alive: -1 (hold for batch)
4. Post-call: explicit unload via keep_alive: 0
5. Re-warm Qwen if it was evicted
```

## Implementation

```python
# tests/eval/judge/run_judge.py  (mirrors DESIGN §4.12 with rotation logic)
import json
import pathlib
import time
from datetime import datetime
from openai import OpenAI

OLLAMA_BASE_URL = "http://localhost:11434"
JUDGE_MODEL = "llama3.1:8b-instruct-q4_K_M"
SERVING_MODEL = "qwen2.5:7b-instruct-q4_K_M"

JUDGE = OpenAI(base_url=f"{OLLAMA_BASE_URL}/v1", api_key="ollama")

import requests

def loaded_models() -> set[str]:
    r = requests.get(f"{OLLAMA_BASE_URL}/api/ps", timeout=5)
    return {m["name"] for m in r.json().get("models", [])}

def ensure_pulled(model: str):
    r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
    have = {m["name"] for m in r.json().get("models", [])}
    if model not in have:
        # Streaming pull
        with requests.post(f"{OLLAMA_BASE_URL}/api/pull",
                           json={"name": model}, stream=True, timeout=600) as resp:
            for line in resp.iter_lines():
                if line: print(line.decode())

def unload(model: str):
    requests.post(f"{OLLAMA_BASE_URL}/api/generate",
                  json={"model": model, "keep_alive": 0}, timeout=10)

def warm(model: str):
    JUDGE.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "warmup"}],
        max_tokens=1,
        extra_body={"keep_alive": "30m"},
    )

def score_one(gt: dict, cand: dict, rubric: str) -> dict:
    PROMPT = f"""You are an SRE eval judge...
GROUND TRUTH: {json.dumps(gt)}
CANDIDATE:    {json.dumps(cand)}
Respond as STRICT JSON: {{"root_cause_match":0|1,"remediation_soundness":0..3,"hallucination":0|1,"rationale":"<≤200 chars>"}}
"""
    resp = JUDGE.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": PROMPT}],
        response_format={"type": "json_object"},
        temperature=0.0,
        extra_body={"keep_alive": "-1"},      # hold across the batch
    )
    return json.loads(resp.choices[0].message.content)


def main():
    pre_loaded = loaded_models()
    print(f"Pre-run loaded: {pre_loaded}")

    # 1. Ensure judge model on disk
    ensure_pulled(JUDGE_MODEL)

    # 2. Unload serving model BEFORE loading judge (avoid simultaneous)
    if SERVING_MODEL in pre_loaded:
        print(f"Unloading {SERVING_MODEL} to free RAM for judge")
        unload(SERVING_MODEL)
        time.sleep(2)

    # 3. Run all judge scores
    gts = sorted(pathlib.Path("datasets/eval/ground_truth").glob("*.json"))
    cands = pathlib.Path("datasets/eval/candidate_runs/latest")
    rubric = pathlib.Path("tests/eval/judge/rubric.yaml").read_text()

    results = []
    for gt_path in gts:
        gt = json.loads(gt_path.read_text())
        cand = json.loads((cands / gt_path.name).read_text())
        results.append({"id": gt_path.stem, **score_one(gt, cand, rubric)})

    # 4. CRITICAL: unload judge before exiting
    print(f"Unloading {JUDGE_MODEL}")
    unload(JUDGE_MODEL)

    # 5. Re-warm serving model if it was running before
    if SERVING_MODEL in pre_loaded:
        print(f"Re-warming {SERVING_MODEL}")
        warm(SERVING_MODEL)

    # Persist results
    out = pathlib.Path(f"datasets/eval/judge_runs/{datetime.utcnow():%Y%m%dT%H%M%S}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "results": results,
        "root_cause_match_rate": sum(r["root_cause_match"] for r in results) / len(results),
    }, indent=2))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
```

## Configuration

| Setting | Why |
|---------|-----|
| `keep_alive: "-1"` during batch | Hold judge across all 10 ground-truth scorings |
| `keep_alive: 0` after batch | Force unload — guarantees serving model can re-warm |
| `temperature=0.0` | Judge should be deterministic |
| `OLLAMA_MAX_LOADED_MODELS=1` (host) | Belt-and-suspenders; OS-level cap |

## CI Wiring (nightly)

```yaml
# .github/workflows/nightly-eval.yml — entry #46
name: Nightly Eval
on:
  schedule: [{ cron: "0 7 * * *" }]
jobs:
  eval:
    runs-on: [self-hosted, mac, m-series]   # needs Metal
    steps:
      - uses: actions/checkout@v4
      - run: ollama pull qwen2.5:7b-instruct-q4_K_M
      - run: ollama pull llama3.1:8b-instruct-q4_K_M
      - run: make demo &           # generate fresh candidates
      - run: sleep 60
      - run: python tests/eval/judge/run_judge.py
      - run: |
          rate=$(jq -r '.root_cause_match_rate' datasets/eval/judge_runs/*.json | tail -1)
          python -c "import sys; sys.exit(0 if float('$rate') >= 0.8 else 1)"
```

## Verification

```bash
# Before
curl -s localhost:11434/api/ps | jq '.models[].name'
# qwen2.5:7b-instruct-q4_K_M

python tests/eval/judge/run_judge.py

# After (judge gone, serving back)
curl -s localhost:11434/api/ps | jq '.models[].name'
# qwen2.5:7b-instruct-q4_K_M
```

## See Also

- concepts/keep-alive-and-cold-load.md — load/unload mechanics
- concepts/model-selection.md — why Qwen + Llama specifically
- patterns/model-rotation-debugging.md — what swap-thrash looks like
