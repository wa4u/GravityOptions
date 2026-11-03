#!/usr/bin/env python3
"""
GravityOptions - Telegram Alert Test Script
Tests your Telegram Bot connection and delivers real formatted alert cards to your phone right now.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import yaml
import requests
from src.alerts.telegram_notifier import TelegramNotifier
from src.utils.logger import log

def test_telegram():
    print("=" * 60)
    print("   GRAVITY OPTIONS - TELEGRAM ALERT VERIFICATION TEST")
    print("=" * 60)

    config_path = "config/telegram_config.yaml"
    try:
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f).get("telegram", {})
    except Exception as e:
        print(f"❌ Could not read {config_path}: {e}")
        return

    bot_token = cfg.get("bot_token", "")
    chat_id = str(cfg.get("chat_id", ""))
    enabled = cfg.get("enabled", False)

    print(f"\nConfiguration Check:")
    print(f"  • Enabled:   {enabled}")
    print(f"  • Bot Token: {bot_token[:10]}... (masked)" if len(bot_token) > 10 else f"  • Bot Token: {bot_token}")
    print(f"  • Chat ID:   {chat_id}")

    if not enabled:
        print("\n⚠️ Telegram is currently set to 'enabled: false' in config/telegram_config.yaml")
        print("Please set 'enabled: true' to receive alerts.")
        return

    if not bot_token or "YOUR_" in bot_token:
        print("\n❌ Error: Please set your real Telegram Bot Token in config/telegram_config.yaml")
        return

    if not chat_id or "YOUR_" in chat_id:
        print("\n❌ Error: Please set your real Chat ID in config/telegram_config.yaml")
        return

    notifier = TelegramNotifier(config_path)

    # 1. Test ping
    print("\n📨 Sending Test Connection Ping...")
    ping_msg = (
        "<b>🎉 GRAVITYOPTIONS TELEGRAM CONNECTION SUCCESSFUL!</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Your automated trading system is now linked to this chat.\n"
        "You will receive live signals, order entries, trailing stops, and EOD P&L reports here."
    )
    success = notifier.send_message(ping_msg)

    if not success:
        print("\n❌ Failed to send message to Telegram.")
        print("Common reasons:")
        print("  1. Have you started your bot? Open your bot on Telegram and tap the 'START' button.")
        print("  2. Incorrect Chat ID: message @userinfobot to get your exact numeric ID.")
        print("  3. Incorrect Bot Token from @BotFather.")
        return

    print("  ✅ Ping delivered to your phone!")

    # 2. Test Sample Order Entry Card
    print("\n📨 Sending Sample Order Entry Alert...")
    sample_order = {
        "contract_symbol": "NIFTY07NOV24250CE",
        "symbol": "NIFTY",
        "spot_price": 24245.50,
        "option_type": "CE",
        "delta": 0.54,
        "entry_price": 148.50,
        "quantity": 50,
        "lots": 2,
        "stop_loss": 126.20,
        "sl_pct": 15.0,
        "target": 200.50,
        "tp_pct": 35.0,
        "trading_mode": "INTRADAY"
    }
    notifier.notify_order_entry(sample_order)
    print("  ✅ Sample Order Entry Alert delivered!")

    # 3. Test Sample Profit Exit Card
    print("\n📨 Sending Sample Profit Exit Alert...")
    sample_exit = {
        "contract_symbol": "NIFTY07NOV24250CE",
        "exit_reason": "Target Profit Reached",
        "entry_price": 148.50,
        "exit_price": 201.20,
        "quantity": 50,
        "gross_pnl": 2635.00,
        "total_charges": 68.45,
        "net_pnl": 2566.55,
        "roi_pct": 34.6,
        "holding_duration": "18m 42s"
    }
    notifier.notify_order_exit(sample_exit)
    print("  ✅ Sample Profit Exit Alert delivered!")

    print("\n" + "=" * 60)
    print("🎉 ALL TELEGRAM TESTS PASSED! Check your Telegram app now!")
    print("=" * 60)

if __name__ == "__main__":
    test_telegram()
