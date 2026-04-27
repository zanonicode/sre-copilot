"""
Long-log chunking strategy for Qwen 2.5 7B.

Decision thresholds (per DESIGN §9.1):
  ≤6,000 tokens  → single-pass (common demo path)
  6,001–18,000   → summarize-then-analyze (map + single analyze pass)
  >18,000        → map-reduce (per-chunk analysis + merge pass)
"""

import tiktoken

_enc = tiktoken.get_encoding("cl100k_base")

SINGLE_PASS_LIMIT = 6_000
SUMMARIZE_LIMIT = 18_000
CHUNK_SIZE = 4_000


def count_tokens(text: str) -> int:
    return len(_enc.encode(text))


def chunk_text(text: str, max_tokens: int = CHUNK_SIZE) -> list[str]:
    lines = text.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for line in lines:
        line_tokens = count_tokens(line)
        if current_tokens + line_tokens > max_tokens and current:
            chunks.append("\n".join(current))
            current = [line]
            current_tokens = line_tokens
        else:
            current.append(line)
            current_tokens += line_tokens
    if current:
        chunks.append("\n".join(current))
    return chunks


def select_strategy(log_payload: str) -> str:
    """Return 'single', 'summarize', or 'map_reduce'."""
    n = count_tokens(log_payload)
    if n <= SINGLE_PASS_LIMIT:
        return "single"
    if n <= SUMMARIZE_LIMIT:
        return "summarize"
    return "map_reduce"
