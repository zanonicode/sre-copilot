"""Layer-1 structural eval: JSON schema and field contract (AT-010).

These tests run on every commit as a CI gate. They do NOT call a live LLM —
they exercise the Pydantic schema against known-good and known-bad payloads
to ensure the schema contract is enforced correctly.
"""
import json

import pytest

from backend.schemas import LogAnalysis, LogAnalysisV2


VALID_PAYLOAD = {
    "severity": "critical",
    "summary": "DataNode replication failures causing data loss risk in HDFS cluster.",
    "root_cause": "Network partition between DataNode and NameNode interrupted heartbeats.",
    "runbook": [
        "Check DataNode logs: journalctl -u datanode -n 200",
        "Verify network connectivity: ping namenode from datanode",
        "Restart DataNode service if heartbeat timeout exceeded",
    ],
    "related_metrics": [
        "hdfs_datanode_block_reports_total",
        "hdfs_namenode_missing_blocks",
    ],
}


class TestLogAnalysisSchema:
    def test_valid_payload_passes(self):
        result = LogAnalysis.model_validate(VALID_PAYLOAD)
        assert result.severity == "critical"
        assert len(result.runbook) >= 1
        assert isinstance(result.related_metrics, list)

    @pytest.mark.parametrize("severity", ["info", "warning", "critical"])
    def test_all_severity_values_accepted(self, severity: str):
        payload = {**VALID_PAYLOAD, "severity": severity}
        result = LogAnalysis.model_validate(payload)
        assert result.severity == severity

    def test_invalid_severity_rejected(self):
        payload = {**VALID_PAYLOAD, "severity": "unknown"}
        with pytest.raises(Exception):
            LogAnalysis.model_validate(payload)

    def test_missing_required_field_rejected(self):
        for required_field in ("severity", "summary", "root_cause", "runbook"):
            payload = {k: v for k, v in VALID_PAYLOAD.items() if k != required_field}
            with pytest.raises(Exception):
                LogAnalysis.model_validate(payload)

    def test_summary_minimum_length_enforced(self):
        payload = {**VALID_PAYLOAD, "summary": "Short."}
        with pytest.raises(Exception):
            LogAnalysis.model_validate(payload)

    def test_summary_maximum_length_enforced(self):
        payload = {**VALID_PAYLOAD, "summary": "x" * 401}
        with pytest.raises(Exception):
            LogAnalysis.model_validate(payload)

    def test_empty_runbook_rejected(self):
        payload = {**VALID_PAYLOAD, "runbook": []}
        with pytest.raises(Exception):
            LogAnalysis.model_validate(payload)

    def test_related_metrics_defaults_to_empty(self):
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "related_metrics"}
        result = LogAnalysis.model_validate(payload)
        assert result.related_metrics == []

    def test_related_metrics_max_length_enforced(self):
        payload = {**VALID_PAYLOAD, "related_metrics": [f"metric_{i}" for i in range(11)]}
        with pytest.raises(Exception):
            LogAnalysis.model_validate(payload)

    def test_json_roundtrip(self):
        result = LogAnalysis.model_validate(VALID_PAYLOAD)
        serialized = result.model_dump_json()
        restored = LogAnalysis.model_validate_json(serialized)
        assert restored == result

    def test_all_5_required_fields_present_in_output(self):
        result = LogAnalysis.model_validate(VALID_PAYLOAD)
        dumped = json.loads(result.model_dump_json())
        for field in ("severity", "summary", "root_cause", "runbook", "related_metrics"):
            assert field in dumped, f"Missing required field: {field}"


class TestLogAnalysisV2Schema:
    def test_v2_extends_v1_with_confidence(self):
        payload = {**VALID_PAYLOAD, "confidence": 0.87}
        result = LogAnalysisV2.model_validate(payload)
        assert result.confidence == pytest.approx(0.87)
        assert result.severity == VALID_PAYLOAD["severity"]

    def test_confidence_range_enforced_low(self):
        payload = {**VALID_PAYLOAD, "confidence": -0.1}
        with pytest.raises(Exception):
            LogAnalysisV2.model_validate(payload)

    def test_confidence_range_enforced_high(self):
        payload = {**VALID_PAYLOAD, "confidence": 1.1}
        with pytest.raises(Exception):
            LogAnalysisV2.model_validate(payload)

    def test_confidence_boundary_values_accepted(self):
        for boundary in (0.0, 1.0):
            payload = {**VALID_PAYLOAD, "confidence": boundary}
            result = LogAnalysisV2.model_validate(payload)
            assert result.confidence == pytest.approx(boundary)

    def test_v2_missing_confidence_rejected(self):
        with pytest.raises(Exception):
            LogAnalysisV2.model_validate(VALID_PAYLOAD)

    def test_v1_payload_does_not_have_confidence(self):
        result = LogAnalysis.model_validate(VALID_PAYLOAD)
        assert not hasattr(result, "confidence")
