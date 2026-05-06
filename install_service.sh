#!/bin/bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/grafana-dashboard-sync-web}"
SERVICE_NAME="${SERVICE_NAME:-grafana-dashboard-sync-web}"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
ENV_FILE="/etc/default/${SERVICE_NAME}"
DROPIN_DIR="/etc/systemd/system/${SERVICE_NAME}.service.d"
DROPIN_FILE="${DROPIN_DIR}/override.conf"

if [ "$(id -u)" -ne 0 ]; then
  echo "[ERRO] Execute este script como root."
  exit 1
fi

if [ ! -d "$APP_DIR" ]; then
  echo "[ERRO] Diretorio da aplicacao nao encontrado: $APP_DIR"
  exit 1
fi

if [ ! -x "$APP_DIR/venv/bin/gunicorn" ]; then
  echo "[ERRO] Gunicorn nao encontrado em: $APP_DIR/venv/bin/gunicorn"
  echo "Verifique se o ambiente virtual foi criado corretamente."
  exit 1
fi

echo "[INFO] Criando/atualizando configuracao em ${ENV_FILE}..."

touch "$ENV_FILE"
chmod 640 "$ENV_FILE"

ensure_env_var() {
  local key="$1"
  local value="$2"

  if grep -q "^${key}=" "$ENV_FILE"; then
    echo "[INFO] Mantendo ${key} ja configurado em ${ENV_FILE}."
  else
    echo "${key}=${value}" >> "$ENV_FILE"
    echo "[INFO] Adicionado ${key}=${value}"
  fi
}

ensure_env_var "APP_PORT" "8080"
ensure_env_var "GUNICORN_WORKERS" "2"
ensure_env_var "GUNICORN_TIMEOUT" "600"
ensure_env_var "GUNICORN_GRACEFUL_TIMEOUT" "600"

if [ -f "$DROPIN_FILE" ]; then
  echo "[INFO] Encontrado override antigo: ${DROPIN_FILE}"
  cp "$DROPIN_FILE" "${DROPIN_FILE}.bkp_$(date +%Y%m%d_%H%M%S)"
  rm -f "$DROPIN_FILE"
  echo "[INFO] Override antigo removido para evitar conflito com o service principal."

  rmdir "$DROPIN_DIR" 2>/dev/null || true
fi

echo "[INFO] Criando/atualizando service em ${SERVICE_FILE}..."

cat > "$SERVICE_FILE" <<SERVICE
[Unit]
Description=Grafana Dashboard Sync Web
After=network.target

[Service]
User=root
Group=root
WorkingDirectory=${APP_DIR}
EnvironmentFile=-${ENV_FILE}
ExecStart=/bin/bash -lc 'exec ${APP_DIR}/venv/bin/gunicorn --workers \${GUNICORN_WORKERS:-2} --timeout \${GUNICORN_TIMEOUT:-600} --graceful-timeout \${GUNICORN_GRACEFUL_TIMEOUT:-600} --bind 0.0.0.0:\${APP_PORT:-8080} app:app'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo
echo "[OK] Service atualizado e reiniciado com timeout configurado."
echo
echo "[INFO] Configuracao atual:"
cat "$ENV_FILE"
echo
systemctl status "$SERVICE_NAME" --no-pager
