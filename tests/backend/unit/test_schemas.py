"""Unit tests for Pydantic schema validation (AT-008 coverage)."""

import pytest
from pydantic import ValidationError

from backend.schemas.analyze import LogAnalysisRequest
from backend.schemas.postmortem import (
    LogAnalysis,
    Postmortem,
    Severity,
)


class TestLogAnalysisRequest:
    def test_valid_request(self):
        req = LogAnalysisRequest(log_payload="error: connection refused to database")
        assert req.log_payload == "error: connection refused to database"
        assert req.context is None

    def test_with_context(self):
        req = LogAnalysisRequest(
            log_payload="error: connection refused",
            context="production HDFS cluster",
        )
        assert req.context == "production HDFS cluster"

    def test_payload_too_short_raises(self):
        with pytest.raises(ValidationError):
            LogAnalysisRequest(log_payload="x")

    def test_payload_too_long_raises(self):
        with pytest.raises(ValidationError):
            LogAnalysisRequest(log_payload="x" * 500_001)

    def test_estimated_tokens_returns_int(self):
        req = LogAnalysisRequest(log_payload="error: connection refused to database host")
        tokens = req.estimated_tokens()
        assert isinstance(tokens, int)
        assert tokens > 0

    def test_context_too_long_raises(self):
        with pytest.raises(ValidationError):
            LogAnalysisRequest(log_payload="some log data here", context="x" * 2_001)


class TestLogAnalysis:
    def _valid(self, **overrides) -> dict:
        base = {
            "severity": "critical",
            "summary": "DataNode shut down due to network partition",
            "root_cause": "Connection reset between DataNode and mirror during block write",
            "runbook": ["restart DataNode", "check network connectivity"],
            "related_metrics": ["dfs_datanode_blocks_written_total"],
        }
        return {**base, **overrides}

    def test_valid_analysis(self):
        a = LogAnalysis(**self._valid())
        assert a.severity == "critical"

    def test_invalid_severity_raises(self):
        with pytest.raises(ValidationError):
            LogAnalysis(**self._valid(severity="unknown"))

    def test_summary_too_short_raises(self):
        with pytest.raises(ValidationError):
            LogAnalysis(**self._valid(summary="short"))

    def test_empty_runbook_raises(self):
        with pytest.raises(ValidationError):
            LogAnalysis(**self._valid(runbook=[]))

    def test_info_severity_allowed(self):
        a = LogAnalysis(**self._valid(severity="info"))
        assert a.severity == "info"

    def test_related_metrics_optional(self):
        data = self._valid()
        data.pop("related_metrics")
        a = LogAnalysis(**data)
        assert a.related_metrics == []


class TestPostmortem:
    def _timeline(self) -> list[dict]:
        return [
            {
                "at": "2024-06-21T06:27:00Z",
                "actor": "deploy-bot",
                "action": "Applied BGP configuration",
            },
            {
                "at": "2024-06-21T06:30:00Z",
                "actor": "on-call-engineer",
                "action": "Acknowledged alert",
            },
        ]

    def _valid(self) -> dict:
        return {
            "summary": "BGP misconfiguration caused 19 minutes of degraded connectivity affecting 30% of requests worldwide.",
            "impact": "30% of requests failed for 19 minutes. ~12,000 zones affected.",
            "severity": "SEV1",
            "detection": "SLO burn-rate alert fired within 2 minutes.",
            "root_cause": "Incorrect BGP local-preference value in new peer configuration triggered route withdrawal loop.",
            "trigger": "Automated deployment of planned network expansion config.",
            "resolution": "Rolled back BGP configuration to known-good state.",
            "timeline": self._timeline(),
            "what_went_well": ["Alert fired within 2 minutes", "Rollback took only 9 minutes"],
            "what_went_wrong": ["No semantic validation of BGP config", "All regions updated simultaneously"],
            "action_items": [
                {
                    "title": "Add semantic validation of BGP local-preference values to pipeline",
                    "owner": "network-infra",
                    "priority": "P0",
                    "due_window": "this_sprint",
                }
            ],
            "lessons_learned": ["Syntax validation is insufficient for infrastructure changes"],
        }

    def test_valid_postmortem(self):
        pm = Postmortem(**self._valid())
        assert pm.severity == Severity.sev1

    def test_timeline_must_be_chronological(self):
        data = self._valid()
        data["timeline"] = list(reversed(data["timeline"]))
        with pytest.raises(ValidationError, match="chronological"):
            Postmortem(**data)

    def test_summary_too_short_raises(self):
        data = self._valid()
        data["summary"] = "Too short."
        with pytest.raises(ValidationError):
            Postmortem(**data)

    def test_action_item_priority_validated(self):
        data = self._valid()
        data["action_items"][0]["priority"] = "P9"
        with pytest.raises(ValidationError):
            Postmortem(**data)
