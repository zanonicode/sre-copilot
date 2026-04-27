import tiktoken
from pydantic import BaseModel, Field

_enc = tiktoken.get_encoding("cl100k_base")


class LogAnalysisRequest(BaseModel):
    log_payload: str = Field(min_length=10, max_length=500_000,
                             description="Raw log lines to analyze.")
    context: str | None = Field(default=None, max_length=2_000,
                                description="Optional operator-supplied context.")

    def estimated_tokens(self) -> int:
        return len(_enc.encode(self.log_payload))


class LogAnalysisDelta(BaseModel):
    type: str
    token: str | None = None
    output_tokens: int | None = None
