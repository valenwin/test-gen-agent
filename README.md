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

## API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/generate` | Submit code for test generation |
| `GET` | `/jobs/{job_id}` | Poll job status and results |

### Example

```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"code": "def add(a: int, b: int) -> int:\n    return a + b", "filename": "math_utils.py"}'
```

Response:
```json
{"job_id": "abc-123", "status": "pending"}
```

```bash
curl http://localhost:8000/jobs/abc-123
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
| `ANTHROPIC_MODEL` | `claude-sonnet-4-5` | Model to use |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `CELERY_BROKER_URL` | `redis://localhost:6379/1` | Celery broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/2` | Celery results |
| `LOG_LEVEL` | `INFO` | Logging level |
| `ENVIRONMENT` | `development` | `development` or `production` |