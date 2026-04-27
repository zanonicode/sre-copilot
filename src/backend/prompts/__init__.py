import pathlib

from jinja2 import Environment, FileSystemLoader

_HERE = pathlib.Path(__file__).parent
_env = Environment(
    loader=FileSystemLoader(str(_HERE)),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)

_HDFS_FEW_SHOT = (_HERE / "few_shots" / "hdfs_datanode.txt").read_text()
_PM_FEW_SHOT = (_HERE / "few_shots" / "cloudflare_pm.txt").read_text()


def _split_few_shot(raw: str) -> tuple[str, str]:
    parts = raw.split("ANALYSIS:", 1)
    logs_part = parts[0].replace("LOGS:", "").strip()
    analysis_part = parts[1].strip() if len(parts) > 1 else ""
    return logs_part, analysis_part


_HDFS_LOGS, _HDFS_ANALYSIS = _split_few_shot(_HDFS_FEW_SHOT)


def render_log_analyzer(log_payload: str, context: str | None = None) -> str:
    tmpl = _env.get_template("log_analyzer.j2")
    return tmpl.render(
        few_shot_hdfs_logs=_HDFS_LOGS,
        few_shot_hdfs_analysis=_HDFS_ANALYSIS,
        user_logs=log_payload,
        context=context,
    )


def render_postmortem(log_analysis: dict, timeline: list | None, context: str | None) -> str:
    import json as _json
    tmpl = _env.get_template("postmortem.j2")
    return tmpl.render(
        few_shot_postmortem=_PM_FEW_SHOT,
        log_analysis=_json.dumps(log_analysis, indent=2),
        timeline=_json.dumps(timeline, indent=2) if timeline else None,
        context=context,
    )
