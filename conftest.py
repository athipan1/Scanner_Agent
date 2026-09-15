"""Unit/contract tests must supply provider evidence, never fetch live prices."""

import socket

import pytest


@pytest.fixture(autouse=True)
def no_live_provider_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise OSError("Live provider network is forbidden in unit tests; mock provider evidence")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    # yfinance uses libcurl, which does not pass through Python sockets.
    from curl_cffi.requests import Session
    monkeypatch.setattr(Session, "request", blocked)
