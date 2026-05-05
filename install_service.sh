#!/bin/bash
set -e

APP_DIR="/opt/grafana-dashboard-sync-web"
SERVICE_NAME="grafana-dashboard-sync-web"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo "[INFO] Criando/atualizando service do ${SERVICE_NAME}..."

cat > "$SERVICE_FILE" <<SERVICE
[Unit]
Description=Grafana Dashboard Sync Web
After=network.target

[Service]
User=root
Group=root
WorkingDirectory=${APP_DIR}
EnvironmentFile=/etc/default/grafana-dashboard-sync-web
ExecStart=/bin/bash -lc 'exec ${APP_DIR}/venv/bin/gunicorn --workers \${GUNICORN_WORKERS:-2} --timeout \${GUNICORN_TIMEOUT:-300} --graceful-timeout \${GUNICORN_GRACEFUL_TIMEOUT:-300} --bind 0.0.0.0:\${APP_PORT:-8080} app:app'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

if [ ! -f /etc/default/grafana-dashboard-sync-web ]; then
  echo "[INFO] Criando arquivo /etc/default/grafana-dashboard-sync-web..."
  cat > /etc/default/grafana-dashboard-sync-web <<ENV
APP_PORT=8080
GUNICORN_WORKERS=2
GUNICORN_TIMEOUT=300
GUNICORN_GRACEFUL_TIMEOUT=300
ENV
fi

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo "[OK] Service atualizado e reiniciado com timeout configurado."
systemctl status "$SERVICE_NAME" --no-pager
