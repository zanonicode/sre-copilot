# Layer-3 Manual Eval Checklist

**Cadence:** Once per sprint, ~30 minutes. Run against the live cluster after `make up`.

**Purpose:** Calibrate the Llama judge (Layer 2) against human judgment. If human pass rate is consistently above 80% for cases the judge fails, the judge rubric needs updating. If human pass rate matches the judge's failure rate, the analyzer prompt needs work.

**Record results in:** `datasets/eval/judge_runs/manual_<YYYY-MM-DD>.json`

---

## Pre-Checklist Setup

```bash
# Ensure cluster is up
make smoke

# Port-forward backend (if not already accessible)
kubectl port-forward -n sre-copilot deploy/backend 8000:8000 &

# Open Grafana (optional — for trace verification)
kubectl port-forward -n observability svc/grafana 3001:80 &
```

---

## Cases to Evaluate (5 per sprint)

Select 5 cases from `datasets/eval/ground_truth/`. Include:
- At least 2 HDFS incidents (`hdfs_*.json`)
- At least 1 synthetic backend incident (`synth_*.json`)
- At least 1 case that the nightly judge failed most recently

For each case, run the analyzer and score manually using the rubric below.

---

## Rubric Reference (from `tests/eval/judge/rubric.yaml`)

| Dimension | Score | Pass Criterion |
|-----------|-------|----------------|
| root_cause_match | 0 or 1 | 1 = same underlying failure; paraphrase OK |
| remediation_soundness | 0–3 | ≥2 = mostly correct |
| hallucination | 0 or 1 | 0 = no invented facts |

**Aggregate pass:** root_cause_match == 1 on ≥4 of 5 cases (80%).

---

## Per-Case Evaluation Sheet

Copy this block 5 times (once per case):

```
### Case: <incident_id>

Ground truth file: datasets/eval/ground_truth/<incident_id>.json

Ground truth root_cause:
  (paste from file)

Analyzer output root_cause:
  (paste from live response)

root_cause_match:  [ ] 0  [ ] 1
  Notes:

Analyzer runbook steps:
  (paste list)

remediation_soundness:  [ ] 0  [ ] 1  [ ] 2  [ ] 3
  Notes:

hallucination detected?  [ ] 0 (none)  [ ] 1 (yes)
  If yes, what was hallucinated:

Overall: [ ] PASS  [ ] FAIL
```

---

## How to Run the Analyzer for a Case

```bash
# Get the log_payload from a ground truth file
LOG_PAYLOAD=$(python3 -c "
import json
gt = json.load(open('datasets/eval/ground_truth/hdfs_001.json'))
print(gt['log_payload'])
")

# Submit to the analyzer
curl -sf -X POST http://localhost:8000/analyze/logs \
  -H 'Content-Type: application/json' \
  -d "$(python3 -c "import json; print(json.dumps({'log_payload': open('datasets/eval/ground_truth/hdfs_001.json').read()}))")" \
  | python3 -c "
import json, sys
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

## Recording Results

After all 5 cases, record your results:

```bash
cat > datasets/eval/judge_runs/manual_$(date +%Y-%m-%d).json << 'EOF'
{
  "type": "manual",
  "evaluator": "<your name>",
  "date": "<YYYY-MM-DD>",
  "cases_evaluated": 5,
  "root_cause_match_rate": <0.0-1.0>,
  "passed": <true|false>,
  "notes": "<any observations about the judge rubric or analyzer output>",
  "cases": [
    {
      "id": "<incident_id>",
      "root_cause_match": <0|1>,
      "remediation_soundness": <0-3>,
      "hallucination": <0|1>,
      "judge_agreed": <true|false>
    }
  ]
}
EOF
```

---

## Calibration Action

| Human pass rate | Judge pass rate | Action |
|-----------------|-----------------|--------|
| ≥80% | ≥80% | No action needed |
| ≥80% | <80% | Judge is too strict — review rubric; may need to loosen root_cause_match criterion |
| <80% | <80% | Analyzer needs prompt work — review failing cases, update prompt template |
| <80% | ≥80% | Judge is too lenient — tighten rubric |

If judge–human agreement diverges for 2 consecutive sprints, escalate to project owner (see [eval-judge-drift runbook](../runbooks/eval-judge-drift.md)).

---

## Sprint Checklist

- [ ] `make smoke` passes before starting
- [ ] 5 cases selected (≥2 HDFS, ≥1 synthetic, ≥1 recent judge failure)
- [ ] All 5 cases manually scored
- [ ] Results JSON written to `datasets/eval/judge_runs/manual_<date>.json`
- [ ] Judge calibration table checked — action taken if needed
- [ ] Results committed: `git add datasets/eval/judge_runs/ && git commit -m "eval: Layer-3 manual checklist <date>"`
