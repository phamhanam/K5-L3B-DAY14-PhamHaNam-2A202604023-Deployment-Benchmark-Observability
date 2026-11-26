"""
Production AI Agent — Part 6 Final Project
"""
import json
import logging
import signal
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra_fields = getattr(record, "extra_fields", None)
        if isinstance(extra_fields, dict):
            payload.update(extra_fields)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _setup_logging() -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    app_logger = logging.getLogger("agent")
    app_logger.setLevel(logging.INFO)
    return app_logger


logger = _setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def _on_sigterm(signum, frame):
        logger.info(
            "Received SIGTERM, starting graceful shutdown",
            extra={"extra_fields": {"event": "sigterm", "signal": signum}},
        )
        if callable(previous_sigterm):
            previous_sigterm(signum, frame)

    signal.signal(signal.SIGTERM, _on_sigterm)

    logger.info(
        "Agent starting up",
        extra={
            "extra_fields": {
                "event": "startup",
                "environment": settings.environment,
                "port": settings.port,
            }
        },
    )
    yield
    logger.info(
        "Agent shutting down",
        extra={"extra_fields": {"event": "shutdown"}},
    )
    try:
        r.close()
    except Exception:
        pass


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: Optional[str] = None


@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    if not redis_healthy():
        logger.warning(
            "Readiness check failed: Redis unreachable",
            extra={"extra_fields": {"event": "readiness_failed"}},
        )
        raise HTTPException(status_code=503, detail="Redis is not ready")
    return {"status": "ready"}


@app.post("/ask")
def ask(
    body: AskRequest,
    api_key: str = Depends(verify_api_key),
):
    started = time.perf_counter()
    check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)
    input_tokens = max(10, len(body.question) // 2)
    output_tokens = max(20, len(answer) // 2)
    cost = record_cost(input_tokens, output_tokens)

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info(
        "Handled /ask request",
        extra={
            "extra_fields": {
                "event": "request",
                "path": "/ask",
                "status": 200,
                "ms": elapsed_ms,
                "cost_usd": round(cost, 6),
            }
        },
    )
    return {
        "question": body.question,
        "answer": answer,
    }
