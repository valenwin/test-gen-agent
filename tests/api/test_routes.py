"""Unit tests for api.routes — Celery tasks are mocked."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)

CODE = "def add(a, b):\n    return a + b\n"


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_returns_ok(self) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /generate
# ---------------------------------------------------------------------------

class TestGenerate:
    def _mock_task(self, task_id: str = "abc-123") -> MagicMock:
        task = MagicMock()
        task.id = task_id
        return task

    def test_returns_202_with_job_id(self) -> None:
        with patch("api.routes.generate_tests_task.delay", return_value=self._mock_task()):
            response = client.post("/generate", json={"code": CODE})
        assert response.status_code == 202
        assert response.json()["job_id"] == "abc-123"
        assert response.json()["status"] == "pending"

    def test_passes_code_and_filename_to_task(self) -> None:
        with patch("api.routes.generate_tests_task.delay", return_value=self._mock_task()) as mock_delay:
            client.post("/generate", json={"code": CODE, "filename": "math.py"})
        mock_delay.assert_called_once_with(
            code=CODE,
            filename="math.py",
            target_coverage=0.8,
        )

    def test_passes_custom_target_coverage(self) -> None:
        with patch("api.routes.generate_tests_task.delay", return_value=self._mock_task()) as mock_delay:
            client.post("/generate", json={"code": CODE, "target_coverage": 0.9})
        assert mock_delay.call_args.kwargs["target_coverage"] == pytest.approx(0.9)

    def test_rejects_empty_code(self) -> None:
        response = client.post("/generate", json={"code": ""})
        assert response.status_code == 422

    def test_rejects_missing_code(self) -> None:
        response = client.post("/generate", json={})
        assert response.status_code == 422

    def test_rejects_coverage_above_1(self) -> None:
        response = client.post("/generate", json={"code": CODE, "target_coverage": 1.5})
        assert response.status_code == 422

    def test_rejects_coverage_below_0(self) -> None:
        response = client.post("/generate", json={"code": CODE, "target_coverage": -0.1})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}
# ---------------------------------------------------------------------------

class TestGetJob:
    def _patch_result(self, state: str, result=None, info=None):
        task = MagicMock()
        task.state = state
        task.result = result
        task.info = info
        return patch("api.routes.generate_tests_task.AsyncResult", return_value=task)

    def test_pending_job(self) -> None:
        with self._patch_result("PENDING"):
            response = client.get("/jobs/abc-123")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert data["job_id"] == "abc-123"

    def test_running_job(self) -> None:
        with self._patch_result("STARTED"):
            response = client.get("/jobs/abc-123")
        assert response.json()["status"] == "running"

    def test_successful_job_returns_tests_and_coverage(self) -> None:
        result = {"tests": "def test_add(): ...", "coverage": 0.95}
        with self._patch_result("SUCCESS", result=result):
            response = client.get("/jobs/abc-123")
        data = response.json()
        assert data["status"] == "success"
        assert data["generated_tests"] == "def test_add(): ..."
        assert data["coverage"] == pytest.approx(0.95)

    def test_failed_job_returns_error(self) -> None:
        with self._patch_result("FAILURE", info=RuntimeError("something broke")):
            response = client.get("/jobs/abc-123")
        data = response.json()
        assert data["status"] == "failed"
        assert "something broke" in data["error"]

    def test_unknown_state_returns_500(self) -> None:
        with self._patch_result("REVOKED"):
            response = client.get("/jobs/abc-123")
        assert response.status_code == 500
