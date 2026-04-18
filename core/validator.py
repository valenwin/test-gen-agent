"""Runs generated pytest tests in an isolated subprocess sandbox."""

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core.logging import logger


@dataclass
class ValidationResult:
    success: bool
    output: str
    coverage: float  # 0.0 – 1.0
    error: str | None = None


class TestValidator:
    """Write source + tests to a temp dir, run pytest, parse result."""

    def __init__(self, timeout: int = 30) -> None:
        self._timeout = timeout

    def validate(
        self,
        source: str,
        tests: str,
        filename: str = "module.py",
    ) -> ValidationResult:
        log = logger.bind(filename=filename)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            src_path = tmp / filename
            src_path.write_text(source)

            stem = Path(filename).stem
            test_path = tmp / f"test_{stem}.py"
            test_path.write_text(tests)

            cmd = [
                "python", "-m", "pytest",
                str(test_path),
                f"--cov={stem}",
                "--cov-report=term-missing",
                "--tb=short",
                "-q",
                "--no-header",
            ]

            log.info("validator_run", test_file=str(test_path))

            try:
                proc = subprocess.run(
                    cmd,
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                )
            except subprocess.TimeoutExpired:
                log.warning("validator_timeout", timeout=self._timeout)
                return ValidationResult(
                    success=False,
                    output="",
                    coverage=0.0,
                    error=f"Pytest timed out after {self._timeout}s",
                )

            output = proc.stdout + proc.stderr
            success = proc.returncode == 0
            coverage = self._parse_coverage(output, stem)

            log.info(
                "validator_done",
                success=success,
                returncode=proc.returncode,
                coverage=coverage,
            )

            return ValidationResult(
                success=success,
                output=output,
                coverage=coverage,
                error=output if not success else None,
            )

    def _parse_coverage(self, output: str, module_name: str) -> float:
        """Extract total coverage % from pytest-cov output."""
        match = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", output)
        if match:
            return int(match.group(1)) / 100.0
        return 0.0
