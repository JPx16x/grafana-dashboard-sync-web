#!/bin/bash

set -e

APP_NAME="grafana-dashboard-sync-web"
APP_DIR="${APP_DIR:-/opt/$APP_NAME}"
SERVICE_NAME="$APP_NAME"
ENV_FILE="/etc/default/$SERVICE_NAME"

REPO_URL="${REPO_URL:-https://github.com/JPx16x/grafana-dashboard-sync-web.git}"
APP_PORT="${APP_PORT:-8080}"
APP_USERNAME="${APP_USERNAME:-admin}"
GUNICORN_WORKERS="${GUNICORN_WORKERS:-2}"

echo "===================================================="
echo " Instalador - Grafana Dashboard Sync Web"
echo "===================================================="

if [ "$(id -u)" -ne 0 ]; then
  echo "[ERRO] Execute como root ou usando sudo."
  exit 1
fi

echo "[INFO] Atualizando pacotes..."
apt update

echo "[INFO] Instalando dependencias do sistema..."
apt install -y git python3 python3-venv python3-pip curl

if [ -z "$APP_PASSWORD" ]; then
  APP_PASSWORD=$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(14))
PY
)
  GENERATED_PASSWORD="yes"
else
  GENERATED_PASSWORD="no"
fi

APP_SECRET_KEY=$(python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)

echo "[INFO] Preparando diretorio da aplicacao: $APP_DIR"

if [ -d "$APP_DIR/.git" ]; then
  echo "[INFO] Projeto ja existe. Atualizando..."
  cd "$APP_DIR"
  git pull
else
  echo "[INFO] Clonando repositorio..."
  rm -rf "$APP_DIR"
  git clone "$REPO_URL" "$APP_DIR"
  cd "$APP_DIR"
fi

echo "[INFO] Criando ambiente virtual..."
python3 -m venv "$APP_DIR/venv"

echo "[INFO] Instalando dependencias Python..."
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "[INFO] Criando diretorios de logs e backups..."
mkdir -p "$APP_DIR/logs" "$APP_DIR/backups"

echo "[INFO] Criando arquivo de configuracao: $ENV_FILE"

if [ -f "$ENV_FILE" ]; then
  cp "$ENV_FILE" "$ENV_FILE.bak.$(date +%Y%m%d_%H%M%S)"
fi

cat > "$ENV_FILE" <<ENV
APP_USERNAME=$APP_USERNAME
APP_PASSWORD=$APP_PASSWORD
APP_SECRET_KEY=$APP_SECRET_KEY
APP_PORT=$APP_PORT
GUNICORN_WORKERS=$GUNICORN_WORKERS
ENV

chmod 600 "$ENV_FILE"

echo "[INFO] Criando servico systemd..."

cat > "/etc/systemd/system/$SERVICE_NAME.service" <<SERVICE
[Unit]
Description=Grafana Dashboard Sync Web
After=network.target

[Service]
User=root
Group=root
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=/bin/bash -lc 'exec $APP_DIR/venv/bin/gunicorn --workers \${GUNICORN_WORKERS:-2} --bind 0.0.0.0:\${APP_PORT:-8080} app:app'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

echo "[INFO] Recarregando systemd..."
systemctl daemon-reload

echo "[INFO] Habilitando servico no boot..."
systemctl enable "$SERVICE_NAME"

echo "[INFO] Reiniciando servico..."
systemctl restart "$SERVICE_NAME"

SERVER_IP=$(hostname -I | awk '{print $1}')

echo "===================================================="
echo " Instalacao concluida!"
echo "===================================================="
echo ""
echo "Acesse:"
echo "http://$SERVER_IP:$APP_PORT"
echo ""
echo "Usuario da aplicacao:"
echo "$APP_USERNAME"
echo ""
echo "Senha da aplicacao:"
echo "$APP_PASSWORD"
echo ""
if [ "$GENERATED_PASSWORD" = "yes" ]; then
  echo "[AVISO] Uma senha automatica foi gerada. Salve essa senha em local seguro."
fi
echo ""
echo "Comandos uteis:"
echo "systemctl status $SERVICE_NAME"
echo "journalctl -u $SERVICE_NAME -f"
echo "systemctl restart $SERVICE_NAME"
echo ""
