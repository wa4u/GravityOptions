#!/usr/bin/env python3
"""
GravityOptions - Smart Market Session Starter
Checks Indian Standard Time (IST) directly, ignoring the host server's local timezone.
Starts the bot if market session is active and not already running.
"""
import sys
import os
import subprocess
from datetime import datetime, time
import pytz

IST = pytz.timezone("Asia/Kolkata")

def is_trading_session_now() -> bool:
    """Return True if current time is Mon-Fri between 09:10 and 15:30 IST."""
    now_ist = datetime.now(IST)
    
    # 0 = Monday, 4 = Friday
    if now_ist.weekday() >= 5:
        return False

    session_start = time(9, 10) # Start 5 minutes before opening bell
    session_end = time(15, 30)
    current_time = now_ist.time()
    
    return session_start <= current_time <= session_end

def is_bot_already_running() -> bool:
    """Check if run_paper_trading.py is already active."""
    try:
        # Check running processes
        output = subprocess.check_output(["pgrep", "-f", "run_paper_trading.py"]).decode().strip()
        return len(output) > 0
    except subprocess.CalledProcessError:
        return False
    except Exception:
        return False

def main():
    now_ist = datetime.now(IST)
    now_str = now_ist.strftime("%Y-%m-%d %H:%M:%S %Z")

    if not is_trading_session_now():
        print(f"[{now_str}] Market is CLOSED. Sleeping...")
        sys.exit(0)

    if is_bot_already_running():
        print(f"[{now_str}] GravityOptions is already active and running. No action needed.")
        sys.exit(0)

    print(f"[{now_str}] 🚀 Indian Market session active! Launching GravityOptions background runner...")
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(base_dir, "venv", "bin", "python")
    if not os.path.exists(venv_python):
        venv_python = sys.executable

    runner_script = os.path.join(base_dir, "run_paper_trading.py")
    log_file = os.path.join(base_dir, "trading.log")

    cmd = f"nohup {venv_python} {runner_script} >> {log_file} 2>&1 &"
    os.system(cmd)
    print(f"[{now_str}] Started successfully! Logging to {log_file}")

if __name__ == "__main__":
    main()
