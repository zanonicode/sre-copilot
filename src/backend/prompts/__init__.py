import os
import pathlib

from jinja2 import Environment, FileSystemLoader

_HERE = pathlib.Path(__file__).parent
_env = Environment(
    loader=FileSystemLoader(str(_HERE)),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)

# Failure-injection hook: load an alternate Jinja2 template at runtime.
# Default empty = use the bundled log_analyzer.j2. Used by
# `make demo-canary-bad-prompt` to demo the LLM-judge gate catching a
# semantically-regressed prompt that operational metrics would let through.
_ANALYZE_PROMPT_PATH = os.getenv("ANALYZE_PROMPT_TEMPLATE_PATH", "")
_ANALYZE_PROMPT_HINT = os.getenv("ANALYZE_PROMPT_OVERRIDE_HINT", "")

# Schema override hints injected into the prompt to make the LLM emit a
# regressed shape. Used by `make demo-canary-bad-schema`.
_SCHEMA_OVERRIDES = {
    "regressed_v1": (
        "\n\nOVERRIDE: emit `summary_v1` instead of `root_cause` at the top "
        "level of the JSON. Do NOT include `root_cause` in the output."
    ),
}

_HDFS_FEW_SHOT = (_HERE / "few_shots" / "hdfs_datanode.txt").read_text()
_PM_FEW_SHOT = (_HERE / "few_shots" / "cloudflare_pm.txt").read_text()


def _split_few_shot(raw: str) -> tuple[str, str]:
    parts = raw.split("ANALYSIS:", 1)
    logs_part = parts[0].replace("LOGS:", "").strip()
    analysis_part = parts[1].strip() if len(parts) > 1 else ""
    return logs_part, analysis_part


_HDFS_LOGS, _HDFS_ANALYSIS = _split_few_shot(_HDFS_FEW_SHOT)


def render_log_analyzer(
    log_payload: str,
    context: str | None = None,
    schema_override: str = "",
) -> str:
    if _ANALYZE_PROMPT_PATH and pathlib.Path(_ANALYZE_PROMPT_PATH).is_file():
        raw = pathlib.Path(_ANALYZE_PROMPT_PATH).read_text()
        rendered = Environment(autoescape=False).from_string(raw).render(
            few_shot_hdfs_logs=_HDFS_LOGS,
            few_shot_hdfs_analysis=_HDFS_ANALYSIS,
            user_logs=log_payload,
            context=context,
            override_hint=_ANALYZE_PROMPT_HINT,
        )
    else:
        tmpl = _env.get_template("log_analyzer.j2")
        rendered = tmpl.render(
            few_shot_hdfs_logs=_HDFS_LOGS,
            few_shot_hdfs_analysis=_HDFS_ANALYSIS,
            user_logs=log_payload,
            context=context,
        )
        if _ANALYZE_PROMPT_HINT:
            rendered = f"HINT: {_ANALYZE_PROMPT_HINT}\n\n{rendered}"

    if schema_override and schema_override in _SCHEMA_OVERRIDES:
        rendered = rendered + _SCHEMA_OVERRIDES[schema_override]
    return rendered


def render_postmortem(log_analysis: dict, timeline: list | None, context: str | None) -> str:
    import json as _json
    tmpl = _env.get_template("postmortem.j2")
    return tmpl.render(
        few_shot_postmortem=_PM_FEW_SHOT,
        log_analysis=_json.dumps(log_analysis, indent=2),
        timeline=_json.dumps(timeline, indent=2) if timeline else None,
        context=context,
    )
