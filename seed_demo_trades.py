#!/usr/bin/env python3
"""
Seeds realistic historical sample trades across the last 30 days
to preview the Daily, Weekly, and Monthly performance analytics dashboard.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from datetime import datetime, timedelta

import random
from src.execution.trade_logger import TradeLogger
from src.reporting.report_generator import ReportGenerator

def seed():
    logger = TradeLogger()
    symbols = [
        ("NIFTY", "INDEX", 24200, 25, 50),
        ("BANKNIFTY", "INDEX", 51500, 15, 100),
        ("SENSEX", "INDEX", 79500, 10, 100),
        ("FINNIFTY", "INDEX", 23800, 25, 50),
        ("RELIANCE", "STOCK", 2980, 250, 20),
        ("HDFCBANK", "STOCK", 1740, 500, 10)
    ]

    reasons = ["Target Profit Reached", "Trailing SL Hit", "Anti-Theta Stagnation Exit", "Stop-Loss Hit"]
    now = datetime.now()

    print("🌱 Seeding realistic sample trades for the last 30 days...")

    # Generate 25 historical trades across the month
    for i in range(25):
        sym, inst_type, base_spot, lot_size, step = random.choice(symbols)
        opt_type = random.choice(["CE", "PE"])
        strike = round(base_spot / step) * step
        qty = lot_size * random.choice([1, 2])
        days_ago = random.randint(0, 28)
        exit_time = now - timedelta(days=days_ago, hours=random.randint(1, 5), minutes=random.randint(10, 50))
        entry_time = exit_time - timedelta(minutes=random.randint(12, 45))

        entry_price = round(random.uniform(90.0, 250.0), 2)
        # 68% win rate bias
        is_win = random.random() < 0.68
        if is_win:
            roi_pct = random.uniform(15.0, 38.0)
            exit_price = round(entry_price * (1.0 + roi_pct / 100.0), 2)
            reason = "Target Profit Reached" if roi_pct > 30 else "Trailing SL Hit"
        else:
            roi_pct = random.uniform(-14.0, -15.0)
            exit_price = round(entry_price * (1.0 + roi_pct / 100.0), 2)
            reason = "Stop-Loss Hit"

        gross_pnl = round((exit_price - entry_price) * qty, 2)
        brokerage = 40.0
        stt = round(exit_price * qty * 0.001, 2)
        exch = round((entry_price + exit_price) * qty * 0.0005, 2)
        gst = round((brokerage + exch) * 0.18, 2)
        stamp = round(entry_price * qty * 0.00003, 2)
        total_charges = round(brokerage + stt + exch + gst + stamp, 2)
        net_pnl = round(gross_pnl - total_charges, 2)
        duration_mins = int((exit_time - entry_time).total_seconds() / 60)

        contract = f"{sym}{strike}{opt_type}"

        logger.log_trade({
            "contract_symbol": contract,
            "symbol": sym,
            "instrument_type": inst_type,
            "option_type": opt_type,
            "strike": strike,
            "quantity": qty,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "exit_reason": reason,
            "gross_pnl": gross_pnl,
            "brokerage": brokerage,
            "stt": stt,
            "exchange_charges": exch,
            "gst": gst,
            "stamp_duty": stamp,
            "total_charges": total_charges,
            "net_pnl": net_pnl,
            "roi_pct": round(roi_pct, 1),
            "holding_duration": f"{duration_mins}m",
            "trading_mode": "INTRADAY"
        })

    # Re-generate report
    import yaml
    web_path = None
    try:
        with open("config/config.yaml", "r") as f:
            cfg = yaml.safe_load(f)
            web_path = cfg.get("system", {}).get("web_report_path")
    except Exception:
        pass

    generator = ReportGenerator(web_export_path=web_path)
    path = generator.generate_html_report()
    print(f"✅ Seeding complete! Dashboard updated: {path}")


if __name__ == "__main__":
    seed()
