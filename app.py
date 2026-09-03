import datetime as dt

import pandas as pd
import streamlit as st

from data_prep import load_all_from_mws, format_parts
from suggest import PartsSuggester

st.set_page_config(page_title="🚲 Vanta ERP — цикл ремонта", page_icon="🚲", layout="wide")

STATUS_COLORS = {
    "ОЖИДАЕТ РЕМОНТА": "#fef08a",
    "РЕМОНТ": "#fecaca",
    "ОЖИДАЕТ ЗАПЧАСТИ": "#fef08a",
    "НА ПРОВЕРКУ": "#ddd6fe",
    "НА ДОРАБОТКУ": "#fed7aa",
    "СВОБОДЕН": "#dcfce7",
    "УТИЛИЗАЦИЯ": "#e2e8f0",
    "КРАЖА": "#1e293b",
    "ГАИ": "#1e293b",
    "В АРЕНДЕ / НЕДОСТУПЕН": "#f1f5f9",
}


def status_badge(status: str) -> str:
    bg = STATUS_COLORS.get(status, "#f1f5f9")
    fg = "#ffffff" if status in ("КРАЖА", "ГАИ") else "#111827"
    return f'<span style="background:{bg};color:{fg};padding:3px 10px;border-radius:6px;font-weight:600;font-size:0.85rem">{status}</span>'


def get_data():
    # Кэш самих HTTP-запросов к MWS живёт внутри mws_client (2 минуты),
    # поэтому здесь отдельное кэширование не нужно — данные не застревают навсегда.
    parts_df, history_df, bikes_df, warnings = load_all_from_mws()
    suggester = PartsSuggester(history_df) if not history_df.empty else None
    return parts_df, history_df, bikes_df, suggester, warnings


parts_df, history_df, _bikes_df_initial, suggester, mws_warnings = get_data()

if mws_warnings:
    with st.expander("⚠️ Предупреждения при загрузке из MWS (посмотри, если что-то не так)", expanded=True):
        for w in mws_warnings:
            st.warning(w)

if "bikes_df" not in st.session_state:
    st.session_state.bikes_df = _bikes_df_initial
if "log" not in st.session_state:
    st.session_state.log = []  # новые записи, сделанные за эту сессию (поверх реальной истории)

bikes_df = st.session_state.bikes_df

if bikes_df.empty:
    st.error("Из «Реестра» не загрузилось ни одной записи — дальше показывать нечего. "
             "Посмотри предупреждения выше про названия полей.")
    st.stop()

with st.expander(f"🔍 Отладка: загружено велосипедов — {len(bikes_df)}, записей истории — {len(history_df)}"):
    st.write("Примеры S/N, как они реально загрузились (первые 10):")
    st.dataframe(bikes_df[["sn", "sn_norm", "status", "loc_status"]].head(10), use_container_width=True)
    st.caption("Если тут S/N выглядит не так, как ты вводишь в поиске (лишние пробелы, "
               "другой регистр, лидирующие нули и т.п.) — вот и причина «ничего не найдено».")

MASTERS = ["Андрей К.", "Александр Л.", "Андрей С.", "Дмитрий Т.", "Сева"]
MANAGERS = ["Женя", "Тест"]


def append_log(sn, from_status, to_status, master, comment, parts_str, work_type, manager, hours=None):
    st.session_state.log.append({
        "date": dt.datetime.now(),
        "sn": sn,
        "from_status": from_status,
        "to_status": to_status,
        "hours": hours,
        "master": master,
        "comment": comment,
        "parts": parts_str,
        "work_type": work_type,
        "manager": manager,
    })


def set_status(row_idx, new_status, **fields):
    for k, v in fields.items():
        bikes_df.at[row_idx, k] = v
    bikes_df.at[row_idx, "status"] = new_status


def get_bike_history(sn_norm, limit=5):
    rows = history_df[history_df["sn_norm"] == sn_norm].sort_values("date", ascending=False).head(limit)
    session_rows = [r for r in st.session_state.log if r["sn"] == sn_norm]
    combined = []
    for r in session_rows[::-1]:
        combined.append(r)
    for _, r in rows.iterrows():
        combined.append(r.to_dict())
    return combined[:limit]


st.title("🚲 Vanta ERP — прототип цикла ремонта")
st.caption("Данные загружены из твоей реальной выгрузки. Это песочница: изменения живут только в этой сессии браузера и не трогают исходный файл.")

tab_master, tab_admin, tab_log = st.tabs(["🔧 Мастер", "✅ Проверка (администратор)", "📜 Журнал сессии"])

# ============================== МАСТЕР ==============================
with tab_master:
    st.subheader("Найти велосипед")
    query = st.text_input("Поиск по S/N, IoT или гос.номеру", key="master_search")

    if query:
        q = query.strip().lower()
        mask = (
            bikes_df["sn_norm"].str.lower().str.contains(q, na=False)
            | bikes_df["iot"].astype(str).str.lower().str.contains(q, na=False)
            | bikes_df["gov"].astype(str).str.lower().str.contains(q, na=False)
        )
        results = bikes_df[mask]
    else:
        results = bikes_df.iloc[0:0]

    if query and results.empty:
        st.warning("Ничего не найдено")
    elif query:
        options = {
            f"{r.sn_norm} · {r.bike_type} · {r.status}": idx
            for idx, r in results.iterrows()
        }
        choice = st.selectbox("Выберите велосипед", list(options.keys()))
        row_idx = options[choice]
        bike = bikes_df.loc[row_idx]

        st.markdown(
            f"**S/N:** {bike.sn_norm} &nbsp;&nbsp; **IoT:** {bike.iot} &nbsp;&nbsp; "
            f"**Гос:** {bike.gov} &nbsp;&nbsp; **Тип:** {bike.bike_type}",
            unsafe_allow_html=True,
        )
        st.markdown(f"**Текущий статус:** {status_badge(bike.status)}", unsafe_allow_html=True)

        with st.expander("История ремонтов этого велосипеда", expanded=True):
            hist = get_bike_history(bike.sn_norm)
            if not hist:
                st.caption("Записей не найдено.")
            for h in hist:
                date_val = h.get("date")
                date_str = date_val.strftime("%d.%m.%Y %H:%M") if isinstance(date_val, (dt.datetime, pd.Timestamp)) else str(date_val)
                st.markdown(
                    f"— **{date_str}**: {h.get('from_status')} → {h.get('to_status')}"
                    + (f", мастер {h.get('master')}" if h.get("master") else "")
                    + (f"<br>&nbsp;&nbsp;💬 {h.get('comment')}" if h.get("comment") else "")
                    + (f"<br>&nbsp;&nbsp;🔩 {h.get('parts')}" if h.get("parts") else ""),
                    unsafe_allow_html=True,
                )

        st.divider()

        if bike.status in ("ОЖИДАЕТ РЕМОНТА", "НА ДОРАБОТКУ"):
            master_name = st.selectbox("Кто берёт в ремонт", MASTERS, key=f"take_{row_idx}")
            if st.button("🔧 Взять в ремонт", type="primary"):
                append_log(bike.sn_norm, bike.status, "РЕМОНТ", master_name, "", "", "ДВИЖЕНИЕ", "")
                set_status(row_idx, "РЕМОНТ", master=master_name, taken_at=dt.datetime.now())
                st.rerun()

        elif bike.status == "РЕМОНТ":
            st.markdown("### Отчёт о ремонте")
            comment = st.text_area(
                "Что сделано (чем подробнее — тем точнее подсказка запчастей)",
                key=f"comment_{row_idx}",
                height=100,
            )

            suggested_parts, similar_cases = suggester.suggest(comment) if (comment and suggester) else ([], [])

            if comment and suggested_parts:
                st.info("💡 Похожие ремонты в истории — вот что обычно использовали:")
                for c in similar_cases[:3]:
                    st.caption(f"похожесть {c['similarity']}: «{c['comment'][:90]}» → {c['parts']}")

            all_part_names = parts_df["name"].tolist()
            default_selection = [p for p in suggested_parts if p in all_part_names]

            selected = st.multiselect(
                "Запчасти (подсказанные из истории отмечены заранее, можно поправить)",
                options=all_part_names,
                default=default_selection,
                key=f"parts_{row_idx}",
            )

            qty = {}
            if selected:
                st.caption("Количество:")
                cols = st.columns(min(4, len(selected)))
                for i, p in enumerate(selected):
                    with cols[i % len(cols)]:
                        qty[p] = st.number_input(p, min_value=1, value=1, step=1, key=f"qty_{row_idx}_{p}")

            complexity = st.select_slider("Сложность ремонта", options=[1, 2, 3], value=1, key=f"cx_{row_idx}")

            if st.button("📤 Сдать на проверку", type="primary"):
                parts_str = format_parts([(p, qty.get(p, 1)) for p in selected])
                taken_at = bike.get("taken_at")
                hours = None
                if isinstance(taken_at, (dt.datetime, pd.Timestamp)):
                    hours = round((dt.datetime.now() - taken_at).total_seconds() / 3600, 2)
                append_log(bike.sn_norm, "РЕМОНТ", "НА ПРОВЕРКУ", bike.master, comment, parts_str, "РЕМОНТ", "", hours=hours)
                set_status(row_idx, "НА ПРОВЕРКУ", repair_info=comment + (" · Запчасти: " + parts_str if parts_str != "Без запчастей" else ""))
                bikes_df.at[row_idx, "_complexity"] = complexity
                st.success("Отправлено на проверку!")
                st.rerun()

        elif bike.status == "НА ПРОВЕРКУ":
            st.info("Велосипед уже сдан и ждёт проверки администратором.")
        else:
            st.caption("Для этого статуса действий мастера в прототипе пока нет.")

# ============================== АДМИНИСТРАТОР ==============================
with tab_admin:
    st.subheader("Очередь на проверку")
    queue = bikes_df[bikes_df["status"] == "НА ПРОВЕРКУ"]

    if queue.empty:
        st.caption("Пусто — нечего проверять.")
    else:
        options = {f"{r.sn_norm} · мастер {r.master}": idx for idx, r in queue.iterrows()}
        choice = st.selectbox("Выберите велосипед для проверки", list(options.keys()), key="admin_choice")
        row_idx = options[choice]
        bike = bikes_df.loc[row_idx]

        st.markdown(f"**S/N:** {bike.sn_norm} &nbsp;&nbsp; **Мастер:** {bike.master}")
        st.markdown(f"**Отчёт:** {bike.get('repair_info', '')}")

        manager_name = st.selectbox("Проверяющий", MANAGERS, key=f"mgr_{row_idx}")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Подтвердить — велосипед свободен", type="primary"):
                append_log(bike.sn_norm, "НА ПРОВЕРКУ", "СВОБОДЕН", bike.master, "", "", "ПРОВЕРКА", manager_name)
                set_status(row_idx, "СВОБОДЕН", manager=manager_name)
                st.success("Подтверждено!")
                st.rerun()
        with col2:
            rework_comment = st.text_input("Причина доработки (обязательно для отправки назад)", key=f"rw_{row_idx}")
            if st.button("↩️ Отправить на доработку"):
                if not rework_comment.strip():
                    st.error("Укажите причину доработки")
                else:
                    append_log(bike.sn_norm, "НА ПРОВЕРКУ", "НА ДОРАБОТКУ", bike.master, rework_comment, "", "ДОРАБОТКА", manager_name)
                    set_status(row_idx, "НА ДОРАБОТКУ", manager=manager_name, repair_info=rework_comment)
                    st.warning("Отправлено на доработку")
                    st.rerun()

# ============================== ЖУРНАЛ СЕССИИ ==============================
with tab_log:
    st.subheader("Что произошло в этой сессии")
    if not st.session_state.log:
        st.caption("Пока пусто — начни с вкладки «Мастер».")
    else:
        log_df = pd.DataFrame(st.session_state.log[::-1])
        st.dataframe(log_df, use_container_width=True)
