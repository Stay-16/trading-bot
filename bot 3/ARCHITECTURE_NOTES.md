# Binary Options Bot Architecture

The bot now follows the architecture in `binary_options_bot_architecture.svg` through explicit layers.

## Layer 1: Data Layer

- File: `data_layer.py`
- Responsibility:
  - Fetch TradingView market analysis
  - Cache market snapshots
  - Normalize market context such as volatility and trend strength

## Layer 2: Signal Engine

- File: `signal_engine.py`
- Responsibility:
  - Produce traditional signals from market analysis
  - Extract AI features from indicators
  - Run the current ML model
  - Detect candle pattern context

## Layer 3: Decision Core

- Files: `decision_core.py`, `decision_engine.py`
- Responsibility:
  - Combine traditional signal, AI signal, candle pattern, trend filter, and volatility filter
  - Use weighted voting to decide `call`, `put`, or `neutral`
  - Produce a confidence score and decision reasons

## Layer 4: Risk Management

- File: `risk_management.py`
- Responsibility:
  - Prevent trading after too many consecutive losses
  - Enforce daily loss limits
  - Calculate dynamic position size from balance and confidence

## Layer 5: Execution Layer

- File: `execution_layer.py`
- Responsibility:
  - Check broker connectivity
  - Fetch current balance
  - Submit execution requests to Quotex

## Orchestration

- File: `trading_orchestrator.py`
- Responsibility:
  - Coordinate end-to-end flow across all layers
  - Provide one analysis path and one execution preparation path to the Telegram bot

## Configuration

- File: `bot_config.py`
- Loads environment variables from `.env` automatically when present
- Keeps secrets outside source code

## Asset Mapping

- File: `asset_mapping.py`
- Responsibility:
  - Normalize Quotex asset symbols
  - Infer market type and TradingView compatibility
  - Convert asset naming for display and internal routing
  - Build and register live asset entries from broker payloads

## Current Status

- `trading_bot.py` remains the Telegram entry point and UI/controller layer
- The main user flow now routes through the new layered orchestrator
- Legacy functions are still present for compatibility and fallback, but the preferred path is the layered one
- `webapp_server.py` exposes the same live-market and analysis engine through HTTP endpoints for the Telegram WebApp
- `webapp_index.html`, `webapp_styles.css`, and `webapp_app.js` provide a Quotex-style dashboard for live markets, top setups, and detailed signal inspection

## WebApp

- Configure `WEBAPP_URL` in `.env` with your public HTTPS URL
- Run the WebApp server with `python run_webapp.py`
- The Telegram bot will show an `Open Web Dashboard` button automatically when `WEBAPP_URL` is configured

## Recommended Next Step

1. Add paper-trading mode as a first-class execution backend
2. Add unit tests for decision and risk layers
3. Move legacy fallback logic out of `trading_bot.py` once stable
