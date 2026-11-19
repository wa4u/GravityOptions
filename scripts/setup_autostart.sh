#!/usr/bin/env bash
# ==============================================================================
# GravityOptions - Automatic System Startup & Supervisor Installer
# Configures systemd and crontab so the bot automatically runs on reboot and market open.
# ==============================================================================

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
SERVICE_NAME="gravityoptions.service"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"

echo "================================================================="
echo "⚙️  CONFIGURING GRAVITYOPTIONS AUTO-START & REBOOT PERSISTENCE"
echo "================================================================="
echo "Target Directory: ${DIR}"

# 1. Verify virtualenv exists
if [ ! -f "${DIR}/venv/bin/python" ]; then
    echo "❌ Error: Virtual environment not found at ${DIR}/venv/bin/python"
    echo "Please create venv first: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# 2. Generate customized systemd service file
cat <<EOF > "${SERVICE_PATH}"
[Unit]
Description=GravityOptions Automated Options Buying Bot Supervisor
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${DIR}
ExecStart=${DIR}/venv/bin/python ${DIR}/start_market_session.py --loop
Restart=always
RestartSec=15
StandardOutput=append:${DIR}/supervisor.log
StandardError=append:${DIR}/supervisor.log

[Install]
WantedBy=multi-user.target
EOF

echo "✅ Installed systemd unit to ${SERVICE_PATH}"

# 3. Reload systemd, enable at boot, and start
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"
echo "✅ systemd service '${SERVICE_NAME}' enabled on boot & started!"

# 4. Configure cron as a secondary watchdog
CRON_REBOOT="@reboot ${DIR}/venv/bin/python ${DIR}/start_market_session.py >> ${DIR}/cron.log 2>&1"
CRON_WATCHDOG="*/5 * * * * ${DIR}/venv/bin/python ${DIR}/start_market_session.py >> ${DIR}/cron.log 2>&1"

# Check if crontab already has GravityOptions
(crontab -l 2>/dev/null | grep -v "start_market_session.py" || true; echo "${CRON_REBOOT}"; echo "${CRON_WATCHDOG}") | crontab -
echo "✅ crontab watchdog configured (@reboot and every 5 minutes during market hours)"

echo ""
echo "================================================================="
echo "🎉 AUTO-START SETUP COMPLETE!"
echo "• The bot supervisor is now running in the background."
echo "• If the server is rebooted, systemd will start it automatically."
echo "• During market hours (09:10 - 15:30 IST), it auto-launches trading."
echo "• Outside market hours, it sleeps safely until the next morning."
echo "================================================================="
echo ""
systemctl status "${SERVICE_NAME}" --no-pager || true
