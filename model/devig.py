"""
De-Vig Module

Strips the bookmaker margin (vig/juice) from odds to estimate
"true" market probabilities. These become your benchmark to beat.

Methods:
1. Multiplicative (basic) — divides each implied prob by total overround
2. Shin — accounts for favorite-longshot bias (better for 1X2)
3. Power — iterative method that's a good middle ground
"""

import math
import logging
import numpy as np
from scipy.optimize import brentq

logger = logging.getLogger(__name__)


def odds_to_implied_prob(decimal_odds: float) -> float:
    """Convert decimal odds to implied probability."""
    return 1.0 / decimal_odds


def implied_prob_to_odds(prob: float) -> float:
    """Convert probability to decimal odds."""
    if prob <= 0:
        return float("inf")
    return 1.0 / prob


class DeVig:
    @staticmethod
    def multiplicative(odds: list[float]) -> list[float]:
        """
        Basic multiplicative de-vig.
        Simply normalizes implied probabilities to sum to 1.
        Fast but doesn't account for favorite-longshot bias.
        """
        implied = [odds_to_implied_prob(o) for o in odds]
        total = sum(implied)  # This is > 1 (the overround)
        margin = total - 1
        logger.debug(f"Multiplicative de-vig: margin = {margin:.4f}")
        return [p / total for p in implied]

    @staticmethod
    def shin(odds: list[float]) -> list[float]:
        """
        Shin method — better for 1X2 markets.
        Accounts for the insider trading parameter (z) which
        models the favorite-longshot bias in betting markets.
        """
        n = len(odds)
        implied = [odds_to_implied_prob(o) for o in odds]
        total = sum(implied)

        def shin_equation(z):
            probs = []
            for p_i in implied:
                # Shin formula
                numerator = (
                    math.sqrt(z**2 + 4 * (1 - z) * (p_i**2 / total)) - z
                )
                denominator = 2 * (1 - z)
                probs.append(numerator / denominator)
            return sum(probs) - 1

        try:
            z = brentq(shin_equation, 0.001, 0.5)
            probs = []
            for p_i in implied:
                numerator = (
                    math.sqrt(z**2 + 4 * (1 - z) * (p_i**2 / total)) - z
                )
                denominator = 2 * (1 - z)
                probs.append(numerator / denominator)

            logger.debug(f"Shin de-vig: z = {z:.4f}")
            return probs
        except Exception as e:
            logger.warning(f"Shin method failed ({e}), falling back to multiplicative")
            return DeVig.multiplicative(odds)

    @staticmethod
    def power(odds: list[float], tol: float = 1e-8) -> list[float]:
        """
        Power method de-vig.
        Finds exponent k such that (implied_prob_i)^k sums to 1.
        Good balance between accuracy and simplicity.
        """
        implied = [odds_to_implied_prob(o) for o in odds]

        def power_eq(k):
            return sum(p**k for p in implied) - 1

        try:
            k = brentq(power_eq, 0.01, 2.0)
            probs = [p**k for p in implied]
            total = sum(probs)
            probs = [p / total for p in probs]  # Normalize for safety
            logger.debug(f"Power de-vig: k = {k:.4f}")
            return probs
        except Exception as e:
            logger.warning(f"Power method failed ({e}), falling back to multiplicative")
            return DeVig.multiplicative(odds)

    @staticmethod
    def best_method(odds: list[float], market_type: str = "h2h") -> list[float]:
        """
        Pick the best de-vig method based on market type.
        - h2h (1X2): Shin (handles favorite-longshot bias)
        - totals/btts (2-way): Power method
        """
        if market_type == "h2h":
            return DeVig.shin(odds)
        else:
            return DeVig.power(odds)


def devig_market_from_books(
    bookmaker_odds: dict, market_type: str = "h2h"
) -> dict:
    """
    De-vig using the sharpest odds across all bookmakers.

    bookmaker_odds: {outcome_key: [list of {price, bookmaker}]}
    Returns: {outcome_key: true_probability}
    """
    outcome_keys = list(bookmaker_odds.keys())

    if not outcome_keys:
        return {}

    # Strategy: Use the HIGHEST odds for each outcome across all books
    # (closest to true price), then de-vig that combination
    best_odds = []
    for key in outcome_keys:
        prices = [entry["price"] for entry in bookmaker_odds[key]]
        best_odds.append(max(prices))  # Best available price

    true_probs = DeVig.best_method(best_odds, market_type)

    result = {}
    for i, key in enumerate(outcome_keys):
        result[key] = {
            "true_prob": true_probs[i],
            "best_odds": best_odds[i],
            "fair_odds": implied_prob_to_odds(true_probs[i]),
            "margin_check": sum(true_probs),
        }

    return result


def compute_market_margin(odds: list[float]) -> float:
    """Calculate the total bookmaker margin (overround)."""
    implied = [odds_to_implied_prob(o) for o in odds]
    return sum(implied) - 1
