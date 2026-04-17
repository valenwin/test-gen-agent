FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e ".[dev]"

COPY src/ ./src/
COPY tests/ ./tests/

CMD ["uvicorn", "test_gen_agent.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
