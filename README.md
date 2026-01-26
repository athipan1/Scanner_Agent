# Scanner_Agent

This is a market scanner agent for a multi-agent trading system.

## GitHub Actions

### Alpaca Connection Test

This repository includes a GitHub Action that tests the connection to the Alpaca API on every push to the `main` branch. To enable this action, you must configure the following secrets in your repository's settings (`Settings` > `Secrets and variables` > `Actions`):

- `APCA_API_KEY_ID`: Your Alpaca API key ID.
- `APCA_API_SECRET_KEY`: Your Alpaca API secret key.
