from alpaca.trading.client import TradingClient
import os
import sys

def check_alpaca_connection():
    """
    Tests the connection to the Alpaca API using the alpaca-py SDK.
    Exits with code 0 on success, 1 on failure.
    """
    api_key = os.getenv("APCA_API_KEY_ID")
    secret_key = os.getenv("APCA_API_SECRET_KEY")

    # Paper trading is the default, which is what we want for testing.
    # The SDK automatically uses the paper endpoint if paper=True.

    if not api_key or not secret_key:
        print("Error: APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set as environment variables.")
        sys.exit(1)

    try:
        # Initialize the trading client
        trading_client = TradingClient(api_key, secret_key, paper=True)

        # Get account information
        account = trading_client.get_account()

        if account.status == 'ACTIVE':
            print("Successfully connected to Alpaca API.")
            print(f"Account Status: {account.status}")
            sys.exit(0)
        else:
            print(f"Connected to Alpaca, but account is not active. Status: {account.status}")
            sys.exit(1)

    except Exception as e:
        print(f"Failed to connect to Alpaca API: {e}")
        sys.exit(1)

def test_alpaca_connection(monkeypatch):
    """Exercise the CLI contract without credentials or broker network access."""
    import pytest
    from types import SimpleNamespace

    calls = []
    monkeypatch.setenv("APCA_API_KEY_ID", "fixture-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "fixture-secret")

    def client(key, secret, *, paper):
        calls.append((key, secret, paper))
        return SimpleNamespace(get_account=lambda: SimpleNamespace(status="ACTIVE"))

    monkeypatch.setitem(check_alpaca_connection.__globals__, "TradingClient", client)
    with pytest.raises(SystemExit) as result:
        check_alpaca_connection()
    assert result.value.code == 0
    assert calls == [("fixture-key", "fixture-secret", True)]


def test_alpaca_connection_missing_credentials(monkeypatch):
    import pytest
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    with pytest.raises(SystemExit) as result:
        check_alpaca_connection()
    assert result.value.code == 1


if __name__ == "__main__":
    check_alpaca_connection()
