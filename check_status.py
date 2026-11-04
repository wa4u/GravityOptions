#!/usr/bin/env python3
"""
GravityOptions - Quick System & Market Status Inspector
Displays live process status, market clock, cash balance, current positions,
and real-time quote feeds directly in the terminal.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import json
import subprocess
from datetime import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")

def check_process():
    try:
        output = subprocess.check_output(["pgrep", "-af", "run_paper_trading.py"]).decode().strip()
        lines = [l for l in output.splitlines() if "check_status.py" not in l]
        return len(lines) > 0, lines
    except Exception:
        return False, []

def main():
    now_ist = datetime.now(IST)
    now_str = now_ist.strftime("%d %b %Y, %I:%M:%S %p %Z")

    print("=" * 68)
    print("        GRAVITY OPTIONS - LIVE SYSTEM STATUS INSPECTOR")
    print(f"        Current Time: {now_str}")
    print("=" * 68)

    # 1. Process Status
    is_running, proc_lines = check_process()
    if is_running:
        print("\n🟢 BOT PROCESS: ACTIVE & RUNNING IN BACKGROUND")
        for p in proc_lines[:2]:
            print(f"   PID / Command: {p}")
    else:
        print("\n🔴 BOT PROCESS: NOT RUNNING")
        print("   To start: su -s /bin/bash gravitywork -c \"venv/bin/python start_market_session.py\"")

    # 2. Market Session
    is_weekday = now_ist.weekday() < 5
    m_start = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
    m_end = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
    is_open = is_weekday and (m_start <= now_ist <= m_end)

    status_str = "🟢 OPEN (09:15 - 15:30 IST)" if is_open else "🔴 CLOSED"
    print(f"\n🏛️  INDIAN MARKET: {status_str}")

    # 3. Live Status File
    status_file = "data/live_status.json"
    if os.path.exists(status_file):
        try:
            with open(status_file, "r") as f:
                st = json.load(f)

            print("\n💼 PORTFOLIO & MARGIN:")
            print(f"  • Cash Available:    ₹{st.get('cash', 100000):,.2f}")
            pnl = st.get('total_pnl', 0.0)
            sign = "+" if pnl >= 0 else ""
            print(f"  • Today's Total P&L: {sign}₹{pnl:,.2f}")
            print(f"  • Active Positions:  {st.get('open_positions', 0)} / 3 allowed")
            print(f"  • Last Scan Heartbeat: {st.get('timestamp', 'N/A')}")

            quotes = st.get("quotes", [])
            if quotes:
                print("\n📈 LIVE QUOTES BEING TRACKED:")
                for q in quotes:
                    print(f"  • {q}")

            positions = st.get("positions", [])
            if positions:
                print("\n🎯 ACTIVE OPEN POSITIONS:")
                for p in positions:
                    print(f"  • Contract: {p.get('contract')}")
                    print(f"    Qty: {p.get('quantity')} | Buy: ₹{p.get('entry_price')} | LTP: ₹{p.get('current_price')} | SL: ₹{p.get('stop_loss')} | TP: ₹{p.get('target')}")
            else:
                print("\n🎯 ACTIVE OPEN POSITIONS: None (Waiting for breakout criteria)")

        except Exception as e:
            print(f"  ⚠️ Could not read {status_file}: {e}")
    else:
        print("\nℹ️  Live status file not generated yet. Check trading.log for progress.")

    # 4. Recent Log Lines
    log_file = "trading.log"
    if os.path.exists(log_file):
        print("\n📜 LAST 5 LINES OF TRADING LOG:")
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                for l in lines[-5:]:
                    print(f"   {l.strip()}")
        except Exception:
            pass

    print("\n" + "=" * 68)
    print("🌐 Web Dashboard:   https://gravity.work.gd/")
    print("🛠️ Control Center:  https://gravity.work.gd/helper.html")
    print("=" * 68)

if __name__ == "__main__":
    main()
