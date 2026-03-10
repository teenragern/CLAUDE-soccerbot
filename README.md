# Soccer Betting Bot 🤖⚽

Dixon-Coles model + EV/de-vig calculator with Telegram alerts.
Designed to run 24/7 on Railway.

## Architecture

```
Data Layer          Model Layer          Output Layer
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│ Odds API    │───▶│ Dixon-Coles  │───▶│ Telegram    │
│ (paid tier) │    │ Poisson/xG   │    │ BET/PASS    │
├─────────────┤    ├──────────────┤    │ alerts      │
│ football-   │───▶│ De-Vig       │    ├─────────────┤
│ data.org    │    │ (Shin/Power) │    │ SQLite DB   │
├─────────────┤    ├──────────────┤    │ CLV + P&L   │
│ API-Football│───▶│ EV Calculator│    │ tracking    │
│ (xG/inj.)  │    │ Kelly sizing │    └─────────────┘
└─────────────┘    └──────────────┘
```

## Quick Start

### 1. Clone & install
```bash
git clone <your-repo>
cd soccer_betting_bot
pip install -r requirements.txt
```

### 2. Configure
```bash
cp .env.example .env
# Edit .env with your API keys and Telegram bot token
```

### 3. Test locally
```bash
# Test Telegram connection
python main.py --test-telegram

# Fit models (takes ~2 min)
python main.py --fit-model

# Run one evaluation cycle
python main.py --run-now
```

### 4. Deploy to Railway
```bash
# Push to GitHub, connect repo in Railway dashboard
# Add all .env variables in Railway's Variables tab
# Railway auto-detects Procfile and starts the worker
```

## Scheduled Jobs

| Job              | Schedule                    | What it does                          |
|------------------|-----------------------------|---------------------------------------|
| `pull_odds`      | Every 6 hours               | Snapshot odds for CLV tracking        |
| `evaluate_alert` | 08:00, 11:00, 14:00, 17:00, 19:00 UTC | Model vs market, send BET alerts |
| `settle_results` | 23:00 UTC daily             | Grade bets, compute P&L and CLV       |
| `fit_models`     | Monday 06:00 UTC            | Refit Dixon-Coles on latest data      |
| `weekly_report`  | Sunday 20:00 UTC            | Performance summary to Telegram       |

## Key Files

- `main.py` — Orchestrator and scheduler
- `model/dixon_coles.py` — Core prediction model
- `model/devig.py` — Shin/Power/Multiplicative de-vig methods
- `model/ev_calculator.py` — Edge detection and Kelly sizing
- `data/odds_api.py` — Odds API integration (multi-book)
- `data/football_data.py` — Historical results and standings
- `data/api_football.py` — xG, injuries, lineups
- `data/team_names.py` — Cross-API team name mapping
- `alerts/telegram_bot.py` — Formatted alerts
- `storage/database.py` — SQLite bet logging and performance tracking

## Tuning Guide

| Parameter              | Default | Aggressive | Conservative |
|------------------------|---------|------------|--------------|
| `MIN_EV_THRESHOLD`     | 0.03    | 0.02       | 0.05         |
| `KELLY_FRACTION`       | 0.25    | 0.50       | 0.10         |
| `TIME_DECAY_HALF_LIFE` | 35      | 25         | 50           |
| `XG_BLEND_WEIGHT`      | 0.60    | 0.70       | 0.40         |

## Adding Leagues

1. Add the league code to `Config.FOOTBALL_DATA_LEAGUES`
2. Add the Odds API sport key to `Config.ODDS_API_SPORTS`
3. Add the API-Football league ID to `Config.API_FOOTBALL_LEAGUES`
4. Add team name mappings in `data/team_names.py`
5. Refit models: `python main.py --fit-model`
