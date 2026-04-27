"""Layer-2 Llama-judge evaluation runner (AT-011).

Loads ground-truth records from datasets/eval/ground_truth/*.json,
asks the backend to analyze the associated log payload, then asks
Llama 3.1 8B (via Ollama) to score the candidate output against the
ground truth using the rubric in rubric.yaml.

Writes results to datasets/eval/judge_runs/<timestamp>.json.
Exits with code 1 if root_cause_match_rate < 0.80.

Usage:
    # With a live cluster (default):
    python tests/eval/judge/run_judge.py

    # With an override backend URL:
    BACKEND_URL=http://localhost:8000 python tests/eval/judge/run_judge.py

    # Point at a different Ollama endpoint:
    OLLAMA_BASE_URL=http://localhost:11434/v1 python tests/eval/judge/run_judge.py

Environment variables:
    BACKEND_URL         Backend API base URL (default: http://localhost:8000)
    OLLAMA_BASE_URL     Ollama OpenAI-compatible base URL (default: http://localhost:11434/v1)
    LLM_JUDGE_MODEL     Ollama model for judging (default: llama3.1:8b-instruct-q4_K_M)
    JUDGE_PASS_THRESHOLD Root-cause-match rate threshold (default: 0.80)
    SKIP_JUDGE          Set to 1 to skip judge entirely (noop exit 0)
"""
import json
import os
import pathlib
import sys
from datetime import datetime, timezone

import httpx
from openai import OpenAI


GROUND_TRUTH_DIR = pathlib.Path("datasets/eval/ground_truth")
JUDGE_RUNS_DIR = pathlib.Path("datasets/eval/judge_runs")
RUBRIC = pathlib.Path("tests/eval/judge/rubric.yaml").read_text()

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
LLM_JUDGE_MODEL = os.environ.get("LLM_JUDGE_MODEL", "llama3.1:8b-instruct-q4_K_M")
JUDGE_PASS_THRESHOLD = float(os.environ.get("JUDGE_PASS_THRESHOLD", "0.80"))
# JUDGE_SAMPLE_SIZE: cap how many ground-truth records to evaluate.
# CI sets this to 6 (≈35min wall time on ubuntu-latest); unset = full corpus.
# Sampling is deterministic (sorted alphabetically, take first N) so re-runs
# grade the same records and pass-rate trends are comparable across runs.
JUDGE_SAMPLE_SIZE = int(os.environ["JUDGE_SAMPLE_SIZE"]) if os.environ.get("JUDGE_SAMPLE_SIZE") else None

JUDGE = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")

JUDGE_PROMPT = """You are an SRE eval judge. Score the CANDIDATE analysis against
the GROUND TRUTH using this rubric:

{rubric}

CRITICAL SCORING RULES — read carefully:

1. root_cause_match is SEMANTIC, not literal. The ground-truth
   `root_cause_keywords` list contains EXAMPLE phrasings — they are hints,
   NOT a list of substrings that must appear verbatim in the candidate.
   Score 1 if the candidate describes the same underlying causal mechanism,
   even if the vocabulary differs. Score 0 only if the candidate identifies
   a fundamentally different cause.

2. Examples of semantic matches that should score root_cause_match=1:
   - GT keyword "heap exhaustion" ↔ candidate says "insufficient JVM heap"
     (same mechanism: heap too small for working set)
   - GT keyword "DataNode registration failure" ↔ candidate says "DataNode
     could not register with NameNode" (same mechanism)
   - GT keyword "OOM" ↔ candidate says "OutOfMemoryError" or "process killed
     by OOMKiller" (same mechanism)

3. Examples that should score root_cause_match=0 (genuine mismatch):
   - GT keyword "DataNode registration failure" but candidate says only
     "ephemeral port exhaustion" (port exhaustion is a possible CAUSE
     of registration failure but is not itself the failure mode the log
     shows; reading the log literally is required).
   - GT keyword "memory leak" but candidate says "CPU spike" (different
     resource, different mechanism).

4. hallucination=1 ONLY if the candidate invents facts not supported by
   the log (wrong hostnames, fabricated error codes, services not in the
   logs). Using different vocabulary is NOT hallucination.

GROUND TRUTH:
{ground_truth}

CANDIDATE:
{candidate}

Respond as STRICT JSON with exactly these keys:
{{
  "root_cause_match": 0 or 1,
  "remediation_soundness": 0 to 3,
  "hallucination": 0 or 1,
  "rationale": "<concise explanation, max 200 chars>"
}}
"""


def fetch_candidate(log_payload: str) -> dict | None:
    try:
        chunks = []
        with httpx.stream(
            "POST",
            f"{BACKEND_URL}/analyze/logs",
            json={"log_payload": log_payload},
            timeout=120.0,
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line.startswith("data: "):
                    continue
                evt = json.loads(line.removeprefix("data: "))
                if evt.get("type") == "delta":
                    chunks.append(evt.get("token", ""))
                elif evt.get("type") == "done":
                    break
        accumulated = "".join(chunks)
        return json.loads(accumulated)
    except Exception as exc:
        print(f"  WARNING: failed to fetch candidate — {exc}", file=sys.stderr)
        return None


def score_one(ground_truth: dict, candidate: dict) -> dict:
    resp = JUDGE.chat.completions.create(
        model=LLM_JUDGE_MODEL,
        messages=[
            {
                "role": "user",
                "content": JUDGE_PROMPT.format(
                    rubric=RUBRIC,
                    ground_truth=json.dumps(ground_truth, indent=2),
                    candidate=json.dumps(candidate, indent=2),
                ),
            }
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    return json.loads(resp.choices[0].message.content)


def main() -> int:
    if os.environ.get("SKIP_JUDGE") == "1":
        print("SKIP_JUDGE=1 — skipping Layer-2 judge evaluation.")
        return 0

    # Ensure output dir exists early so the CI commit step never trips over a
    # missing path even on hard-fail runs.
    JUDGE_RUNS_DIR.mkdir(parents=True, exist_ok=True)

    gt_paths = sorted(GROUND_TRUTH_DIR.glob("*.json"))
    if not gt_paths:
        print(f"ERROR: no ground-truth files in {GROUND_TRUTH_DIR}", file=sys.stderr)
        return 1

    total_records = len(gt_paths)
    if JUDGE_SAMPLE_SIZE and JUDGE_SAMPLE_SIZE < total_records:
        # Stratify by filename prefix (e.g., hdfs_, synth_) so each category
        # gets proportional representation. Within each bucket take the first
        # alphabetically — keeps sampling deterministic across runs.
        buckets: dict[str, list] = {}
        for p in gt_paths:
            prefix = p.stem.split("_")[0]
            buckets.setdefault(prefix, []).append(p)
        per_bucket = max(1, JUDGE_SAMPLE_SIZE // len(buckets))
        sampled = []
        for prefix, paths in sorted(buckets.items()):
            sampled.extend(paths[:per_bucket])
        gt_paths = sampled[:JUDGE_SAMPLE_SIZE]
        print(f"==> Layer-2 judge: sampled {len(gt_paths)}/{total_records} records "
              f"(JUDGE_SAMPLE_SIZE={JUDGE_SAMPLE_SIZE}, stratified by prefix)")
    else:
        print(f"==> Layer-2 judge: evaluating {total_records} ground-truth records")
    print(f"    judge model : {LLM_JUDGE_MODEL}")
    print(f"    backend url : {BACKEND_URL}")
    print(f"    pass threshold: {JUDGE_PASS_THRESHOLD:.0%}")

    results = []
    skipped = 0

    for gt_path in gt_paths:
        gt = json.loads(gt_path.read_text())
        incident_id = gt_path.stem
        log_payload = gt.get("log_payload") or gt.get("log_snippet", "")

        if not log_payload:
            print(f"  SKIP {incident_id} — no log_payload/log_snippet in ground truth")
            skipped += 1
            continue

        print(f"  Evaluating {incident_id}...")
        candidate = fetch_candidate(log_payload)
        if candidate is None:
            print(f"  SKIP {incident_id} — backend returned no candidate")
            skipped += 1
            continue

        scores = score_one(gt, candidate)
        results.append({
            "id": incident_id,
            "root_cause_match": scores.get("root_cause_match", 0),
            "remediation_soundness": scores.get("remediation_soundness", 0),
            "hallucination": scores.get("hallucination", 1),
            "rationale": scores.get("rationale", ""),
        })
        match_symbol = "PASS" if scores.get("root_cause_match") == 1 else "FAIL"
        print(f"    root_cause_match={scores.get('root_cause_match')} [{match_symbol}]  "
              f"remediation={scores.get('remediation_soundness')}  "
              f"hallucination={scores.get('hallucination')}")

    if not results:
        print("ERROR: all records skipped — cannot compute pass rate", file=sys.stderr)
        return 1

    match_rate = sum(r["root_cause_match"] for r in results) / len(results)
    passed = match_rate >= JUDGE_PASS_THRESHOLD

    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "judge_model": LLM_JUDGE_MODEL,
        "backend_url": BACKEND_URL,
        "pass_threshold": JUDGE_PASS_THRESHOLD,
        "total_records": len(gt_paths),
        "evaluated": len(results),
        "skipped": skipped,
        "root_cause_match_rate": round(match_rate, 4),
        "passed": passed,
        "results": results,
    }

    JUDGE_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out_path = JUDGE_RUNS_DIR / f"{ts}.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\n==> Results written to {out_path}")
    print(f"    root_cause_match_rate: {match_rate:.1%}  "
          f"({'PASS' if passed else 'FAIL'} — threshold {JUDGE_PASS_THRESHOLD:.0%})")

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
