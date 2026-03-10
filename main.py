"""
Soccer Betting Bot — Main Orchestrator

Runs on Railway via APScheduler. Three core jobs:
1. ODDS PULL — Snapshot odds every 6 hours
2. MODEL RUN — Predict & alert 2-3 hours before kickoff windows
3. RESULTS   — Settle bets, update CLV, log P&L nightly

Usage:
    python main.py              # Run scheduler (production)
    python main.py --run-now    # One-shot run for testing
    python main.py --fit-model  # Refit model on historical data
"""

import sys
import logging
import argparse
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler

from config import Config
from data.odds_api import OddsAPI
from data.football_data import FootballDataOrg
from data.api_football import APIFootball
from model.dixon_coles import DixonColesModel
from model.ev_calculator import EVCalculator
from alerts.telegram_bot import TelegramBot
from storage.database import Database

# ─── Logging ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log"),
    ],
)
logger = logging.getLogger("main")

# ─── Globals ───────────────────────────────────────────────
odds_api = OddsAPI()
football_data = FootballDataOrg()
api_football = APIFootball()
telegram = TelegramBot()
db = Database()

# Models per league (fitted separately)
models = {}


# ═══════════════════════════════════════════════════════════
# JOB 1: FIT MODELS
# ═══════════════════════════════════════════════════════════
def fit_models():
    """
    Fit Dixon-Coles model for each league on historical data.
    Run on startup and weekly (e.g., Monday morning).
    """
    logger.info("═══ FITTING MODELS ═══")

    for league_code, sport_key in Config.FOOTBALL_DATA_LEAGUES.items():
        logger.info(f"Fitting model for {league_code}...")

        # Pull 2 seasons of historical results
        matches = football_data.get_historical_seasons(league_code, num_seasons=2)

        if len(matches) < 100:
            logger.warning(
                f"Only {len(matches)} matches for {league_code} — "
                f"need more data for reliable model"
            )
            continue

        # Also add current season matches
        current_season = datetime.now().year
        current = football_data.get_matches(league_code, season=current_season)
        matches.extend(current)

        # Deduplicate by date + teams
        seen = set()
        unique = []
        for m in matches:
            key = f"{m['date']}_{m['home_team']}_{m['away_team']}"
            if key not in seen:
                seen.add(key)
                unique.append(m)

        logger.info(f"Total unique matches for {league_code}: {len(unique)}")

        # Fit the model
        model = DixonColesModel()
        model.fit(unique)

        if model.is_fitted:
            models[league_code] = model
            db.log_model_params(league_code, model)

            # Send power ratings to Telegram
            ratings = model.get_team_ratings()
            telegram.send_model_update(ratings, league_code)

            logger.info(f"Model fitted for {league_code} ✓")
        else:
            logger.error(f"Model fitting FAILED for {league_code}")


# ═══════════════════════════════════════════════════════════
# JOB 2: PULL ODDS & SNAPSHOT
# ═══════════════════════════════════════════════════════════
def pull_odds():
    """
    Pull odds from all bookmakers and store snapshots.
    Runs every 6 hours to build CLV data.
    """
    logger.info("═══ PULLING ODDS ═══")

    all_matches = odds_api.get_all_upcoming()
    logger.info(f"Pulled odds for {len(all_matches)} matches")

    for match in all_matches:
        db.log_odds_snapshot(match)

    logger.info(f"Odds snapshot stored. API remaining: {odds_api.remaining_requests}")


# ═══════════════════════════════════════════════════════════
# JOB 3: EVALUATE & ALERT (THE MONEY JOB)
# ═══════════════════════════════════════════════════════════
def evaluate_and_alert():
    """
    Run model predictions against current odds.
    Send BET alerts to Telegram for +EV opportunities.
    """
    logger.info("═══ EVALUATING MATCHES ═══")

    if not models:
        logger.warning("No fitted models — run fit_models first")
        fit_models()

    all_matches = odds_api.get_all_upcoming()
    all_bets = []
    pass_count = 0

    for match in all_matches:
        sport = match.get("sport", "")
        commence = match.get("commence_time", "")

        # Only evaluate matches within the pre-match window
        try:
            kickoff = datetime.fromisoformat(commence.replace("Z", "+00:00"))
            hours_until = (kickoff - datetime.now(timezone.utc)).total_seconds() / 3600
            if hours_until < 0 or hours_until > 24:
                continue
        except Exception:
            continue

        # Find the right model for this sport
        league_code = None
        for code, mapped_sport in Config.FOOTBALL_DATA_LEAGUES.items():
            if mapped_sport in sport or sport in Config.ODDS_API_SPORTS:
                # Match Odds API sport key to our league code
                sport_to_league = {
                    "soccer_epl": "PL",
                    "soccer_germany_bundesliga": "BL1",
                    "soccer_spain_la_liga": "PD",
                }
                league_code = sport_to_league.get(sport)
                break

        if not league_code or league_code not in models:
            continue

        model = models[league_code]
        home = match["home_team"]
        away = match["away_team"]

        # Check if teams are in our model
        if home not in model.teams or away not in model.teams:
            # Try fuzzy matching (team names may differ between APIs)
            home = _fuzzy_match_team(home, model.teams) or home
            away = _fuzzy_match_team(away, model.teams) or away

        # Get prediction
        prediction = model.predict_match(home, away)

        # Evaluate against odds
        ev_calc = EVCalculator(model)
        opportunities = ev_calc.evaluate_match(match, prediction)

        for opp in opportunities:
            db.log_signal(opp, league=league_code)

            if opp["signal"] == "BET":
                telegram.send_bet_alert(opp)
                all_bets.append(opp)
                logger.info(
                    f"🟢 BET: {opp['match']} | {opp['market']} {opp['selection']} "
                    f"@ {opp['best_odds']} | EV: {opp['ev']*100:+.1f}%"
                )
            else:
                pass_count += 1

    # Send daily summary
    telegram.send_daily_summary(all_bets, pass_count)
    logger.info(f"Evaluation complete: {len(all_bets)} bets, {pass_count} passes")


# ═══════════════════════════════════════════════════════════
# JOB 4: SETTLE RESULTS
# ═══════════════════════════════════════════════════════════
def settle_results():
    """
    Check completed matches, settle bets, calculate P&L and CLV.
    Runs nightly.
    """
    logger.info("═══ SETTLING RESULTS ═══")

    unsettled = db.get_unsettled_bets()
    if not unsettled:
        logger.info("No unsettled bets")
        return

    results = []
    for bet in unsettled:
        home = bet["home_team"]
        away = bet["away_team"]

        # Try to find the result from football-data.org
        for league_code in Config.FOOTBALL_DATA_LEAGUES:
            matches = football_data.get_matches(league_code)
            for m in matches:
                if (
                    _teams_match(m["home_team"], home)
                    and _teams_match(m["away_team"], away)
                    and m.get("home_goals") is not None
                ):
                    # Get closing odds from our last snapshot
                    # (simplified — in production you'd query the snapshot table)
                    closing_odds = bet["best_odds"]  # Placeholder

                    result = db.settle_bet(
                        bet["id"],
                        m["home_goals"],
                        m["away_goals"],
                        closing_odds,
                    )
                    if result:
                        result["match"] = bet["match_name"]
                        result["market"] = bet["market"]
                        result["selection"] = bet["selection"]
                        result["actual_score"] = f"{m['home_goals']}-{m['away_goals']}"
                        results.append(result)
                    break

    if results:
        telegram.send_results_update(results)

    logger.info(f"Settled {len(results)} bets")


# ═══════════════════════════════════════════════════════════
# JOB 5: WEEKLY REPORT
# ═══════════════════════════════════════════════════════════
def weekly_report():
    """Send weekly performance summary."""
    logger.info("═══ WEEKLY REPORT ═══")
    stats = db.get_performance_stats(days=7)
    telegram.send_weekly_report(stats)


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════
def _fuzzy_match_team(name: str, known_teams: list[str]) -> str | None:
    """
    Simple fuzzy matching for team names across APIs.
    E.g., "Arsenal FC" vs "Arsenal" vs "Arsenal London"
    """
    name_lower = name.lower().replace("fc", "").replace("cf", "").strip()

    for team in known_teams:
        team_lower = team.lower().replace("fc", "").replace("cf", "").strip()
        if name_lower in team_lower or team_lower in name_lower:
            return team

    # Try matching first word (e.g., "Barcelona" matches "FC Barcelona")
    first_word = name_lower.split()[0] if name_lower else ""
    for team in known_teams:
        if first_word and first_word in team.lower():
            return team

    return None


def _teams_match(team1: str, team2: str) -> bool:
    """Check if two team names refer to the same team."""
    t1 = team1.lower().replace("fc", "").replace("cf", "").strip()
    t2 = team2.lower().replace("fc", "").replace("cf", "").strip()
    return t1 in t2 or t2 in t1


# ═══════════════════════════════════════════════════════════
# SCHEDULER (Railway keeps this alive)
# ═══════════════════════════════════════════════════════════
def run_scheduler():
    """Production scheduler — runs on Railway."""
    logger.info("🚀 Starting Soccer Betting Bot")

    # Fit models on startup
    fit_models()

    scheduler = BlockingScheduler()

    # Pull odds every 6 hours
    scheduler.add_job(
        pull_odds, "interval", hours=Config.ODDS_PULL_INTERVAL_HOURS, id="odds_pull"
    )

    # Evaluate matches at key times (before major kickoff windows)
    # European matches: ~11:00 UTC, ~14:00 UTC, ~17:00 UTC, ~19:00 UTC
    for hour in [8, 11, 14, 17, 19]:
        scheduler.add_job(
            evaluate_and_alert,
            "cron",
            hour=hour,
            minute=0,
            id=f"eval_{hour}",
        )

    # Settle results nightly at 23:00 UTC
    scheduler.add_job(settle_results, "cron", hour=23, minute=0, id="settle")

    # Refit models every Monday at 06:00 UTC
    scheduler.add_job(
        fit_models, "cron", day_of_week="mon", hour=6, minute=0, id="refit"
    )

    # Weekly report every Sunday at 20:00 UTC
    scheduler.add_job(
        weekly_report, "cron", day_of_week="sun", hour=20, minute=0, id="weekly"
    )

    logger.info("Scheduler started. Jobs registered:")
    for job in scheduler.get_jobs():
        logger.info(f"  → {job.id}: {job.trigger}")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Soccer Betting Bot")
    parser.add_argument(
        "--run-now", action="store_true", help="One-shot evaluation run"
    )
    parser.add_argument(
        "--fit-model", action="store_true", help="Fit models only"
    )
    parser.add_argument(
        "--settle", action="store_true", help="Settle results only"
    )
    parser.add_argument(
        "--test-telegram", action="store_true", help="Send test message"
    )
    args = parser.parse_args()

    if args.fit_model:
        fit_models()
    elif args.run_now:
        fit_models()
        evaluate_and_alert()
    elif args.settle:
        settle_results()
    elif args.test_telegram:
        telegram.send_message("🤖 Soccer Betting Bot is alive! ✅")
    else:
        run_scheduler()
