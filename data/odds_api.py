"""
Odds API Integration (Paid Tier)
- Pulls odds from multiple bookmakers for de-vigging
- Markets: 1X2 (h2h), Over/Under (totals), BTTS
- Snapshots stored for CLV tracking
"""

import time
import logging
import requests
from datetime import datetime, timezone
from config import Config

logger = logging.getLogger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4"


class OddsAPI:
    def __init__(self):
        self.api_key = Config.ODDS_API_KEY
        self.remaining_requests = None
        self.used_requests = None

    def _get(self, endpoint: str, params: dict) -> dict | None:
        params["apiKey"] = self.api_key
        try:
            resp = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=15)
            # Track quota usage
            self.remaining_requests = resp.headers.get("x-requests-remaining")
            self.used_requests = resp.headers.get("x-requests-used")
            logger.info(
                f"Odds API quota: {self.used_requests} used, {self.remaining_requests} remaining"
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Odds API error: {e}")
            return None

    def get_upcoming_odds(self, sport: str, markets: list[str] = None) -> list[dict]:
        """
        Pull upcoming match odds with all available bookmakers.
        Returns enriched match data with odds from every book.
        """
        if markets is None:
            markets = ["h2h", "totals"]

        params = {
            "regions": "us,uk,eu,au",  # Max bookmaker coverage for better de-vig
            "markets": ",".join(markets),
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }

        data = self._get(f"sports/{sport}/odds", params)
        if not data:
            return []

        matches = []
        for event in data:
            match = {
                "id": event["id"],
                "sport": sport,
                "home_team": event["home_team"],
                "away_team": event["away_team"],
                "commence_time": event["commence_time"],
                "snapshot_time": datetime.now(timezone.utc).isoformat(),
                "bookmakers": {},
                "markets": {},
            }

            for bookmaker in event.get("bookmakers", []):
                bk_key = bookmaker["key"]
                bk_title = bookmaker["title"]
                match["bookmakers"][bk_key] = bk_title

                for market in bookmaker.get("markets", []):
                    mkt_key = market["key"]
                    if mkt_key not in match["markets"]:
                        match["markets"][mkt_key] = {}

                    outcomes = {}
                    for outcome in market.get("outcomes", []):
                        name = outcome["name"]
                        price = outcome["price"]
                        point = outcome.get("point")  # For totals (e.g., 2.5)
                        key = f"{name}_{point}" if point else name
                        outcomes[key] = {
                            "name": name,
                            "price": price,
                            "point": point,
                        }

                    match["markets"][mkt_key][bk_key] = outcomes

            matches.append(match)

        logger.info(f"Pulled {len(matches)} matches for {sport}")
        return matches

    def get_all_upcoming(self) -> list[dict]:
        """Pull odds across all configured leagues."""
        all_matches = []
        for sport in Config.ODDS_API_SPORTS:
            matches = self.get_upcoming_odds(sport, Config.MARKETS)
            all_matches.extend(matches)
            time.sleep(0.5)  # Respect rate limits
        return all_matches

    def extract_best_odds(self, match: dict, market: str) -> dict:
        """
        Find the best available odds across all bookmakers for a market.
        Returns {outcome_name: {price, bookmaker}} for the best price on each outcome.
        """
        best = {}
        market_data = match.get("markets", {}).get(market, {})

        for bk_key, outcomes in market_data.items():
            for key, outcome in outcomes.items():
                if key not in best or outcome["price"] > best[key]["price"]:
                    best[key] = {
                        "name": outcome["name"],
                        "price": outcome["price"],
                        "point": outcome.get("point"),
                        "bookmaker": bk_key,
                        "bookmaker_title": match["bookmakers"].get(bk_key, bk_key),
                    }

        return best

    def get_all_bookmaker_odds(self, match: dict, market: str) -> dict:
        """
        Get odds from all bookmakers for a specific market.
        Returns {outcome_key: [list of (price, bookmaker)]} for de-vig calculations.
        """
        all_odds = {}
        market_data = match.get("markets", {}).get(market, {})

        for bk_key, outcomes in market_data.items():
            for key, outcome in outcomes.items():
                if key not in all_odds:
                    all_odds[key] = []
                all_odds[key].append(
                    {"price": outcome["price"], "bookmaker": bk_key}
                )

        return all_odds
