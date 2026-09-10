"""Unit tests for the Python LLM Extraction Bridge."""

from unittest.mock import patch, MagicMock
import pytest
from crawler.adapters.llm_bridge import LLMExtractionBridge


def test_llm_extraction_bridge_success():
    bridge = LLMExtractionBridge()

    dummy_output = {
        "schemaVersion": "1.0",
        "recordType": "STARTUP",
        "source": {"name": "Web", "url": "https://example.com"},
        "content": {"entityName": "TestCo", "data": {"employeeCount": 100}},
        "collectedAt": "2026-09-10T00:00:00Z"
    }

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = '{"schemaVersion": "1.0", "recordType": "STARTUP", "source": {"name": "Web", "url": "https://example.com"}, "content": {"entityName": "TestCo", "data": {"employeeCount": 100}}, "collectedAt": "2026-09-10T00:00:00Z"}'
    mock_proc.stderr = ""

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        result = bridge.extract(
            content="<h1>TestCo</h1><p>100 employees</p>",
            schema="startup",
            source_url="https://example.com"
        )

        assert result["content"]["entityName"] == "TestCo"
        assert result["content"]["data"]["employeeCount"] == 100
        mock_run.assert_called_once()


def test_llm_extraction_bridge_failure():
    bridge = LLMExtractionBridge()

    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stderr = "All providers failed"

    with patch("subprocess.run", return_value=mock_proc):
        with pytest.raises(RuntimeError) as exc_info:
            bridge.extract(content="broken", schema="startup")

        assert "LLM Extraction Engine failed" in str(exc_info.value)
