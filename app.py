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


@app.route("/api/create-org", methods=["POST"])
@login_required
def create_org_api():
    data = request.get_json() or {}

    grafana_url = normalize_url(data.get("grafana_url", ""))
    grafana_user = data.get("grafana_user", "").strip()
    grafana_password = data.get("grafana_password", "")
    org_name = data.get("org_name", "").strip()

    if not grafana_url:
        return jsonify({"ok": False, "error": "Informe a URL do Grafana."}), 400

    if not grafana_user or not grafana_password:
        return jsonify({"ok": False, "error": "Informe usuario e senha do Grafana."}), 400

    if not org_name:
        return jsonify({"ok": False, "error": "Informe o nome da organizacao."}), 400

    try:
        session_grafana = grafana_session(grafana_user, grafana_password)

        response = session_grafana.post(
            f"{grafana_url}/api/orgs",
            json={"name": org_name},
            timeout=30,
        )

        if response.status_code in (200, 201):
            payload = response.json() if response.text else {}
            return jsonify({
                "ok": True,
                "message": f"Organizacao '{org_name}' criada com sucesso.",
                "org": payload,
            })

        if response.status_code == 409:
            return jsonify({
                "ok": False,
                "error": f"Organizacao '{org_name}' ja existe.",
            }), 409

        return jsonify({
            "ok": False,
            "error": f"Falha ao criar organizacao. HTTP {response.status_code}: {response.text}",
        }), response.status_code

    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/create-orgs-bulk", methods=["POST"])
@login_required
def create_orgs_bulk_api():
    data = request.get_json() or {}

    grafana_url = normalize_url(data.get("grafana_url", ""))
    grafana_user = data.get("grafana_user", "").strip()
    grafana_password = data.get("grafana_password", "")
    org_names = data.get("org_names", [])

    if not grafana_url:
        return jsonify({"ok": False, "error": "Informe a URL do Grafana."}), 400

    if not grafana_user or not grafana_password:
        return jsonify({"ok": False, "error": "Informe usuario e senha do Grafana."}), 400

    if not isinstance(org_names, list):
        return jsonify({"ok": False, "error": "A lista de organizacoes esta invalida."}), 400

    clean_names = []
    seen = set()

    for name in org_names:
        clean_name = str(name).strip()
        if not clean_name:
            continue

        key = clean_name.lower()
        if key in seen:
            continue

        seen.add(key)
        clean_names.append(clean_name)

    if not clean_names:
        return jsonify({"ok": False, "error": "Nenhuma organizacao valida informada."}), 400

    results = []
    created = 0
    already_exists = 0
    errors = 0

    try:
        session_grafana = grafana_session(grafana_user, grafana_password)

        for org_name in clean_names:
            try:
                response = session_grafana.post(
                    f"{grafana_url}/api/orgs",
                    json={"name": org_name},
                    timeout=30,
                )

                if response.status_code in (200, 201):
                    created += 1
                    payload = response.json() if response.text else {}
                    results.append({
                        "name": org_name,
                        "status": "created",
                        "message": "Criada com sucesso.",
                        "org": payload,
                    })
                    continue

                if response.status_code == 409:
                    already_exists += 1
                    results.append({
                        "name": org_name,
                        "status": "exists",
                        "message": "Organizacao ja existe.",
                    })
                    continue

                errors += 1
                results.append({
                    "name": org_name,
                    "status": "error",
                    "message": f"HTTP {response.status_code}: {response.text}",
                })

            except Exception as item_exc:
                errors += 1
                results.append({
                    "name": org_name,
                    "status": "error",
                    "message": str(item_exc),
                })

        return jsonify({
            "ok": errors == 0,
            "summary": {
                "total": len(clean_names),
                "created": created,
                "already_exists": already_exists,
                "errors": errors,
            },
            "results": results,
        })

    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/create-users-bulk", methods=["POST"])
@login_required
def create_users_bulk_api():
    data = request.get_json() or {}

    grafana_url = normalize_url(data.get("grafana_url", ""))
    grafana_user = data.get("grafana_user", "").strip()
    grafana_password = data.get("grafana_password", "")
    users = data.get("users") or []

    if not grafana_url:
        return jsonify({"ok": False, "error": "Informe a URL do Grafana."}), 400

    if not grafana_user or not grafana_password:
        return jsonify({"ok": False, "error": "Informe usuario e senha do Grafana."}), 400

    if not isinstance(users, list) or not users:
        return jsonify({"ok": False, "error": "Informe pelo menos um usuario para criar."}), 400

    allowed_roles = {
        "admin": "Admin",
        "editor": "Editor",
        "viewer": "Viewer",
    }

    results = []
    success_count = 0
    error_count = 0

    try:
        session_grafana = grafana_session(grafana_user, grafana_password)

        orgs_response = session_grafana.get(
            f"{grafana_url}/api/orgs",
            timeout=30,
        )

        if orgs_response.status_code != 200:
            return jsonify({
                "ok": False,
                "error": f"Falha ao listar organizacoes. HTTP {orgs_response.status_code}: {orgs_response.text}",
            }), orgs_response.status_code

        orgs = orgs_response.json() or []
        org_map = {
            str(org.get("name", "")).strip().lower(): org
            for org in orgs
            if org.get("name")
        }

        for index, item in enumerate(users, start=1):
            login = str(item.get("usuario") or item.get("login") or item.get("user") or "").strip()
            email = str(item.get("email") or "").strip()
            name = str(item.get("nome") or item.get("name") or login or email).strip()
            password = str(item.get("senha") or item.get("password") or "").strip()
            role_raw = str(item.get("role") or item.get("permissao") or item.get("permissao") or "").strip()
            org_name = str(item.get("organizacao") or item.get("organization") or item.get("org") or "").strip()

            row_result = {
                "line": index,
                "usuario": login,
                "email": email,
                "nome": name,
                "role": role_raw,
                "organizacao": org_name,
                "status": "ok",
                "messages": [],
            }

            try:
                if not login and email:
                    login = email
                    row_result["usuario"] = login

                if not email and login:
                    email = login
                    row_result["email"] = email

                if not login:
                    raise RuntimeError("Usuario/login nao informado.")

                if not email:
                    raise RuntimeError("Email nao informado.")

                if not password:
                    raise RuntimeError("Senha nao informada.")

                if not role_raw:
                    raise RuntimeError("Permissao nao informada. Use Admin, Editor ou Viewer.")

                role = allowed_roles.get(role_raw.lower())

                if not role:
                    raise RuntimeError("Permissao invalida. Use Admin, Editor ou Viewer.")

                row_result["role"] = role

                if not org_name:
                    raise RuntimeError("Organizacao nao informada.")

                target_org = org_map.get(org_name.lower())

                if not target_org:
                    raise RuntimeError(f"Organizacao '{org_name}' nao encontrada no Grafana.")

                target_org_id = target_org.get("id")

                if not target_org_id:
                    raise RuntimeError(f"Organizacao '{org_name}' sem ID valido.")

                user_lookup = None

                lookup_response = session_grafana.get(
                    f"{grafana_url}/api/users/lookup",
                    params={"loginOrEmail": login},
                    timeout=30,
                )

                if lookup_response.status_code == 200:
                    user_lookup = lookup_response.json()
                    row_result["messages"].append("Usuario ja existe.")
                elif lookup_response.status_code == 404:
                    create_response = session_grafana.post(
                        f"{grafana_url}/api/admin/users",
                        json={
                            "name": name,
                            "email": email,
                            "login": login,
                            "password": password,
                        },
                        timeout=30,
                    )

                    if create_response.status_code not in (200, 201):
                        raise RuntimeError(
                            f"Falha ao criar usuario. HTTP {create_response.status_code}: {create_response.text}"
                        )

                    user_lookup = create_response.json() if create_response.text else {}
                    row_result["messages"].append("Usuario criado.")
                else:
                    raise RuntimeError(
                        f"Falha ao consultar usuario. HTTP {lookup_response.status_code}: {lookup_response.text}"
                    )

                add_response = session_grafana.post(
                    f"{grafana_url}/api/orgs/{target_org_id}/users",
                    json={
                        "loginOrEmail": login,
                        "role": role,
                    },
                    timeout=30,
                )

                if add_response.status_code in (200, 201):
                    row_result["messages"].append(f"Usuario vinculado na organizacao como {role}.")
                elif add_response.status_code in (400, 409, 412):
                    users_response = session_grafana.get(
                        f"{grafana_url}/api/orgs/{target_org_id}/users",
                        timeout=30,
                    )

                    if users_response.status_code != 200:
                        raise RuntimeError(
                            f"Usuario pode ja existir na org, mas falhou ao listar usuarios da org. HTTP {users_response.status_code}: {users_response.text}"
                        )

                    org_users = users_response.json() or []
                    matched_user = None

                    for org_user in org_users:
                        org_login = str(org_user.get("login") or "").lower()
                        org_email = str(org_user.get("email") or "").lower()

                        if org_login == login.lower() or org_email == email.lower():
                            matched_user = org_user
                            break

                    if not matched_user:
                        raise RuntimeError(
                            f"Falha ao vincular usuario na organizacao. HTTP {add_response.status_code}: {add_response.text}"
                        )

                    user_id = matched_user.get("userId") or matched_user.get("id")

                    if not user_id:
                        raise RuntimeError("Usuario encontrado na org, mas sem userId para atualizar permissao.")

                    patch_response = session_grafana.patch(
                        f"{grafana_url}/api/orgs/{target_org_id}/users/{user_id}",
                        json={"role": role},
                        timeout=30,
                    )

                    if patch_response.status_code not in (200, 201):
                        raise RuntimeError(
                            f"Falha ao atualizar permissao. HTTP {patch_response.status_code}: {patch_response.text}"
                        )

                    row_result["messages"].append(f"Usuario ja estava na organizacao. Permissao ajustada para {role}.")
                else:
                    raise RuntimeError(
                        f"Falha ao vincular usuario na organizacao. HTTP {add_response.status_code}: {add_response.text}"
                    )

                success_count += 1

            except Exception as exc:
                error_count += 1
                row_result["status"] = "error"
                row_result["error"] = str(exc)

            results.append(row_result)

        return jsonify({
            "ok": error_count == 0,
            "message": f"Processamento finalizado. Sucesso: {success_count}. Erros: {error_count}.",
            "success": success_count,
            "errors": error_count,
            "results": results,
        })

    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
