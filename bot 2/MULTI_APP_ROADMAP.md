# Product Roadmap

This project is now focused on a tighter and stronger product surface:

- Telegram bot
- Telegram Mini App
- Web dashboard

The goal is to keep one backend and one shared trading engine, while using Telegram and the browser as the two main user surfaces.

## Product Direction

The backend already contains the right core layers:

- `data_layer.py`
- `signal_engine.py`
- `decision_core.py`
- `decision_engine.py`
- `risk_management.py`
- `execution_layer.py`
- `trading_orchestrator.py`

The next step is to keep these layers as a platform backend and make both Web and Telegram thin clients.

## Target Architecture

### Backend Core

- Python
- FastAPI
- Shared trading engine
- Shared execution and risk rules
- Shared live analysis pipeline

### Client Surfaces

- Telegram bot: commands, alerts, quick actions
- Telegram Mini App: in-app visual dashboard inside Telegram
- Web dashboard: browser access and larger-screen control

## Why this direction is better now

- Lower maintenance cost
- Fewer moving parts
- Faster iteration
- One UI logic path instead of several separate app shells
- Telegram Mini App gives mobile access without a separate mobile build pipeline

## Delivery Order

### Phase 1: Backend Stability

1. Stabilize execution and Quotex connectivity
2. Reduce timeouts and polling pressure
3. Improve health diagnostics and logs
4. Keep risk rules strict

### Phase 2: Web Dashboard

1. Improve live market board
2. Improve scanner quality
3. Improve journal and analytics
4. Improve execution feedback and failure diagnostics

### Phase 3: Telegram Surface

1. Keep `/start`, `/stats`, `/performance`, and trade actions clean
2. Improve callback flows
3. Make Mini App launch smooth from Telegram
4. Share the same API and execution rules used by the web dashboard

## API First Rules

Both Web and Telegram should consume the same backend concepts:

- `/api/health`
- `/api/markets`
- `/api/analyze`
- `/api/live-snapshot`
- `/api/top-setups`
- `/api/execute`
- `/api/trade-journal`
- `/api/journal-analytics`

Clients must not duplicate trading logic locally.

## Definition Of Success

The system is successful when:

- Telegram bot and Web dashboard read the same live analysis engine
- Confidence, recommendation, and execution rules remain identical everywhere
- Mini App opens the same dashboard experience from inside Telegram
- UI changes do not require changing trading logic
