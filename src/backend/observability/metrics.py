from opentelemetry.metrics import get_meter

m = get_meter("sre_copilot.backend")

LLM_TTFT = m.create_histogram(
    "llm.ttft_seconds", unit="s",
    description="Time to first token from Ollama",
)
LLM_RESPONSE = m.create_histogram(
    "llm.response_seconds", unit="s",
    description="Full LLM response time",
)
LLM_OUTPUT_TOKENS = m.create_counter("llm.tokens_output_total")
LLM_INPUT_TOKENS = m.create_counter("llm.tokens_input_total")
LLM_ACTIVE = m.create_up_down_counter("llm.active_requests")
