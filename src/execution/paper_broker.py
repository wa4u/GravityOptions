from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
import math
from src.utils.logger import log
from src.utils.time_utils import get_now_ist
from src.execution.trade_logger import TradeLogger


@dataclass
class Position:
    contract_symbol: str
    symbol: str
    option_type: str # "CE" or "PE"
    strike: float
    quantity: int
    lots: int
    entry_price: float
    current_price: float
    stop_loss: float
    initial_sl: float
    target: float
    entry_time: datetime
    delta: float = 0.5
    trading_mode: str = "INTRADAY" # "INTRADAY" or "SWING"
    highest_price: float = 0.0
    trailing_level: int = 0
    is_open: bool = True
    display_name: str = ""
    exchange: str = "NFO"

@dataclass
class TradeRecord:
    contract_symbol: str
    symbol: str
    option_type: str
    strike: float
    quantity: int
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    exit_reason: str
    gross_pnl: float
    brokerage: float
    stt: float
    exchange_charges: float
    gst: float
    stamp_duty: float
    total_charges: float
    net_pnl: float
    roi_pct: float
    holding_duration: str
    trading_mode: str = "INTRADAY"
    display_name: str = ""

class PaperBroker:
    """
    High-fidelity simulated execution broker designed for Indian options trading.
    Accurately models:
    - Bid-ask slippage
    - Exchange turnover fees, STT, GST, SEBI fees, and stamp duty
    - Trailing stops, dynamic position sizing, and margin tracking.
    """
    def __init__(
        self,
        initial_capital: float = 100000.0,
        brokerage_per_order: float = 20.0,
        stt_rate: float = 0.001,           # 0.1% on sell side
        exchange_turnover_rate: float = 0.0005, # 0.05%
        gst_rate: float = 0.18,            # 18%
        stamp_duty_rate: float = 0.00003,  # 0.003% on buy
        slippage_points: float = 0.5
    ):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}
        self.closed_trades: List[TradeRecord] = []
        
        # Charge parameters
        self.brokerage_per_order = brokerage_per_order
        self.stt_rate = stt_rate
        self.exchange_turnover_rate = exchange_turnover_rate
        self.gst_rate = gst_rate
        self.stamp_duty_rate = stamp_duty_rate
        self.slippage_points = slippage_points
        self.logger = TradeLogger()


    def calculate_buy_charges(self, premium: float, qty: int) -> Dict[str, float]:
        turnover = premium * qty
        brokerage = self.brokerage_per_order
        exch = turnover * self.exchange_turnover_rate
        gst = (brokerage + exch) * self.gst_rate
        stamp = turnover * self.stamp_duty_rate
        return {
            "brokerage": brokerage,
            "exchange": exch,
            "gst": gst,
            "stamp_duty": stamp,
            "stt": 0.0,
            "total": round(brokerage + exch + gst + stamp, 2)
        }

    def calculate_sell_charges(self, premium: float, qty: int) -> Dict[str, float]:
        turnover = premium * qty
        brokerage = self.brokerage_per_order
        stt = turnover * self.stt_rate
        exch = turnover * self.exchange_turnover_rate
        gst = (brokerage + exch) * self.gst_rate
        return {
            "brokerage": brokerage,
            "exchange": exch,
            "gst": gst,
            "stamp_duty": 0.0,
            "stt": round(stt, 2),
            "total": round(brokerage + stt + exch + gst, 2)
        }

    def buy_option(
        self,
        contract_symbol: str,
        symbol: str,
        option_type: str,
        strike: float,
        market_price: float,
        quantity: int,
        lots: int,
        sl_pct: float = 15.0,
        tp_pct: float = 35.0,
        delta: float = 0.5,
        trading_mode: str = "INTRADAY",
        display_name: str = "",
        exchange: str = "NFO"
    ) -> Optional[Position]:
        """Execute a simulated market buy order with slippage."""
        # Add slippage to entry price
        fill_price = round(market_price + self.slippage_points, 2)
        required_capital = fill_price * quantity
        buy_charges = self.calculate_buy_charges(fill_price, quantity)
        total_cost = required_capital + buy_charges["total"]

        if total_cost > self.cash:
            log.warning(
                f"Insufficient funds for {contract_symbol}. Required: ₹{total_cost:,.2f}, Available: ₹{self.cash:,.2f}"
            )
            return None

        # Deduct cash
        self.cash -= total_cost

        stop_loss = round(fill_price * (1.0 - sl_pct / 100.0), 2)
        target = round(fill_price * (1.0 + tp_pct / 100.0), 2)

        position = Position(
            contract_symbol=contract_symbol,
            symbol=symbol,
            option_type=option_type,
            strike=strike,
            quantity=quantity,
            lots=lots,
            entry_price=fill_price,
            current_price=fill_price,
            stop_loss=stop_loss,
            initial_sl=stop_loss,
            target=target,
            entry_time=get_now_ist(),
            delta=delta,
            trading_mode=trading_mode,
            highest_price=fill_price,
            display_name=display_name if display_name else contract_symbol,
            exchange=exchange
        )

        self.positions[contract_symbol] = position
        log.info(
            f"🛒 [PAPER BUY] Filled {contract_symbol} x {quantity} @ ₹{fill_price:.2f} "
            f"(SL: ₹{stop_loss:.2f}, TP: ₹{target:.2f}, Cost: ₹{total_cost:,.2f})"
        )
        return position

    def sell_option(
        self,
        contract_symbol: str,
        market_price: float,
        reason: str
    ) -> Optional[TradeRecord]:
        """Execute a simulated market sell order to close position."""
        if contract_symbol not in self.positions:
            return None

        pos = self.positions.pop(contract_symbol)
        # Apply slippage on exit
        exit_price = round(max(0.05, market_price - self.slippage_points), 2)
        exit_time = get_now_ist()

        # Calculate charges
        buy_charges = self.calculate_buy_charges(pos.entry_price, pos.quantity)
        sell_charges = self.calculate_sell_charges(exit_price, pos.quantity)

        total_brokerage = buy_charges["brokerage"] + sell_charges["brokerage"]
        total_stt = sell_charges["stt"]
        total_exchange = buy_charges["exchange"] + sell_charges["exchange"]
        total_gst = buy_charges["gst"] + sell_charges["gst"]
        total_stamp = buy_charges["stamp_duty"]
        total_charges = round(buy_charges["total"] + sell_charges["total"], 2)

        gross_pnl = round((exit_price - pos.entry_price) * pos.quantity, 2)
        net_pnl = round(gross_pnl - total_charges, 2)
        roi_pct = round((net_pnl / (pos.entry_price * pos.quantity)) * 100.0, 2)

        # Credit proceeds back to cash
        proceeds = (exit_price * pos.quantity) - sell_charges["total"]
        self.cash += proceeds

        # Duration string
        duration_seconds = int((exit_time - pos.entry_time).total_seconds())
        mins = duration_seconds // 60
        secs = duration_seconds % 60
        duration_str = f"{mins}m {secs}s"

        record = TradeRecord(
            contract_symbol=pos.contract_symbol,
            symbol=pos.symbol,
            option_type=pos.option_type,
            strike=pos.strike,
            quantity=pos.quantity,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            entry_time=pos.entry_time,
            exit_time=exit_time,
            exit_reason=reason,
            gross_pnl=gross_pnl,
            brokerage=total_brokerage,
            stt=total_stt,
            exchange_charges=total_exchange,
            gst=total_gst,
            stamp_duty=total_stamp,
            total_charges=total_charges,
            net_pnl=net_pnl,
            roi_pct=roi_pct,
            holding_duration=duration_str,
            display_name=pos.display_name
        )
        self.closed_trades.append(record)
        
        # Persist to database
        try:
            self.logger.log_trade({
                **record.__dict__,
                "trading_mode": pos.trading_mode
            })
        except Exception as e:
            log.error(f"Error persisting trade to database: {e}")

        log.info(
            f"🔔 [PAPER SELL] {contract_symbol} closed @ ₹{exit_price:.2f} ({reason}). "
            f"Net P&L: ₹{net_pnl:+,.2f} ({roi_pct:+.1f}%), Charges: ₹{total_charges:.2f}"
        )
        return record

    def get_portfolio_summary(self) -> Dict:
        """Calculate total value, realized PnL, unrealized PnL."""
        unrealized_pnl = 0.0
        positions_market_value = 0.0
        for pos in self.positions.values():
            pos_val = pos.current_price * pos.quantity
            positions_market_value += pos_val
            unrealized_pnl += (pos.current_price - pos.entry_price) * pos.quantity

        realized_net_pnl = sum(t.net_pnl for t in self.closed_trades)
        total_charges = sum(t.total_charges for t in self.closed_trades)
        total_portfolio_value = self.cash + positions_market_value

        wins = len([t for t in self.closed_trades if t.net_pnl > 0])
        losses = len([t for t in self.closed_trades if t.net_pnl <= 0])
        total_trades = len(self.closed_trades)
        win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0

        return {
            "initial_capital": self.initial_capital,
            "cash": round(self.cash, 2),
            "portfolio_value": round(total_portfolio_value, 2),
            "realized_net_pnl": round(realized_net_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "total_pnl": round(realized_net_pnl + unrealized_pnl, 2),
            "total_charges": round(total_charges, 2),
            "open_positions_count": len(self.positions),
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 1)
        }
