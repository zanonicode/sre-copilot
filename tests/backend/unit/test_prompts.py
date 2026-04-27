"""Unit tests for prompt assembly (template rendering)."""



from backend.prompts import render_log_analyzer, render_postmortem


class TestRenderLogAnalyzer:
    def test_renders_without_context(self):
        result = render_log_analyzer("ERROR: connection refused\nWARN: retrying")
        assert "ERROR: connection refused" in result
        assert "ANALYSIS:" in result
        assert "few-shot" not in result.lower() or "HDFS" in result

    def test_renders_with_context(self):
        result = render_log_analyzer("ERROR: disk full", context="production HDFS")
        assert "production HDFS" in result

    def test_few_shot_hdfs_injected(self):
        result = render_log_analyzer("some log line here")
        assert "DataNode" in result or "blk_" in result

    def test_schema_present_in_prompt(self):
        result = render_log_analyzer("ERROR: something failed")
        assert "severity" in result
        assert "root_cause" in result
        assert "runbook" in result

    def test_context_absent_when_none(self):
        result = render_log_analyzer("some log data")
        assert "CONTEXT:" not in result

    def test_context_present_when_given(self):
        result = render_log_analyzer("some log data", context="test env")
        assert "CONTEXT: test env" in result


class TestRenderPostmortem:
    def _log_analysis(self) -> dict:
        return {
            "severity": "critical",
            "summary": "DataNode shutdown due to network partition",
            "root_cause": "Connection reset during block replication",
            "runbook": ["restart DataNode", "check network"],
            "related_metrics": ["dfs_datanode_blocks_written_total"],
        }

    def test_renders_without_context(self):
        result = render_postmortem(self._log_analysis(), None, None)
        assert "summary" in result
        assert "action_items" in result

    def test_renders_with_context(self):
        result = render_postmortem(self._log_analysis(), None, "HDFS cluster incident")
        assert "HDFS cluster incident" in result

    def test_log_analysis_included(self):
        result = render_postmortem(self._log_analysis(), None, None)
        assert "DataNode shutdown" in result

    def test_postmortem_schema_fields_present(self):
        result = render_postmortem(self._log_analysis(), None, None)
        for field in ["severity", "root_cause", "timeline", "what_went_well", "lessons_learned"]:
            assert field in result
