import pathlib
import pytest


GROUND_TRUTH_DIR = pathlib.Path("datasets/eval/ground_truth")


def _load_log_payload(filename: str) -> str:
    log_dir = pathlib.Path("datasets/loghub/hdfs")
    sample = log_dir / "HDFS.log"
    if sample.exists():
        lines = sample.read_text(errors="replace").splitlines()
        return "\n".join(lines[:50])
    return (
        "ERROR 2024-01-15 14:23:01 DataNode blk_1234567890 "
        "Lost contact with namenode, retrying... "
        "CRITICAL 2024-01-15 14:23:05 DataNode replication failed for block blk_1234567890 "
        "ERROR 2024-01-15 14:23:10 NameNode Unable to replicate block to 3 nodes"
    )


@pytest.fixture(scope="session")
def hdfs_sample() -> str:
    return _load_log_payload("HDFS.log")


@pytest.fixture(scope="session")
def synth_sample() -> str:
    return (
        "ERROR 2024-01-15 14:23:01 backend downstream.timeout "
        "GET /upstream/api timed out after 5000ms\n"
        "ERROR 2024-01-15 14:23:02 backend retry.attempt "
        "retrying GET /upstream/api (attempt 2/3)\n"
        "CRITICAL 2024-01-15 14:23:03 backend circuit.open "
        "circuit breaker OPEN for upstream-api"
    )


@pytest.fixture(scope="session")
def ground_truth_records() -> list[dict]:
    import json
    records = []
    for p in sorted(GROUND_TRUTH_DIR.glob("*.json")):
        records.append(json.loads(p.read_text()))
    return records
