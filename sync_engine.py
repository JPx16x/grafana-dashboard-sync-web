import copy
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


BACKUP_DIR = Path("backups")
LOG_DIR = Path("logs")


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_") or "sem_nome"


def get_headers(org_id: int) -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Grafana-Org-Id": str(org_id),
    }


def grafana_session(user: str, password: str) -> requests.Session:
    session = requests.Session()
    session.auth = (user, password)
    return session


def normalize_url(url: str) -> str:
    return url.strip().rstrip("/")


def add_log(logs: List[Dict[str, str]], level: str, message: str) -> None:
    logs.append({
        "time": datetime.now().strftime("%H:%M:%S"),
        "level": level,
        "message": message,
    })


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    expected: Tuple[int, ...] = (200,),
    **kwargs: Any,
) -> Any:
    response = session.request(method, url, timeout=90, **kwargs)

    if response.status_code not in expected:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text}")

    if not response.text:
        return None

    try:
        return response.json()
    except json.JSONDecodeError:
        return response.text


def list_orgs(session: requests.Session, grafana_url: str) -> List[Dict[str, Any]]:
    return request_json(session, "GET", f"{grafana_url}/api/orgs") or []


def get_dashboard(
    session: requests.Session,
    grafana_url: str,
    org_id: int,
    dashboard_uid: str,
) -> Optional[Dict[str, Any]]:
    response = session.get(
        f"{grafana_url}/api/dashboards/uid/{dashboard_uid}",
        headers=get_headers(org_id),
        timeout=60,
    )

    if response.status_code == 404:
        return None

    if response.status_code != 200:
        raise RuntimeError(f"Dashboard UID {dashboard_uid}: HTTP {response.status_code}: {response.text}")

    return response.json()


def get_datasources(
    session: requests.Session,
    grafana_url: str,
    org_id: int,
) -> List[Dict[str, Any]]:
    return request_json(
        session,
        "GET",
        f"{grafana_url}/api/datasources",
        headers=get_headers(org_id),
    ) or []


def get_datasource_by_name(
    session: requests.Session,
    grafana_url: str,
    org_id: int,
    datasource_name: str,
) -> Optional[Dict[str, Any]]:
    datasources = get_datasources(session, grafana_url, org_id)

    for datasource in datasources:
        if datasource.get("name") == datasource_name:
            return datasource

    return None


def list_folders(
    session: requests.Session,
    grafana_url: str,
    org_id: int,
) -> List[Dict[str, Any]]:
    return request_json(
        session,
        "GET",
        f"{grafana_url}/api/folders",
        headers=get_headers(org_id),
    ) or []


def find_folder_by_title(
    session: requests.Session,
    grafana_url: str,
    org_id: int,
    title: str,
) -> Optional[Dict[str, Any]]:
    for folder in list_folders(session, grafana_url, org_id):
        if folder.get("title") == title:
            return folder

    return None


def create_folder(
    session: requests.Session,
    grafana_url: str,
    org_id: int,
    title: str,
    dry_run: bool,
    logs: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    if dry_run:
        add_log(logs, "info", f"[DRY-RUN] Criaria a pasta '{title}' na org ID {org_id}")
        return {
            "id": 0,
            "uid": None,
            "title": title,
        }

    response = session.post(
        f"{grafana_url}/api/folders",
        headers=get_headers(org_id),
        json={"title": title},
        timeout=60,
    )

    if response.status_code == 200:
        return response.json()

    if response.status_code == 409:
        return find_folder_by_title(session, grafana_url, org_id, title)

    raise RuntimeError(f"Erro criando pasta '{title}': HTTP {response.status_code}: {response.text}")


def ensure_folder(
    session: requests.Session,
    grafana_url: str,
    target_org_id: int,
    source_dashboard_data: Dict[str, Any],
    dry_run: bool,
    logs: List[Dict[str, str]],
) -> Tuple[Optional[int], Optional[str], str]:
    meta = source_dashboard_data.get("meta", {}) or {}
    folder_title = meta.get("folderTitle") or ""

    if not folder_title or meta.get("folderId", 0) == 0:
        return 0, None, "General"

    target_folder = find_folder_by_title(session, grafana_url, target_org_id, folder_title)

    if target_folder:
        return target_folder.get("id"), target_folder.get("uid"), folder_title

    created_folder = create_folder(
        session,
        grafana_url,
        target_org_id,
        folder_title,
        dry_run,
        logs,
    )

    if created_folder:
        return created_folder.get("id"), created_folder.get("uid"), folder_title

    return None, None, folder_title


def backup_dashboard(
    org_name: str,
    dashboard_uid: str,
    dashboard_data: Dict[str, Any],
    logs: List[Dict[str, str]],
) -> str:
    backup_timestamp = timestamp()
    org_dir = BACKUP_DIR / slugify(org_name)
    org_dir.mkdir(parents=True, exist_ok=True)

    dashboard_title = dashboard_data.get("dashboard", {}).get("title", dashboard_uid)
    filename = f"{slugify(dashboard_title)}_{dashboard_uid}_{backup_timestamp}.json"
    backup_path = org_dir / filename

    backup_path.write_text(
        json.dumps(dashboard_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    add_log(logs, "ok", f"Backup salvo: {backup_path}")
    return str(backup_path)


def replace_datasource_references(
    obj: Any,
    source_uid: str,
    target_uid: str,
    datasource_name: str,
) -> Any:
    if isinstance(obj, dict):
        new_obj = {}

        for key, value in obj.items():
            if key == "datasource" and isinstance(value, dict):
                ds_obj = copy.deepcopy(value)

                if ds_obj.get("uid") == source_uid or ds_obj.get("name") == datasource_name:
                    ds_obj["uid"] = target_uid
                    ds_obj["name"] = datasource_name

                new_obj[key] = replace_datasource_references(
                    ds_obj,
                    source_uid,
                    target_uid,
                    datasource_name,
                )

            elif key == "uid" and value == source_uid:
                new_obj[key] = target_uid

            else:
                new_obj[key] = replace_datasource_references(
                    value,
                    source_uid,
                    target_uid,
                    datasource_name,
                )

        return new_obj

    if isinstance(obj, list):
        return [
            replace_datasource_references(item, source_uid, target_uid, datasource_name)
            for item in obj
        ]

    if isinstance(obj, str):
        return obj.replace(source_uid, target_uid)

    return obj


def prepare_dashboard_payload(
    source_dashboard_data: Dict[str, Any],
    source_ds_uid: str,
    target_ds_uid: str,
    datasource_name: str,
) -> Dict[str, Any]:
    dashboard_json = copy.deepcopy(source_dashboard_data["dashboard"])

    dashboard_json = replace_datasource_references(
        dashboard_json,
        source_uid=source_ds_uid,
        target_uid=target_ds_uid,
        datasource_name=datasource_name,
    )

    dashboard_json["id"] = None
    dashboard_json["version"] = 0

    return dashboard_json


def import_dashboard(
    session: requests.Session,
    grafana_url: str,
    target_org_id: int,
    dashboard_json: Dict[str, Any],
    folder_id: Optional[int],
    folder_uid: Optional[str],
    dry_run: bool,
    logs: List[Dict[str, str]],
) -> None:
    if dry_run:
        location = f"folderId={folder_id}" if folder_id else "General"
        add_log(logs, "info", f"[DRY-RUN] Importaria dashboard '{dashboard_json.get('title')}' em {location}")
        return

    payload: Dict[str, Any] = {
        "dashboard": dashboard_json,
        "overwrite": True,
        "message": "Atualizado automaticamente pelo Grafana Dashboard Sync Web",
    }

    if folder_id and folder_id > 0:
        payload["folderId"] = folder_id
    elif folder_uid:
        payload["folderUid"] = folder_uid
    else:
        payload["folderId"] = 0

    response = session.post(
        f"{grafana_url}/api/dashboards/db",
        headers=get_headers(target_org_id),
        json=payload,
        timeout=90,
    )

    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text}")


def write_execution_log(result: Dict[str, Any]) -> str:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"sync_web_{timestamp()}.json"

    log_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return str(log_path)


def run_sync(config: Dict[str, Any]) -> Dict[str, Any]:
    logs: List[Dict[str, str]] = []

    started_at = datetime.now().isoformat()
    start_time = time.time()

    stats = {
        "orgs_total": 0,
        "orgs_ok": 0,
        "orgs_error": 0,
        "dashboards_ok": 0,
        "dashboards_error": 0,
        "backups_ok": 0,
        "datasources_ok": 0,
        "datasources_error": 0,
    }

    result: Dict[str, Any] = {
        "ok": True,
        "started_at": started_at,
        "dry_run": bool(config.get("dry_run", True)),
        "stats": stats,
        "logs": logs,
        "orgs": [],
    }

    try:
        grafana_url = normalize_url(config.get("grafana_url", ""))
        grafana_user = config.get("grafana_user", "").strip()
        grafana_password = config.get("grafana_password", "")
        source_org_id = int(config.get("source_org_id"))
        source_org_name = config.get("source_org_name", f"Org {source_org_id}")
        datasource_name = config.get("datasource_name", "").strip()
        dashboard_uids = config.get("dashboard_uids", [])
        target_orgs = config.get("target_orgs", [])
        dry_run = bool(config.get("dry_run", True))

        if not grafana_url or not grafana_user or not grafana_password:
            raise RuntimeError("Informe URL, usuario e senha do Grafana.")

        if not datasource_name:
            raise RuntimeError("Informe o datasource de referencia.")

        if not dashboard_uids:
            raise RuntimeError("Selecione pelo menos um dashboard.")

        if not target_orgs:
            raise RuntimeError("Selecione pelo menos uma organizacao destino.")

        session = grafana_session(grafana_user, grafana_password)

        add_log(logs, "info", f"Grafana: {grafana_url}")
        add_log(logs, "info", f"Org origem: {source_org_name} / ID {source_org_id}")
        add_log(logs, "info", f"Datasource de referencia: {datasource_name}")
        add_log(logs, "info", f"Modo dry-run: {'sim' if dry_run else 'nao'}")

        source_ds = get_datasource_by_name(
            session,
            grafana_url,
            source_org_id,
            datasource_name,
        )

        if not source_ds:
            raise RuntimeError(f"Datasource '{datasource_name}' nao encontrado na org origem.")

        source_ds_uid = source_ds.get("uid")

        if not source_ds_uid:
            raise RuntimeError(f"Datasource '{datasource_name}' na org origem nao possui UID.")

        add_log(logs, "ok", f"Datasource origem encontrado: {datasource_name} / UID {source_ds_uid}")

        source_dashboards: Dict[str, Dict[str, Any]] = {}

        for dashboard_uid in dashboard_uids:
            dashboard_data = get_dashboard(
                session,
                grafana_url,
                source_org_id,
                dashboard_uid,
            )

            if not dashboard_data:
                raise RuntimeError(f"Dashboard origem nao encontrado: UID {dashboard_uid}")

            title = dashboard_data.get("dashboard", {}).get("title", dashboard_uid)
            source_dashboards[dashboard_uid] = dashboard_data
            add_log(logs, "ok", f"Dashboard origem validado: {title} / UID {dashboard_uid}")

        stats["orgs_total"] = len(target_orgs)

        for target_org in target_orgs:
            target_org_id = int(target_org.get("id"))
            target_org_name = target_org.get("name", f"Org {target_org_id}")

            org_result = {
                "id": target_org_id,
                "name": target_org_name,
                "status": "ok",
                "dashboards": [],
            }

            add_log(logs, "info", f"Iniciando org destino: {target_org_name} / ID {target_org_id}")

            target_ds = get_datasource_by_name(
                session,
                grafana_url,
                target_org_id,
                datasource_name,
            )

            if not target_ds:
                stats["datasources_error"] += 1
                stats["orgs_error"] += 1
                org_result["status"] = "error"
                org_result["error"] = f"Datasource '{datasource_name}' nao encontrado."
                result["orgs"].append(org_result)
                add_log(logs, "error", f"Datasource '{datasource_name}' nao encontrado na org {target_org_name}. Pulando org.")
                continue

            target_ds_uid = target_ds.get("uid")

            if not target_ds_uid:
                stats["datasources_error"] += 1
                stats["orgs_error"] += 1
                org_result["status"] = "error"
                org_result["error"] = f"Datasource '{datasource_name}' sem UID."
                result["orgs"].append(org_result)
                add_log(logs, "error", f"Datasource '{datasource_name}' sem UID na org {target_org_name}. Pulando org.")
                continue

            stats["datasources_ok"] += 1
            add_log(logs, "ok", f"Datasource destino encontrado em {target_org_name}: {datasource_name} / UID {target_ds_uid}")

            org_had_error = False

            for dashboard_uid in dashboard_uids:
                source_dashboard_data = source_dashboards[dashboard_uid]
                dashboard_title = source_dashboard_data.get("dashboard", {}).get("title", dashboard_uid)

                dashboard_result = {
                    "uid": dashboard_uid,
                    "title": dashboard_title,
                    "status": "ok",
                }

                try:
                    existing_dashboard = get_dashboard(
                        session,
                        grafana_url,
                        target_org_id,
                        dashboard_uid,
                    )

                    if existing_dashboard:
                        dashboard_result["action"] = "updated"

                        if dry_run:
                            add_log(logs, "info", f"[DRY-RUN] Backup seria feito: {target_org_name} / {dashboard_title}")
                        else:
                            backup_dashboard(
                                target_org_name,
                                dashboard_uid,
                                existing_dashboard,
                                logs,
                            )
                            stats["backups_ok"] += 1

                    else:
                        dashboard_result["action"] = "created"
                        add_log(logs, "info", f"Dashboard ainda nao existe em {target_org_name}: {dashboard_title} / UID {dashboard_uid}")

                    folder_id, folder_uid, folder_title = ensure_folder(
                        session,
                        grafana_url,
                        target_org_id,
                        source_dashboard_data,
                        dry_run,
                        logs,
                    )

                    dashboard_result["folder"] = folder_title

                    if folder_id is None and folder_uid is None:
                        raise RuntimeError(f"Nao foi possivel garantir a pasta '{folder_title}'")

                    dashboard_payload = prepare_dashboard_payload(
                        source_dashboard_data,
                        source_ds_uid=source_ds_uid,
                        target_ds_uid=target_ds_uid,
                        datasource_name=datasource_name,
                    )

                    import_dashboard(
                        session,
                        grafana_url,
                        target_org_id,
                        dashboard_payload,
                        folder_id,
                        folder_uid,
                        dry_run,
                        logs,
                    )

                    stats["dashboards_ok"] += 1
                    add_log(logs, "ok", f"Dashboard sincronizado em {target_org_name}: {dashboard_title} / UID {dashboard_uid}")

                except Exception as exc:
                    org_had_error = True
                    stats["dashboards_error"] += 1
                    dashboard_result["status"] = "error"
                    dashboard_result["error"] = str(exc)
                    add_log(logs, "error", f"Erro no dashboard {dashboard_title} em {target_org_name}: {exc}")

                org_result["dashboards"].append(dashboard_result)

            if org_had_error:
                stats["orgs_error"] += 1
                org_result["status"] = "error"
            else:
                stats["orgs_ok"] += 1

            result["orgs"].append(org_result)

    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)
        add_log(logs, "error", str(exc))

    result["finished_at"] = datetime.now().isoformat()
    result["duration_seconds"] = round(time.time() - start_time, 2)
    result["stats"] = stats

    try:
        log_path = write_execution_log(result)
        result["log_path"] = log_path
        add_log(logs, "ok", f"Log salvo: {log_path}")
    except Exception as exc:
        add_log(logs, "error", f"Falha ao salvar log: {exc}")

    return result
