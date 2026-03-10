"""
EV Calculator

Compares Dixon-Coles model probabilities against de-vigged market
probabilities. Generates BET/PASS signals with Kelly sizing.

This is where edge is identified and quantified.
"""

import math
import logging
from config import Config
from model.devig import devig_market_from_books, DeVig

logger = logging.getLogger(__name__)


def calculate_ev(model_prob: float, decimal_odds: float) -> float:
    """
    Expected Value calculation.
    EV = (prob × (odds - 1)) - (1 - prob)
    Positive = profitable long-term.
    """
    return (model_prob * (decimal_odds - 1)) - (1 - model_prob)


def kelly_criterion(
    model_prob: float, decimal_odds: float, fraction: float = None
) -> float:
    """
    Kelly criterion bet sizing.
    f* = (bp - q) / b
    where b = odds - 1, p = win prob, q = 1 - p

    Returns fraction of bankroll to wager.
    Capped at fraction-Kelly for safety.
    """
    if fraction is None:
        fraction = Config.KELLY_FRACTION

    b = decimal_odds - 1
    if b <= 0:
        return 0

    p = model_prob
    q = 1 - p

    full_kelly = (b * p - q) / b

    if full_kelly <= 0:
        return 0

    # Apply fractional Kelly
    sized = full_kelly * fraction

    # Cap at 10% of bankroll max (safety rail)
    return min(sized, 0.10)


def edge_strength(ev: float) -> str:
    """Classify edge strength for alerts."""
    if ev >= 0.10:
        return "STRONG"
    elif ev >= 0.05:
        return "MODERATE"
    elif ev >= Config.MIN_EV_THRESHOLD:
        return "SLIGHT"
    else:
        return "NONE"


class EVCalculator:
    def __init__(self, model):
        self.model = model

    def evaluate_match(self, match_odds: dict, prediction: dict) -> list[dict]:
        """
        Evaluate all markets for a single match.
        Returns list of opportunities (BET or PASS for each market).
        """
        opportunities = []
        home = prediction["home_team"]
        away = prediction["away_team"]

        # --- 1X2 Market ---
        h2h_odds = match_odds.get("markets", {}).get("h2h", {})
        if h2h_odds:
            opportunities.extend(
                self._evaluate_1x2(h2h_odds, prediction, home, away, match_odds)
            )

        # --- Over/Under Market ---
        totals_odds = match_odds.get("markets", {}).get("totals", {})
        if totals_odds:
            opportunities.extend(
                self._evaluate_totals(totals_odds, prediction, home, away, match_odds)
            )

        # --- BTTS Market ---
        btts_odds = match_odds.get("markets", {}).get("btts", {})
        if btts_odds:
            opportunities.extend(
                self._evaluate_btts(btts_odds, prediction, home, away, match_odds)
            )

        return opportunities

    def _evaluate_1x2(
        self, market_data, prediction, home, away, match_odds
    ) -> list[dict]:
        """Evaluate 1X2 market opportunities."""
        opps = []

        # Collect all bookmaker odds per outcome
        all_odds = {"Home": [], "Draw": [], "Away": []}
        for bk, outcomes in market_data.items():
            for key, outcome in outcomes.items():
                name = outcome["name"]
                if name == home:
                    all_odds["Home"].append({"price": outcome["price"], "bookmaker": bk})
                elif name == away:
                    all_odds["Away"].append({"price": outcome["price"], "bookmaker": bk})
                elif name == "Draw":
                    all_odds["Draw"].append({"price": outcome["price"], "bookmaker": bk})

        if not all(all_odds.values()):
            return opps

        # Get best odds per outcome
        best_home = max(all_odds["Home"], key=lambda x: x["price"])
        best_draw = max(all_odds["Draw"], key=lambda x: x["price"])
        best_away = max(all_odds["Away"], key=lambda x: x["price"])

        best_prices = [best_home["price"], best_draw["price"], best_away["price"]]

        # De-vig using Shin method
        true_probs = DeVig.shin(best_prices)

        # Compare model vs market for each outcome
        model_probs = prediction["1x2"]
        outcomes = [
            ("Home Win", model_probs["home_win"], best_home, true_probs[0]),
            ("Draw", model_probs["draw"], best_draw, true_probs[1]),
            ("Away Win", model_probs["away_win"], best_away, true_probs[2]),
        ]

        for label, model_prob, best, market_prob in outcomes:
            ev = calculate_ev(model_prob, best["price"])
            edge = model_prob - market_prob

            kelly = kelly_criterion(model_prob, best["price"])
            units = round(kelly * Config.BANKROLL / 10, 1)  # Convert to units (1u = $10 default)

            signal = "BET" if ev >= Config.MIN_EV_THRESHOLD else "PASS"

            opps.append(
                {
                    "match": f"{home} vs {away}",
                    "market": "1X2",
                    "selection": label,
                    "signal": signal,
                    "model_prob": round(model_prob, 4),
                    "market_prob": round(market_prob, 4),
                    "edge": round(edge, 4),
                    "ev": round(ev, 4),
                    "ev_strength": edge_strength(ev),
                    "best_odds": best["price"],
                    "best_book": best["bookmaker"],
                    "fair_odds": round(1 / market_prob, 2) if market_prob > 0 else 0,
                    "kelly_fraction": round(kelly, 4),
                    "suggested_units": units,
                    "commence_time": match_odds.get("commence_time"),
                }
            )

        return opps

    def _evaluate_totals(
        self, market_data, prediction, home, away, match_odds
    ) -> list[dict]:
        """Evaluate Over/Under market opportunities."""
        opps = []

        # Group by point line (e.g., 2.5)
        lines = {}
        for bk, outcomes in market_data.items():
            for key, outcome in outcomes.items():
                point = outcome.get("point")
                if point is None:
                    continue
                name = outcome["name"]  # "Over" or "Under"
                line_key = str(point)

                if line_key not in lines:
                    lines[line_key] = {"Over": [], "Under": []}

                if name == "Over":
                    lines[line_key]["Over"].append(
                        {"price": outcome["price"], "bookmaker": bk}
                    )
                elif name == "Under":
                    lines[line_key]["Under"].append(
                        {"price": outcome["price"], "bookmaker": bk}
                    )

        for line, sides in lines.items():
            if not sides["Over"] or not sides["Under"]:
                continue

            best_over = max(sides["Over"], key=lambda x: x["price"])
            best_under = max(sides["Under"], key=lambda x: x["price"])

            true_probs = DeVig.power([best_over["price"], best_under["price"]])

            # Get model probability for this line
            ou_data = prediction.get("over_under", {}).get(line)
            if not ou_data:
                continue

            for side, idx, best in [
                ("Over", 0, best_over),
                ("Under", 1, best_under),
            ]:
                model_prob = ou_data[side.lower()]
                market_prob = true_probs[idx]

                ev = calculate_ev(model_prob, best["price"])
                edge = model_prob - market_prob
                kelly = kelly_criterion(model_prob, best["price"])
                units = round(kelly * Config.BANKROLL / 10, 1)

                signal = "BET" if ev >= Config.MIN_EV_THRESHOLD else "PASS"

                opps.append(
                    {
                        "match": f"{home} vs {away}",
                        "market": f"O/U {line}",
                        "selection": side,
                        "signal": signal,
                        "model_prob": round(model_prob, 4),
                        "market_prob": round(market_prob, 4),
                        "edge": round(edge, 4),
                        "ev": round(ev, 4),
                        "ev_strength": edge_strength(ev),
                        "best_odds": best["price"],
                        "best_book": best["bookmaker"],
                        "fair_odds": round(1 / market_prob, 2) if market_prob > 0 else 0,
                        "kelly_fraction": round(kelly, 4),
                        "suggested_units": units,
                        "commence_time": match_odds.get("commence_time"),
                    }
                )

        return opps

    def _evaluate_btts(
        self, market_data, prediction, home, away, match_odds
    ) -> list[dict]:
        """Evaluate BTTS market opportunities."""
        opps = []

        yes_odds = []
        no_odds = []
        for bk, outcomes in market_data.items():
            for key, outcome in outcomes.items():
                if outcome["name"] == "Yes":
                    yes_odds.append({"price": outcome["price"], "bookmaker": bk})
                elif outcome["name"] == "No":
                    no_odds.append({"price": outcome["price"], "bookmaker": bk})

        if not yes_odds or not no_odds:
            return opps

        best_yes = max(yes_odds, key=lambda x: x["price"])
        best_no = max(no_odds, key=lambda x: x["price"])

        true_probs = DeVig.power([best_yes["price"], best_no["price"]])

        model_btts = prediction["btts"]

        for side, idx, best in [("Yes", 0, best_yes), ("No", 1, best_no)]:
            model_prob = model_btts[side.lower()]
            market_prob = true_probs[idx]

            ev = calculate_ev(model_prob, best["price"])
            edge = model_prob - market_prob
            kelly = kelly_criterion(model_prob, best["price"])
            units = round(kelly * Config.BANKROLL / 10, 1)

            signal = "BET" if ev >= Config.MIN_EV_THRESHOLD else "PASS"

            opps.append(
                {
                    "match": f"{home} vs {away}",
                    "market": "BTTS",
                    "selection": side,
                    "signal": signal,
                    "model_prob": round(model_prob, 4),
                    "market_prob": round(market_prob, 4),
                    "edge": round(edge, 4),
                    "ev": round(ev, 4),
                    "ev_strength": edge_strength(ev),
                    "best_odds": best["price"],
                    "best_book": best["bookmaker"],
                    "fair_odds": round(1 / market_prob, 2) if market_prob > 0 else 0,
                    "kelly_fraction": round(kelly, 4),
                    "suggested_units": units,
                    "commence_time": match_odds.get("commence_time"),
                }
            )

        return opps
