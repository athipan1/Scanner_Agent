# Scanner_Agent

This is a market scanner agent for a multi-agent trading system.

## GitHub Actions

### Alpaca Connection Test

This repository includes a GitHub Action that tests the connection to the Alpaca API on every push to the `main` branch. To enable this action, you must configure the following secrets in your repository's settings (`Settings` > `Secrets and variables` > `Actions`):

- `APCA_API_KEY_ID`: Your Alpaca API key ID.
- `APCA_API_SECRET_KEY`: Your Alpaca API secret key.

### Continuous Integration

This repository also includes a Continuous Integration (CI) workflow that runs on every push and pull request to the `main` branch. This workflow installs the project's dependencies and runs the test suite to ensure that the code is functioning correctly.
