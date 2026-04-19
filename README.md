# Test Generation Agent

AI agent that accepts Python code and generates quality pytest tests, targeting coverage gaps.

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   CLI /     │────▶│  FastAPI Gateway │────▶│  Celery Worker  │
│   Web UI    │     │   (async)        │     │  (generation)   │
└─────────────┘     └──────────────────┘     └────────┬────────┘
                           │                           │
                           ▼                           ▼
                    ┌──────────────┐          ┌──────────────────┐
                    │  Redis       │          │  AST Analyzer    │
                    │  (cache +    │          │  (ast, inspect)  │
                    │   queue)     │          └────────┬─────────┘
                    └──────────────┘                   │
                                                       ▼
                                              ┌──────────────────┐
                                              │  Prompt Builder  │
                                              │  (few-shot, ctx) │
                                              └────────┬─────────┘
                                                       │
                                                       ▼
                                              ┌──────────────────┐
                                              │  Anthropic API   │
                                              │  (tool calling)  │
                                              └────────┬─────────┘
                                                       │
                                                       ▼
                                              ┌──────────────────┐
                                              │  Test Validator  │
                                              │  (Docker sandbox)│
                                              └────────┬─────────┘
                                                       │
                                                       ▼
                                              ┌──────────────────┐
                                              │  Coverage        │
                                              │  Analyzer        │
                                              └──────────────────┘
```

## Tech Stack

| Layer | Tool |
|---|---|
| API | FastAPI + uvicorn |
| Queue | Celery + Redis |
| LLM | Anthropic Claude (Sonnet) |
| Code analysis | `ast`, `inspect` |
| Test execution | `pytest`, `coverage.py` |
| Sandbox | Docker + `subprocess` with timeout |
| Observability | `structlog` |

## Getting Started

### Prerequisites

- Python 3.12+
- Docker & Docker Compose
- [Pipenv](https://pipenv.pypa.io/)
- Anthropic API key

### Setup

```bash
# Install dependencies
pipenv install --dev

# Copy env file and fill in your API key
cp .env.example .env

# Start Redis
docker compose up redis -d
```

### Run

```bash
# API server
pipenv run uvicorn api.main:app --reload

# Celery worker (separate terminal)
pipenv run celery -A worker.celery_app worker --loglevel=info

# Or run everything with Docker Compose
docker compose up
```

### Tests

```bash
pipenv run pytest tests/ -v
pipenv run pytest tests/ -v --cov=. --cov-report=term-missing
```

### Lint & type check

```bash
pipenv run ruff check .
pipenv run mypy .
```

## Usage

### CLI (recommended)

The easiest way to generate tests is via the included `cli.py` script — no JSON escaping needed.

**1. Write your source file**

```python
# math.py
def divide(a: float, b: float) -> float:
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
```

**2. Run the CLI**

```bash
pipenv run python cli.py math.py
```

The agent will:
1. Parse `math.py` with the AST analyzer — extracting functions, complexity, raise/return paths
2. Build a structured prompt with coverage gaps (e.g. "test the zero-division branch")
3. Send the prompt to Claude, which may call `get_function_source` to inspect implementation details
4. Extract the generated tests from the `<tests>...</tests>` response block
5. Run `pytest --cov` in a sandbox to verify the tests pass and measure coverage
6. If coverage is below the target (default 80%), retry with the coverage gap as feedback — up to 3 times
7. Return the final test code

**3. Output**

```
Submitting math.py...
Job ID: 9ad025df-2f95-46f0-b342-d6aac17cb31d
  [2s] status: running
  [4s] status: success
Done! Coverage: 100%

============================================================
import pytest
from math import divide


def test_divide_returns_correct_result():
    assert divide(10.0, 2.0) == pytest.approx(5.0)


def test_divide_by_zero_raises_value_error():
    with pytest.raises(ValueError, match="Cannot divide by zero"):
        divide(1.0, 0.0)


@pytest.mark.parametrize("a,b,expected", [
    (6.0, 3.0, 2.0),
    (-4.0, 2.0, -2.0),
    (0.0, 5.0, 0.0),
])
def test_divide_parametrized(a, b, expected):
    assert divide(a, b) == pytest.approx(expected)
```

**Save to a file instead of stdout:**

```bash
pipenv run python cli.py math.py --out test_math.py
```

**Custom coverage target:**

```bash
pipenv run python cli.py math.py --coverage 0.95
```

---

### API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/generate` | Submit code for test generation |
| `GET` | `/jobs/{job_id}` | Poll job status and results |

#### POST /generate

```json
{
  "code": "<Python source as a string>",
  "filename": "math.py",
  "target_coverage": 0.8
}
```

Returns immediately with a job ID:

```json
{"job_id": "9ad025df-2f95-46f0-b342-d6aac17cb31d", "status": "pending"}
```

#### GET /jobs/{job_id}

Poll until `status` is `"success"` or `"failed"`:

```json
{
  "job_id": "9ad025df-2f95-46f0-b342-d6aac17cb31d",
  "status": "success",
  "generated_tests": "import pytest\n...",
  "coverage": 1.0
}
```

## Project Structure

```
├── api/              # FastAPI app (routes, schemas)
├── analyzer/         # AST-based code analyzer
├── worker/           # Celery tasks
├── core/             # Shared utilities (logging)
├── tests/            # Unit & integration tests
├── config.py         # Pydantic settings
├── docker-compose.yml
└── pyproject.toml
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required. Your Anthropic API key |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Model to use |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `CELERY_BROKER_URL` | `redis://localhost:6379/1` | Celery broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/2` | Celery results |
| `LOG_LEVEL` | `INFO` | Logging level |
| `ENVIRONMENT` | `development` | `development` or `production` |