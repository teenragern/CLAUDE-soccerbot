"""
Database Module — SQLite Storage

Tracks every signal (BET and PASS), results, CLV, and performance metrics.
This is your betting ledger and the foundation for model improvement.
"""

import os
import json
import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from config import Config

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or Config.DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        """Create tables if they don't exist."""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.executescript(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                match_name TEXT NOT NULL,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                league TEXT,
                market TEXT NOT NULL,
                selection TEXT NOT NULL,
                signal TEXT NOT NULL,
                model_prob REAL NOT NULL,
                market_prob REAL NOT NULL,
                edge REAL NOT NULL,
                ev REAL NOT NULL,
                ev_strength TEXT,
                best_odds REAL NOT NULL,
                best_book TEXT,
                fair_odds REAL,
                kelly_fraction REAL,
                suggested_units REAL,
                commence_time TEXT,
                -- Closing line (filled later)
                closing_odds REAL,
                closing_prob REAL,
                clv REAL,
                -- Result (filled after match)
                actual_home_goals INTEGER,
                actual_away_goals INTEGER,
                won INTEGER,
                pnl REAL,
                settled INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS odds_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_time TEXT NOT NULL,
                match_id TEXT NOT NULL,
                sport TEXT,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                commence_time TEXT,
                market TEXT NOT NULL,
                bookmaker TEXT NOT NULL,
                outcome TEXT NOT NULL,
                price REAL NOT NULL,
                point REAL
            );

            CREATE TABLE IF NOT EXISTS model_params (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fitted_at TEXT NOT NULL,
                league TEXT NOT NULL,
                num_matches INTEGER,
                home_advantage REAL,
                rho REAL,
                params_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS performance_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period TEXT NOT NULL,
                total_bets INTEGER,
                wins INTEGER,
                losses INTEGER,
                total_pnl REAL,
                roi REAL,
                avg_ev REAL,
                avg_clv REAL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_signals_settled ON signals(settled);
            CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(commence_time);
            CREATE INDEX IF NOT EXISTS idx_snapshots_match ON odds_snapshots(match_id);
        """
        )

        conn.commit()
        conn.close()
        logger.info("Database initialized")

    def log_signal(self, opp: dict, league: str = None):
        """Log a BET or PASS signal."""
        conn = self._get_conn()
        teams = opp["match"].split(" vs ")
        home = teams[0] if len(teams) == 2 else opp["match"]
        away = teams[1] if len(teams) == 2 else ""

        conn.execute(
            """
            INSERT INTO signals (
                created_at, match_name, home_team, away_team, league,
                market, selection, signal, model_prob, market_prob,
                edge, ev, ev_strength, best_odds, best_book, fair_odds,
                kelly_fraction, suggested_units, commence_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                datetime.now(timezone.utc).isoformat(),
                opp["match"],
                home,
                away,
                league,
                opp["market"],
                opp["selection"],
                opp["signal"],
                opp["model_prob"],
                opp["market_prob"],
                opp["edge"],
                opp["ev"],
                opp["ev_strength"],
                opp["best_odds"],
                opp["best_book"],
                opp.get("fair_odds"),
                opp["kelly_fraction"],
                opp["suggested_units"],
                opp.get("commence_time"),
            ),
        )
        conn.commit()
        conn.close()

    def log_odds_snapshot(self, match: dict):
        """Store a full odds snapshot for CLV tracking."""
        conn = self._get_conn()
        snapshot_time = datetime.now(timezone.utc).isoformat()

        for market_key, bookmakers in match.get("markets", {}).items():
            for bk_key, outcomes in bookmakers.items():
                for outcome_key, outcome in outcomes.items():
                    conn.execute(
                        """
                        INSERT INTO odds_snapshots (
                            snapshot_time, match_id, sport, home_team, away_team,
                            commence_time, market, bookmaker, outcome, price, point
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            snapshot_time,
                            match["id"],
                            match.get("sport"),
                            match["home_team"],
                            match["away_team"],
                            match.get("commence_time"),
                            market_key,
                            bk_key,
                            outcome["name"],
                            outcome["price"],
                            outcome.get("point"),
                        ),
                    )

        conn.commit()
        conn.close()

    def log_model_params(self, league: str, model):
        """Store model parameters after each fitting."""
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO model_params (fitted_at, league, num_matches,
                                      home_advantage, rho, params_json)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (
                datetime.now(timezone.utc).isoformat(),
                league,
                len(model.teams) * 10,  # Rough estimate
                model.params.get("home_adv", 0),
                model.params.get("rho", 0),
                json.dumps(
                    {
                        "attack": model.params.get("attack", {}),
                        "defense": model.params.get("defense", {}),
                    }
                ),
            ),
        )
        conn.commit()
        conn.close()

    def settle_bet(
        self,
        signal_id: int,
        home_goals: int,
        away_goals: int,
        closing_odds: float = None,
    ):
        """
        Settle a bet with the actual result.
        Calculates P&L and CLV.
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM signals WHERE id = ?", (signal_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return

        # Map columns
        cols = [desc[0] for desc in cursor.description]
        signal = dict(zip(cols, row))

        # Determine if bet won
        won = self._check_win(
            signal["market"],
            signal["selection"],
            home_goals,
            away_goals,
        )

        # P&L (only for BET signals)
        if signal["signal"] == "BET":
            if won:
                pnl = signal["suggested_units"] * (signal["best_odds"] - 1)
            else:
                pnl = -signal["suggested_units"]
        else:
            pnl = 0

        # CLV calculation
        clv = None
        if closing_odds and signal["signal"] == "BET":
            closing_prob = 1 / closing_odds
            clv = (1 / signal["best_odds"]) - closing_prob  # Negative = you got better odds

        cursor.execute(
            """
            UPDATE signals SET
                actual_home_goals = ?, actual_away_goals = ?,
                won = ?, pnl = ?, closing_odds = ?,
                closing_prob = ?, clv = ?, settled = 1
            WHERE id = ?
        """,
            (home_goals, away_goals, int(won), pnl, closing_odds,
             1/closing_odds if closing_odds else None, clv, signal_id),
        )
        conn.commit()
        conn.close()

        return {"won": won, "pnl": pnl, "clv": clv}

    def _check_win(
        self, market: str, selection: str, home_goals: int, away_goals: int
    ) -> bool:
        """Determine if a selection won given the result."""
        total = home_goals + away_goals

        if market == "1X2":
            if selection == "Home Win":
                return home_goals > away_goals
            elif selection == "Draw":
                return home_goals == away_goals
            elif selection == "Away Win":
                return away_goals > home_goals

        elif market.startswith("O/U"):
            line = float(market.split()[-1])
            if selection == "Over":
                return total > line
            elif selection == "Under":
                return total < line

        elif market == "BTTS":
            if selection == "Yes":
                return home_goals > 0 and away_goals > 0
            elif selection == "No":
                return home_goals == 0 or away_goals == 0

        return False

    def get_unsettled_bets(self) -> list[dict]:
        """Get all unsettled BET signals."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM signals WHERE signal = 'BET' AND settled = 0"
        )
        cols = [desc[0] for desc in cursor.description]
        rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
        conn.close()
        return rows

    def get_performance_stats(self, days: int = 7) -> dict:
        """Calculate performance metrics over a period."""
        conn = self._get_conn()
        cursor = conn.cursor()

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        cursor.execute(
            """
            SELECT
                COUNT(*) as total_bets,
                SUM(CASE WHEN won = 1 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN won = 0 THEN 1 ELSE 0 END) as losses,
                SUM(pnl) as total_pnl,
                AVG(ev) as avg_ev,
                AVG(clv) as avg_clv,
                SUM(suggested_units) as total_risked
            FROM signals
            WHERE signal = 'BET' AND settled = 1 AND created_at >= ?
        """,
            (cutoff,),
        )

        row = cursor.fetchone()
        conn.close()

        if not row or row[0] == 0:
            return {
                "period": f"Last {days} days",
                "total_bets": 0,
                "wins": 0,
                "losses": 0,
                "total_pnl": 0,
                "roi": 0,
                "avg_ev": 0,
                "avg_clv": 0,
            }

        total_risked = row[6] or 1
        return {
            "period": f"Last {days} days",
            "total_bets": row[0],
            "wins": row[1] or 0,
            "losses": row[2] or 0,
            "total_pnl": round(row[3] or 0, 2),
            "roi": round(((row[3] or 0) / total_risked) * 100, 2),
            "avg_ev": round((row[4] or 0) * 100, 2),
            "avg_clv": round((row[5] or 0) * 100, 2),
        }

    def get_recent_bets(self, limit: int = 20) -> list[dict]:
        """Get the most recent bet signals for the mini-log."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM signals
            WHERE signal = 'BET'
            ORDER BY created_at DESC LIMIT ?
        """,
            (limit,),
        )
        cols = [desc[0] for desc in cursor.description]
        rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
        conn.close()
        return rows
