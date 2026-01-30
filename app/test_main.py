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
    assert "agent" in response_json
    assert "timestamp" in response_json
    if response_json["data"]:
        assert "symbols" in response_json["data"]
        assert isinstance(response_json["data"]["symbols"], list)

def test_scan_fundamental_endpoint_with_symbols():
    response = client.post("/scan/fundamental", json={"symbols": ["AAPL", "GOOG"]})
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["status"] in ["partial_success", "success", "failure"]
    if response_json["data"]:
        assert "symbols" in response_json["data"]
        assert len(response_json["data"]["symbols"]) <= 2

def test_scan_endpoint():
    response = client.post("/scan", json={"symbols": ["AAPL", "MSFT"]})
    assert response.status_code == 200
    response_json = response.json()
    assert "agent" in response_json
    assert "status" in response_json
    if response_json["data"]:
        assert "symbols" in response_json["data"]
