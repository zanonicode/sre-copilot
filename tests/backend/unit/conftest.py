import pathlib
import sys

import pytest

# Ensure src/ is on the path when running pytest from the project root
sys.path.insert(0, str(pathlib.Path(__file__).parents[3] / "src"))


@pytest.fixture()
def hdfs_sample() -> str:
    path = pathlib.Path(__file__).parents[3] / "datasets" / "loghub" / "hdfs" / "HDFS.log"
    if path.exists():
        lines = path.read_text().splitlines()
        return "\n".join(lines[:50])
    return (
        "081109 203519 35 ERROR dfs.DataNode$DataXceiver: Got exception while serving blk_-1608999687919862906\n"
        "java.io.IOException: Connection reset by peer\n"
        "081109 203522 35 ERROR dfs.DataNode: DataNode is shutting down"
    )
