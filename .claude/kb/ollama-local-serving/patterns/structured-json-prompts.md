# Structured JSON Prompts

> **Purpose**: Combine Ollama's `response_format={"type":"json_object"}` with prompt scaffolding and Pydantic post-validation so the backend reliably gets schema-conformant JSON
> **MCP Validated**: 2026-04-26

## When to Use

- DESIGN §4.10 (log analyzer prompt) and §4.2 (Pydantic schema)
- Any endpoint whose contract requires a fixed JSON shape

## Three Layers of Defense

```text
1. Prompt instructs model to emit STRICT JSON matching schema
2. response_format={"type":"json_object"} forces JSON syntax
3. Pydantic .model_validate() enforces schema; raises on mismatch
```

Layer 2 alone gives valid-JSON output but NOT schema-correct output. Layer 3 is the safety net.

## Prompt Template (Jinja2, DESIGN §4.10)

```jinja
{# src/backend/prompts/log_analyzer.j2 #}
You are an SRE assistant. Analyze the log payload below and produce STRICT JSON
matching this schema (no prose, no markdown):
{
  "severity": "info" | "warning" | "critical",
  "summary": "<one sentence, ≤400 chars>",
  "root_cause": "<concise reasoning>",
  "runbook": ["<step 1>", "<step 2>", ...],
  "related_metrics": ["<promql or metric name>", ...]
}

### Example (HDFS DataNode failure)
LOGS:
{{ few_shot_hdfs_logs }}
ANALYSIS:
{{ few_shot_hdfs_analysis }}

### Now analyze
LOGS:
{{ user_logs }}
{% if context %}CONTEXT: {{ context }}{% endif %}
ANALYSIS:
```

Key elements:

- Schema in the prompt, not just in code (model needs to see it)
- `STRICT JSON` + `no prose, no markdown` — explicit
- One few-shot example — increases compliance dramatically
- Trailing `ANALYSIS:` — the next token starts the output

## SDK Call

```python
resp = await client.chat.completions.create(
    model="qwen2.5:7b-instruct-q4_K_M",
    messages=[{"role": "user", "content": prompt}],
    stream=True,
    response_format={"type": "json_object"},
    temperature=0.2,                         # low for reliability
    max_tokens=1024,
)
```

`temperature=0.2` reduces creativity → fewer schema violations. Don't use 0 — tiny non-determinism actually helps escape local minima.

## Post-Validation (DESIGN §4.2)

```python
# src/backend/schemas/log_analysis.py
from typing import Literal
from pydantic import BaseModel, Field

class LogAnalysis(BaseModel):
    severity: Literal["info", "warning", "critical"]
    summary: str = Field(min_length=10, max_length=400)
    root_cause: str = Field(min_length=10)
    runbook: list[str] = Field(min_length=1, max_length=10)
    related_metrics: list[str] = Field(default_factory=list, max_length=10)
```

Used at the end of streaming:

```python
# After accumulating all delta tokens into `accumulated`
import json
from backend.schemas import LogAnalysis

try:
    parsed = json.loads(accumulated)
    validated = LogAnalysis.model_validate(parsed)
except (json.JSONDecodeError, ValidationError) as e:
    yield await _sse({"type": "error", "code": "schema_violation",
                      "message": str(e)})
```

## Cleanup Hacks (when models misbehave)

Some models occasionally wrap JSON in ```json fences despite instructions. Add a sanitizer:

```python
import re
def strip_fence(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    return s

parsed = json.loads(strip_fence(accumulated))
```

For SRE Copilot Qwen 2.5 7B with the prompt above, fence-wrapping was rare in our testing (<1%). Llama 3.1 was higher (~5%). Always strip defensively.

## Streaming Caveat

When `stream=True`, JSON arrives token-by-token. You CANNOT validate until the stream ends. Two options:

1. Accumulate then validate (most common — what DESIGN §4.1 does).
2. Use a streaming JSON parser (e.g., `ijson`) to emit deltas to the client only after key boundaries — complex; skip for MVP.

For SRE Copilot, the SSE stream is for UX (typewriter effect). The client also accumulates and re-parses at `done` event. Server emits a final structured payload separately if desired.

## Few-shot Curation

The few-shot example is doing 60% of the heavy lifting. Use ONE high-quality, format-perfect example. More examples = more tokens = more cost without quality gains for schema-shape problems.

For SRE Copilot the few-shot is one HDFS DataNode failure (from Loghub dataset) with hand-written perfect analysis JSON.

## Tools Mode (Function Calling) — SKIPPED

Ollama supports `tools` for some models, which gives even stronger schema enforcement. We skip it for SRE Copilot because:

- Not all models support it well (Qwen 2.5 yes, others varied)
- The Pydantic + `json_object` path works reliably
- Tools mode adds API surface area for marginal gain

Document as a v1.1 enhancement.

## Verification

```python
# tests/eval/structural/test_sse_contract.py — DESIGN §4.11 (excerpt)
async def test_sse_emits_valid_final_payload(hdfs_sample):
    ...
    parsed = json.loads(accumulated)
    LogAnalysis.model_validate(parsed)         # raises if FR1 field missing
```

## See Also

- patterns/openai-sdk-streaming.md — full SSE handler
- concepts/openai-compat-api.md — what `response_format` actually does
- DESIGN §4.2, §4.10, §4.11 — schemas + prompt + test
