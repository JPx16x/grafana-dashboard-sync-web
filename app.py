from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
import hmac
import os
import requests

from sync_engine import run_sync

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET_KEY", "change-this-secret-key")

APP_USERNAME = os.environ.get("APP_USERNAME", "admin")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            if request.path.startswith("/api/"):
                return jsonify({
                    "ok": False,
                    "message": "Sessao expirada ou usuario nao autenticado."
                }), 401
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper


def normalize_url(url):
    return url.strip().rstrip("/")


def grafana_session(user, password):
    session_req = requests.Session()
    session_req.auth = (user, password)
    return session_req


def get_headers(org_id):
    return {
        "Content-Type": "application/json",
        "X-Grafana-Org-Id": str(org_id)
    }


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        valid_user = hmac.compare_digest(username, APP_USERNAME)
        valid_password = bool(APP_PASSWORD) and hmac.compare_digest(password, APP_PASSWORD)

        if valid_user and valid_password:
            session["authenticated"] = True
            session["username"] = username
            return redirect(url_for("index"))

        error = "Usuario ou senha invalidos."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/api/test-connection", methods=["POST"])
@login_required
def test_connection():
    data = request.get_json() or {}

    grafana_url = normalize_url(data.get("grafana_url", ""))
    grafana_user = data.get("grafana_user", "").strip()
    grafana_password = data.get("grafana_password", "")

    if not grafana_url or not grafana_user or not grafana_password:
        return jsonify({
            "ok": False,
            "message": "Informe URL, usuario e senha do Grafana."
        }), 400

    try:
        session_req = grafana_session(grafana_user, grafana_password)

        orgs_response = session_req.get(
            f"{grafana_url}/api/orgs",
            timeout=15
        )

        if orgs_response.status_code != 200:
            return jsonify({
                "ok": False,
                "message": f"Falha ao listar organizacoes. HTTP {orgs_response.status_code}",
                "details": orgs_response.text
            }), 500

        orgs = orgs_response.json() or []

        return jsonify({
            "ok": True,
            "message": "Conexao realizada com sucesso.",
            "orgs": orgs
        })

    except requests.RequestException as exc:
        return jsonify({
            "ok": False,
            "message": "Erro de conexao com o Grafana.",
            "details": str(exc)
        }), 500


@app.route("/api/source-data", methods=["POST"])
@login_required
def source_data():
    data = request.get_json() or {}

    grafana_url = normalize_url(data.get("grafana_url", ""))
    grafana_user = data.get("grafana_user", "").strip()
    grafana_password = data.get("grafana_password", "")
    source_org_id = data.get("source_org_id")

    if not grafana_url or not grafana_user or not grafana_password or not source_org_id:
        return jsonify({
            "ok": False,
            "message": "Informe URL, usuario, senha e organizacao origem."
        }), 400

    try:
        source_org_id = int(source_org_id)
        session_req = grafana_session(grafana_user, grafana_password)

        dashboards_response = session_req.get(
            f"{grafana_url}/api/search",
            params={"type": "dash-db"},
            headers=get_headers(source_org_id),
            timeout=20
        )

        if dashboards_response.status_code != 200:
            return jsonify({
                "ok": False,
                "message": f"Falha ao listar dashboards. HTTP {dashboards_response.status_code}",
                "details": dashboards_response.text
            }), 500

        datasources_response = session_req.get(
            f"{grafana_url}/api/datasources",
            headers=get_headers(source_org_id),
            timeout=20
        )

        if datasources_response.status_code != 200:
            return jsonify({
                "ok": False,
                "message": f"Falha ao listar datasources. HTTP {datasources_response.status_code}",
                "details": datasources_response.text
            }), 500

        dashboards = dashboards_response.json() or []
        datasources = datasources_response.json() or []

        dashboards = [
            {
                "uid": dash.get("uid"),
                "title": dash.get("title"),
                "folderTitle": dash.get("folderTitle") or "General",
                "url": dash.get("url")
            }
            for dash in dashboards
            if dash.get("type") == "dash-db"
        ]

        datasources = [
            {
                "uid": ds.get("uid"),
                "name": ds.get("name"),
                "type": ds.get("type"),
                "isDefault": ds.get("isDefault", False)
            }
            for ds in datasources
        ]

        return jsonify({
            "ok": True,
            "message": "Dados da organizacao origem carregados com sucesso.",
            "dashboards": dashboards,
            "datasources": datasources
        })

    except Exception as exc:
        return jsonify({
            "ok": False,
            "message": "Erro ao carregar dados da organizacao origem.",
            "details": str(exc)
        }), 500


@app.route("/api/run-sync", methods=["POST"])
@login_required
def run_sync_api():
    data = request.get_json() or {}

    try:
        result = run_sync(data)

        status_code = 200
        if not result.get("ok"):
            status_code = 400

        return jsonify(result), status_code

    except Exception as exc:
        return jsonify({
            "ok": False,
            "message": "Erro inesperado ao executar sincronizacao.",
            "details": str(exc)
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("APP_PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=True)
