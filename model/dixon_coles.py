"""
Dixon-Coles Model Implementation

Core of the prediction system. Estimates team attack/defense parameters
with a low-scoring correction factor (rho) and time-decay weighting.

Reference: Dixon & Coles (1997) "Modelling Association Football Scores
and Inefficiencies in the Football Betting Market"
"""

import math
import logging
import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson
from datetime import datetime, timezone
from config import Config

logger = logging.getLogger(__name__)


def tau(x, y, lambda_val, mu_val, rho):
    """
    Dixon-Coles correction factor for low-scoring matches.
    Adjusts probabilities for 0-0, 1-0, 0-1, 1-1 scorelines
    where the independent Poisson assumption breaks down.
    """
    if x == 0 and y == 0:
        return 1 - lambda_val * mu_val * rho
    elif x == 0 and y == 1:
        return 1 + lambda_val * rho
    elif x == 1 and y == 0:
        return 1 + mu_val * rho
    elif x == 1 and y == 1:
        return 1 - rho
    else:
        return 1.0


def time_decay_weight(match_date: str, half_life: int = None) -> float:
    """
    Exponential decay weighting — recent matches matter more.
    half_life is in days.
    """
    if half_life is None:
        half_life = Config.TIME_DECAY_HALF_LIFE * 7  # Convert matchdays to ~days

    try:
        if isinstance(match_date, str):
            dt = datetime.fromisoformat(match_date.replace("Z", "+00:00"))
        else:
            dt = match_date

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        days_ago = (datetime.now(timezone.utc) - dt).days
        return math.exp(-math.log(2) * days_ago / half_life)
    except Exception:
        return 0.5  # Default weight for unparseable dates


class DixonColesModel:
    def __init__(self):
        self.params = {}
        self.teams = []
        self.is_fitted = False

    def _build_team_index(self, matches: list[dict]):
        """Create a mapping of team names to indices."""
        teams = set()
        for m in matches:
            teams.add(m["home_team"])
            teams.add(m["away_team"])
        self.teams = sorted(teams)
        self._team_idx = {t: i for i, t in enumerate(self.teams)}

    def _neg_log_likelihood(self, params, matches, weights):
        """
        Negative log-likelihood for the Dixon-Coles model.
        Parameters: [attack_1, ..., attack_n, defense_1, ..., defense_n, home_adv, rho]
        """
        n = len(self.teams)
        attack = params[:n]
        defense = params[n : 2 * n]
        home_adv = params[2 * n]
        rho = params[2 * n + 1]

        log_lik = 0.0
        for i, m in enumerate(matches):
            hi = self._team_idx.get(m["home_team"])
            ai = self._team_idx.get(m["away_team"])
            if hi is None or ai is None:
                continue

            # Expected goals
            lambda_val = max(
                math.exp(attack[hi] + defense[ai] + home_adv), 0.001
            )
            mu_val = max(math.exp(attack[ai] + defense[hi]), 0.001)

            hg = m["home_goals"]
            ag = m["away_goals"]

            # Poisson probability × Dixon-Coles correction × time weight
            p_home = poisson.pmf(hg, lambda_val)
            p_away = poisson.pmf(ag, mu_val)
            tau_val = tau(hg, ag, lambda_val, mu_val, rho)

            prob = p_home * p_away * tau_val
            if prob > 0:
                log_lik += weights[i] * math.log(prob)

        return -log_lik

    def fit(self, matches: list[dict]):
        """
        Fit the Dixon-Coles model to historical match data.
        Pass in 1-2 seasons of completed matches.
        """
        logger.info(f"Fitting Dixon-Coles on {len(matches)} matches...")
        self._build_team_index(matches)
        n = len(self.teams)

        # Compute time-decay weights
        weights = [time_decay_weight(m["date"]) for m in matches]

        # Initial parameters: attack=0, defense=0, home_adv=0.25, rho=0
        x0 = np.zeros(2 * n + 2)
        x0[2 * n] = 0.25  # home advantage prior
        x0[2 * n + 1] = -0.05  # rho prior (slightly negative)

        # Constraint: sum of attack params = 0 (identifiability)
        constraints = [
            {"type": "eq", "fun": lambda p: np.sum(p[:n])},
        ]

        # Bounds: rho in [-1, 1], others unconstrained
        bounds = [(None, None)] * (2 * n)
        bounds.append((None, None))  # home_adv
        bounds.append((-1, 1))  # rho

        result = minimize(
            self._neg_log_likelihood,
            x0,
            args=(matches, weights),
            method="SLSQP",
            constraints=constraints,
            bounds=bounds,
            options={"maxiter": 500, "ftol": 1e-8},
        )

        if result.success:
            self.params = {
                "attack": {
                    self.teams[i]: result.x[i] for i in range(n)
                },
                "defense": {
                    self.teams[i]: result.x[n + i] for i in range(n)
                },
                "home_adv": result.x[2 * n],
                "rho": result.x[2 * n + 1],
            }
            self.is_fitted = True
            logger.info(
                f"Model fitted. Home advantage: {self.params['home_adv']:.3f}, "
                f"Rho: {self.params['rho']:.4f}"
            )
        else:
            logger.error(f"Model fitting failed: {result.message}")

        return self

    def predict_score_probs(
        self, home_team: str, away_team: str, max_goals: int = 7
    ) -> np.ndarray:
        """
        Predict the probability matrix for all scorelines up to max_goals.
        Returns a (max_goals+1) x (max_goals+1) matrix where [i][j] = P(home=i, away=j).
        """
        if not self.is_fitted:
            raise RuntimeError("Model not fitted. Call fit() first.")

        attack = self.params["attack"]
        defense = self.params["defense"]
        home_adv = self.params["home_adv"]
        rho = self.params["rho"]

        # Handle unknown teams with league average (0)
        h_att = attack.get(home_team, 0)
        h_def = defense.get(home_team, 0)
        a_att = attack.get(away_team, 0)
        a_def = defense.get(away_team, 0)

        lambda_val = math.exp(h_att + a_def + home_adv)
        mu_val = math.exp(a_att + h_def)

        # Build probability matrix with Dixon-Coles correction
        prob_matrix = np.zeros((max_goals + 1, max_goals + 1))
        for i in range(max_goals + 1):
            for j in range(max_goals + 1):
                p = (
                    poisson.pmf(i, lambda_val)
                    * poisson.pmf(j, mu_val)
                    * tau(i, j, lambda_val, mu_val, rho)
                )
                prob_matrix[i][j] = p

        # Normalize (the corrections can make total != 1)
        prob_matrix /= prob_matrix.sum()

        return prob_matrix

    def predict_match(self, home_team: str, away_team: str) -> dict:
        """
        Full match prediction with all market probabilities.
        This is what gets compared against de-vigged market odds.
        """
        matrix = self.predict_score_probs(home_team, away_team)

        # 1X2 probabilities
        home_win = sum(
            matrix[i][j] for i in range(8) for j in range(8) if i > j
        )
        draw = sum(matrix[i][i] for i in range(8))
        away_win = sum(
            matrix[i][j] for i in range(8) for j in range(8) if i < j
        )

        # Over/Under for common lines
        over_under = {}
        for line in [0.5, 1.5, 2.5, 3.5, 4.5]:
            over = sum(
                matrix[i][j]
                for i in range(8)
                for j in range(8)
                if (i + j) > line
            )
            over_under[line] = {"over": over, "under": 1 - over}

        # BTTS
        btts_yes = sum(
            matrix[i][j] for i in range(1, 8) for j in range(1, 8)
        )

        # Expected goals
        attack = self.params["attack"]
        defense = self.params["defense"]
        home_adv = self.params["home_adv"]

        h_att = attack.get(home_team, 0)
        a_def = defense.get(away_team, 0)
        a_att = attack.get(away_team, 0)
        h_def = defense.get(home_team, 0)

        exp_home = math.exp(h_att + a_def + home_adv)
        exp_away = math.exp(a_att + h_def)

        # Most likely scoreline
        flat_idx = np.argmax(matrix)
        ml_home, ml_away = divmod(flat_idx, matrix.shape[1])

        return {
            "home_team": home_team,
            "away_team": away_team,
            "1x2": {
                "home_win": round(home_win, 4),
                "draw": round(draw, 4),
                "away_win": round(away_win, 4),
            },
            "over_under": {
                str(k): {
                    "over": round(v["over"], 4),
                    "under": round(v["under"], 4),
                }
                for k, v in over_under.items()
            },
            "btts": {
                "yes": round(btts_yes, 4),
                "no": round(1 - btts_yes, 4),
            },
            "expected_goals": {
                "home": round(exp_home, 2),
                "away": round(exp_away, 2),
                "total": round(exp_home + exp_away, 2),
            },
            "most_likely_score": f"{ml_home}-{ml_away}",
            "score_matrix": matrix,
        }

    def adjust_with_xg(
        self, prediction: dict, xg_home: float, xg_away: float
    ) -> dict:
        """
        Blend Dixon-Coles expected goals with xG data.
        xG smooths out variance from actual goals.
        """
        w = Config.XG_BLEND_WEIGHT  # Weight for xG (0.6 default)

        blended_home = w * xg_home + (1 - w) * prediction["expected_goals"]["home"]
        blended_away = w * xg_away + (1 - w) * prediction["expected_goals"]["away"]

        # Rebuild probabilities using blended expected goals
        matrix = np.zeros((8, 8))
        rho = self.params["rho"]

        for i in range(8):
            for j in range(8):
                p = (
                    poisson.pmf(i, blended_home)
                    * poisson.pmf(j, blended_away)
                    * tau(i, j, blended_home, blended_away, rho)
                )
                matrix[i][j] = p

        matrix /= matrix.sum()

        # Recalculate everything
        home_win = sum(matrix[i][j] for i in range(8) for j in range(8) if i > j)
        draw_prob = sum(matrix[i][i] for i in range(8))
        away_win = sum(matrix[i][j] for i in range(8) for j in range(8) if i < j)

        over_under = {}
        for line in [0.5, 1.5, 2.5, 3.5, 4.5]:
            over = sum(
                matrix[i][j] for i in range(8) for j in range(8) if (i + j) > line
            )
            over_under[line] = {"over": over, "under": 1 - over}

        btts_yes = sum(matrix[i][j] for i in range(1, 8) for j in range(1, 8))

        flat_idx = np.argmax(matrix)
        ml_home, ml_away = divmod(flat_idx, 8)

        prediction.update(
            {
                "1x2": {
                    "home_win": round(home_win, 4),
                    "draw": round(draw_prob, 4),
                    "away_win": round(away_win, 4),
                },
                "over_under": {
                    str(k): {
                        "over": round(v["over"], 4),
                        "under": round(v["under"], 4),
                    }
                    for k, v in over_under.items()
                },
                "btts": {"yes": round(btts_yes, 4), "no": round(1 - btts_yes, 4)},
                "expected_goals": {
                    "home": round(blended_home, 2),
                    "away": round(blended_away, 2),
                    "total": round(blended_home + blended_away, 2),
                },
                "most_likely_score": f"{ml_home}-{ml_away}",
                "xg_adjusted": True,
            }
        )
        return prediction

    def get_team_ratings(self) -> list[dict]:
        """Return sorted team strength ratings for logging/review."""
        if not self.is_fitted:
            return []

        ratings = []
        for team in self.teams:
            att = self.params["attack"][team]
            dfn = self.params["defense"][team]
            # Overall = attack - defense (lower defense = better)
            overall = att - dfn
            ratings.append(
                {
                    "team": team,
                    "attack": round(att, 3),
                    "defense": round(dfn, 3),
                    "overall": round(overall, 3),
                }
            )

        return sorted(ratings, key=lambda x: x["overall"], reverse=True)
