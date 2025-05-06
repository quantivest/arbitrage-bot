# Crypto Arbitrage Bot

A spot-to-spot crypto arbitrage bot with a web dashboard, supporting multiple exchanges and featuring live trading and test modes.

## Features

- Exchange integration with CCXT library
- Arbitrage detection algorithm with configurable buffer percentage
- WebSocket support for real-time updates
- Test mode with simulated trading
- Modern UI with React, TypeScript, and Tailwind CSS

## Deployment to DigitalOcean App Platform

This repository is configured for easy deployment to DigitalOcean App Platform.

### Prerequisites

- A DigitalOcean account
- GitHub repository connected to DigitalOcean

### Deployment Steps

1. Log in to your DigitalOcean account
2. Go to the App Platform section
3. Click "Create App"
4. Select GitHub as your source
5. Connect your GitHub account if not already connected
6. Select this repository
7. DigitalOcean will automatically detect the configuration in the `.do/app.yaml` file
8. Review the configuration and click "Launch App"

### Environment Variables

The following environment variables are required:

#### Backend
- `BUFFER_PERCENTAGE`: Default buffer percentage for arbitrage (default: 0.0001)
- `TEST_MODE_DEFAULT_CAPITAL`: Default capital for test mode (default: 10.0)

#### Frontend
- `API_URL`: URL of the backend API (automatically set by DigitalOcean)

## Local Development

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## License

MIT
