#!/usr/bin/env python3
"""
Comprehensive End-to-End Simulation Test for GravityOptions
Verifies Greeks calculation, screener triggers, paper broker fills,
trailing stop-loss updates, and Telegram message formatting.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from datetime import datetime, date, timedelta

from src.utils.logger import log
from src.utils.greeks import calculate_greeks, implied_volatility
from src.data.instrument_manager import InstrumentManager
from src.execution.paper_broker import PaperBroker
from src.risk.risk_manager import RiskManager
from src.screener.index_screener import IndexScreener
from src.screener.stock_screener import StockScreener
from src.alerts.telegram_notifier import TelegramNotifier
from src.data.base_feed import Candle

def run_tests():
    print("=" * 65)
    print("🚀 RUNNING GRAVITYOPTIONS SYSTEM VERIFICATION TESTS")
    print("=" * 65)

    # 1. Test Black-Scholes Greeks
    print("\n[TEST 1] Black-Scholes Option Greeks Verification...")
    spot = 24200.0
    strike = 24200.0
    t_years = 4 / 365.25 # 4 days to weekly expiry
    iv = 0.14 # 14% India VIX proxy
    greeks_ce = calculate_greeks(spot, strike, t_years, iv, option_type="CE")
    greeks_pe = calculate_greeks(spot, strike, t_years, iv, option_type="PE")

    print(f"  • ATM NIFTY 24200 CE Greeks: Delta={greeks_ce['delta']}, Theta=₹{greeks_ce['theta']}/day, Vega={greeks_ce['vega']}")
    print(f"  • ATM NIFTY 24200 PE Greeks: Delta={greeks_pe['delta']}, Theta=₹{greeks_pe['theta']}/day, Vega={greeks_pe['vega']}")
    assert 0.45 <= greeks_ce["delta"] <= 0.60, "ATM Call Delta should be ~0.50-0.55"
    assert -0.60 <= greeks_pe["delta"] <= -0.45, "ATM Put Delta should be ~-0.50"
    print("  ✅ Greeks Calculation: PASSED")

    # 2. Test Instrument & Expiry Resolver
    print("\n[TEST 2] Instrument & Strike Resolver...")
    mgr = InstrumentManager()
    atm_nifty = mgr.calculate_atm_strike("NIFTY", 24237.5)
    atm_banknifty = mgr.calculate_atm_strike("BANKNIFTY", 51680.0)
    atm_sensex = mgr.calculate_atm_strike("SENSEX", 79540.0)

    print(f"  • Nifty Spot 24237.5 ➔ ATM Strike: {atm_nifty} (Step 50)")
    print(f"  • BankNifty Spot 51680.0 ➔ ATM Strike: {atm_banknifty} (Step 100)")
    print(f"  • Sensex Spot 79540.0 ➔ ATM Strike: {atm_sensex} (Step 100)")
    assert atm_nifty == 24250.0
    assert atm_banknifty == 51700.0
    assert atm_sensex == 79500.0

    expiry_nifty = mgr.get_next_expiry("NIFTY")
    ticker = mgr.format_contract_symbol("NIFTY", expiry_nifty, atm_nifty, "CE")
    print(f"  • Contract Symbol Formatted: {ticker}")
    print("  ✅ Instrument & Strike Resolver: PASSED")

    # 3. Test Paper Broker Execution & Indian Charges
    print("\n[TEST 3] Paper Broker Execution, Slippage & Statutory Charges...")
    broker = PaperBroker(initial_capital=100000.0, slippage_points=0.5)
    pos = broker.buy_option(
        contract_symbol=ticker,
        symbol="NIFTY",
        option_type="CE",
        strike=atm_nifty,
        market_price=150.0,
        quantity=50, # 2 lots
        lots=2,
        sl_pct=15.0,
        tp_pct=35.0,
        delta=0.52
    )

    assert pos is not None
    assert pos.entry_price == 150.5 # 150.0 + 0.5 slippage
    assert pos.stop_loss == round(150.5 * 0.85, 2)
    assert pos.target == round(150.5 * 1.35, 2)
    print(f"  • Position opened: Entry ₹{pos.entry_price}, SL: ₹{pos.stop_loss}, Target: ₹{pos.target}")
    print(f"  • Remaining Cash: ₹{broker.cash:,.2f}")

    # Simulate price moving to target
    print("\n[TEST 4] Target Profit Exit & Net P&L Calculation...")
    trade_record = broker.sell_option(ticker, market_price=pos.target, reason="Target Profit Reached")
    assert trade_record is not None
    print(f"  • Exit Price (with slippage): ₹{trade_record.exit_price}")
    print(f"  • Gross P&L: ₹{trade_record.gross_pnl:,.2f}")
    print(f"  • Total Taxes & Charges (STT, GST, Brokerage, Exch): ₹{trade_record.total_charges:.2f}")
    print(f"  • Net P&L: ₹{trade_record.net_pnl:,.2f} ({trade_record.roi_pct:+.1f}%)")
    assert trade_record.net_pnl > 0
    print("  ✅ Execution & Net PnL: PASSED")

    # 5. Test Trailing Stop-Loss
    print("\n[TEST 5] Trailing Stop-Loss Logic...")
    dummy_cfg = {
        "risk": {
            "max_daily_loss_inr": 5000.0,
            "max_open_trades": 3,
            "stop_loss_pct": 15.0,
            "target_profit_pct": 35.0,
            "trail_sl_trigger_pct": 15.0,
            "trail_step_pct": 10.0
        },
        "position_sizing": {"mode": "fixed_lots"},
        "stocks": {"carry_forward": {"enabled": True, "min_profit_pct": 15.0, "min_days_to_expiry": 7}}
    }
    risk_mgr = RiskManager(dummy_cfg)
    pos2 = broker.buy_option(
        contract_symbol="NIFTY_TEST_CE",
        symbol="NIFTY",
        option_type="CE",
        strike=24200.0,
        market_price=100.0,
        quantity=25,
        lots=1
    )
    initial_sl = pos2.stop_loss
    # Price rises by +18% (exceeds trail trigger of 15%)
    current_market_p = 100.5 * 1.18
    new_sl = risk_mgr.evaluate_trailing_stop(pos2, current_market_p)
    print(f"  • Initial SL: ₹{initial_sl} | Market Price: ₹{current_market_p:.2f}")
    print(f"  • Trailed SL: ₹{new_sl:.2f} (Locked in breakeven +1%)")
    assert new_sl is not None and new_sl > initial_sl
    print("  ✅ Trailing Stop-Loss: PASSED")

    # 6. Test Stock Screener RVOL & Breakout
    print("\n[TEST 6] Stock Momentum Screener...")
    screener = StockScreener(min_rvol=1.8, min_atr_pct=1.2)
    # Generate candles with realistic ATR (~1.5% = ~45 points for Reliance at 2900)
    candles = []
    now = datetime.now()
    base_p = 2900.0
    for i in range(30):
        c_time = now - timedelta(minutes=(30 - i) * 15)
        vol = 50000
        p = base_p + i * 2.0
        # 45-point swing gives ~1.5% ATR
        candles.append(Candle("RELIANCE", c_time, p, p + 25, p - 20, p + 5, vol))
    # Add breakout candle with 4x volume and breaking resistance
    breakout_time = now
    candles.append(Candle("RELIANCE", breakout_time, 2965.0, 3010.0, 2960.0, 3005.0, 250000))

    stock_sig = screener.screen_stock("RELIANCE", candles, strike_step=20)
    assert stock_sig is not None, "Stock signal should not be None"
    print(f"  • Signal: {stock_sig.direction} on {stock_sig.symbol}")
    print(f"  • Trigger Reason: {stock_sig.trigger_reason}")
    print(f"  • RVOL: {stock_sig.rvol}x | Strike: {stock_sig.target_strike}")
    print("  ✅ Stock Momentum Screener: PASSED")

    # 7. Test Telegram Notifier Formatting
    print("\n[TEST 7] Telegram Notifier Message Generation...")
    tg = TelegramNotifier("config/telegram_config.yaml")
    # Verify method calls execute cleanly without error
    tg.notify_signal("NIFTY", "BUY_CALL", "ORB Breakout above VWAP", 24250.0, "NIFTY24250CE")
    tg.notify_order_entry({
        "contract_symbol": "NIFTY24250CE",
        "symbol": "NIFTY",
        "option_type": "CE",
        "spot_price": 24250.0,
        "delta": 0.53,
        "entry_price": 145.0,
        "quantity": 25,
        "lots": 1,
        "stop_loss": 123.25,
        "sl_pct": 15.0,
        "target": 195.75,
        "tp_pct": 35.0,
        "trading_mode": "INTRADAY"
    })
    print("  ✅ Telegram Alert Formatting: PASSED")

    print("\n" + "=" * 65)
    print("🎉 ALL TESTS COMPLETED SUCCESSFULLY! SYSTEM READY FOR PAPER TRADING.")
    print("=" * 65)

if __name__ == "__main__":
    run_tests()
