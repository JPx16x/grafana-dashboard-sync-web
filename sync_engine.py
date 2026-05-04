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


def sanitize_datasource_payload(source_ds: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prepara o payload para criar um datasource em outra org.

    Observacao:
    Campos sensiveis nao sao retornados pela API do Grafana.
    Exemplo: senha, token, basicAuthPassword.
    Por isso esta funcao copia a estrutura e configuracoes visiveis.
    """
    blocked_fields = {
        "id",
        "orgId",
        "version",
        "uid",
        "readOnly",
        "secureJsonFields",
        "created",
        "updated",
    }

    payload: Dict[str, Any] = {}

    for key, value in source_ds.items():
        if key in blocked_fields:
            continue

        if value is None:
            continue

        payload[key] = copy.deepcopy(value)

    payload.setdefault("name", source_ds.get("name"))
    payload.setdefault("type", source_ds.get("type"))
    payload.setdefault("access", source_ds.get("access", "proxy"))
    payload.setdefault("isDefault", False)

    # Evita conflito de datasource default em varias orgs.
    payload["isDefault"] = bool(source_ds.get("isDefault", False))

    return payload


def create_datasource_from_source(
    session: requests.Session,
    grafana_url: str,
    target_org_id: int,
    source_ds: Dict[str, Any],
    secure_json_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = sanitize_datasource_payload(source_ds)

    secure_clean: Dict[str, Any] = {}

    if isinstance(secure_json_data, dict):
        for key, value in secure_json_data.items():
            if key and value not in (None, ""):
                secure_clean[str(key)] = str(value)

    if secure_clean:
        payload["secureJsonData"] = secure_clean

    response = session.post(
        f"{grafana_url}/api/datasources",
        headers=get_headers(target_org_id),
        json=payload,
        timeout=60,
    )

    if response.status_code not in (200, 201):
        raise RuntimeError(f"HTTP {response.status_code}: {response.text}")

    data = response.json() or {}

    # Algumas versoes retornam {"datasource": {...}}, outras retornam campos no topo.
    created_ds = data.get("datasource") if isinstance(data, dict) else None

    if not created_ds:
        created_ds = get_datasource_by_name(
            session,
            grafana_url,
            target_org_id,
            payload.get("name", ""),
        )

    if not created_ds:
        raise RuntimeError("Datasource criado, mas nao foi possivel localizar o retorno.")

    return created_ds


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
    datasource_mappings: List[Dict[str, str]],
) -> Any:
    """
    Substitui referencias de um ou mais datasources no JSON do dashboard.

    Cada item de datasource_mappings contem:
    - name
    - source_uid
    - target_uid
    """
    uid_map = {
        item["source_uid"]: item["target_uid"]
        for item in datasource_mappings
        if item.get("source_uid") and item.get("target_uid")
    }

    name_to_target_uid = {
        item["name"]: item["target_uid"]
        for item in datasource_mappings
        if item.get("name") and item.get("target_uid")
    }

    if isinstance(obj, dict):
        new_obj = {}

        for key, value in obj.items():
            if key == "datasource" and isinstance(value, dict):
                ds_obj = copy.deepcopy(value)
                ds_uid = ds_obj.get("uid")
                ds_name = ds_obj.get("name")

                if ds_uid in uid_map:
                    ds_obj["uid"] = uid_map[ds_uid]

                if ds_name in name_to_target_uid:
                    ds_obj["uid"] = name_to_target_uid[ds_name]
                    ds_obj["name"] = ds_name

                new_obj[key] = replace_datasource_references(ds_obj, datasource_mappings)

            elif key == "uid" and value in uid_map:
                new_obj[key] = uid_map[value]

            else:
                new_obj[key] = replace_datasource_references(value, datasource_mappings)

        return new_obj

    if isinstance(obj, list):
        return [
            replace_datasource_references(item, datasource_mappings)
            for item in obj
        ]

    if isinstance(obj, str):
        new_value = obj
        for source_uid, target_uid in uid_map.items():
            new_value = new_value.replace(source_uid, target_uid)
        return new_value

    return obj


def prepare_dashboard_payload(
    source_dashboard_data: Dict[str, Any],
    datasource_mappings: List[Dict[str, str]],
) -> Dict[str, Any]:
    dashboard_json = copy.deepcopy(source_dashboard_data["dashboard"])

    dashboard_json = replace_datasource_references(
        dashboard_json,
        datasource_mappings=datasource_mappings,
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

    create_missing_datasources = bool(config.get("create_missing_datasources", False))
    datasource_secure_json_data = config.get("datasource_secure_json_data") or {}

    if not isinstance(datasource_secure_json_data, dict):
        datasource_secure_json_data = {}

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
        datasource_names = config.get("datasource_names") or []
        if isinstance(datasource_names, str):
            datasource_names = [datasource_names]

        datasource_names = [
            str(name).strip()
            for name in datasource_names
            if str(name).strip()
        ]

        # Compatibilidade com versoes antigas
        if not datasource_names and config.get("datasource_name"):
            datasource_names = [str(config.get("datasource_name")).strip()]
        dashboard_uids = config.get("dashboard_uids", [])
        target_orgs = config.get("target_orgs", [])
        dry_run = bool(config.get("dry_run", True))

        if not grafana_url or not grafana_user or not grafana_password:
            raise RuntimeError("Informe URL, usuario e senha do Grafana.")

        if not datasource_names:
            raise RuntimeError("Selecione pelo menos um datasource de referencia.")

        if not dashboard_uids:
            raise RuntimeError("Selecione pelo menos um dashboard.")

        if not target_orgs:
            raise RuntimeError("Selecione pelo menos uma organizacao destino.")

        session = grafana_session(grafana_user, grafana_password)

        add_log(logs, "info", f"Grafana: {grafana_url}")
        add_log(logs, "info", f"Org origem: {source_org_name} / ID {source_org_id}")
        add_log(logs, "info", f"Datasources de referencia: {', '.join(datasource_names)}")
        add_log(logs, "info", f"Modo dry-run: {'sim' if dry_run else 'nao'}")
        add_log(logs, "info", f"Criar datasources ausentes: {'sim' if create_missing_datasources else 'nao'}")

        source_datasource_map: Dict[str, str] = {}

        for datasource_name in datasource_names:
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

            source_datasource_map[datasource_name] = source_ds_uid
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

            datasource_mappings: List[Dict[str, str]] = []
            target_missing_datasource = False
            missing_datasources: List[str] = []

            for datasource_name in datasource_names:
                target_ds = get_datasource_by_name(
                    session,
                    grafana_url,
                    target_org_id,
                    datasource_name,
                )

                if not target_ds:
                    source_ds = get_datasource_by_name(
                        session,
                        grafana_url,
                        source_org_id,
                        datasource_name,
                    )

                    if create_missing_datasources:
                        if dry_run:
                            stats["datasources_ok"] += 1
                            target_ds_uid = source_datasource_map[datasource_name]
                            datasource_mappings.append({
                                "name": datasource_name,
                                "source_uid": source_datasource_map[datasource_name],
                                "target_uid": target_ds_uid,
                            })
                            add_log(logs, "info", f"[DRY-RUN] Criaria datasource em {target_org_name}: {datasource_name}")
                            continue

                        try:
                            secure_values = datasource_secure_json_data.get(datasource_name) or {}

                            if secure_values:
                                add_log(
                                    logs,
                                    "info",
                                    f"Credenciais seguras informadas para {datasource_name}: {', '.join(secure_values.keys())}",
                                )

                            created_ds = create_datasource_from_source(
                                session,
                                grafana_url,
                                target_org_id,
                                source_ds,
                                secure_json_data=secure_values,
                            )

                            target_ds = created_ds
                            add_log(logs, "ok", f"Datasource criado em {target_org_name}: {datasource_name}")

                        except Exception as exc:
                            stats["datasources_error"] += 1
                            target_missing_datasource = True
                            missing_datasources.append(datasource_name)
                            add_log(logs, "error", f"Falha ao criar datasource '{datasource_name}' em {target_org_name}: {exc}")
                            continue
                    else:
                        stats["datasources_error"] += 1
                        target_missing_datasource = True
                        missing_datasources.append(datasource_name)
                        add_log(logs, "error", f"Datasource '{datasource_name}' nao encontrado na org {target_org_name}.")
                        continue

                target_ds_uid = target_ds.get("uid")

                if not target_ds_uid:
                    stats["datasources_error"] += 1
                    target_missing_datasource = True
                    missing_datasources.append(datasource_name)
                    add_log(logs, "error", f"Datasource '{datasource_name}' sem UID na org {target_org_name}.")
                    continue

                stats["datasources_ok"] += 1
                datasource_mappings.append({
                    "name": datasource_name,
                    "source_uid": source_datasource_map[datasource_name],
                    "target_uid": target_ds_uid,
                })

                add_log(logs, "ok", f"Datasource destino pronto em {target_org_name}: {datasource_name} / UID {target_ds_uid}")

            if target_missing_datasource:
                stats["orgs_error"] += 1
                org_result["status"] = "error"
                org_result["error"] = "Datasource(s) nao encontrado(s): " + ", ".join(missing_datasources)
                result["orgs"].append(org_result)
                add_log(logs, "error", f"Org {target_org_name} ignorada por ausencia de datasource(s): {', '.join(missing_datasources)}")
                continue

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
                        datasource_mappings=datasource_mappings,
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
