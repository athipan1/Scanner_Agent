import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models import StandardAgentResponse


REQUIRED_STANDARD_RESPONSE_FIELDS = {
    "status",
    "agent_type",
    "version",
    "schema_version",
    "timestamp",
    "correlation_id",
    "data",
    "metadata",
    "error",
    "confidence_score",
}


def assert_standard_response(payload):
    assert REQUIRED_STANDARD_RESPONSE_FIELDS.issubset(payload.keys())
    assert payload["agent_type"] == "scanner"
    assert payload["version"] == "1.2.0"
    assert payload["schema_version"] == "1.0"


def test_standard_response_has_contract_defaults():
    response = StandardAgentResponse(status="success", data={"ok": True})
    payload = response.model_dump(mode="json")

    assert REQUIRED_STANDARD_RESPONSE_FIELDS.issubset(payload.keys())
    assert payload["agent_type"] == "scanner"
    assert payload["version"] == "1.2.0"
    assert payload["schema_version"] == "1.0"
    assert payload["correlation_id"] is None
    assert payload["metadata"] == {}
    assert payload["confidence_score"] is None


def test_standard_response_rejects_invalid_schema_version():
    with pytest.raises(ValidationError):
        StandardAgentResponse(
            status="success",
            schema_version="v1",
            data={},
        )


def test_version_endpoint_uses_standard_contract():
    client = TestClient(app)
    response = client.get("/version")

    assert response.status_code == 200
    payload = response.json()
    assert_standard_response(payload)
    assert payload["data"]["api_contract"] == (
        "multi-agent-trading-api-contract"
    )
    assert payload["data"]["schema_version"] == "1.0"
    assert payload["data"]["service_version"] == "1.2.0"
    assert payload["data"]["bucket_hint_version"] == (
        "scanner-bucket-hints-v2"
    )
    assert payload["data"]["bucket_hint_policy_version"] == (
        "scanner-bucket-hint-policy-v3"
    )
    assert payload["metadata"]["generic_tag_bucket_hints"] is False


def test_ready_endpoint_uses_standard_contract():
    client = TestClient(app)
    response = client.get("/ready")

    assert response.status_code == 200
    payload = response.json()
    assert_standard_response(payload)
    assert "ready" in payload["data"]
    assert "dev_fallback_allowed" in payload["data"]
    assert payload["data"]["generic_tag_bucket_hints"] is False
    assert payload["metadata"]["contract_source"] == (
        "scanner-agent-runtime-contract"
    )


def test_health_endpoint_uses_standard_contract():
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert_standard_response(payload)
    assert payload["data"]["message"] == "healthy"
    assert "trading_mode" in payload["metadata"]
    assert payload["metadata"]["bucket_hint_policy_version"] == (
        "scanner-bucket-hint-policy-v3"
    )
