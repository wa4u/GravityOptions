#!/usr/bin/env python3
"""
GravityOptions - Live Paper Trading Runner
Executes real-time options buying automation for Indian Indices and Stocks.
"""
import sys
import os

base_dir = os.path.dirname(os.path.abspath(__file__))
if base_dir:
    os.chdir(base_dir)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import time
from datetime import datetime
from src.utils.logger import log
from src.utils.time_utils import get_now_ist, is_market_open
from src.engine import TradingEngine

def main():
    print("=" * 60)
    print("   GRAVITY OPTIONS - AUTOMATED OPTIONS BUYING SYSTEM")
    print("   Paper Trading & Real-time Telegram Alerting")
    print("=" * 60)

    try:
        engine = TradingEngine(config_file="config/config.yaml", telegram_file="config/telegram_config.yaml")
    except Exception as e:
        log.critical(f"Failed to initialize Trading Engine: {e}")
        sys.exit(1)

    log.info("System initialized. Starting market monitor...")
    log.info("Press Ctrl+C to terminate cleanly.")

    try:
        while True:
            now = get_now_ist()
            
            # Check market session
            if not is_market_open(now) and engine.config.get("system", {}).get("mode") == "live":
                log.info(f"Market closed [{now.strftime('%H:%M:%S')}]. Waiting for next session (09:15 - 15:30 IST)...")
                time.sleep(30)
                continue

            # Run trading cycle
            engine.run_cycle()

            # End of day check
            if now.hour == 15 and now.minute >= 30:
                engine.generate_eod_summary()
                log.info("Market session concluded. EOD summary generated.")
                break

            time.sleep(5) # 5-second polling loop

    except KeyboardInterrupt:
        log.warning("\nShutdown requested by user. Generating current session summary...")
        engine.generate_eod_summary()
        engine.feed.disconnect()
        log.info("Clean shutdown complete.")

if __name__ == "__main__":
    main()
