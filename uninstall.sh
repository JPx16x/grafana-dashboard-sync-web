#!/bin/bash

set -e

APP_NAME="grafana-dashboard-sync-web"
APP_DIR="${APP_DIR:-/opt/$APP_NAME}"
SERVICE_NAME="$APP_NAME"
ENV_FILE="/etc/default/$SERVICE_NAME"

if [ "$(id -u)" -ne 0 ]; then
  echo "[ERRO] Execute como root ou usando sudo."
  exit 1
fi

echo "[INFO] Parando servico..."
systemctl stop "$SERVICE_NAME" || true

echo "[INFO] Desabilitando servico..."
systemctl disable "$SERVICE_NAME" || true

echo "[INFO] Removendo arquivo systemd..."
rm -f "/etc/systemd/system/$SERVICE_NAME.service"

echo "[INFO] Recarregando systemd..."
systemctl daemon-reload

echo "[INFO] Removendo aplicacao..."
rm -rf "$APP_DIR"

echo "[INFO] Removendo configuracao..."
rm -f "$ENV_FILE"

echo "[OK] Grafana Dashboard Sync Web removido."
