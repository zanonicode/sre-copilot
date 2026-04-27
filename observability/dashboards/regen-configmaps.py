#!/usr/bin/env python3
"""
Regenerate observability/dashboards/configmaps.yaml from the source *.json
dashboards in this directory.

Why this exists: the JSON dashboards are the source of truth (designed in
Grafana, exported, committed). configmaps.yaml is *derived* — it wraps each
JSON in a ConfigMap with the grafana_dashboard=1 label so Grafana's sidecar
auto-loads it. Running this keeps both in sync; otherwise you risk editing
the JSON, forgetting the YAML, and the cluster runs stale dashboards.

Run after editing any *.json file:
    python3 observability/dashboards/regen-configmaps.py
    kubectl apply -f observability/dashboards/configmaps.yaml
"""
from __future__ import annotations

import json
import pathlib
import sys
import textwrap

HERE = pathlib.Path(__file__).parent
DASHBOARD_NAMES = ["overview", "llm-performance", "cluster-health", "cost-capacity"]
NAMESPACE = "observability"
GRAFANA_FOLDER = "SRE Copilot"


def main() -> int:
    out: list[str] = [
        "# Grafana dashboard ConfigMaps — auto-loaded by Grafana sidecar (label: grafana_dashboard=1)",
        "# DO NOT EDIT BY HAND — regenerate with:",
        "#     python3 observability/dashboards/regen-configmaps.py",
        "# Source of truth is the *.json files in this directory.",
    ]
    rendered = 0
    for name in DASHBOARD_NAMES:
        src = HERE / f"{name}.json"
        if not src.exists():
            print(f"  SKIP {name}.json (not found)", file=sys.stderr)
            continue
        try:
            obj = json.loads(src.read_text())
        except json.JSONDecodeError as exc:
            print(f"  FAIL {name}.json — {exc}", file=sys.stderr)
            return 1
        body = textwrap.indent(json.dumps(obj, indent=2), "    ")
        out.append(
            f"""---
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-dashboard-{name}
  namespace: {NAMESPACE}
  labels:
    grafana_dashboard: "1"
  annotations:
    grafana_folder: "{GRAFANA_FOLDER}"
data:
  {name}.json: |-
{body}"""
        )
        rendered += 1

    target = HERE / "configmaps.yaml"
    target.write_text("\n".join(out) + "\n")
    print(f"Regenerated {target.relative_to(HERE.parent.parent)} from {rendered} dashboards")
    return 0


if __name__ == "__main__":
    sys.exit(main())
