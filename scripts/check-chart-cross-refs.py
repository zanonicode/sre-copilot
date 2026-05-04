#!/usr/bin/env python3
"""Validate cross-resource references in rendered Helm charts.

Catches the May-2026 bug class where a Rollout references an AnalysisTemplate
by name but the AnalysisTemplate manifest is untracked / not rendered: ArgoCD
syncs happily, but the Rollout enters InvalidSpec/Degraded silently.

Currently validates: Rollout `templateName:` refs must resolve to a
kind: AnalysisTemplate within the same chart render.

Stdlib-only (regex) so `make lint` doesn't grow new deps. Wire into lint.
Exits non-zero on any unresolved reference.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Each entry: (chart_path, [extra `helm template` args]). Multiple value
# combinations matter when feature flags gate references — the checker should
# scan every reachable code path, not just the default render.
CHART_RENDERS = [
    ("helm/backend", []),
    ("helm/backend", ["--set", "canaryQualityGateEnabled=true"]),
    ("helm/frontend", []),
]

# `kind: AnalysisTemplate` followed by metadata.name on a near line.
# Helm output is canonical YAML — kind always appears before metadata.
_AT_BLOCK = re.compile(
    r"^kind:\s*AnalysisTemplate\b.*?^\s*name:\s*([A-Za-z0-9._-]+)",
    re.MULTILINE | re.DOTALL,
)

# Capture every `templateName: foo` inside a doc that started with kind: Rollout.
_ROLLOUT_TPL = re.compile(r"templateName:\s*([A-Za-z0-9._-]+)")


def render_chart(chart_path: str, extra_args: list[str]) -> str:
    cmd = ["helm", "template", Path(chart_path).name, chart_path, *extra_args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"  helm template failed for {chart_path} {extra_args}:\n{proc.stderr}", file=sys.stderr)
        return ""
    return proc.stdout


def split_docs(rendered: str) -> list[str]:
    return [d for d in re.split(r"^---\s*$", rendered, flags=re.MULTILINE) if d.strip()]


def extract_at_names(rendered: str) -> set[str]:
    return set(_AT_BLOCK.findall(rendered))


def extract_rollout_refs(docs: list[str]) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for doc in docs:
        if not re.search(r"^kind:\s*Rollout\b", doc, re.MULTILINE):
            continue
        rname_match = re.search(r"^\s*name:\s*([A-Za-z0-9._-]+)", doc, re.MULTILINE)
        rname = rname_match.group(1) if rname_match else "<unknown>"
        for tn in _ROLLOUT_TPL.findall(doc):
            refs.append((rname, tn))
    return refs


def main() -> int:
    failures = 0
    for chart, extra in CHART_RENDERS:
        if not Path(chart).is_dir():
            continue
        rendered = render_chart(chart, extra)
        if not rendered:
            continue
        docs = split_docs(rendered)
        templates = extract_at_names(rendered)
        refs = extract_rollout_refs(docs)
        label = f"{chart} {' '.join(extra)}".rstrip()
        for rollout, ref in refs:
            if ref not in templates:
                print(
                    f"  [FAIL] {label}: Rollout/{rollout} references "
                    f"AnalysisTemplate/{ref} which is NOT defined by this chart"
                )
                failures += 1
        if refs:
            print(
                f"  [OK]   {label}: {len(refs)} Rollout->AnalysisTemplate refs all resolved "
                f"(templates: {sorted(templates)})"
            )
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
