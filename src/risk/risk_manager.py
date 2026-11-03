from datetime import datetime, date
from typing import Dict, Any, Tuple, Optional
from src.utils.logger import log
from src.execution.paper_broker import Position, PaperBroker
from src.utils.time_utils import get_now_ist

class RiskManager:
    """
    Enforces risk rules:
    - Maximum daily drawdown circuit breaker
    - Position sizing (Fixed lots vs Risk %)
    - Trailing stop-loss
    - Time-stop (Anti-theta stagnation)
    - Stock carry-forward qualification checks
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.risk_cfg = config.get("risk", {})
        self.sizing_cfg = config.get("position_sizing", {})
        self.stocks_cfg = config.get("stocks", {})
        
        self.max_daily_loss = self.risk_cfg.get("max_daily_loss_inr", 5000.0)
        self.max_open_trades = self.risk_cfg.get("max_open_trades", 3)
        self.default_sl_pct = self.risk_cfg.get("stop_loss_pct", 15.0)
        self.default_tp_pct = self.risk_cfg.get("target_profit_pct", 35.0)
        self.trail_trigger_pct = self.risk_cfg.get("trail_sl_trigger_pct", 15.0)
        self.trail_step_pct = self.risk_cfg.get("trail_step_pct", 10.0)
        self.stagnation_timeout_mins = config.get("system", {}).get("stagnation_timeout_mins", 20)
        
        self.is_circuit_broken = False
        self.circuit_break_reason = ""

    def check_circuit_breaker(self, broker: PaperBroker) -> Tuple[bool, str]:
        """Verify whether daily loss limit has been breached."""
        if self.is_circuit_broken:
            return True, self.circuit_break_reason

        summary = broker.get_portfolio_summary()
        current_net_pnl = summary["total_pnl"]

        if current_net_pnl <= -abs(self.max_daily_loss):
            self.is_circuit_broken = True
            self.circuit_break_reason = (
                f"Daily loss limit breached: ₹{abs(current_net_pnl):,.2f} >= max ₹{self.max_daily_loss:,.2f}"
            )
            log.critical(f"🚨 CIRCUIT BREAKER TRIPPED! {self.circuit_break_reason}")
            return True, self.circuit_break_reason

        return False, ""

    def can_open_new_trade(self, broker: PaperBroker) -> Tuple[bool, str]:
        """Check if broker can open another position."""
        broken, reason = self.check_circuit_breaker(broker)
        if broken:
            return False, f"Trading halted: {reason}"

        if len(broker.positions) >= self.max_open_trades:
            return False, f"Max concurrent trades ({self.max_open_trades}) reached"

        return True, "OK"

    def calculate_position_size(
        self,
        symbol: str,
        lot_size: int,
        entry_price: float,
        broker_capital: float,
        configured_lots: int = 1
    ) -> Tuple[int, int]:
        """
        Calculate (quantity, lots).
        Supports 'fixed_lots' or 'risk_percentage' modes.
        """
        mode = self.sizing_cfg.get("mode", "fixed_lots")
        
        if mode == "risk_percentage":
            risk_pct = self.sizing_cfg.get("risk_per_trade_pct", 1.5)
            max_risk_amount = broker_capital * (risk_pct / 100.0)
            sl_point_risk = entry_price * (self.default_sl_pct / 100.0)
            
            if sl_point_risk > 0:
                raw_qty = int(max_risk_amount / sl_point_risk)
                calculated_lots = max(1, raw_qty // lot_size)
                # Cap at 5 lots max for safety
                calculated_lots = min(calculated_lots, 5)
                return calculated_lots * lot_size, calculated_lots

        # Default: fixed lots
        lots = max(1, configured_lots)
        return lots * lot_size, lots

    def evaluate_trailing_stop(self, pos: Position, current_price: float) -> Optional[float]:
        """
        Check if stop-loss should be trailed higher.
        Returns new_sl if trailed, else None.
        """
        gain_pct = ((current_price - pos.entry_price) / pos.entry_price) * 100.0
        
        # Level 1: At +15% profit, lock in Breakeven (+1%)
        if pos.trailing_level == 0 and gain_pct >= self.trail_trigger_pct:
            new_sl = round(pos.entry_price * 1.01, 2)
            if new_sl > pos.stop_loss:
                pos.trailing_level = 1
                pos.stop_loss = new_sl
                return new_sl

        # Level 2+: Trail by steps
        elif pos.trailing_level >= 1:
            threshold = self.trail_trigger_pct + (pos.trailing_level * self.trail_step_pct)
            if gain_pct >= threshold:
                lock_in_pct = threshold - self.trail_step_pct
                new_sl = round(pos.entry_price * (1.0 + lock_in_pct / 100.0), 2)
                if new_sl > pos.stop_loss:
                    pos.trailing_level += 1
                    pos.stop_loss = new_sl
                    return new_sl

        return None

    def check_stagnation(self, pos: Position, current_time: datetime = None) -> bool:
        """
        Anti-Theta Rule: If an intraday option hasn't moved favorably in
        stagnation_timeout_mins, exit early to prevent time bleed.
        """
        if current_time is None:
            current_time = get_now_ist()
            
        elapsed_mins = (current_time - pos.entry_time).total_seconds() / 60.0
        gain_pct = ((pos.current_price - pos.entry_price) / pos.entry_price) * 100.0

        # If more than timeout minutes have passed and position is sluggish (< 2% profit)
        if elapsed_mins >= self.stagnation_timeout_mins and gain_pct < 2.0:
            log.info(f"⏳ Stagnation detected on {pos.contract_symbol} (Elapsed: {elapsed_mins:.1f}m, Gain: {gain_pct:.1f}%)")
            return True

        return False

    def can_carry_forward_stock(
        self,
        pos: Position,
        days_to_expiry: int,
        daily_candle_closed_near_high: bool
    ) -> Tuple[bool, str]:
        """
        Evaluate if a stock option can be held overnight (BTST / Swing).
        Indices are NEVER carried forward.
        """
        # Indices are strictly intraday
        if pos.symbol in ["NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY"]:
            return False, "Indices are restricted to strict intraday execution"

        carry_cfg = self.stocks_cfg.get("carry_forward", {})
        if not carry_cfg.get("enabled", True):
            return False, "Stock carry-forward disabled in config"

        min_profit_pct = carry_cfg.get("min_profit_pct", 15.0)
        min_days = carry_cfg.get("min_days_to_expiry", 7)

        gain_pct = ((pos.current_price - pos.entry_price) / pos.entry_price) * 100.0

        # Must have sufficient profit cushion
        if gain_pct < min_profit_pct:
            return False, f"Profit {gain_pct:.1f}% below required buffer of {min_profit_pct}%"

        # Must have enough days to expiry to avoid delivery margin & extreme theta
        if days_to_expiry < min_days:
            return False, f"Days to expiry ({days_to_expiry}) is less than safe margin of {min_days} days"

        if not daily_candle_closed_near_high:
            return False, "Daily underlying price action does not indicate strong continuation close"

        return True, f"Qualified: Profit +{gain_pct:.1f}%, Expiry in {days_to_expiry} days, Strong closing structure"
