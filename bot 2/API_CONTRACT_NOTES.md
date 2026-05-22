# API Contract Notes

All client apps should depend on stable response shapes.

## Critical Endpoints

- `GET /api/health`
- `GET /api/markets`
- `GET /api/analyze`
- `GET /api/live-snapshot`
- `GET /api/top-setups`
- `POST /api/execute`
- `GET /api/trade-journal`
- `GET /api/journal-analytics`

## Required Stability

These fields should stay aligned across all clients:

- `direction`
- `confidence`
- `decision_score`
- `risk_level`
- `live_sentiment`
- `live_payout`
- `support_resistance`
- `breakout_structure`
- `decision_reasons`
- `live_analysis_steps`

## Next Refactor

Create a shared schema module so Telegram, Web, Desktop, and Mobile consume the same backend contracts without frontend-specific branching.
