"""
Клиент для MWS Tables REST API. Работает только на сервере (Streamlit Cloud),
не в браузере — поэтому CORS тут ни при чём.
"""
import requests
import streamlit as st

BASE_URL = "https://tables.mws.ru/fusion/v1"

TABLES = {
    "parts":     {"datasheetId": "dst3VS4Stv4E8nLS84", "viewId": "viwqpEVQwCbTb", "label": "База запчастей"},
    "bikes":     {"datasheetId": "dstdNq0D8LM4JXNFaK", "viewId": "viwygjYeVG394", "label": "Реестр"},
    "history":   {"datasheetId": "dsttLLP76YbBo642EU", "viewId": "viwxWKlCL27qB", "label": "История ремонтов"},
    "locations": {"datasheetId": "dsteuJmbKgmwF2Uo1P", "viewId": "viwsSf4kuDGNP", "label": "Локации"},
}


def _get_token() -> str:
    # Токен берём из Secrets Streamlit Cloud (Settings -> Secrets), а не из кода.
    try:
        return st.secrets["MWS_TOKEN"]
    except Exception:
        raise RuntimeError(
            "Не найден MWS_TOKEN в Secrets. Зайди в настройки приложения на "
            "share.streamlit.io -> Settings -> Secrets и добавь строку:\n"
            'MWS_TOKEN = "твой_токен"'
        )


@st.cache_data(ttl=120, show_spinner="Загружаю данные из MWS...")
def fetch_all_records(table_key: str) -> list[dict]:
    """Возвращает список записей вида [{recordId, fields: {...}}, ...] для одной таблицы."""
    if table_key not in TABLES:
        raise ValueError(f"Неизвестная таблица: {table_key}")

    cfg = TABLES[table_key]
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}"}

    all_records = []
    page_num = 1
    page_size = 1000

    while True:
        url = f"{BASE_URL}/datasheets/{cfg['datasheetId']}/records"
        params = {
            "viewId": cfg["viewId"],
            "fieldKey": "name",
            "pageSize": page_size,
            "pageNum": page_num,
        }
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()

        if not payload.get("success"):
            raise RuntimeError(f"MWS API вернул ошибку для «{cfg['label']}»: {payload}")

        records = payload["data"].get("records", [])
        all_records.extend(records)

        if len(records) < page_size:
            break
        page_num += 1
        if page_num > 50:  # предохранитель
            break

    return all_records


def create_record(table_key: str, fields: dict) -> str:
    """Создаёт новую запись в указанной таблице MWS. Возвращает recordId."""
    if table_key not in TABLES:
        raise ValueError(f"Неизвестная таблица: {table_key}")

    cfg = TABLES[table_key]
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = f"{BASE_URL}/datasheets/{cfg['datasheetId']}/records"
    params = {"viewId": cfg["viewId"], "fieldKey": "name"}
    body = {"fieldKey": "name", "records": [{"fields": fields}]}

    resp = requests.post(url, headers=headers, params=params, json=body, timeout=30)
    resp.raise_for_status()
    payload = resp.json()

    if not payload.get("success"):
        raise RuntimeError(f"MWS API вернул ошибку при создании записи в «{cfg['label']}»: {payload}")

    return payload["data"]["records"][0]["recordId"]


def invalidate_cache():
    """Сбрасывает кэш fetch_all_records, чтобы следующая загрузка забрала свежие данные
    сразу после записи, а не ждала истечения TTL (2 минуты)."""
    fetch_all_records.clear()


def records_to_field_rows(records: list[dict]) -> list[dict]:
    """[{recordId, fields: {...}}] -> [{...fields..., '_recordId': ...}]"""
    rows = []
    for r in records:
        row = dict(r.get("fields", {}))
        row["_recordId"] = r.get("recordId")
        rows.append(row)
    return rows
