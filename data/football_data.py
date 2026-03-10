"""
football-data.org Integration (FREE_PLUS_THREE Tier)
- Historical match results for Dixon-Coles fitting
- Standings and team form
- 10 requests/minute rate limit
"""

import time
import logging
import requests
from datetime import datetime, timedelta
from config import Config

logger = logging.getLogger(__name__)

BASE_URL = "https://api.football-data.org/v4"


class FootballDataOrg:
    def __init__(self):
        self.headers = {"X-Auth-Token": Config.FOOTBALL_DATA_API_KEY}
        self._last_request = 0

    def _rate_limit(self):
        """Enforce ~6 requests/minute to stay safe under free tier."""
        elapsed = time.time() - self._last_request
        if elapsed < 10:
            time.sleep(10 - elapsed)
        self._last_request = time.time()

    def _get(self, endpoint: str, params: dict = None) -> dict | None:
        self._rate_limit()
        try:
            resp = requests.get(
                f"{BASE_URL}/{endpoint}",
                headers=self.headers,
                params=params or {},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"football-data.org error: {e}")
            return None

    def get_matches(
        self, league_code: str, season: int = None, matchday: int = None
    ) -> list[dict]:
        """
        Get match results for a league.
        Used to build the historical dataset for Dixon-Coles.
        """
        params = {}
        if season:
            params["season"] = season
        if matchday:
            params["matchday"] = matchday

        data = self._get(f"competitions/{league_code}/matches", params)
        if not data:
            return []

        matches = []
        for m in data.get("matches", []):
            if m["status"] != "FINISHED":
                continue
            matches.append(
                {
                    "date": m["utcDate"],
                    "matchday": m.get("matchday"),
                    "home_team": m["homeTeam"]["name"],
                    "away_team": m["awayTeam"]["name"],
                    "home_goals": m["score"]["fullTime"]["home"],
                    "away_goals": m["score"]["fullTime"]["away"],
                    "league": league_code,
                    "season": season or self._extract_season(m["utcDate"]),
                }
            )

        logger.info(f"Fetched {len(matches)} finished matches for {league_code}")
        return matches

    def get_upcoming_matches(self, league_code: str) -> list[dict]:
        """Get scheduled (not yet played) matches."""
        params = {"status": "SCHEDULED"}
        data = self._get(f"competitions/{league_code}/matches", params)
        if not data:
            return []

        upcoming = []
        for m in data.get("matches", []):
            upcoming.append(
                {
                    "date": m["utcDate"],
                    "matchday": m.get("matchday"),
                    "home_team": m["homeTeam"]["name"],
                    "away_team": m["awayTeam"]["name"],
                    "league": league_code,
                }
            )
        return upcoming

    def get_standings(self, league_code: str, season: int = None) -> list[dict]:
        """Current league standings — useful for context and team strength proxy."""
        params = {}
        if season:
            params["season"] = season

        data = self._get(f"competitions/{league_code}/standings", params)
        if not data:
            return []

        standings = []
        for table in data.get("standings", []):
            if table["type"] != "TOTAL":
                continue
            for entry in table.get("table", []):
                standings.append(
                    {
                        "position": entry["position"],
                        "team": entry["team"]["name"],
                        "played": entry["playedGames"],
                        "won": entry["won"],
                        "draw": entry["draw"],
                        "lost": entry["lost"],
                        "goals_for": entry["goalsFor"],
                        "goals_against": entry["goalsAgainst"],
                        "goal_diff": entry["goalDifference"],
                        "points": entry["points"],
                    }
                )
        return standings

    def get_historical_seasons(
        self, league_code: str, num_seasons: int = 2
    ) -> list[dict]:
        """
        Pull multiple seasons of match data for Dixon-Coles fitting.
        This is the core dataset your model trains on.
        """
        current_year = datetime.now().year
        all_matches = []

        for i in range(num_seasons):
            season = current_year - 1 - i  # e.g., 2024, 2023
            matches = self.get_matches(league_code, season=season)
            all_matches.extend(matches)
            logger.info(f"  Season {season}: {len(matches)} matches")

        return all_matches

    def _extract_season(self, date_str: str) -> int:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.year if dt.month >= 7 else dt.year - 1
