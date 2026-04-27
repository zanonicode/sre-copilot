# Loghub HDFS Dataset Subset

## Source

**Loghub HDFS v1** — a widely-cited, labeled HDFS distributed-filesystem log dataset
originally published by the LogPai research group.

- Paper: He et al., "Loghub: A Large Collection of System Log Datasets towards Automated Log Analytics"
- Repository: https://github.com/logpai/loghub
- Zenodo archive: https://zenodo.org/records/8196385
- License: MIT (see `LICENSE.md`)

## Subset Selection (OQ-B1)

The full HDFS v1 dataset is ~1.5 GB — too large to commit to Git without LFS.
This directory contains a curated ~50K-line, ~7 MB subset selected as follows:

1. **Base corpus:** first 45,000 lines in chronological order from `HDFS.log`
   (covers normal DataNode replication traffic, namenode interactions, block writes)
2. **Anomaly enrichment:** all lines referencing block IDs labeled `Anomaly`
   in `anomaly_label.csv` that fall outside the base 45K window (~5,000 additional lines)
3. **Sort:** merged corpus is sorted by log timestamp prefix for chronological coherence

**Result:** 50,000 lines containing a representative mix of:
- Normal DataNode `Receiving block` / `PacketResponder` traffic
- HDFS block allocation and storage events
- Anomaly events: DataNode `Connection reset by peer`, `DataNode is shutting down`,
  block replication failures, IOException in offerService

This selection ensures all demo log analysis scenarios have in-distribution examples
and Layer-2 judge evaluation covers diverse failure modes.

## Re-fetching

To re-generate from the upstream source:

```bash
python datasets/loghub/hdfs/fetch_loghub.py
```

This requires network access and downloads ~150 MB. The committed subset is
sufficient for all demo and eval workflows without network access.

## Files

| File | Description |
|------|-------------|
| `HDFS.log` | Curated 50K-line log subset |
| `anomaly_label.csv` | Block-level anomaly labels (`BlockId`, `Label`) |
| `fetch_loghub.py` | Upstream fetch + subset extraction script |
| `README.md` | This file |
| `LICENSE.md` | MIT licence attribution |
