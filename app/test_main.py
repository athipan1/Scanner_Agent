from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    json_data = response.json()
    assert json_data["status"] == "success"
    assert json_data["agent_type"] == "scanner"
    assert json_data["data"] == {"message": "healthy"}

def test_scan_fundamental_endpoint_no_symbols():
    response = client.post("/scan/fundamental", json={})
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["status"] in ["success", "error"]
    assert "agent_type" in response_json
    assert "timestamp" in response_json
    if response_json["data"]:
        assert "candidates" in response_json["data"]
        assert isinstance(response_json["data"]["candidates"], list)

def test_scan_fundamental_endpoint_with_symbols():
    response = client.post("/scan/fundamental", json={"symbols": ["AAPL", "GOOG"]})
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["status"] in ["success", "error"]
    if response_json["data"]:
        assert "candidates" in response_json["data"]
        assert len(response_json["data"]["candidates"]) <= 2

def test_scan_endpoint():
    response = client.post("/scan", json={"symbols": ["AAPL", "MSFT"]})
    assert response.status_code == 200
    response_json = response.json()
    assert "agent_type" in response_json
    assert "status" in response_json
    if response_json["data"]:
        assert "candidates" in response_json["data"]
