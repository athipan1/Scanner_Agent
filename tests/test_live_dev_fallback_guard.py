from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app, _mock_candidates

client = TestClient(app)
HEADERS = {"X-API-KEY": "test-key"}


def test_health_exposes_dev_fallback_status():
    with (
        patch("app.main.settings.TRADING_MODE", "LIVE"),
        patch("app.main.settings.SCANNER_DEV_MODE", True),
    ):
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {"message": "healthy"}
    metadata = body["metadata"]
    assert metadata["trading_mode"] == "LIVE"
    assert metadata["scanner_dev_mode"] is True
    assert metadata["dev_fallback_allowed"] is False


def test_mock_candidates_forbidden_in_live():
    with (
        patch("app.main.settings.TRADING_MODE", "LIVE"),
        patch("app.main.settings.SCANNER_DEV_MODE", True),
    ):
        response_error = None
        try:
            _mock_candidates(["AAPL"], "technical")
        except Exception as exc:
            response_error = exc

    assert response_error is not None
    assert getattr(response_error, "status_code", None) == 503


def test_technical_scan_rejects_dev_fallback_in_live():
    with (
        patch("app.main.settings.TRADING_MODE", "LIVE"),
        patch("app.main.settings.SCANNER_DEV_MODE", True),
        patch("app.main.scan_market", side_effect=RuntimeError("scanner down")),
    ):
        response = client.post("/scan", json={"symbols": ["AAPL"], "screener": "default", "exchange": "NASDAQ"})

    assert response.status_code == 503
    assert "dev fallback is forbidden" in response.json()["detail"]


def test_fundamental_scan_rejects_dev_fallback_in_live():
    with (
        patch("app.main.settings.TRADING_MODE", "LIVE"),
        patch("app.main.settings.SCANNER_DEV_MODE", True),
        patch("app.main.scan_long_term", side_effect=RuntimeError("scanner down")),
    ):
        response = client.post("/scan/fundamental", json={"symbols": ["AAPL"], "screener": "default", "exchange": "NASDAQ"})

    assert response.status_code == 503
    assert "dev fallback is forbidden" in response.json()["detail"]


def test_paper_mode_still_allows_dev_fallback_candidates():
    with (
        patch("app.main.settings.TRADING_MODE", "PAPER"),
        patch("app.main.settings.SCANNER_DEV_MODE", True),
        patch("app.main.scan_market", return_value=([], [])),
    ):
        response = client.post("/scan", json={"symbols": ["AAPL"], "screener": "default", "exchange": "NASDAQ"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["count"] == 1
    assert body["data"]["candidates"][0]["metadata"]["source"] == "dev_fallback"
