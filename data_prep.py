"""
Загрузка и подготовка данных из выгрузки Иры (data/vanta.xlsx, 3 листа):
- "Список запчастей"    -> parts_df
- "История ремонтов"    -> history_df
- "Список велосипедов"  -> bikes_df
"""
import re
import pandas as pd


def norm_id(x) -> str:
    """Приводит S/N к единому строковому виду: 342822403030097.0 -> '342822403030097',
    'ZS2012240400366' остаётся как есть."""
    if x is None:
        return ""
    s = str(x).strip()
    if s.endswith(".0"):
        try:
            f = float(s)
            if f.is_integer():
                return str(int(f))
        except ValueError:
            pass
    return s


def parse_price(x) -> float:
    if x is None:
        return 0.0
    s = str(x)
    s = s.replace("\xa0", "").replace("р.", "").replace(" ", "").replace(",", ".")
    s = re.sub(r"[^\d.]", "", s)
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def parse_parts_string(s: str):
    """'Название (x2), Другое (x1)' -> [('Название', 2), ('Другое', 1)]"""
    if not s or not isinstance(s, str) or s.strip().lower() in ("без запчастей", "-", ""):
        return []
    items = []
    for chunk in s.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = re.match(r"^(.*?)\s*\(x(\d+)\)\s*$", chunk)
        if m:
            items.append((m.group(1).strip(), int(m.group(2))))
        else:
            items.append((chunk, 1))
    return items


def format_parts(items) -> str:
    if not items:
        return "Без запчастей"
    return ", ".join(f"{name} (x{qty})" for name, qty in items)


def pick_field(row: dict, candidates: list[str]):
    """Ищет первое поле из candidates в row (без учёта регистра/пробелов по краям).
    Возвращает (значение, найденное_имя) или (None, None), если не найдено."""
    lower_map = {str(k).strip().lower(): k for k in row.keys()}
    for cand in candidates:
        key = lower_map.get(cand.strip().lower())
        if key is not None:
            return row[key], key
    return None, None


def load_all_from_mws():
    """Загружает parts_df/history_df/bikes_df живыми запросами к MWS вместо xlsx.
    Возвращает (parts_df, history_df, bikes_df, warnings) — warnings это список строк
    о полях, которые не удалось найти по ожидаемым названиям (чтобы показать в интерфейсе
    и поправить маппинг по факту, а не гадать)."""
    from mws_client import fetch_all_records, records_to_field_rows

    warnings = []

    # ---------- База запчастей ----------
    parts_rows = records_to_field_rows(fetch_all_records("parts"))
    parts_out = []
    for row in parts_rows:
        name, _ = pick_field(row, ["Расходник", "Название запчасти", "Название"])
        price_raw, _ = pick_field(row, ["Закупочная цена", "Стоимость", "Цена"])
        if name is None:
            continue
        parts_out.append({"name": name, "price": parse_price(price_raw)})
    parts_df = pd.DataFrame(parts_out)
    if parts_df.empty:
        warnings.append("«База запчастей»: не нашла поле с названием запчасти — проверь маппинг.")

    # ---------- Реестр (велосипеды) ----------
    # В «Реестре» нет отдельного поля "Статус ремонта" — актуальный статус велосипеда
    # определяется по последней записи в "Истории ремонтов" (поле "Куда"), а карточка
    # велосипеда хранит только паспортные данные + статус локации/учёта.
    bikes_rows = records_to_field_rows(fetch_all_records("bikes"))
    bike_field_candidates = {
        "sn": ["S/N", "SN", "Серийный номер", "Серийный", "ID"],
        "gov": ["ГОС текущий", "Гос текущий", "Гос", "Гос.номер", "Гос номер"],
        "bike_type": ["Тип велосипеда", "Тип"],
        "acc_status": ["Статус учета", "Статус учёта"],
        "loc_status": ["Статус локации", "Локация"],
        "tech_status": ["Тех статус", "Тех.статус"],
        "rental_type": ["Тип аренды"],
        "comment": ["Комментарий"],
        "errors": ["ОШИБКИ", "Ошибки"],
    }
    # "IOT текущий" — поле типа "Магическая ссылка" (связь с другой записью), а не текст.
    # Значение приходит как массив ID связанных записей — читаемого номера IoT напрямую
    # без похода в связанную таблицу не получить, поэтому просто сохраняем как есть.
    bikes_out = []
    found_bike_field_counts = {key: 0 for key in bike_field_candidates}
    for row in bikes_rows:
        entry = {}
        for key, candidates in bike_field_candidates.items():
            val, found = pick_field(row, candidates)
            entry[key] = val
            if found is not None:
                found_bike_field_counts[key] += 1
        iot_val, _ = pick_field(row, ["IOT текущий", "IoT текущий", "IoT", "IOT"])
        if isinstance(iot_val, list):
            entry["iot"] = ", ".join(str(v) for v in iot_val) if iot_val else ""
        else:
            entry["iot"] = iot_val or ""
        bikes_out.append(entry)
    # Предупреждаем только если поля нет НИ В ОДНОЙ записи — MWS просто не отдаёт
    # пустые поля конкретной записи, так что отсутствие в паре строк — это норма,
    # а не ошибка маппинга.
    for key, count in found_bike_field_counts.items():
        if bikes_rows and count == 0:
            warnings.append(f"«Реестр»: поле «{key}» не встретилось ни в одной записи (пробовала: {bike_field_candidates[key]}).")

    bikes_df = pd.DataFrame(bikes_out)
    if not bikes_df.empty:
        bike_text_cols = ["sn", "gov", "bike_type", "acc_status", "loc_status",
                           "tech_status", "rental_type", "comment", "errors"]
        for col in bike_text_cols:
            bikes_df[col] = bikes_df[col].where(bikes_df[col].notna(), "")

        bikes_df["sn_norm"] = bikes_df["sn"].apply(norm_id)
        bikes_df["master"] = ""
        bikes_df["manager"] = ""
        bikes_df["taken_at"] = pd.NaT

    # ---------- История ремонтов ----------
    history_rows = records_to_field_rows(fetch_all_records("history"))
    history_field_candidates = {
        "date": ["Дата"],
        "sn": ["ID/Серийный", "S/N", "Серийный"],
        "from_status": ["Откуда"],
        "to_status": ["Куда"],
        "hours": ["Время (ч)", "Время"],
        "master": ["Кто", "Мастер"],
        "comment": ["Комментарий"],
        "parts": ["Запчасти"],
        "work_type": ["Тип работы"],
        "manager": ["Менеджер (проверил)", "Менеджер"],
    }
    history_out = []
    found_hist_field_counts = {key: 0 for key in history_field_candidates}
    for row in history_rows:
        entry = {}
        for key, candidates in history_field_candidates.items():
            val, found = pick_field(row, candidates)
            entry[key] = val
            if found is not None:
                found_hist_field_counts[key] += 1
        history_out.append(entry)
    for key, count in found_hist_field_counts.items():
        if history_rows and count == 0:
            warnings.append(f"«История ремонтов»: поле «{key}» не встретилось ни в одной записи (пробовала: {history_field_candidates[key]}).")

    history_df = pd.DataFrame(history_out)
    if not history_df.empty:
        # MWS не присылает пустые поля конкретной записи — они приходят как None и потом
        # превращаются в NaN, который в f-строках печатается как текст "nan". Заменяем
        # на обычную пустую строку сразу, чтобы это нигде не всплывало в интерфейсе.
        text_cols = ["sn", "from_status", "to_status", "master", "comment", "parts", "work_type", "manager"]
        for col in text_cols:
            history_df[col] = history_df[col].where(history_df[col].notna(), "")

        history_df["sn_norm"] = history_df["sn"].apply(norm_id)
        # Поле "Дата" в MWS отдаёт timestamp в миллисекундах (число), а не строку с датой —
        # если вдруг пришла строка, пробуем распарсить и так, не теряя исходное значение.
        date_raw = history_df["date"]
        date_from_ms = pd.to_datetime(pd.to_numeric(date_raw, errors="coerce"), unit="ms", errors="coerce")
        date_from_str = pd.to_datetime(date_raw, errors="coerce")
        history_df["date"] = date_from_ms.fillna(date_from_str)

    # ---------- Актуальный статус велосипеда ----------
    # "История ремонтов" фиксирует только цикл ремонта (ремонт -> проверка -> свободен),
    # но НЕ фиксирует момент сдачи велика в аренду — это отдельное событие, которое в неё
    # не попадает. Поэтому если велик СЕЙЧАС в аренде (по "Статус локации" в "Реестре") —
    # это более свежий и более авторитетный факт, чем любая старая запись в истории,
    # и статус ремонта из истории в этом случае игнорируется. Историю смотрим только
    # для великов, которые сейчас не в аренде — чтобы понять, на каком этапе ремонта они.
    RENTED_LOC_VALUES = ("в аренде", "аренда", "выдан", "у клиента")

    if not bikes_df.empty:
        if not history_df.empty:
            history_sorted = history_df.dropna(subset=["date"]).sort_values("date", ascending=False)
            latest_by_bike = history_sorted.drop_duplicates(subset=["sn_norm"], keep="first").set_index("sn_norm")
        else:
            latest_by_bike = pd.DataFrame()

        def infer_status(row):
            loc = str(row.get("loc_status") or "").strip().lower()

            if loc in RENTED_LOC_VALUES:
                return "В АРЕНДЕ / НЕДОСТУПЕН"

            sn = row["sn_norm"]
            if not latest_by_bike.empty and sn in latest_by_bike.index:
                to_status = latest_by_bike.loc[sn, "to_status"]
                if isinstance(to_status, str) and to_status.strip():
                    return to_status.strip().upper()
            if loc in ("свободен", "склад"):
                return "ОЖИДАЕТ РЕМОНТА"
            return "В АРЕНДЕ / НЕДОСТУПЕН"

        def latest_info(row, field):
            sn = row["sn_norm"]
            if not latest_by_bike.empty and sn in latest_by_bike.index:
                return latest_by_bike.loc[sn, field]
            return ""

        bikes_df["status"] = bikes_df.apply(infer_status, axis=1)
        bikes_df["repair_info"] = bikes_df.apply(lambda r: latest_info(r, "comment") or r.get("comment", ""), axis=1)
        if not latest_by_bike.empty:
            bikes_df["master"] = bikes_df.apply(lambda r: latest_info(r, "master") or "", axis=1)

    return parts_df, history_df, bikes_df, warnings


def load_all(path="data/vanta.xlsx"):
    parts_raw = pd.read_excel(path, sheet_name="Список запчастей")
    history_raw = pd.read_excel(path, sheet_name="История ремонтов")
    bikes_raw = pd.read_excel(path, sheet_name="Список велосипедов")

    parts_df = parts_raw.rename(columns={"Название запчасти": "name", "Стоимость": "price_raw"})
    parts_df["price"] = parts_df["price_raw"].apply(parse_price)
    parts_df = parts_df[["name", "price"]].dropna(subset=["name"]).reset_index(drop=True)

    history_df = history_raw.rename(columns={
        "Дата": "date", "ID/Серийный": "sn", "Откуда": "from_status", "Куда": "to_status",
        "Время (ч)": "hours", "Кто": "master", "Комментарий": "comment",
        "Запчасти": "parts", "Тип работы": "work_type", "Менеджер (проверил)": "manager",
    })
    history_df["sn_norm"] = history_df["sn"].apply(norm_id)
    history_df["date"] = pd.to_datetime(history_df["date"], errors="coerce")

    bikes_df = bikes_raw.rename(columns={
        "S/N": "sn", "IoT": "iot", "Гос": "gov", "Тип велосипеда": "bike_type",
        "Статус учёта": "acc_status", "Статус локации": "loc_status",
        "Тех.статус (импорт)": "import_tech", "Статус ремонта": "repair_status",
        "Инфо ремонта": "repair_info",
    })
    bikes_df["sn_norm"] = bikes_df["sn"].apply(norm_id)

    # Для прототипа: если статус ремонта пуст, но велосипед на складе свободен по локации —
    # считаем, что он ждёт ремонта (в реальной системе это делает checkAwaitingRepair() по триггеру).
    def infer_status(row):
        st = row["repair_status"]
        if isinstance(st, str) and st.strip():
            return st.strip().upper()
        loc = str(row["loc_status"]).strip().lower()
        if loc in ("свободен", "склад"):
            return "ОЖИДАЕТ РЕМОНТА"
        return "В АРЕНДЕ / НЕДОСТУПЕН"

    bikes_df["status"] = bikes_df.apply(infer_status, axis=1)
    bikes_df["master"] = ""
    bikes_df["manager"] = ""
    bikes_df["taken_at"] = pd.NaT

    return parts_df, history_df, bikes_df
