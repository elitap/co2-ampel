"""HTTP-Zugriff mit Timeouts, Retries, exponentiellem Backoff und Zeitbudget."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

USER_AGENT = "co2-ampel/1.0 (+https://github.com/elitap/co2-ampel)"
RETRY_STATUS = {429, 500, 502, 503, 504}


class Budget:
    """Zeitbudget (Sekunden) für eine Folge von Anfragen."""

    def __init__(self, seconds: float) -> None:
        self.deadline = time.monotonic() + seconds

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def exhausted(self) -> bool:
        return self.remaining() <= 0


@dataclass
class HttpResult:
    status: int
    body: bytes


class HttpClient:
    def __init__(
        self,
        timeout: tuple[float, float] = (10.0, 60.0),
        max_attempts: int = 5,
        backoff_base: float = 2.0,
        max_wait: float = 120.0,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self.max_wait = max_wait
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._sleep: Callable[[float], None] = time.sleep if sleep is None else sleep
        self.request_count = 0

    def get(
        self,
        url: str,
        params: Mapping[str, str] | None = None,
        budget: Budget | None = None,
        log_url: str | None = None,
    ) -> HttpResult | None:
        """GET mit Retries. Gibt None zurück, wenn kein verwertbares Ergebnis erzielt wurde.

        ``log_url`` ersetzt die URL in Logmeldungen (z. B. um Tokens nicht zu loggen).
        """
        shown = log_url or url
        for attempt in range(1, self.max_attempts + 1):
            if budget is not None and budget.exhausted():
                log.warning("Zeitbudget erschöpft, überspringe %s", shown)
                return None
            wait: float
            try:
                self.request_count += 1
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                log.warning("Versuch %d/%d für %s fehlgeschlagen: %s", attempt, self.max_attempts, shown,
                            type(exc).__name__)
                wait = self.backoff_base ** attempt + random.uniform(0, 1)  # noqa: S311
            else:
                if resp.status_code not in RETRY_STATUS:
                    return HttpResult(resp.status_code, resp.content)
                retry_after = resp.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    wait = float(retry_after) + random.uniform(0.5, 2.0)  # noqa: S311
                else:
                    wait = self.backoff_base ** attempt + random.uniform(0, 1)  # noqa: S311
                log.info("HTTP %d für %s, warte %.0f s (Versuch %d/%d)", resp.status_code, shown, wait,
                         attempt, self.max_attempts)
            if attempt == self.max_attempts:
                break
            wait = min(wait, self.max_wait)
            if budget is not None and wait > budget.remaining():
                log.warning("Wartezeit %.0f s übersteigt Restbudget, überspringe %s", wait, shown)
                return None
            self._sleep(wait)
        log.error("Keine Antwort für %s nach %d Versuchen", shown, self.max_attempts)
        return None
