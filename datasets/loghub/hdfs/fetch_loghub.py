"""
Download the public Loghub HDFS log dataset and extract a curated ~50K-line subset.

Usage:
    python datasets/loghub/hdfs/fetch_loghub.py

Outputs:
    datasets/loghub/hdfs/HDFS.log        (~50K lines, ~5 MB)
    datasets/loghub/hdfs/anomaly_label.csv

The subset selection strategy (OQ-B1):
  - Take the first 50,000 lines of HDFS_v1 (chronological order)
  - Always include all lines associated with BLOCK* anomaly events from the label file
  - This preserves failure mode diversity while keeping the file Git-friendly (<10 MB)

Source: https://github.com/logpai/loghub (MIT licence, see LICENSE.md)
"""

import csv
import gzip
import io
import pathlib
import urllib.request

HDFS_URL = (
    "https://zenodo.org/records/8196385/files/HDFS_v1.zip?download=1"
)
LABEL_URL = (
    "https://raw.githubusercontent.com/logpai/loghub/master/HDFS/anomaly_label.csv"
)

TARGET_LINES = 50_000
HERE = pathlib.Path(__file__).parent


def _fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "sre-copilot/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def _extract_hdfs_log_from_zip(raw: bytes) -> list[str]:
    import zipfile

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = zf.namelist()
        log_name = next((n for n in names if n.endswith("HDFS.log")), None)
        if not log_name:
            raise FileNotFoundError(f"HDFS.log not found in zip. Contents: {names}")
        with zf.open(log_name) as f:
            return f.read().decode("utf-8", errors="replace").splitlines()


def _load_anomaly_block_ids(label_csv: str) -> set[str]:
    reader = csv.DictReader(io.StringIO(label_csv))
    return {row["BlockId"] for row in reader if row.get("Label") == "Anomaly"}


def _select_subset(all_lines: list[str], anomaly_ids: set[str]) -> list[str]:
    first_50k = set(range(TARGET_LINES))
    anomaly_lines: list[str] = []
    normal_lines: list[str] = []

    for i, line in enumerate(all_lines):
        is_anomaly = any(bid in line for bid in anomaly_ids)
        if i < TARGET_LINES:
            normal_lines.append(line)
        elif is_anomaly:
            anomaly_lines.append(line)

    combined = normal_lines + anomaly_lines
    combined.sort(key=lambda l: l[:15])
    return combined


def main() -> None:
    label_path = HERE / "anomaly_label.csv"
    hdfs_path = HERE / "HDFS.log"

    if hdfs_path.exists() and label_path.exists():
        print(f"Subset already present ({hdfs_path.stat().st_size // 1024} KB). Delete to re-fetch.")
        return

    print("Fetching anomaly label CSV...")
    label_csv = _fetch_bytes(LABEL_URL).decode()
    label_path.write_text(label_csv)
    anomaly_ids = _load_anomaly_block_ids(label_csv)
    print(f"  {len(anomaly_ids)} anomaly block IDs loaded")

    print("Fetching HDFS log zip (may take a minute)...")
    raw_zip = _fetch_bytes(HDFS_URL)
    print(f"  Downloaded {len(raw_zip) // 1024 // 1024} MB")

    all_lines = _extract_hdfs_log_from_zip(raw_zip)
    print(f"  Total lines in source: {len(all_lines):,}")

    subset = _select_subset(all_lines, anomaly_ids)
    hdfs_path.write_text("\n".join(subset) + "\n")
    print(f"  Subset written: {len(subset):,} lines / {hdfs_path.stat().st_size // 1024} KB")
    print("Done.")


if __name__ == "__main__":
    main()
