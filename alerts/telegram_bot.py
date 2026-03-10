"""
Telegram Alert System

Sends BET/PASS signals to your Telegram bot.
Formats alerts for quick decision-making.
"""

import logging
import requests
from datetime import datetime, timezone
from config import Config

logger = logging.getLogger(__name__)

BASE_URL = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}"


class TelegramBot:
    def __init__(self):
        self.chat_id = Config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}"

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message to the configured chat."""
        try:
            resp = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    def send_bet_alert(self, opp: dict) -> bool:
        """Send a formatted BET alert."""
        signal_emoji = "🟢" if opp["signal"] == "BET" else "🔴"
        strength_emoji = {
            "STRONG": "🔥",
            "MODERATE": "📈",
            "SLIGHT": "📊",
            "NONE": "⚪",
        }.get(opp["ev_strength"], "⚪")

        msg = (
            f"{signal_emoji} <b>{opp['signal']}</b> | {opp['match']}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Market:</b> {opp['market']} — {opp['selection']}\n"
            f"💰 <b>Best Odds:</b> {opp['best_odds']} @ {opp['best_book']}\n"
            f"📈 <b>Model:</b> {opp['model_prob']*100:.1f}% | "
            f"<b>Market:</b> {opp['market_prob']*100:.1f}%\n"
            f"{strength_emoji} <b>EV:</b> {opp['ev']*100:+.1f}% | "
            f"<b>Edge:</b> {opp['edge']*100:+.1f}%\n"
            f"📏 <b>Suggested:</b> {opp['suggested_units']}u "
            f"(Kelly: {opp['kelly_fraction']*100:.1f}%)\n"
        )

        if opp.get("commence_time"):
            try:
                dt = datetime.fromisoformat(
                    opp["commence_time"].replace("Z", "+00:00")
                )
                msg += f"⏰ <b>Kickoff:</b> {dt.strftime('%b %d %H:%M UTC')}\n"
            except Exception:
                pass

        return self.send_message(msg)

    def send_daily_summary(self, bets: list[dict], passes: int) -> bool:
        """Send end-of-day summary of all signals."""
        if not bets and passes == 0:
            return self.send_message("📋 <b>Daily Summary:</b> No matches evaluated today.")

        msg = (
            f"📋 <b>DAILY SUMMARY</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🟢 Bets Found: {len(bets)}\n"
            f"🔴 Passes: {passes}\n\n"
        )

        if bets:
            total_units = sum(b["suggested_units"] for b in bets)
            avg_ev = sum(b["ev"] for b in bets) / len(bets) if bets else 0

            msg += f"💰 Total Units Risked: {total_units:.1f}u\n"
            msg += f"📈 Avg EV: {avg_ev*100:+.1f}%\n\n"

            for b in sorted(bets, key=lambda x: x["ev"], reverse=True):
                msg += (
                    f"  • {b['match']}: {b['market']} {b['selection']} "
                    f"@ {b['best_odds']} ({b['ev']*100:+.1f}% EV)\n"
                )

        return self.send_message(msg)

    def send_results_update(self, results: list[dict]) -> bool:
        """Send results of settled bets with P&L."""
        if not results:
            return True

        total_pnl = sum(r.get("pnl", 0) for r in results)
        wins = sum(1 for r in results if r.get("won"))
        losses = len(results) - wins

        pnl_emoji = "📈" if total_pnl >= 0 else "📉"

        msg = (
            f"{pnl_emoji} <b>RESULTS UPDATE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Wins: {wins} | ❌ Losses: {losses}\n"
            f"💰 P&L: {total_pnl:+.1f}u\n\n"
        )

        for r in results:
            emoji = "✅" if r.get("won") else "❌"
            msg += (
                f"  {emoji} {r['match']}: {r['market']} {r['selection']} "
                f"→ {r.get('actual_score', '?')} ({r.get('pnl', 0):+.1f}u)\n"
            )

        return self.send_message(msg)

    def send_weekly_report(self, stats: dict) -> bool:
        """Weekly performance metrics."""
        msg = (
            f"📊 <b>WEEKLY REPORT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 Period: {stats.get('period', 'Last 7 days')}\n"
            f"🎯 Record: {stats.get('wins', 0)}W - {stats.get('losses', 0)}L\n"
            f"💰 P&L: {stats.get('total_pnl', 0):+.1f}u\n"
            f"📈 ROI: {stats.get('roi', 0):+.1f}%\n"
            f"🎯 CLV: {stats.get('avg_clv', 0):+.1f}%\n"
            f"📊 Avg EV at bet: {stats.get('avg_ev', 0):+.1f}%\n"
            f"🔥 Streak: {stats.get('streak', 'N/A')}\n"
        )

        return self.send_message(msg)

    def send_model_update(self, ratings: list[dict], league: str) -> bool:
        """Send updated team power ratings after model refit."""
        msg = (
            f"🔄 <b>MODEL UPDATE — {league}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Top 5 Power Ratings:</b>\n"
        )

        for i, r in enumerate(ratings[:5], 1):
            msg += (
                f"  {i}. {r['team']} — "
                f"ATT: {r['attack']:+.2f} DEF: {r['defense']:+.2f}\n"
            )

        msg += f"\n<b>Bottom 5:</b>\n"
        for i, r in enumerate(ratings[-5:], 1):
            msg += (
                f"  {i}. {r['team']} — "
                f"ATT: {r['attack']:+.2f} DEF: {r['defense']:+.2f}\n"
            )

        return self.send_message(msg)
