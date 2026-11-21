"""HTTP-Client: Retries, Backoff, Retry-After, Budget."""

from __future__ import annotations

from typing import Any

import requests

from co2ampel.http import Budget, HttpClient


class FakeResponse:
    def __init__(self, status: int, headers: dict[str, str] | None = None, content: bytes = b"ok") -> None:
        self.status_code = status
        self.headers = headers or {}
        self.content = content


class FakeSession(requests.Session):
    def __init__(self, responses: list[Any]) -> None:
        super().__init__()
        self.responses = responses
        self.n = 0

    def get(self, url: str | bytes, **kwargs: Any) -> Any:
        r = self.responses[self.n]
        self.n += 1
        if isinstance(r, Exception):
            raise r
        return r


def test_retry_after_is_honoured() -> None:
    sleeps: list[float] = []
    s = FakeSession([FakeResponse(429, {"Retry-After": "7"}), FakeResponse(200)])
    res = HttpClient(session=s, sleep=sleeps.append).get("https://x")
    assert res is not None and res.status == 200
    assert 7 <= sleeps[0] <= 9


def test_backoff_on_errors_then_give_up() -> None:
    sleeps: list[float] = []
    s = FakeSession([requests.ConnectionError(), FakeResponse(503), FakeResponse(502)])
    res = HttpClient(session=s, sleep=sleeps.append, max_attempts=3).get("https://x")
    assert res is None
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0] - 1


def test_404_is_not_retried() -> None:
    s = FakeSession([FakeResponse(404)])
    res = HttpClient(session=s, sleep=lambda _: None).get("https://x")
    assert res is not None and res.status == 404 and s.n == 1


def test_budget_stops_long_waits() -> None:
    s = FakeSession([FakeResponse(429, {"Retry-After": "600"}), FakeResponse(200)])
    res = HttpClient(session=s, sleep=lambda _: None).get("https://x", budget=Budget(5))
    assert res is None and s.n == 1
