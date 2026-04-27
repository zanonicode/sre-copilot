"""
AT-012: Egress-deny NetworkPolicy test.

Verifies that backend pods cannot reach external internet endpoints (api.openai.com:443),
confirming the default-deny-egress NetworkPolicy is in effect.

Runs in two modes:
1. With a live cluster (kubeconfig available): executes `kubectl exec` to attempt the curl.
2. Without a cluster (CI without kind): skips with a clear reason message.

The test is intentionally pure-Python so it runs in the same pytest session as other
integration tests without needing cluster access as a hard dependency.
"""

import os
import shutil
import subprocess
import pytest


KUBECONFIG = os.environ.get(
    "KUBECONFIG",
    os.path.expanduser("~/.kube/sre-copilot.config"),
)

NAMESPACE = "sre-copilot"
EGRESS_TARGET = "https://api.openai.com"
CURL_TIMEOUT = "3"


def _kubectl_available() -> bool:
    return shutil.which("kubectl") is not None


def _kubeconfig_exists() -> bool:
    return os.path.isfile(KUBECONFIG)


def _get_backend_pod() -> str | None:
    result = subprocess.run(
        [
            "kubectl",
            "--kubeconfig", KUBECONFIG,
            "get", "pods",
            "-n", NAMESPACE,
            "-l", "app.kubernetes.io/name=backend",
            "--field-selector", "status.phase=Running",
            "-o", "jsonpath={.items[0].metadata.name}",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    name = result.stdout.strip()
    return name if name else None


@pytest.mark.skipif(
    not _kubectl_available() or not _kubeconfig_exists(),
    reason=(
        "kubectl not available or kubeconfig not found at "
        f"{KUBECONFIG} — skipping live-cluster AT-012 test. "
        "Run `make up` then `pytest tests/integration/test_egress_denied.py` to execute."
    ),
)
def test_egress_to_openai_is_denied():
    """
    AT-012: Backend pod must NOT be able to reach api.openai.com:443.
    NetworkPolicy default-deny-egress blocks all traffic not explicitly allowed.
    Port 443 is not in the allow-list, so the connection must timeout or be refused.
    """
    pod_name = _get_backend_pod()
    if pod_name is None:
        pytest.skip(
            "No Running backend pod found in sre-copilot namespace. "
            "Cluster may be down or backend may not be deployed."
        )

    result = subprocess.run(
        [
            "kubectl",
            "--kubeconfig", KUBECONFIG,
            "exec",
            "-n", NAMESPACE,
            pod_name,
            "--",
            "curl",
            "--silent",
            "--max-time", CURL_TIMEOUT,
            "--write-out", "%{http_code}",
            "--output", "/dev/null",
            EGRESS_TARGET,
        ],
        capture_output=True,
        text=True,
        timeout=int(CURL_TIMEOUT) + 5,
    )

    exit_code = result.returncode
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    print(f"kubectl exec exit code: {exit_code}")
    print(f"curl stdout (http_code): {stdout!r}")
    print(f"curl stderr: {stderr!r}")

    assert exit_code != 0, (
        f"Expected non-zero exit code (connection denied/timeout), "
        f"but got 0. NetworkPolicy may not be enforcing egress deny. "
        f"http_code={stdout!r}, stderr={stderr!r}"
    )

    assert stdout not in ("200", "301", "302", "403"), (
        f"Received an HTTP response from api.openai.com (http_code={stdout!r}), "
        f"which means egress was NOT blocked. "
        f"Check that NetworkPolicy default-deny-egress is applied in namespace {NAMESPACE}."
    )


def test_egress_deny_unit_documented():
    """
    Unit-level documentation test: verify the NetworkPolicy manifest includes
    the default-deny-egress policy (static file check, no cluster needed).
    """
    import pathlib

    np_file = pathlib.Path(
        "helm/platform/networkpolicies/templates/networkpolicies.yaml"
    )
    assert np_file.exists(), (
        f"NetworkPolicy template not found at {np_file}. "
        "This file must exist for AT-012 to be meaningful."
    )

    content = np_file.read_text()
    assert "default-deny-egress" in content, (
        "NetworkPolicy template does not contain 'default-deny-egress' policy. "
        "AT-012 relies on this baseline denial rule."
    )
    assert "policyTypes" in content and "Egress" in content, (
        "NetworkPolicy template must declare Egress policyType."
    )
