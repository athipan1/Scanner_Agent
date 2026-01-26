from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_scan_fundamental_endpoint_no_symbols():
    response = client.post("/scan/fundamental", json={})
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["status"] in ["partial_success", "success", "failure"]
    if response_json["data"] and response_json["data"]["candidates"]:
        assert "symbol" in response_json["data"]["candidates"][0]
        assert "grade" in response_json["data"]["candidates"][0]
        assert "fundamental_score" in response_json["data"]["candidates"][0]

def test_scan_fundamental_endpoint_with_symbols():
    response = client.post("/scan/fundamental", json={"symbols": ["AAPL", "GOOG"]})
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["status"] in ["partial_success", "success", "failure"]
    if response_json["data"] and response_json["data"]["candidates"]:
        assert len(response_json["data"]["candidates"]) <= 2
        candidate = response_json["data"]["candidates"][0]
        assert "symbol" in candidate
        assert "grade" in candidate
        assert "fundamental_score" in candidate
        assert "quality" in candidate
        assert "growth" in candidate
        assert "valuation" in candidate
        assert "thesis" in candidate
