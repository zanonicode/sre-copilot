"""
Smoke probe: send a minimal SSE request to the backend and assert
the stream opens and emits at least one data frame within 15 seconds.
Run by `make smoke`. Does not require Ollama to be loaded — just the HTTP layer.
"""

import json
import sys
import urllib.request

BACKEND_URL = "http://localhost:8000"
PAYLOAD = json.dumps({"log_payload": "ERROR: connection timeout to upstream service after 5s"}).encode()


def probe() -> int:
    req = urllib.request.Request(
        f"{BACKEND_URL}/analyze/logs",
        data=PAYLOAD,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            if r.status != 200:
                print(f"FAIL: HTTP {r.status}", file=sys.stderr)
                return 1
            ct = r.headers.get("Content-Type", "")
            if "text/event-stream" not in ct:
                print(f"FAIL: Content-Type={ct}", file=sys.stderr)
                return 1
            first_line = r.readline().decode()
            if not first_line.startswith("data:"):
                print(f"FAIL: first SSE frame missing: {first_line!r}", file=sys.stderr)
                return 1
            print(f"OK: SSE stream opened, first frame: {first_line.strip()!r}")
            return 0
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(probe())
