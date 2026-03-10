import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # API Keys
    ODDS_API_KEY = os.getenv("ODDS_API_KEY")
    FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")
    API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")

    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

    # Model
    MIN_EV_THRESHOLD = float(os.getenv("MIN_EV_THRESHOLD", 0.03))
    KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", 0.25))
    BANKROLL = float(os.getenv("BANKROLL", 1000))
    TIME_DECAY_HALF_LIFE = int(os.getenv("TIME_DECAY_HALF_LIFE", 35))
    XG_BLEND_WEIGHT = float(os.getenv("XG_BLEND_WEIGHT", 0.6))

    # Scheduling
    ODDS_PULL_INTERVAL_HOURS = int(os.getenv("ODDS_PULL_INTERVAL_HOURS", 6))
    PRE_MATCH_HOURS = int(os.getenv("PRE_MATCH_HOURS", 3))

    # Leagues — football-data.org codes for your FREE_PLUS_THREE picks
    # PL = Premier League, BL1 = Bundesliga, PD = La Liga
    # SA = Serie A, FL1 = Ligue 1, CL = Champions League
    FOOTBALL_DATA_LEAGUES = {
        "PL": "england_premier_league",
        "BL1": "germany_bundesliga",
        "PD": "spain_la_liga",
    }

    # Odds API sport keys (soccer)
    ODDS_API_SPORTS = [
        "soccer_epl",
        "soccer_germany_bundesliga",
        "soccer_spain_la_liga",
    ]

    # API-Football league IDs
    API_FOOTBALL_LEAGUES = {
        "soccer_epl": 39,
        "soccer_germany_bundesliga": 78,
        "soccer_spain_la_liga": 140,
    }

    # Markets to pull
    MARKETS = ["h2h", "totals", "btts"]

    # Database
    DB_PATH = os.getenv("DB_PATH", "data/betting_bot.db")
