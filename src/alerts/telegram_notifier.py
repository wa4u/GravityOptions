import html
import requests
import yaml
from typing import Dict, Any, Optional
from src.utils.logger import log

class TelegramNotifier:
    """
    Handles formatting and dispatching rich HTML alerts to Telegram
    with fine-grained configuration toggles.
    """
    def __init__(self, config_path: str = "config/telegram_config.yaml"):
        self.config_path = config_path
        self.enabled = False
        self.bot_token = ""
        self.chat_id = ""
        self.toggles: Dict[str, bool] = {}
        self.load_config()

    def load_config(self):
        try:
            with open(self.config_path, "r") as f:
                cfg = yaml.safe_load(f).get("telegram", {})
                self.enabled = cfg.get("enabled", False)
                self.bot_token = cfg.get("bot_token", "")
                self.chat_id = cfg.get("chat_id", "")
                self.toggles = cfg.get("notifications", {})
                self.format_opts = cfg.get("format", {})
        except Exception as e:
            log.warning(f"Could not load telegram config: {e}. Telegram notifications disabled.")
            self.enabled = False

    def send_message(self, text: str) -> bool:
        """Send raw HTML text to Telegram chat."""
        if not self.enabled or not self.bot_token or not self.chat_id or "YOUR_" in self.bot_token:
            log.debug(f"[Telegram Mock] {text}")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            resp = requests.post(url, json=payload, timeout=8)
            if resp.status_code == 200:
                return True
            else:
                log.error(f"Telegram send failed [{resp.status_code}]: {resp.text}")
                return False
        except Exception as e:
            log.error(f"Telegram error: {e}")
            return False

    def notify_login_success(self, client_id: str, broker: str = "Angel One"):
        if not self.toggles.get("login_success", True):
            return
        from src.utils.time_utils import get_now_ist
        now_str = get_now_ist().strftime("%d %b %Y, %I:%M:%S %p IST")
        safe_client = html.escape(str(client_id))
        safe_broker = html.escape(str(broker))

        msg = (
            f"<b>🔐 BROKER AUTHENTICATION SUCCESSFUL</b> 🟢\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Broker:</b> {safe_broker} SmartAPI\n"
            f"<b>Client ID:</b> <code>{safe_client}</code>\n"
            f"<b>Status:</b> Connected and Session Active\n"
            f"<b>Time:</b> {now_str}\n"
            f"<i>Live data feed, Open Interest analyzer, and risk engines are online and ready for trading.</i>"
        )
        self.send_message(msg)

    def notify_login_failed(self, client_id: str, broker: str = "Angel One", reason: str = ""):
        if not self.toggles.get("login_success", True):
            return
        from src.utils.time_utils import get_now_ist
        now_str = get_now_ist().strftime("%d %b %Y, %I:%M:%S %p IST")
        safe_client = html.escape(str(client_id))
        safe_broker = html.escape(str(broker))
        safe_reason = html.escape(str(reason)) if reason else "Invalid credentials or TOTP error"

        msg = (
            f"<b>🚨 BROKER LOGIN FAILED</b> 🔴\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Broker:</b> {safe_broker} SmartAPI\n"
            f"<b>Client ID:</b> <code>{safe_client}</code>\n"
            f"<b>Status:</b> Authentication Failed\n"
            f"<b>Reason:</b> <i>{safe_reason}</i>\n"
            f"<b>Time:</b> {now_str}\n"
            f"<b>Action:</b> Falling back to Mock Replay Feed. Please check credentials/TOTP."
        )
        self.send_message(msg)

    def notify_signal(
        self,
        symbol: str,
        direction: str,
        trigger_reason: str,
        spot: float,
        strike: str,
        display_name: str = "",
        oi_info: Optional[Dict[str, Any]] = None
    ):
        if not self.toggles.get("signal_detected", True):
            return
        emoji = "⚡"
        color_dot = "🟢" if direction.upper() in ["BUY", "CALL", "CE"] else "🔴"
        safe_reason = html.escape(str(trigger_reason))
        display = display_name if display_name else strike
        sub = f" (<code>{strike}</code>)" if display != strike else ""

        oi_line = ""
        if oi_info and oi_info.get("is_valid"):
            pcr = oi_info.get("pcr", 1.0)
            sent = oi_info.get("sentiment", "NEUTRAL")
            cw = oi_info.get("call_wall", 0.0)
            pw = oi_info.get("put_wall", 0.0)
            mp = oi_info.get("max_pain", 0.0)
            score = oi_info.get("conviction_score", 50)
            flow = oi_info.get("net_oi_flow", "NEUTRAL")
            c_chg = oi_info.get("atm_call_oi_change", 0)
            p_chg = oi_info.get("atm_put_oi_change", 0)

            c_tag = f"{c_chg:+,d}" if abs(c_chg) < 100000 else f"{c_chg/100000:+.2f}L"
            p_tag = f"{p_chg:+,d}" if abs(p_chg) < 100000 else f"{p_chg/100000:+.2f}L"
            score_badge = "🔥 [HIGH]" if score >= 70 else ("⚡ [MODERATE]" if score >= 55 else "⚠️ [LOW]")

            oi_line = (
                f"<b>🧠 Institutional Conviction:</b> <code>{score}/100</code> {score_badge}\n"
                f"<b>🌊 Order Flow:</b> <b>{flow}</b>\n"
                f"<b>⚡ ATM Writer Flow:</b> CE: <code>{c_tag}</code> | PE: <code>{p_tag}</code>\n"
                f"<b>📊 PCR:</b> <code>{pcr:.2f}</code> ({sent}) | <b>🎯 MaxPain:</b> ₹{mp:,.0f}\n"
                f"<b>🛡️ Put Wall:</b> ₹{pw:,.0f} | <b>🧱 Call Wall:</b> ₹{cw:,.0f}\n"
            )

        msg = (
            f"<b>{emoji} SIGNAL DETECTED</b> {color_dot}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Underlying:</b> <code>{symbol}</code>\n"
            f"<b>Direction:</b> {direction.upper()}\n"
            f"<b>Target Option:</b> <b>{display}</b>{sub}\n"
            f"<b>Spot Price:</b> ₹{spot:,.2f}\n"
            f"{oi_line}"
            f"<b>Trigger Setup:</b> <i>{safe_reason}</i>\n"
            f"<i>Validating risk rules before execution...</i>"
        )
        self.send_message(msg)

    def notify_order_entry(self, order: Dict[str, Any]):
        if not self.toggles.get("order_entry", True):
            return
        opt_type = order.get("option_type", "CE")
        dot = "🟢" if opt_type == "CE" else "🔴"
        delta = order.get("delta", 0.50)
        mode = order.get("trading_mode", "INTRADAY")
        display = order.get("display_name") or order.get("contract_symbol")
        code = order.get("contract_symbol")
        sub = f" (<code>{code}</code>)" if display != code else ""

        oi_info = order.get("oi_info")
        oi_line = ""
        if oi_info and oi_info.get("is_valid"):
            pcr = oi_info.get("pcr", 1.0)
            cw = oi_info.get("call_wall", 0.0)
            pw = oi_info.get("put_wall", 0.0)
            score = oi_info.get("conviction_score", 50)
            flow = oi_info.get("net_oi_flow", "NEUTRAL")
            oi_line = (
                f"<b>🧠 Conviction:</b> <code>{score}/100</code> | <b>Flow:</b> <b>{flow}</b>\n"
                f"<b>📊 OI Confirmation:</b> PCR {pcr:.2f} | Put ₹{pw:,.0f} | Call ₹{cw:,.0f}\n"
            )
        
        msg = (
            f"<b>{dot} OPTION BUY ENTRY EXECUTED</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Instrument:</b> <b>{display}</b>{sub}\n"
            f"<b>Underlying:</b> {order.get('symbol')} (Spot: ₹{order.get('spot_price', 0):,.2f})\n"
            f"<b>Type & Delta:</b> {opt_type} | Δ: {delta:+.2f}\n"
            f"{oi_line}"
            f"<b>Fill Price:</b> ₹{order.get('entry_price', 0):.2f}\n"
            f"<b>Quantity / Lots:</b> {order.get('quantity')} ({order.get('lots', 1)} Lot)\n"
            f"<b>Stop Loss (SL):</b> ₹{order.get('stop_loss', 0):.2f} (-{order.get('sl_pct', 15):.1f}%)\n"
            f"<b>Target (TP):</b> ₹{order.get('target', 0):.2f} (+{order.get('tp_pct', 35):.1f}%)\n"
            f"<b>Holding Mode:</b> {mode}\n"
            f"<b>Estimated Margin:</b> ₹{order.get('entry_price', 0) * order.get('quantity', 0):,.2f}"
        )
        self.send_message(msg)

    def notify_trailing_sl(self, contract: str, old_sl: float, new_sl: float, current_price: float, profit_pct: float, display_name: str = ""):
        if not self.toggles.get("trailing_sl_updated", True):
            return
        display = display_name if display_name else contract
        sub = f" (<code>{contract}</code>)" if display != contract else ""
        msg = (
            f"<b>🔄 TRAILING STOP-LOSS UPDATED</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Contract:</b> <b>{display}</b>{sub}\n"
            f"<b>Current Price:</b> ₹{current_price:.2f} (Gain: +{profit_pct:.1f}%)\n"
            f"<b>Old SL:</b> ₹{old_sl:.2f} ➔ <b>New Trailed SL:</b> ₹{new_sl:.2f}\n"
            f"<i>Risk locked in at breakeven / higher profit.</i>"
        )
        self.send_message(msg)

    def notify_order_exit(self, exit_info: Dict[str, Any]):
        if not self.toggles.get("order_exit", True):
            return
        net_pnl = exit_info.get("net_pnl", 0.0)
        roi = exit_info.get("roi_pct", 0.0)
        pnl_emoji = "🎉 <b>PROFIT!</b> 🟢" if net_pnl >= 0 else "🛑 <b>LOSS</b> 🔴"
        display = exit_info.get("display_name") or exit_info.get("contract_symbol")
        code = exit_info.get("contract_symbol")
        sub = f" (<code>{code}</code>)" if display != code else ""
        
        msg = (
            f"<b>{pnl_emoji} POSITION CLOSED</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Contract:</b> <b>{display}</b>{sub}\n"
            f"<b>Exit Reason:</b> <b>{exit_info.get('exit_reason')}</b>\n"
            f"<b>Buy Price:</b> ₹{exit_info.get('entry_price', 0):.2f}\n"
            f"<b>Exit Price:</b> ₹{exit_info.get('exit_price', 0):.2f}\n"
            f"<b>Quantity:</b> {exit_info.get('quantity')}\n"
            f"<b>Gross P&L:</b> ₹{exit_info.get('gross_pnl', 0):+,.2f}\n"
            f"<b>Taxes & Charges:</b> ₹{exit_info.get('total_charges', 0):,.2f}\n"
            f"<b>Net P&L:</b> <b>₹{net_pnl:+,.2f} ({roi:+.1f}%)</b>\n"
            f"<b>Duration:</b> {exit_info.get('holding_duration', 'N/A')}"
        )
        self.send_message(msg)

    def notify_stock_carry_decision(self, symbol: str, contract: str, carried: bool, reason: str, profit_pct: float):
        if not self.toggles.get("stock_carry_decision", True):
            return
        badge = "🌙 <b>OVERNIGHT HOLD APPROVED</b> 🟢" if carried else "⏰ <b>INTRADAY SQUARE-OFF</b> ⚠️"
        msg = (
            f"<b>{badge}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Stock:</b> <code>{symbol}</code> ({contract})\n"
            f"<b>Decision:</b> {'Carrying overnight (BTST/Swing)' if carried else 'Closed at 15:15 IST'}\n"
            f"<b>Unrealized Profit:</b> {profit_pct:+.1f}%\n"
            f"<b>Rule Evaluation:</b> {reason}"
        )
        self.send_message(msg)

    def notify_circuit_breaker(self, current_loss: float, max_loss: float):
        if not self.toggles.get("risk_circuit_breaker", True):
            return
        msg = (
            f"<b>🚨 RISK CIRCUIT BREAKER TRIGGERED 🚨</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Current Daily Loss:</b> -₹{abs(current_loss):,.2f}\n"
            f"<b>Daily Hard Cutoff:</b> -₹{max_loss:,.2f}\n"
            f"<b>Action:</b> ALL open positions squared off immediately. Trading halted for the remainder of today to protect capital!"
        )
        self.send_message(msg)

    def notify_daily_summary(self, summary: Dict[str, Any]):
        if not self.toggles.get("daily_summary", True):
            return
        net = summary.get("net_pnl", 0.0)
        badge = "🏆 <b>GREEN DAY</b> 🟢" if net >= 0 else "📉 <b>RED DAY</b> 🔴"
        msg = (
            f"<b>📊 END-OF-DAY PERFORMANCE SUMMARY</b>\n"
            f"{badge}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Date:</b> {summary.get('date')}\n"
            f"<b>Total Trades:</b> {summary.get('total_trades', 0)}\n"
            f"<b>Win Rate:</b> {summary.get('win_rate', 0):.1f}% ({summary.get('wins', 0)}W / {summary.get('losses', 0)}L)\n"
            f"<b>Gross P&L:</b> ₹{summary.get('gross_pnl', 0):+,.2f}\n"
            f"<b>Brokerage & Taxes:</b> ₹{summary.get('charges', 0):,.2f}\n"
            f"<b>Net P&L:</b> <b>₹{net:+,.2f}</b>\n"
            f"<b>Virtual Account Balance:</b> ₹{summary.get('closing_balance', 0):,.2f}"
        )
        self.send_message(msg)

    def notify_heartbeat(self, status: str, active_positions: int, capital: float):
        if not self.toggles.get("system_heartbeat", False):
            return
        msg = (
            f"<b>💓 BOT HEARTBEAT</b>\n"
            f"• Status: {status}\n"
            f"• Open Positions: {active_positions}\n"
            f"• Available Capital: ₹{capital:,.2f}"
        )
        self.send_message(msg)
