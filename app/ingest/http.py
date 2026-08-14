from __future__ import annotations

import time

import httpx

from app.config import HTTP_TIMEOUT, USER_AGENT


def get_json(url: str, params: dict | None = None, retries: int = 3) -> dict | list:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with httpx.Client(timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
                response = client.get(url, params=params)
                if response.status_code == 429:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                response.raise_for_status()
                return response.json()
        except Exception as exc:  # noqa: BLE001 — ingest must keep going
            last_error = exc
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed: {last_error}")


def get_bytes(url: str, retries: int = 3) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with httpx.Client(timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
                response = client.get(url)
                if response.status_code == 429:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                response.raise_for_status()
                return response.content
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed: {last_error}")
