"""Tests never reach a search engine."""

import pytest


@pytest.fixture(autouse=True)
def _no_web_search(monkeypatch):
    from hamenagen import websearch

    monkeypatch.setattr(websearch, "http_get", lambda url, timeout=8: "")
