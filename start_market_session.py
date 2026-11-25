#!/usr/bin/env python3
"""
GravityOptions - Smart Market Session Starter & Supervisor
Checks Indian Standard Time (IST) directly, ignoring the host server's local timezone.
Starts the bot if market session is active and not already running.
Supports both one-shot mode (for cron) and continuous supervisor mode (for systemd).
"""
import sys
import os

# Auto-switch to virtual environment python if available and not already inside venv
base_dir = os.path.dirname(os.path.abspath(__file__))
venv_python = os.path.join(base_dir, "venv", "bin", "python")
if os.path.exists(venv_python) and sys.executable != venv_python:
    os.execv(venv_python, [venv_python] + sys.argv)

import time
import subprocess
from datetime import datetime, time as dtime

try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except ImportError:
    try:
        import pytz
        IST = pytz.timezone("Asia/Kolkata")
    except ImportError:
        from datetime import timezone, timedelta
        IST = timezone(timedelta(hours=5, minutes=30), name="IST")

def is_trading_session_now() -> bool:
    """Return True if current time is Mon-Fri (non-holiday) between 09:10 and 15:30 IST."""
    now_ist = datetime.now(IST)
    
    # 0 = Monday, 4 = Friday
    if now_ist.weekday() >= 5:
        return False

    try:
        from src.utils.time_utils import get_market_holiday_name
        if get_market_holiday_name(now_ist):
            return False
    except Exception:
        pass

    session_start = dtime(9, 10) # Start 5 minutes before opening bell
    session_end = dtime(15, 30)
    current_time = now_ist.time()
    
    return session_start <= current_time <= session_end

def is_bot_already_running(base_dir: str) -> bool:
    """Check if run_paper_trading.py is already active via PID file or process list."""
    pid_file = os.path.join(base_dir, "data", "bot.pid")
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f:
                content = f.read().strip()
            if content:
                pid = int(content)
                if os.name != "nt":
                    os.kill(pid, 0)
                    return True
                else:
                    return True
        except (OSError, ValueError):
            pass

    # Secondary check: running processes via pgrep or ps
    try:
        output = subprocess.check_output(["pgrep", "-f", "run_paper_trading.py"]).decode().strip()
        pids = [p for p in output.split() if int(p) != os.getpid()]
        return len(pids) > 0
    except Exception:
        pass

    return False

def start_runner(base_dir: str) -> bool:
    """Launch run_paper_trading.py in background if not already running."""
    now_ist = datetime.now(IST)
    now_str = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")

    if not is_trading_session_now():
        return False

    if is_bot_already_running(base_dir):
        return False

    print(f"[{now_str}] 🚀 Indian Market session active! Launching GravityOptions background runner...")
    
    py_exec = venv_python if os.path.exists(venv_python) else sys.executable
    runner_script = os.path.join(base_dir, "run_paper_trading.py")
    log_file = os.path.join(base_dir, "trading.log")

    cmd = f"cd {base_dir} && nohup {py_exec} {runner_script} >> {log_file} 2>&1 &"
    os.system(cmd)
    print(f"[{now_str}] Started successfully! Logging to {log_file}")
    return True

def run_supervisor(base_dir: str):
    """Continuous supervisor mode (ideal for systemd service)."""
    now_ist = datetime.now(IST)
    print(f"[{now_ist.strftime('%Y-%m-%d %H:%M:%S IST')}] 🛡️ GravityOptions Supervisor daemon started.")
    
    last_log_time = 0.0
    while True:
        try:
            now_ist = datetime.now(IST)
            in_session = is_trading_session_now()
            bot_running = is_bot_already_running(base_dir)

            if in_session:
                if not bot_running:
                    print(f"[{now_ist.strftime('%Y-%m-%d %H:%M:%S IST')}] ⚠️ Market is OPEN but bot is NOT running! Restarting now...")
                    start_runner(base_dir)
            else:
                # Outside session: print status once every 30 minutes
                current_ts = time.time()
                if current_ts - last_log_time > 1800:
                    print(f"[{now_ist.strftime('%Y-%m-%d %H:%M:%S IST')}] 🌙 Market is CLOSED. Supervisor sleeping until 09:10 IST...")
                    last_log_time = current_ts

        except Exception as e:
            print(f"Supervisor loop error: {e}")

        time.sleep(15)

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    now_ist = datetime.now(IST)
    now_str = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")

    # Check if supervisor flag passed
    if "--loop" in sys.argv or "--supervisor" in sys.argv or "-d" in sys.argv:
        run_supervisor(base_dir)
        return

    # One-shot check (ideal for cron or manual CLI invocation)
    if not is_trading_session_now():
        print(f"[{now_str}] Market is CLOSED (Trading window: 09:10 - 15:30 IST Mon-Fri). Sleeping...")
        sys.exit(0)

    if is_bot_already_running(base_dir):
        print(f"[{now_str}] GravityOptions is already active and running (PID lock active). No action needed.")
        sys.exit(0)

    start_runner(base_dir)

if __name__ == "__main__":
    main()
