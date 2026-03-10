"""
API-Football Integration (Free Tier)
- ~100 requests/day — use surgically
- xG data for model enhancement
- Injuries/suspensions for lineup adjustments
- Pre-match lineups when available
"""

import time
import logging
import requests
from datetime import datetime, timezone
from config import Config

logger = logging.getLogger(__name__)

BASE_URL = "https://v3.football.api-sports.io"


class APIFootball:
    def __init__(self):
        self.headers = {
            "x-apisports-key": Config.API_FOOTBALL_KEY,
        }
        self._daily_calls = 0
        self._max_daily = 95  # Buffer under 100 limit

    def _can_call(self) -> bool:
        if self._daily_calls >= self._max_daily:
            logger.warning("API-Football daily limit approaching — skipping call")
            return False
        return True

    def _get(self, endpoint: str, params: dict) -> dict | None:
        if not self._can_call():
            return None

        try:
            resp = requests.get(
                f"{BASE_URL}/{endpoint}",
                headers=self.headers,
                params=params,
                timeout=15,
            )
            self._daily_calls += 1
            remaining = resp.headers.get("x-ratelimit-requests-remaining", "?")
            logger.info(f"API-Football call #{self._daily_calls}, remaining: {remaining}")
            resp.raise_for_status()
            data = resp.json()
            if data.get("errors"):
                logger.error(f"API-Football errors: {data['errors']}")
                return None
            return data
        except requests.RequestException as e:
            logger.error(f"API-Football error: {e}")
            return None

    def get_fixture_stats(self, fixture_id: int) -> dict | None:
        """
        Get detailed match statistics including xG.
        Use for completed matches to build xG history.
        """
        data = self._get("fixtures/statistics", {"fixture": fixture_id})
        if not data or not data.get("response"):
            return None

        stats = {}
        for team_stats in data["response"]:
            team_name = team_stats["team"]["name"]
            stats[team_name] = {}
            for stat in team_stats.get("statistics", []):
                stats[team_name][stat["type"]] = stat["value"]

        return stats

    def get_fixtures_by_date(self, league_id: int, date: str) -> list[dict]:
        """Get fixtures for a specific date. Format: YYYY-MM-DD."""
        data = self._get(
            "fixtures", {"league": league_id, "date": date, "season": datetime.now().year}
        )
        if not data or not data.get("response"):
            return []

        fixtures = []
        for f in data["response"]:
            fixtures.append(
                {
                    "fixture_id": f["fixture"]["id"],
                    "date": f["fixture"]["date"],
                    "status": f["fixture"]["status"]["short"],
                    "home_team": f["teams"]["home"]["name"],
                    "away_team": f["teams"]["away"]["name"],
                    "home_goals": f["goals"]["home"],
                    "away_goals": f["goals"]["away"],
                }
            )
        return fixtures

    def get_injuries(self, fixture_id: int) -> list[dict]:
        """
        Get injuries/suspensions for a fixture.
        Critical for adjusting pre-match predictions.
        """
        data = self._get("injuries", {"fixture": fixture_id})
        if not data or not data.get("response"):
            return []

        injuries = []
        for inj in data["response"]:
            injuries.append(
                {
                    "team": inj["team"]["name"],
                    "player": inj["player"]["name"],
                    "type": inj["player"].get("type", "unknown"),
                    "reason": inj["player"].get("reason", ""),
                }
            )
        return injuries

    def get_predictions(self, fixture_id: int) -> dict | None:
        """
        API-Football's own predictions — useful as a sanity check
        against your Dixon-Coles output, NOT as a primary signal.
        """
        data = self._get("predictions", {"fixture": fixture_id})
        if not data or not data.get("response"):
            return None

        pred = data["response"][0]
        return {
            "home_win_pct": pred["predictions"]["percent"]["home"],
            "draw_pct": pred["predictions"]["percent"]["draw"],
            "away_win_pct": pred["predictions"]["percent"]["away"],
            "advice": pred["predictions"].get("advice", ""),
            "goals_home": pred["predictions"].get("goals", {}).get("home"),
            "goals_away": pred["predictions"].get("goals", {}).get("away"),
        }

    def get_team_xg_history(
        self, league_id: int, team_id: int, last_n: int = 10
    ) -> list[dict]:
        """
        Pull recent fixtures for a team and extract xG.
        Budget: costs 1 call per team lookup + 1 per fixture stats.
        Use sparingly — only for teams in upcoming bets.
        """
        data = self._get(
            "fixtures",
            {"league": league_id, "team": team_id, "last": last_n, "status": "FT"},
        )
        if not data or not data.get("response"):
            return []

        xg_history = []
        for f in data["response"]:
            home = f["teams"]["home"]
            away = f["teams"]["away"]
            is_home = home["id"] == team_id

            xg_history.append(
                {
                    "fixture_id": f["fixture"]["id"],
                    "date": f["fixture"]["date"],
                    "is_home": is_home,
                    "opponent": away["name"] if is_home else home["name"],
                    "goals_for": f["goals"]["home"] if is_home else f["goals"]["away"],
                    "goals_against": f["goals"]["away"] if is_home else f["goals"]["home"],
                    # xG may need a separate stats call — check if included
                    "xg_for": f.get("xg", {}).get("home" if is_home else "away"),
                    "xg_against": f.get("xg", {}).get("away" if is_home else "home"),
                }
            )

        return xg_history
