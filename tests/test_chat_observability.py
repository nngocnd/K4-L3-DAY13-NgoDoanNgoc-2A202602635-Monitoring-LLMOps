from __future__ import annotations

import json
import asyncio
from pathlib import Path

import httpx

from app import logging_config
from app.main import app


def test_chat_response_log_exposes_quality_for_dashboard(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            return await client.post(
                "/chat",
                json={
                    "user_id": "student-01",
                    "session_id": "session-01",
                    "feature": "qa",
                    "message": "Explain observability",
                },
            )

    response = asyncio.run(send_request())

    assert response.status_code == 200
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    response_event = next(event for event in events if event["event"] == "response_sent")
    assert response_event["quality_score"] == response.json()["quality_score"]
    assert response_event["ttft_ms"] == response.json()["ttft_ms"]
    assert response_event["tool_name"] == "retrieval"
    assert response_event["tool_success"] is True


def test_correlation_id_and_pii_scrubbing_in_chat(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    async def send_requests() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            r1 = await client.post(
                "/chat",
                headers={"x-request-id": "req-custom99"},
                json={
                    "user_id": "student-01",
                    "session_id": "session-01",
                    "feature": "qa",
                    "message": "My email is student@vinuni.edu.vn and phone is 0901234567",
                },
            )
            r2 = await client.post(
                "/chat",
                json={
                    "user_id": "student-02",
                    "session_id": "session-02",
                    "feature": "summary",
                    "message": "My card is 4111 1111 1111 1111 and CCCD is 001099123456",
                },
            )
            return r1, r2

    r1, r2 = asyncio.run(send_requests())

    assert r1.status_code == 200
    assert r1.headers["x-request-id"] == "req-custom99"
    assert "x-response-time-ms" in r1.headers
    assert float(r1.headers["x-response-time-ms"]) >= 0

    assert r2.status_code == 200
    assert r2.headers["x-request-id"].startswith("req-")
    assert r2.headers["x-request-id"] != "req-custom99"
    assert "x-response-time-ms" in r2.headers

    lines = log_path.read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines]

    # Verify context enrichment on api logs
    api_events = [e for e in events if e.get("service") == "api"]
    for e in api_events:
        assert "correlation_id" in e and e["correlation_id"] != "MISSING"
        assert "user_id_hash" in e
        assert "session_id" in e
        assert "feature" in e
        assert "model" in e
        assert "env" in e

    # Verify PII scrubbing in logs
    raw_logs = log_path.read_text(encoding="utf-8")
    assert "student@vinuni.edu.vn" not in raw_logs
    assert "0901234567" not in raw_logs
    assert "4111 1111 1111 1111" not in raw_logs
    assert "001099123456" not in raw_logs
    assert "REDACTED_EMAIL" in raw_logs
    assert "REDACTED_PHONE_VN" in raw_logs
    assert "REDACTED_CREDIT_CARD" in raw_logs
    assert "REDACTED_CCCD" in raw_logs

