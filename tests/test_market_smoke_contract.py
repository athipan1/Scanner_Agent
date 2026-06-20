from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import ErrorDetail

client = TestClient(app)


def test_us_default_inputs_return_real_watchlist_when_strict_scan_has_no_candidates():
    with patch("app.main.scan_market", return_value=([], [ErrorDetail(symbol="AAPL", error="no buy signal")])):
        response = client.post("/scan", json={"symbols": ["AAPL"], "screener": "default", "exchange": "US"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["count"] >= 0
    for candidate in body["data"]["candidates"]:
        assert candidate["metadata"].get("source") != "dev_fallback"


def test_fundamental_scan_no_candidates_does_not_use_dev_fallback():
    with patch("app.main.scan_long_term", return_value=([], [ErrorDetail(symbol="AAPL", error="missing financials")])):
        response = client.post("/scan/fundamental", json={"symbols": ["AAPL"], "screener": "default", "exchange": "US"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"success", "error"}
    for candidate in body["data"]["candidates"]:
        assert candidate["metadata"].get("source") != "dev_fallback"
