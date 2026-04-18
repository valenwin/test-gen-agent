"""Unit tests for core.validator.TestValidator — subprocess calls are mocked."""

from unittest.mock import MagicMock, patch

import pytest

from core.validator import TestValidator, ValidationResult

SOURCE = "def add(a, b):\n    return a + b\n"
VALID_TESTS = (
    "from module import add\n\n"
    "def test_add():\n"
    "    assert add(1, 2) == 3\n"
)


def _make_proc(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestValidate:
    def test_returns_success_on_zero_returncode(self) -> None:
        proc = _make_proc(0, stdout="1 passed\n")
        with patch("core.validator.subprocess.run", return_value=proc):
            result = TestValidator().validate(SOURCE, VALID_TESTS, "module.py")
        assert result.success is True
        assert result.error is None

    def test_returns_failure_on_nonzero_returncode(self) -> None:
        proc = _make_proc(1, stdout="FAILED test_module.py::test_add\n")
        with patch("core.validator.subprocess.run", return_value=proc):
            result = TestValidator().validate(SOURCE, VALID_TESTS, "module.py")
        assert result.success is False
        assert result.error is not None

    def test_output_combines_stdout_and_stderr(self) -> None:
        proc = _make_proc(0, stdout="out\n", stderr="err\n")
        with patch("core.validator.subprocess.run", return_value=proc):
            result = TestValidator().validate(SOURCE, VALID_TESTS, "module.py")
        assert "out" in result.output
        assert "err" in result.output

    def test_returns_validation_result_type(self) -> None:
        proc = _make_proc(0)
        with patch("core.validator.subprocess.run", return_value=proc):
            result = TestValidator().validate(SOURCE, VALID_TESTS, "module.py")
        assert isinstance(result, ValidationResult)


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------

class TestTimeout:
    def test_timeout_returns_failure(self) -> None:
        import subprocess
        with patch("core.validator.subprocess.run", side_effect=subprocess.TimeoutExpired("pytest", 30)):
            result = TestValidator(timeout=30).validate(SOURCE, VALID_TESTS, "module.py")
        assert result.success is False
        assert result.coverage == 0.0
        assert "timed out" in (result.error or "").lower()

    def test_timeout_value_passed_to_subprocess(self) -> None:
        proc = _make_proc(0)
        with patch("core.validator.subprocess.run", return_value=proc) as mock_run:
            TestValidator(timeout=42).validate(SOURCE, VALID_TESTS, "module.py")
        assert mock_run.call_args.kwargs["timeout"] == 42


# ---------------------------------------------------------------------------
# Coverage parsing
# ---------------------------------------------------------------------------

class TestCoverageParsing:
    def test_parses_coverage_from_output(self) -> None:
        cov_output = "TOTAL   100   20   80%\n"
        proc = _make_proc(0, stdout=cov_output)
        with patch("core.validator.subprocess.run", return_value=proc):
            result = TestValidator().validate(SOURCE, VALID_TESTS, "module.py")
        assert result.coverage == pytest.approx(0.80)

    def test_zero_coverage_when_no_cov_line(self) -> None:
        proc = _make_proc(0, stdout="1 passed\n")
        with patch("core.validator.subprocess.run", return_value=proc):
            result = TestValidator().validate(SOURCE, VALID_TESTS, "module.py")
        assert result.coverage == 0.0

    def test_coverage_100_percent(self) -> None:
        proc = _make_proc(0, stdout="TOTAL   50   0   100%\n")
        with patch("core.validator.subprocess.run", return_value=proc):
            result = TestValidator().validate(SOURCE, VALID_TESTS, "module.py")
        assert result.coverage == pytest.approx(1.0)
