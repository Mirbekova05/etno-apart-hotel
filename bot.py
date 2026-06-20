import os
import logging
import threading
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8953721099:AAELEQ316qvo9FxMbRN-DgSxTN_tKsTnNsw"
SHEET_ID = "1hLNcIosjOy_4sGw1hrYNFRHG7bmN4-V9JolaVtLyTME"
CREDS_FILE = "credentials.json"

ROOMS = {
    1:  {"name": "№1 — 1к двуспальная",  "max": 2},
    2:  {"name": "№2 — 1к трёхместная",  "max": 3},
    3:  {"name": "№3 — 2к квартира",      "max": 4},
    4:  {"name": "№4 — 1к двуспальная",  "max": 2},
    5:  {"name": "№5 — 1к трёхместная",  "max": 3},
    6:  {"name": "№6 — 1к двуспальная",  "max": 2},
    7:  {"name": "№7 — 1к двуспальная",  "max": 2},
    8:  {"name": "№8 — 1к двуспальная",  "max": 2},
    9:  {"name": "№9 — 1к трёхместная",  "max": 3},
    10: {"name": "№10 — 1к двуспальная", "max": 2},
    11: {"name": "№11 — 1к двуспальная", "max": 2},
    12: {"name": "№12 — 3к квартира",    "max": 7},
    13: {"name": "№13 — 2к квартира",    "max": 4},
    14: {"name": "№14 — СЛУЖЕБНАЯ",      "max": 0},
    15: {"name": "№15 — 1к двуместная",  "max": 2},
    16: {"name": "№16 — 1к трёхместная", "max": 3},
    17: {"name": "№17 — 3к квартира",    "max": 7},
    18: {"name": "№18 — 1к двуместная",  "max": 2},
    19: {"name": "№19 — 1к трёхместная", "max": 3},
    20: {"name": "№20 — 2к квартира",    "max": 4},
    21: {"name": "№21 — 2к квартира",    "max": 4},
    22: {"name": "№22 — 2к квартира",    "max": 4},
}

COLOR_GREEN = {"red": 0.57, "green": 0.82, "blue": 0.31}
COLOR_BLUE  = {"red": 0.27, "green": 0.51, "blue": 0.96}
COLOR_RED   = {"red": 0.96, "green": 0.27, "blue": 0.27}

def norm_status(s):
    """Нормализует статус для надёжного сравнения: ё->е, обрезка пробелов, регистр"""
    return str(s or "").strip().replace("ё", "е").replace("Ё", "Е").lower()

STATUS_CLEAN_NEEDED = "Надо убрать"
STATUS_CLEANED = "Убрано"
STATUS_CANCELLED = "Отменён"
STATUS_BOOKED = "Бронь"
STATUS_OCCUPIED = "Занят"
STATUS_FREE = "Свободен"

# Нормализованные версии для надёжного сравнения
_N_CLEAN_NEEDED = norm_status(STATUS_CLEAN_NEEDED)
_N_CLEANED = norm_status(STATUS_CLEANED)
_N_CANCELLED = norm_status(STATUS_CANCELLED)
_N_BOOKED = norm_status(STATUS_BOOKED)
_N_OCCUPIED = norm_status(STATUS_OCCUPIED)
_N_FREE = norm_status(STATUS_FREE)

# ===== GOOGLE SHEETS =====
def get_client():
    try:
        import gspread
        from oauth2client.service_account import ServiceAccountCredentials
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        google_creds = os.environ.get("GOOGLE_CREDS")
        if google_creds:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(google_creds), scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, scope)
        return gspread.authorize(creds)
    except Exception as e:
        logger.error(f"Auth error: {e}")
        return None

def get_book():
    client = get_client()
    if not client:
        return None
    try:
        return client.open_by_key(SHEET_ID)
    except Exception as e:
        logger.error(f"Book error: {e}")
        return None

def get_ws():
    book = get_book()
    if not book:
        return None
    try:
        try:
            return book.worksheet("Бронирования")
        except Exception:
            ws = book.add_worksheet("Бронирования", 1000, 17)
            ws.append_row(["ID", "Номер", "Гость", "Людей", "Заезд", "Выезд", "Ночей",
                "Цена/сутки", "Итого", "Задаток", "Способ задатка",
                "Доплата", "Способ доплаты", "Долг", "Статус оплаты", "Статус", "Дата записи"])
            return ws
    except Exception as e:
        logger.error(f"WS error: {e}")
        return None

def get_cleaning_ws():
    """Отдельный лист 'Уборка' — одна строка на номер, источник истины по физической чистоте."""
    book = get_book()
    if not book:
        return None
    try:
        try:
            ws = book.worksheet("Уборка")
        except Exception:
            ws = book.add_worksheet("Уборка", 30, 3)
            ws.append_row(["Номер", "Статус уборки", "Обновлено"])
            room_nums = sorted([n for n in ROOMS if n != 14])
            ws.append_rows([[n, STATUS_CLEAN_NEEDED, ""] for n in room_nums])
            return ws
        # Если лист уже есть, но в нём не все номера — докидываем недостающие
        existing = ws.col_values(1)[1:]  # пропускаем заголовок
        existing_nums = set(str(x).strip() for x in existing if x)
        missing = [n for n in ROOMS if n != 14 and str(n) not in existing_nums]
        if missing:
            ws.append_rows([[n, STATUS_CLEAN_NEEDED, ""] for n in sorted(missing)])
        return ws
    except Exception as e:
        logger.error(f"get_cleaning_ws error: {e}")
        return None

def get_cleaning_status(room_num):
    """Возвращает 'Убрано' или 'Надо убрать' для номера из отдельного листа Уборка."""
    ws = get_cleaning_ws()
    if not ws:
        return STATUS_CLEANED  # по умолчанию считаем чистым, чтобы не блокировать работу
    try:
        records = ws.get_all_records()
        for r in records:
            if str(r.get("Номер")).strip() == str(room_num):
                raw = str(r.get("Статус уборки", STATUS_CLEANED)).strip()
                if norm_status(raw) == _N_CLEAN_NEEDED:
                    return STATUS_CLEAN_NEEDED
                return STATUS_CLEANED
        return STATUS_CLEANED
    except Exception as e:
        logger.error(f"get_cleaning_status error: {e}")
        return STATUS_CLEANED

def set_cleaning_status(room_num, status):
    """Записывает статус уборки в отдельный лист. Возвращает True при успехе."""
    ws = get_cleaning_ws()
    if not ws:
        return False
    try:
        records = ws.get_all_records()
        for i, r in enumerate(records):
            if str(r.get("Номер")).strip() == str(room_num):
                row = i + 2
                ws.update_cell(row, 2, status)
                ws.update_cell(row, 3, datetime.now().strftime("%d.%m.%Y %H:%M"))
                check = ws.cell(row, 2).value
                logger.info(f"set_cleaning_status: №{room_num} row={row} -> '{status}', проверка='{check}'")
                return norm_status(check) == norm_status(status)
        # Номер не найден в листе — добавляем
        ws.append_row([room_num, status, datetime.now().strftime("%d.%m.%Y %H:%M")])
        return True
    except Exception as e:
        logger.error(f"set_cleaning_status error: {e}")
        return False

def get_all_cleaning_statuses():
    """Возвращает dict {room_num_str: 'Убрано'/'Надо убрать'} для всех номеров."""
    ws = get_cleaning_ws()
    result = {}
    if not ws:
        return result
    try:
        records = ws.get_all_records()
        for r in records:
            num = str(r.get("Номер")).strip()
            raw = str(r.get("Статус уборки", STATUS_CLEANED)).strip()
            result[num] = STATUS_CLEAN_NEEDED if norm_status(raw) == _N_CLEAN_NEEDED else STATUS_CLEANED
    except Exception as e:
        logger.error(f"get_all_cleaning_statuses error: {e}")
    return result

def get_bookings():
    ws = get_ws()
    if not ws:
        return []
    try:
        return ws.get_all_records()
    except Exception:
        return []

def get_room_status(b):
    """Вычисляем текущий статус брони по датам.
    В листе 'Бронирования' статус теперь только: Бронь / Занят / Свободен.
    Когда выезд прошёл - сразу 'Свободен' (физическая уборка живёт в отдельном листе)."""
    try:
        raw = str(b.get("Статус", "")).strip()
        s = norm_status(raw)
        # Поддержка старых записей с прежними статусами (на случай если остались в таблице)
        if s == _N_CLEAN_NEEDED or s == _N_CLEANED:
            return STATUS_FREE
        if s == _N_CANCELLED or s.startswith(norm_status("Отменено")):
            return STATUS_CANCELLED
        today = date.today()
        dt_in = datetime.strptime(b["Заезд"], "%d.%m.%Y").date()
        dt_out = datetime.strptime(b["Выезд"], "%d.%m.%Y").date()
        if today < dt_in:
            return STATUS_BOOKED
        if dt_in <= today < dt_out:
            return STATUS_OCCUPIED
        if today >= dt_out:
            return STATUS_FREE
        return raw
    except Exception:
        return str(b.get("Статус", "")).strip()

def is_room_free_for_dates(room_num, d_in, d_out, bookings):
    for b in bookings:
        if str(b.get("Номер")) != str(room_num):
            continue
        s = norm_status(b.get("Статус", ""))
        if s == _N_CLEANED or s == _N_CANCELLED or s.startswith(norm_status("Отменено")):
            continue
        try:
            b_in = datetime.strptime(b["Заезд"], "%d.%m.%Y").date()
            b_out = datetime.strptime(b["Выезд"], "%d.%m.%Y").date()
            if d_in < b_out and d_out > b_in:
                logger.info(f"is_room_free_for_dates: №{room_num} ЗАНЯТ — статус='{s}' гость='{b.get('Гость')}' {b_in}->{b_out}")
                return False
        except Exception:
            pass
    return True

def find_all_bookings(room_num):
    """Возвращает список (row_index, booking_dict) для ВСЕХ активных броней номера, хронологически"""
    records = get_bookings()
    result = []
    for i, r in enumerate(records):
        if str(r.get("Номер")) != str(room_num):
            continue
        raw_status = r.get("Статус", "")
        status_clean = norm_status(raw_status)
        is_final_inactive = (status_clean == _N_CLEANED or status_clean == _N_CANCELLED or
                             status_clean.startswith(norm_status("Отменено")))
        logger.info(f"find_all_bookings: №{room_num} row={i+2} гость='{r.get('Гость')}' raw_status='{raw_status}' normalized='{status_clean}' is_final_inactive={is_final_inactive}")
        if not is_final_inactive:
            result.append((i + 2, r))
    try:
        result.sort(key=lambda x: datetime.strptime(x[1]["Заезд"], "%d.%m.%Y"))
    except Exception:
        pass
    return result

def find_booking(room_num):
    """Первая активная бронь номера (для обратной совместимости в простых случаях)"""
    all_b = find_all_bookings(room_num)
    if all_b:
        return all_b[0]
    return None, None

def find_booking_needing_cleaning(room_num):
    """Находит последнюю бронь со статусом 'Свободен' (выезд прошёл) для данного номера —
    используется чтобы знать какого гостя/даты очистить в календаре после уборки."""
    all_b = find_all_bookings(room_num)
    for row, b in all_b:
        if get_room_status(b) == STATUS_FREE:
            return row, b
    return None, None

def save_booking(data):
    ws = get_ws()
    if not ws:
        return
    bid = len(ws.get_all_records()) + 1
    pay_status = "Оплачено ✅" if data.get("debt", 0) == 0 else "Долг ⚠️"
    ws.append_row([bid, data["room"], data["guest"], data["people"],
        data["date_in"], data["date_out"], data["nights"], data.get("price_day", 0),
        data.get("total", 0), data.get("prepay", 0), data.get("prepay_method", "—"),
        0, "—", data.get("debt", 0), pay_status, data.get("status", STATUS_BOOKED),
        datetime.now().strftime("%d.%m.%Y %H:%M")])
    update_calendar(data["room"], data["guest"], data["date_in"], data["date_out"], data.get("status", STATUS_BOOKED))

def set_status(row, status, booking=None):
    """Меняет статус. Если передан booking - проверяет что row соответствует ему (защита от рассинхрона)."""
    ws = get_ws()
    if not ws:
        return False
    try:
        if booking is not None:
            actual = ws.row_values(row)
            if len(actual) >= 6 and (actual[2] != booking.get("Гость") or actual[4] != booking.get("Заезд")):
                logger.warning(f"set_status: row {row} не совпадает с {booking.get('Гость')}, ищу точную строку")
                exact_row = find_exact_row(booking)
                if exact_row:
                    row = exact_row
                else:
                    logger.error("set_status: не удалось найти точную строку")
                    return False
        ws.update_cell(row, 16, status)
        check = ws.cell(row, 16).value
        if check != status:
            logger.error(f"set_status: запись не прошла! row={row} ожидали '{status}' получили '{check}'")
            return False
        logger.info(f"set_status: row={row} -> '{status}' OK")
        return True
    except Exception as e:
        logger.error(f"set_status error: {e}")
        return False

def update_cell_ws(row, col, value):
    ws = get_ws()
    if ws:
        ws.update_cell(row, col, value)

def find_exact_row(booking):
    """Находит точный номер строки в таблице по уникальным данным брони (защита от рассинхрона индексов)"""
    ws = get_ws()
    if not ws:
        return None
    try:
        all_records = ws.get_all_records()
        for i, r in enumerate(all_records):
            if (str(r.get("Номер")) == str(booking.get("Номер")) and
                r.get("Гость") == booking.get("Гость") and
                r.get("Заезд") == booking.get("Заезд") and
                r.get("Выезд") == booking.get("Выезд")):
                return i + 2
    except Exception as e:
        logger.error(f"find_exact_row error: {e}")
    return None

def cancel_booking(row, booking, kept_amount=0):
    """Отмена брони. kept_amount - сколько удержали (0 = полный возврат задатка)"""
    ws = get_ws()
    if not ws:
        logger.error("cancel_booking: не удалось получить worksheet")
        return False
    # Защита от рассинхрона: проверяем что row реально соответствует этой брони
    try:
        actual = ws.row_values(row)
        # actual[2]=Гость(col3), actual[4]=Заезд(col5), actual[5]=Выезд(col6) — индексы с 0
        if len(actual) >= 6 and (actual[2] != booking.get("Гость") or actual[4] != booking.get("Заезд")):
            logger.warning(f"cancel_booking: row {row} не совпадает с брони {booking.get('Гость')}, ищу точную строку")
            exact_row = find_exact_row(booking)
            if exact_row:
                row = exact_row
            else:
                logger.error("cancel_booking: не удалось найти точную строку брони")
                return False
    except Exception as e:
        logger.error(f"cancel_booking row check error: {e}")

    logger.info(f"cancel_booking: row={row}, room={booking.get('Номер')}, guest={booking.get('Гость')}, kept={kept_amount}")
    ws.update_cell(row, 9, kept_amount)   # Итого = удержанная сумма
    ws.update_cell(row, 10, kept_amount)  # Задаток = удержанная сумма
    ws.update_cell(row, 14, 0)  # Долг
    ws.update_cell(row, 15, "Отменено" if kept_amount == 0 else "Отменено (частично)")
    ws.update_cell(row, 16, STATUS_CANCELLED)
    # Проверяем что записалось
    try:
        check = ws.cell(row, 16).value
        logger.info(f"cancel_booking: после записи статус в row={row} = '{check}'")
        if check != STATUS_CANCELLED:
            logger.error(f"cancel_booking: ЗАПИСЬ НЕ ПРОШЛА! Ожидали '{STATUS_CANCELLED}', получили '{check}'")
            return False
    except Exception as e:
        logger.error(f"cancel_booking verify error: {e}")
        return False
    clear_calendar(booking["Номер"], booking["Заезд"], booking["Выезд"])
    return True

def add_payment(row, booking, amount, method):
    """Принимает оплату: если бронь ещё без задатка - пишет в Задаток, иначе в Доплату. Возвращает новый долг."""
    ws = get_ws()
    if not ws:
        return 0
    current_debt = int(booking.get("Долг", 0))
    current_prepay = int(booking.get("Задаток", 0))
    status = get_room_status(booking)
    new_debt = max(0, current_debt - amount)

    if status == STATUS_BOOKED and current_prepay == 0:
        # Это первый платёж по брони без задатка — пишем как задаток
        ws.update_cell(row, 10, amount)   # Задаток
        ws.update_cell(row, 11, method)   # Способ задатка
    else:
        # Уже был задаток или уже заселены — пишем как доплату
        current_extra = int(booking.get("Доплата", 0))
        new_extra = current_extra + amount
        ws.update_cell(row, 12, new_extra)  # Доплата
        ws.update_cell(row, 13, method)     # Способ доплаты

    ws.update_cell(row, 14, new_debt)
    ws.update_cell(row, 15, "Оплачено ✅" if new_debt == 0 else "Долг ⚠️")
    return new_debt

# ===== КАЛЕНДАРЬ (по 2 недели) =====
CALENDAR_START = date(2026, 6, 16)
CALENDAR_END = date(2026, 8, 31)

def get_calendar_sheets():
    sheets = []
    d = CALENDAR_START
    while d <= CALENDAR_END:
        end = min(d + timedelta(days=13), CALENDAR_END)
        name = f"{d.strftime('%d.%m')}—{end.strftime('%d.%m')}"
        sheets.append((name, d, end))
        d = end + timedelta(days=1)
    return sheets

def update_calendar(room, guest, date_in_str, date_out_str, status):
    try:
        book = get_book()
        if not book:
            return
        dt_in = datetime.strptime(date_in_str, "%d.%m.%Y").date()
        dt_out = datetime.strptime(date_out_str, "%d.%m.%Y").date()
        color = COLOR_BLUE if status == STATUS_BOOKED else COLOR_RED
        for sheet_name, start, end in get_calendar_sheets():
            if dt_out <= start or dt_in > end:
                continue
            try:
                ws = book.worksheet(sheet_name)
            except Exception:
                days = (end - start).days + 1
                ws = book.add_worksheet(sheet_name, 25, days + 1)
                dates = [(start + timedelta(days=i)).strftime("%d.%m") for i in range(days)]
                ws.append_row(["Номер"] + dates)
                room_nums = [n for n in ROOMS if n != 14]
                ws.append_rows([[f"№{n}"] + [""] * days for n in room_nums])
                try:
                    last_col = chr(ord('A') + days)
                    ws.format(f"B2:{last_col}{len(room_nums)+1}", {"backgroundColor": COLOR_GREEN})
                except Exception:
                    pass
            header = ws.row_values(1)
            all_vals = ws.get_all_values()
            room_row = next((i + 1 for i, r in enumerate(all_vals) if r and r[0] == f"№{room}"), None)
            if not room_row:
                continue
            d = max(dt_in, start)
            while d < dt_out and d <= end:
                date_str = d.strftime("%d.%m")
                if date_str in header:
                    col = header.index(date_str) + 1
                    ws.update_cell(room_row, col, guest)
                    ws.format(ws.cell(room_row, col).address, {"backgroundColor": color, "textFormat": {"bold": True}})
                d += timedelta(days=1)
    except Exception as e:
        logger.error(f"update_calendar error: {e}")

def clear_calendar(room, date_in_str, date_out_str):
    try:
        book = get_book()
        if not book:
            return
        dt_in = datetime.strptime(date_in_str, "%d.%m.%Y").date()
        dt_out = datetime.strptime(date_out_str, "%d.%m.%Y").date()
        for sheet_name, start, end in get_calendar_sheets():
            if dt_out <= start or dt_in > end:
                continue
            try:
                ws = book.worksheet(sheet_name)
            except Exception:
                continue
            header = ws.row_values(1)
            all_vals = ws.get_all_values()
            room_row = next((i + 1 for i, r in enumerate(all_vals) if r and r[0] == f"№{room}"), None)
            if not room_row:
                continue
            d = max(dt_in, start)
            while d < dt_out and d <= end:
                date_str = d.strftime("%d.%m")
                if date_str in header:
                    col = header.index(date_str) + 1
                    ws.update_cell(room_row, col, "")
                    ws.format(ws.cell(room_row, col).address, {"backgroundColor": COLOR_GREEN})
                d += timedelta(days=1)
    except Exception as e:
        logger.error(f"clear_calendar error: {e}")

# ===== СОСТОЯНИЯ =====
user_states = {}
user_data = {}

def get_state(uid):
    return user_states.get(uid, "menu")

def set_state(uid, s):
    user_states[uid] = s

def get_data(uid):
    return user_data.get(uid, {})

def update_data(uid, k, v):
    if uid not in user_data:
        user_data[uid] = {}
    user_data[uid][k] = v

def clear(uid):
    user_states.pop(uid, None)
    user_data.pop(uid, None)

def icon_for(s):
    return {STATUS_OCCUPIED: "🔴", STATUS_BOOKED: "🔵", STATUS_CLEAN_NEEDED: "🧹",
            STATUS_CLEANED: "🟢", STATUS_FREE: "⬜"}.get(s, "🟢")

# ===== КЛАВИАТУРЫ =====
def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 Подобрать номер", callback_data="search")],
        [InlineKeyboardButton("🔵 Бронь", callback_data="book"),
         InlineKeyboardButton("💰 Принять оплату", callback_data="payment")],
        [InlineKeyboardButton("🔍 Инфо", callback_data="info"),
         InlineKeyboardButton("🧹 Уборка", callback_data="cleaning")],
        [InlineKeyboardButton("✏️ Изменить данные", callback_data="edit"),
         InlineKeyboardButton("❌ Отменить бронь", callback_data="cancelbooking")],
    ])

def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="menu")]])

def price_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1,500 сом", callback_data="ci_price_1500"),
         InlineKeyboardButton("2,500 сом", callback_data="ci_price_2500")],
        [InlineKeyboardButton("✏️ Своя цена", callback_data="ci_price_custom")],
    ])

def all_rooms_kb(prefix):
    """Показывает ВСЕ номера с вместимостью — занятость проверяется после ввода дат"""
    kb = []
    row = []
    for num in ROOMS:
        if num == 14:
            continue
        max_p = ROOMS[num]["max"]
        row.append(InlineKeyboardButton(f"№{num} — {max_p} чел.", callback_data=f"{prefix}_{num}"))
        if len(row) == 3:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
    return InlineKeyboardMarkup(kb)

def free_rooms_kb(prefix):
    bookings = get_bookings()
    today = date.today()
    occupied = set()
    for b in bookings:
        s = get_room_status(b)
        if s == STATUS_OCCUPIED:
            occupied.add(str(b["Номер"]))
        elif s == STATUS_BOOKED:
            try:
                if datetime.strptime(b["Заезд"], "%d.%m.%Y").date() <= today:
                    occupied.add(str(b["Номер"]))
            except Exception:
                occupied.add(str(b["Номер"]))
    kb = []
    row = []
    for num in ROOMS:
        if num == 14:
            continue
        if str(num) not in occupied:
            row.append(InlineKeyboardButton(f"№{num}", callback_data=f"{prefix}_{num}"))
            if len(row) == 4:
                kb.append(row)
                row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
    return InlineKeyboardMarkup(kb)

def active_rooms_kb(prefix):
    bookings = get_bookings()
    seen = set()
    kb = []
    row = []
    for b in bookings:
        s = get_room_status(b)
        if s in [STATUS_OCCUPIED, STATUS_BOOKED]:
            num = str(b["Номер"])
            if num in seen:
                continue
            seen.add(num)
            row.append(InlineKeyboardButton(f"{icon_for(s)}№{num}", callback_data=f"{prefix}_{num}"))
            if len(row) == 4:
                kb.append(row)
                row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
    return InlineKeyboardMarkup(kb)

def booking_choice_kb(prefix, room_num):
    """Если на номере несколько броней - показать список для выбора"""
    bookings = find_all_bookings(room_num)
    kb = []
    for row, b in bookings:
        s = get_room_status(b)
        icon = icon_for(s)
        label = f"{icon} {b['Гость']} ({b['Заезд']}→{b['Выезд']})"
        kb.append([InlineKeyboardButton(label, callback_data=f"{prefix}_{room_num}_{row}")])
    kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
    return InlineKeyboardMarkup(kb)

def get_booking_by_row(room_num, row):
    bookings = get_bookings()
    if 0 <= row - 2 < len(bookings):
        return bookings[row - 2]
    return None

def edit_fields_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Имя гостя", callback_data="ef_guest"),
         InlineKeyboardButton("👥 Кол-во людей", callback_data="ef_people")],
        [InlineKeyboardButton("📅 Дата заезда", callback_data="ef_date_in"),
         InlineKeyboardButton("📅 Дата выезда", callback_data="ef_date_out")],
        [InlineKeyboardButton("💰 Итоговая сумма", callback_data="ef_total"),
         InlineKeyboardButton("✅ Задаток", callback_data="ef_prepay")],
        [InlineKeyboardButton("🏠 Номер квартиры", callback_data="ef_room"),
         InlineKeyboardButton("🔄 Статус", callback_data="ef_status")],
        [InlineKeyboardButton("◀️ Меню", callback_data="menu")],
    ])

def status_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔵 Бронь", callback_data=f"es_{STATUS_BOOKED}"),
         InlineKeyboardButton("🔴 Занят", callback_data=f"es_{STATUS_OCCUPIED}")],
        [InlineKeyboardButton("⬜ Свободен", callback_data=f"es_{STATUS_FREE}")],
        [InlineKeyboardButton("◀️ Назад", callback_data="edit")],
    ])

# ===== ХЭНДЛЕРЫ =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    clear(uid)
    await update.message.reply_text("🏠 *Управление квартирами*\n\nВыбери действие:", reply_markup=main_kb(), parse_mode="Markdown")

async def reset_cleaning_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Разовая команда: ставит ВСЕМ номерам в листе Уборка статус 'Надо убрать' —
    чтобы можно было самостоятельно проверить каждый и отметить вручную."""
    ws = get_cleaning_ws()
    if not ws:
        await update.message.reply_text("⚠️ Не удалось открыть лист Уборка.")
        return
    try:
        records = ws.get_all_records()
        count = 0
        for i, r in enumerate(records):
            row = i + 2
            ws.update_cell(row, 2, STATUS_CLEAN_NEEDED)
            count += 1
        await update.message.reply_text(f"✅ Все {count} номеров в листе «Уборка» теперь «Надо убрать». Проверь каждый сама через кнопку 🧹 Уборка.")
    except Exception as e:
        logger.error(f"reset_cleaning_cmd error: {e}")
        await update.message.reply_text(f"⚠️ Ошибка: {e}")

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    d = q.data

    if d == "menu":
        clear(uid)
        await q.edit_message_text("🏠 *Управление квартирами*\n\nВыбери действие:", reply_markup=main_kb(), parse_mode="Markdown")
        return

    # ===== ПОДОБРАТЬ НОМЕР =====
    if d == "search":
        user_data[uid] = {"mode": "search"}
        set_state(uid, "search_people")
        await q.edit_message_text("🔎 *Подобрать номер*\n\nСколько человек?", parse_mode="Markdown")
        return

    # ===== БРОНЬ =====
    if d == "book":
        user_data[uid] = {"status": STATUS_BOOKED}
        set_state(uid, "ci_room_selected")
        await q.edit_message_text("🔵 *Бронирование*\n\nВыбери номер:", reply_markup=all_rooms_kb("ci_room"), parse_mode="Markdown")
        return

    # ===== ЗАСЕЛЕНИЕ =====
    if d == "checkin":
        bookings = get_bookings()
        booked = [b for b in bookings if get_room_status(b) in [STATUS_BOOKED, STATUS_OCCUPIED]]
        kb_rows = []
        if booked:
            kb_rows.append([InlineKeyboardButton("🔵 Заселить из брони", callback_data="checkin_from_book")])
        kb_rows.append([InlineKeyboardButton("✅ Новое заселение", callback_data="checkin_new")])
        kb_rows.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
        await q.edit_message_text("✅ *Заселение*\n\nВыбери тип:", reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode="Markdown")
        return

    if d == "checkin_new":
        user_data[uid] = {"status": STATUS_OCCUPIED}
        set_state(uid, "ci_guest")
        await q.edit_message_text("✅ *Новое заселение*\n\nВыбери номер:", reply_markup=free_rooms_kb("ci_room"), parse_mode="Markdown")
        return

    if d == "checkin_from_book":
        bookings = get_bookings()
        booked = [b for b in bookings if get_room_status(b) == STATUS_BOOKED]
        if not booked:
            await q.edit_message_text("Нет активных броней.", reply_markup=back_kb())
            return
        kb = []
        row = []
        seen = set()
        for b in booked:
            num = str(b["Номер"])
            row.append(InlineKeyboardButton(f"🔵№{num} — {b['Гость']}", callback_data=f"checkinpick_{num}"))
            if len(row) == 2:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data="checkin")])
        await q.edit_message_text("🔵 *Выбери бронь для заселения:*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    if d.startswith("checkinpick_"):
        num = int(d.split("_")[-1])
        all_b = find_all_bookings(num)
        active_bookings = [(r, b) for r, b in all_b if get_room_status(b) == STATUS_BOOKED]
        if not active_bookings:
            await q.edit_message_text("Бронь не найдена.", reply_markup=back_kb())
            return
        if len(active_bookings) > 1:
            kb = []
            for row, b in active_bookings:
                kb.append([InlineKeyboardButton(f"{b['Гость']} ({b['Заезд']}→{b['Выезд']})", callback_data=f"checkin_book_{num}_{row}")])
            kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
            await q.edit_message_text(f"🔵 *№{num} — несколько броней*\n\nВыбери нужную:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        else:
            row, booking = active_bookings[0]
            await show_checkin_booking(q, uid, row, booking)
        return

    if d.startswith("checkin_book_"):
        parts = d.split("_")
        num = int(parts[2])
        row = int(parts[3])
        booking = get_booking_by_row(num, row)
        if not booking:
            await q.edit_message_text("Бронь не найдена.", reply_markup=back_kb())
            return
        await show_checkin_booking(q, uid, row, booking)
        return

    if d == "checkin_pay_now":
        data = get_data(uid)
        booking = data["checkin_booking"]
        set_state(uid, "checkin_pay_amount")
        await q.edit_message_text(f"💰 Долг: *{int(booking['Долг']):,} сом*\n\nВведи сумму оплаты:", parse_mode="Markdown")
        return

    if d == "checkin_no_pay":
        data = get_data(uid)
        row = data["checkin_row"]
        booking = data["checkin_booking"]
        set_status(row, STATUS_OCCUPIED, booking=booking)
        update_calendar(booking["Номер"], booking["Гость"], booking["Заезд"], booking["Выезд"], STATUS_OCCUPIED)
        clear(uid)
        await q.edit_message_text(
            f"✅ *№{booking['Номер']} заселён!*\n\n👤 {booking['Гость']}\n⚠️ Долг: *{int(booking['Долг']):,} сом*",
            reply_markup=back_kb(), parse_mode="Markdown")
        return

    if d.startswith("checkin_paymethod_"):
        method = "💵 Наличка" if d == "checkin_paymethod_cash" else "💳 Карта"
        data = get_data(uid)
        row = data["checkin_row"]
        booking = data["checkin_booking"]
        amount = data["checkin_pay_amount"]
        new_debt = add_payment(row, booking, amount, method)
        set_status(row, STATUS_OCCUPIED, booking=booking)
        update_calendar(booking["Номер"], booking["Гость"], booking["Заезд"], booking["Выезд"], STATUS_OCCUPIED)
        pay_text = "🎉 Оплачено полностью!" if new_debt == 0 else f"⚠️ Остаток долга: *{new_debt:,} сом*"
        clear(uid)
        await q.edit_message_text(
            f"✅ *№{booking['Номер']} заселён!*\n\n💳 Принято: *{amount:,} сом* ({method})\n{pay_text}",
            reply_markup=back_kb(), parse_mode="Markdown")
        return

    if d.startswith("ci_room_"):
        num = int(d.split("_")[-1])
        update_data(uid, "room", num)
        data = get_data(uid)
        if data.get("status") == STATUS_BOOKED:
            # При брони — сначала спрашиваем даты, потом проверяем занятость
            set_state(uid, "book_date_in")
            await q.edit_message_text(
                f"🔵 *{ROOMS[num]['name']}*\n\nДата заезда? (например: 19.06)",
                parse_mode="Markdown")
        else:
            # При заселении — сразу имя
            set_state(uid, "ci_guest")
            await q.edit_message_text(f"*{ROOMS[num]['name']}*\n\nВведи имя гостя:", parse_mode="Markdown")
        return

    if d.startswith("ci_price_"):
        if d == "ci_price_custom":
            set_state(uid, "ci_price_custom")
            await q.edit_message_text("✏️ Введи цену за сутки с 1 человека:")
        else:
            await calc_total(q, uid, int(d.split("_")[-1]))
        return

    if d == "ci_total_ok":
        data = get_data(uid)
        update_data(uid, "total", data["total_suggested"])
        set_state(uid, "ci_prepay")
        await q.edit_message_text(
            f"💰 Итого: *{data['total_suggested']:,} сом*\n\nСколько взял задаток?\n_(введи 0 если не брал)_",
            parse_mode="Markdown")
        return

    if d == "ci_total_custom":
        set_state(uid, "ci_total_custom")
        await q.edit_message_text("✏️ Введи итоговую сумму:")
        return

    if d.startswith("ci_prepay_"):
        method = "💵 Наличка" if d == "ci_prepay_cash" else "💳 Карта"
        data = get_data(uid)
        data["prepay_method"] = method
        total = data["total"]
        prepay = data["prepay"]
        debt = max(0, total - prepay)
        data["debt"] = debt
        save_booking(data)
        status = data.get("status", STATUS_OCCUPIED)
        icon = "🔵" if status == STATUS_BOOKED else "✅"
        title = "Бронь оформлена!" if status == STATUS_BOOKED else "Заселение оформлено!"
        pay_text = "🎉 *Оплачено полностью!*" if debt == 0 else f"⚠️ *Долг: {debt:,} сом*"
        clear(uid)
        await q.edit_message_text(
            f"{icon} *{title}*\n\n🏠 {ROOMS[data['room']]['name']}\n"
            f"👤 {data['guest']} ({data['people']} чел.)\n"
            f"📅 {data['date_in']} → {data['date_out']} ({data['nights']} н.)\n"
            f"━━━━━━━━━━━━\n💰 Итого: *{total:,} сом*\n"
            f"✅ Задаток: *{prepay:,} сом* ({method})\n{pay_text}",
            reply_markup=back_kb(), parse_mode="Markdown")
        return

    if d.startswith("search_room_"):
        num = int(d.split("_")[-1])
        data = get_data(uid)
        user_data[uid] = {
            "status": STATUS_BOOKED,
            "room": num,
            "people": data.get("search_people", 1),
            "date_in": data.get("search_date_in", ""),
            "date_out": data.get("search_date_out", ""),
            "nights": data.get("search_nights", 1),
        }
        set_state(uid, "ci_guest")
        await q.edit_message_text(
            f"🔵 *Бронирование №{num}*\n"
            f"📅 {data['search_date_in']} → {data['search_date_out']}\n\nВведи имя гостя:", parse_mode="Markdown")
        return

    # ===== ВЫСЕЛЕНИЕ =====
    if d == "checkout":
        bookings = get_bookings()
        active = [b for b in bookings if get_room_status(b) == STATUS_OCCUPIED]
        if not active:
            await q.edit_message_text("Нет активных заселений.", reply_markup=back_kb())
            return
        kb = []
        row = []
        seen = set()
        for b in active:
            num = str(b["Номер"])
            if num in seen:
                continue
            seen.add(num)
            row.append(InlineKeyboardButton(f"🔴№{num} — {b['Гость']}", callback_data=f"copick_{num}"))
            if len(row) == 2:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
        kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
        await q.edit_message_text("🚪 *Выселение*\n\nВыбери номер:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    if d.startswith("copick_"):
        num = int(d.split("_")[-1])
        all_b = find_all_bookings(num)
        active_bookings = [(r, b) for r, b in all_b if get_room_status(b) == STATUS_OCCUPIED]
        if not active_bookings:
            await q.edit_message_text("Активная бронь не найдена.", reply_markup=back_kb())
            return
        if len(active_bookings) > 1:
            kb = []
            for row, b in active_bookings:
                kb.append([InlineKeyboardButton(f"{b['Гость']} ({b['Заезд']}→{b['Выезд']})", callback_data=f"co_room_{num}_{row}")])
            kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
            await q.edit_message_text(f"🚪 *№{num} — несколько броней*\n\nВыбери нужную:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        else:
            row, booking = active_bookings[0]
            await show_checkout_booking(q, uid, row, booking)
        return

    if d.startswith("co_room_"):
        parts = d.split("_")
        num = int(parts[2])
        row = int(parts[3])
        booking = get_booking_by_row(num, row)
        if not booking:
            await q.edit_message_text("Бронь не найдена.", reply_markup=back_kb())
            return
        await show_checkout_booking(q, uid, row, booking)
        return

    if d == "co_pay_and_out":
        data = get_data(uid)
        booking = data["co_booking"]
        set_state(uid, "co_pay_amount")
        await q.edit_message_text(f"💰 Долг: *{int(booking['Долг']):,} сом*\n\nВведи сумму оплаты:", parse_mode="Markdown")
        return

    if d.startswith("co_paymethod_"):
        method = "💵 Наличка" if d == "co_paymethod_cash" else "💳 Карта"
        data = get_data(uid)
        booking = data["co_booking"]
        new_debt = add_payment(data["co_row"], booking, data["co_pay_amount"], method)
        set_status(data["co_row"], STATUS_FREE, booking=booking)
        set_cleaning_status(booking["Номер"], STATUS_CLEAN_NEEDED)
        clear(uid)
        pay_text = "🎉 Долг погашен!" if new_debt == 0 else f"⚠️ Остаток: *{new_debt:,} сом*"
        await q.edit_message_text(
            f"✅ *№{booking['Номер']} выселен!*\n\n💳 Принято: *{data['co_pay_amount']:,} сом* ({method})\n{pay_text}\n\n🧹 Нужна уборка!",
            reply_markup=back_kb(), parse_mode="Markdown")
        return

    if d == "co_confirm":
        data = get_data(uid)
        booking = data["co_booking"]
        set_status(data["co_row"], STATUS_FREE, booking=booking)
        set_cleaning_status(booking["Номер"], STATUS_CLEAN_NEEDED)
        clear(uid)
        await q.edit_message_text(f"✅ *№{booking['Номер']} выселен!*\n\n🧹 Нужна уборка!", reply_markup=back_kb(), parse_mode="Markdown")
        return

    # ===== ИНФО =====
    if d == "info":
        await show_info_list(q)
        return

    if d.startswith("info_room_"):
        num = int(d.split("_")[-1])
        await show_info_room(q, num)
        return

    # ===== ОПЛАТА =====
    if d == "payment":
        bookings = get_bookings()
        with_debt = [b for b in bookings if get_room_status(b) not in [STATUS_CANCELLED] and int(b.get("Долг", 0)) > 0]
        if not with_debt:
            await q.edit_message_text("✅ Все долги оплачены!", reply_markup=back_kb())
            return
        kb = []
        row = []
        seen_nums = {}
        for b in with_debt:
            num = str(b["Номер"])
            seen_nums[num] = seen_nums.get(num, 0) + 1
        added = set()
        for b in with_debt:
            num = str(b["Номер"])
            if num in added:
                continue
            added.add(num)
            row.append(InlineKeyboardButton(f"{icon_for(get_room_status(b))}№{num}", callback_data=f"paypick_{num}"))
            if len(row) == 3:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
        kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
        await q.edit_message_text("💰 *Принять оплату*\n\nНомера с долгом:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    if d.startswith("paypick_"):
        num = int(d.split("_")[-1])
        all_b = find_all_bookings(num)
        with_debt = [(r, b) for r, b in all_b if int(b.get("Долг", 0)) > 0]
        if not with_debt:
            await q.edit_message_text("У этого номера нет долга.", reply_markup=back_kb())
            return
        if len(with_debt) > 1:
            kb = []
            for row, b in with_debt:
                kb.append([InlineKeyboardButton(f"{b['Гость']} — долг {int(b['Долг']):,}с", callback_data=f"pay_room_{num}_{row}")])
            kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
            await q.edit_message_text(f"💰 *№{num} — несколько броней с долгом*\n\nВыбери нужную:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        else:
            row, booking = with_debt[0]
            update_data(uid, "pay_row", row)
            update_data(uid, "pay_booking", booking)
            set_state(uid, "pay_amount")
            await q.edit_message_text(
                f"💰 №{num} — {booking['Гость']}\n"
                f"💰 Итого: *{int(booking['Итого']):,} сом*\n"
                f"✅ Задаток: *{int(booking['Задаток']):,} сом*\n"
                f"⚠️ Долг: *{int(booking['Долг']):,} сом*\n\nВведи сумму оплаты:",
                parse_mode="Markdown")
        return

    if d.startswith("pay_room_"):
        parts = d.split("_")
        num = int(parts[2])
        row = int(parts[3])
        booking = get_booking_by_row(num, row)
        if not booking:
            await q.edit_message_text("Бронь не найдена.", reply_markup=back_kb())
            return
        update_data(uid, "pay_row", row)
        update_data(uid, "pay_booking", booking)
        set_state(uid, "pay_amount")
        await q.edit_message_text(
            f"💰 №{num} — {booking['Гость']}\n"
            f"💰 Итого: *{int(booking['Итого']):,} сом*\n"
            f"✅ Задаток: *{int(booking['Задаток']):,} сом*\n"
            f"⚠️ Долг: *{int(booking['Долг']):,} сом*\n\nВведи сумму оплаты:",
            parse_mode="Markdown")
        return

    if d.startswith("pay_method_"):
        method = "💵 Наличка" if d == "pay_method_cash" else "💳 Карта"
        data = get_data(uid)
        new_debt = add_payment(data["pay_row"], data["pay_booking"], data["pay_amount"], method)
        pay_text = "🎉 Долг погашен!" if new_debt == 0 else f"⚠️ Остаток: *{new_debt:,} сом*"
        clear(uid)
        await q.edit_message_text(f"✅ Оплата принята!\n💳 {data['pay_amount']:,} сом ({method})\n{pay_text}",
            reply_markup=back_kb(), parse_mode="Markdown")
        return

    # ===== УБОРКА =====
    if d == "cleaning":
        cleaning_statuses = get_all_cleaning_statuses()
        nums_needing = [num for num, st in cleaning_statuses.items() if st == STATUS_CLEAN_NEEDED]
        if not nums_needing:
            await q.edit_message_text("✅ Все номера чистые!", reply_markup=back_kb())
            return

        # Для каждого номера найдём последнего гостя (для подписи в кнопке), если есть
        bookings = get_bookings()
        last_guest = {}
        for b in bookings:
            num = str(b["Номер"])
            if num in nums_needing:
                try:
                    dt_out = datetime.strptime(b["Выезд"], "%d.%m.%Y").date()
                except Exception:
                    continue
                if num not in last_guest or dt_out > last_guest[num][1]:
                    last_guest[num] = (b["Гость"], dt_out)

        kb = []
        row = []
        for num in sorted(nums_needing, key=lambda x: int(x)):
            guest_name = last_guest.get(num, ("",))[0]
            label = f"🧹№{num}" + (f" — {guest_name}" if guest_name else "")
            row.append(InlineKeyboardButton(label, callback_data=f"clean_{num}"))
            if len(row) == 2:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
        kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
        await q.edit_message_text("🧹 *Нужна уборка:*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    if d.startswith("clean_") and not d.startswith("clean_done_") and not d.startswith("clean_skip_"):
        num = int(d.split("_")[-1])
        _, booking = find_booking_needing_cleaning(num)
        if not booking:
            await q.edit_message_text(f"Номер №{num} не найден или уже убран.", reply_markup=back_kb())
            return
        await q.edit_message_text(
            f"🧹 *№{num} — {booking['Гость']}*\n\nСтатус уборки?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Убрано", callback_data=f"clean_done_{num}")],
                [InlineKeyboardButton("❌ Не убрано", callback_data=f"clean_skip_{num}")],
                [InlineKeyboardButton("◀️ Назад", callback_data="cleaning")],
            ]), parse_mode="Markdown")
        return

    if d.startswith("clean_done_"):
        num = int(d.split("_")[-1])
        success = set_cleaning_status(num, STATUS_CLEANED)
        logger.info(f"clean_done_: №{num} set_cleaning_status success={success}")
        if not success:
            await q.edit_message_text(
                f"⚠️ *Не удалось обновить статус №{num}!*\n\nПопробуй ещё раз.",
                reply_markup=back_kb(), parse_mode="Markdown")
            return
        # Очищаем календарь для последней брони этого номера (если есть)
        _, last_booking = find_booking_needing_cleaning(num)
        if last_booking:
            clear_calendar(num, last_booking["Заезд"], last_booking["Выезд"])

        # Показываем обновлённый список — заново читаем лист уборки (источник истины)
        cleaning_statuses = get_all_cleaning_statuses()
        nums_needing = [n for n, st in cleaning_statuses.items() if st == STATUS_CLEAN_NEEDED]

        if not nums_needing:
            await q.edit_message_text(f"✅ *№{num} убрано!*\n\n🎉 Все номера чистые!", reply_markup=back_kb(), parse_mode="Markdown")
        else:
            bookings = get_bookings()
            last_guest = {}
            for b in bookings:
                bn = str(b["Номер"])
                if bn in nums_needing:
                    try:
                        dt_out = datetime.strptime(b["Выезд"], "%d.%m.%Y").date()
                    except Exception:
                        continue
                    if bn not in last_guest or dt_out > last_guest[bn][1]:
                        last_guest[bn] = (b["Гость"], dt_out)
            kb = []
            row2 = []
            for n in sorted(nums_needing, key=lambda x: int(x)):
                guest_name = last_guest.get(n, ("",))[0]
                label = f"🧹№{n}" + (f" — {guest_name}" if guest_name else "")
                row2.append(InlineKeyboardButton(label, callback_data=f"clean_{n}"))
                if len(row2) == 2:
                    kb.append(row2)
                    row2 = []
            if row2:
                kb.append(row2)
            kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
            await q.edit_message_text(f"✅ *№{num} убрано!*\n\n🧹 *Ещё нужна уборка:*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    if d.startswith("clean_skip_"):
        num = int(d.split("_")[-1])
        set_cleaning_status(num, STATUS_CLEAN_NEEDED)
        await q.edit_message_text(f"⏳ №{num} — отмечено как ещё не убрано.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ К списку уборки", callback_data="cleaning")]
        ]))
        return

    # ===== ИЗМЕНИТЬ =====
    if d == "edit":
        await q.edit_message_text("✏️ *Изменить данные*\n\nВыбери номер:", reply_markup=active_rooms_kb("editpick"), parse_mode="Markdown")
        return

    if d.startswith("editpick_"):
        num = int(d.split("_")[-1])
        all_b = find_all_bookings(num)
        if not all_b:
            await q.edit_message_text("Бронь не найдена.", reply_markup=back_kb())
            return
        if len(all_b) > 1:
            kb = []
            for row, b in all_b:
                s = get_room_status(b)
                kb.append([InlineKeyboardButton(f"{icon_for(s)} {b['Гость']} ({b['Заезд']}→{b['Выезд']})", callback_data=f"edit_room_{num}_{row}")])
            kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
            await q.edit_message_text(f"✏️ *№{num} — несколько броней*\n\nВыбери нужную:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        else:
            row, booking = all_b[0]
            await show_edit_booking(q, uid, num, row, booking)
        return

    if d.startswith("edit_room_"):
        parts = d.split("_")
        num = int(parts[2])
        row = int(parts[3])
        booking = get_booking_by_row(num, row)
        if not booking:
            await q.edit_message_text("Бронь не найдена.", reply_markup=back_kb())
            return
        await show_edit_booking(q, uid, num, row, booking)
        return

    if d.startswith("ef_"):
        field = d[3:]
        update_data(uid, "edit_field", field)
        if field == "status":
            set_state(uid, "edit_status")
            await q.edit_message_text("🔄 Выбери новый статус:", reply_markup=status_kb())
        elif field == "room":
            await q.edit_message_text("🏠 Выбери новый номер для этого гостя:", reply_markup=all_rooms_kb("efroom"))
        else:
            prompts = {"guest": "имя гостя", "people": "количество людей", "date_in": "дату заезда (19.06)",
                       "date_out": "дату выезда (21.06)", "total": "итоговую сумму", "prepay": "сумму задатка"}
            set_state(uid, "edit_value")
            await q.edit_message_text(f"✏️ Введи новое {prompts.get(field, field)}:")
        return

    if d.startswith("efroom_"):
        new_room = int(d.split("_")[-1])
        data = get_data(uid)
        row = data["edit_row"]
        booking = data["edit_booking"]
        old_room = booking["Номер"]
        # Проверяем, что новый номер свободен на эти даты (если это другой номер)
        if new_room != old_room:
            bookings = get_bookings()
            try:
                d_in = datetime.strptime(booking["Заезд"], "%d.%m.%Y").date()
                d_out = datetime.strptime(booking["Выезд"], "%d.%m.%Y").date()
            except Exception:
                d_in = d_out = None
            if d_in and not is_room_free_for_dates(new_room, d_in, d_out, bookings):
                await q.edit_message_text(
                    f"❌ *№{new_room} занят* на эти даты ({booking['Заезд']}→{booking['Выезд']})!\n\nВыбери другой номер:",
                    reply_markup=all_rooms_kb("efroom"), parse_mode="Markdown")
                return
            # Очищаем календарь старого номера, переносим на новый
            clear_calendar(old_room, booking["Заезд"], booking["Выезд"])
            update_cell_ws(row, 2, new_room)  # колонка "Номер"
            s = get_room_status(booking)
            update_calendar(new_room, booking["Гость"], booking["Заезд"], booking["Выезд"], s)
        clear(uid)
        await q.edit_message_text(
            f"✅ *Номер изменён!*\n\n👤 {booking['Гость']}\n🏠 №{old_room} → №{new_room}",
            reply_markup=back_kb(), parse_mode="Markdown")
        return

    if d.startswith("es_"):
        new_status = d[3:]
        data = get_data(uid)
        booking = data["edit_booking"]
        set_status(data["edit_row"], new_status, booking=booking)
        if new_status in [STATUS_OCCUPIED, STATUS_BOOKED]:
            update_calendar(booking["Номер"], booking["Гость"], booking["Заезд"], booking["Выезд"], new_status)
        clear(uid)
        await q.edit_message_text(f"✅ Статус №{booking['Номер']} изменён на *{new_status}*", reply_markup=back_kb(), parse_mode="Markdown")
        return

    # ===== НАПОМИНАНИЯ О ЗАДАТКЕ =====
    if d.startswith("remind_yes_"):
        num = int(d.split("_")[-1])
        row, booking = find_booking(num)
        if not booking:
            await q.edit_message_text("Бронь не найдена.", reply_markup=back_kb())
            return
        update_data(uid, "pay_row", row)
        update_data(uid, "pay_booking", booking)
        set_state(uid, "pay_amount")
        await q.edit_message_text(
            f"✅ №{num} — {booking['Гость']}\n\nСколько получили задатком?")
        return

    if d.startswith("remind_no_"):
        num = d.split("_")[-1]
        await q.edit_message_text(f"👍 Понял. Напомним завтра снова про №{num}.", reply_markup=back_kb())
        return

    if d.startswith("remind_cancel_"):
        num = int(d.split("_")[-1])
        all_b = find_all_bookings(num)
        if not all_b:
            await q.edit_message_text("Бронь не найдена.", reply_markup=back_kb())
            return
        row, booking = all_b[0]
        cancel_booking(row, booking, kept_amount=0)
        await q.edit_message_text(
            f"❌ *Бронь №{num} отменена*\n\n👤 {booking['Гость']}",
            reply_markup=back_kb(), parse_mode="Markdown")
        return

    # ===== ОТМЕНА БРОНИ =====
    if d == "cancelbooking":
        bookings = get_bookings()
        active = [b for b in bookings if get_room_status(b) in [STATUS_BOOKED, STATUS_OCCUPIED]]
        if not active:
            await q.edit_message_text("Нет активных броней для отмены.", reply_markup=back_kb())
            return
        kb = []
        row = []
        seen = set()
        for b in active:
            num = str(b["Номер"])
            if num in seen:
                continue
            seen.add(num)
            s = get_room_status(b)
            row.append(InlineKeyboardButton(f"{icon_for(s)}№{num}", callback_data=f"cancelpick_{num}"))
            if len(row) == 4:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
        kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
        await q.edit_message_text("❌ *Отменить бронь*\n\nВыбери номер:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    if d.startswith("cancelpick_"):
        num = int(d.split("_")[-1])
        all_b = find_all_bookings(num)
        if not all_b:
            await q.edit_message_text("Бронь не найдена.", reply_markup=back_kb())
            return
        if len(all_b) > 1:
            kb = []
            for row, b in all_b:
                s = get_room_status(b)
                kb.append([InlineKeyboardButton(f"{icon_for(s)} {b['Гость']} ({b['Заезд']}→{b['Выезд']})", callback_data=f"cancel_confirm_{num}_{row}")])
            kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
            await q.edit_message_text(f"❌ *№{num} — несколько броней*\n\nВыбери какую отменить:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        else:
            row, booking = all_b[0]
            await show_cancel_confirm(q, uid, num, row, booking)
        return

    if d.startswith("cancel_confirm_"):
        parts = d.split("_")
        num = int(parts[2])
        row = int(parts[3])
        booking = get_booking_by_row(num, row)
        if not booking:
            await q.edit_message_text("Бронь не найдена.", reply_markup=back_kb())
            return
        await show_cancel_confirm(q, uid, num, row, booking)
        return

    if d == "cancel_full_refund":
        data = get_data(uid)
        row = data["cancel_row"]
        booking = data["cancel_booking"]
        success = cancel_booking(row, booking, kept_amount=0)
        clear(uid)
        if success:
            await q.edit_message_text(
                f"❌ *Бронь №{booking['Номер']} отменена*\n\n👤 {booking['Гость']}\n💰 Задаток возвращён полностью",
                reply_markup=back_kb(), parse_mode="Markdown")
        else:
            await q.edit_message_text(
                f"⚠️ *Не удалось отменить бронь!*\n\nПопробуй ещё раз через меню → Изменить данные → Статус → вручную поставь 'Отменён'.",
                reply_markup=back_kb(), parse_mode="Markdown")
        return

    if d == "cancel_partial":
        set_state(uid, "cancel_kept_amount")
        await q.edit_message_text("✂️ Введи сумму которую удерживаем (остальное возвращаем гостю):")
        return


async def show_checkin_booking(q, uid, row, booking):
    debt = int(booking.get("Долг", 0))
    prepay = int(booking.get("Задаток", 0))
    update_data(uid, "checkin_row", row)
    update_data(uid, "checkin_booking", booking)
    set_state(uid, "checkin_payment")
    kb = []
    if debt > 0:
        kb.append([InlineKeyboardButton("💰 Принять оплату", callback_data="checkin_pay_now")])
    kb.append([InlineKeyboardButton("✅ Заселить без оплаты", callback_data="checkin_no_pay")])
    kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
    await q.edit_message_text(
        f"✅ *Заселение №{booking['Номер']}*\n\n"
        f"👤 {booking['Гость']} ({booking['Людей']} чел.)\n"
        f"📅 {booking['Заезд']} → {booking['Выезд']}\n"
        f"━━━━━━━━━━━━\n"
        f"💰 Итого: *{int(booking['Итого']):,} сом*\n"
        f"✅ Задаток: *{prepay:,} сом* ({booking.get('Способ задатка','—')})\n"
        f"⚠️ Долг: *{debt:,} сом*",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def show_checkout_booking(q, uid, row, booking):
    update_data(uid, "co_row", row)
    update_data(uid, "co_booking", booking)
    debt = int(booking.get("Долг", 0))
    pay_text = f"⚠️ Долг: *{debt:,} сом*" if debt > 0 else "✅ Оплачено полностью"
    kb = []
    if debt > 0:
        kb.append([InlineKeyboardButton("💰 Принять оплату и выселить", callback_data="co_pay_and_out")])
    kb.append([InlineKeyboardButton("🚪 Выселить без оплаты", callback_data="co_confirm")])
    kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
    await q.edit_message_text(
        f"🚪 *Выселение №{booking['Номер']}*\n\n👤 {booking['Гость']} ({booking['Людей']} чел.)\n"
        f"📅 {booking['Заезд']} → {booking['Выезд']}\n━━━━━━━━━━━━\n"
        f"💰 Итого: *{int(booking['Итого']):,} сом*\n"
        f"✅ Задаток: *{int(booking['Задаток']):,} сом* ({booking.get('Способ задатка','—')})\n"
        f"💳 Доплата: *{int(booking.get('Доплата',0)):,} сом*\n{pay_text}",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def show_edit_booking(q, uid, num, row, booking):
    update_data(uid, "edit_row", row)
    update_data(uid, "edit_booking", booking)
    update_data(uid, "edit_room", num)
    s = get_room_status(booking)
    await q.edit_message_text(
        f"✏️ *{icon_for(s)} №{num} — {booking['Гость']}*\n\n"
        f"📅 {booking['Заезд']} → {booking['Выезд']}\n"
        f"👥 {booking['Людей']} чел. | 💰 {int(booking['Итого']):,} сом\n\n"
        f"Что хочешь изменить?",
        reply_markup=edit_fields_kb(), parse_mode="Markdown")

async def show_cancel_confirm(q, uid, num, row, booking):
    update_data(uid, "cancel_row", row)
    update_data(uid, "cancel_booking", booking)
    prepay = int(booking.get("Задаток", 0))
    await q.edit_message_text(
        f"❌ *Отмена брони №{num}*\n\n"
        f"👤 {booking['Гость']} ({booking['Людей']} чел.)\n"
        f"📅 {booking['Заезд']} → {booking['Выезд']}\n"
        f"💰 Итого: *{int(booking['Итого']):,} сом*\n"
        f"✅ Задаток внесён: *{prepay:,} сом*\n\n"
        f"Как поступаем с задатком?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Вернуть полностью", callback_data="cancel_full_refund")],
            [InlineKeyboardButton("✂️ Удержать часть", callback_data="cancel_partial")],
            [InlineKeyboardButton("◀️ Назад", callback_data="menu")]
        ]), parse_mode="Markdown")

async def show_info_list(q):
    bookings = get_bookings()
    cleaning_statuses = get_all_cleaning_statuses()
    status_map = {}
    for b in bookings:
        s = get_room_status(b)
        n = str(b["Номер"])
        if s == STATUS_FREE:
            # Если выезд прошёл, смотрим — может быть номер ещё не убран
            s = cleaning_statuses.get(n, STATUS_CLEANED)
            if s == STATUS_CLEANED:
                continue  # действительно свободен и чист — не считаем активным статусом
        if s not in [STATUS_CLEANED, STATUS_CANCELLED]:
            if n not in status_map:
                status_map[n] = s
    kb = []
    row = []
    lines = []
    for num, info in ROOMS.items():
        if num == 14:
            continue
        s = status_map.get(str(num), STATUS_FREE)
        icon = icon_for(s)
        type_name = info["name"].split("— ")[1] if "— " in info["name"] else info["name"]
        lines.append(f"{icon} №{num} — {type_name}")
        row.append(InlineKeyboardButton(f"{icon}№{num}", callback_data=f"info_room_{num}"))
        if len(row) == 4:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
    text = "🔍 *Все номера:*\n\n" + "\n".join(lines)
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def show_info_room(q, num):
    room = ROOMS[num]
    all_b = find_all_bookings(num)
    if all_b:
        lines = []
        for row, b in all_b:
            s = get_room_status(b)
            icon = icon_for(s)
            debt = int(b.get("Долг", 0))
            debt_str = f" | Долг: {debt:,} сом ⚠️" if debt > 0 else " | ✅ Оплачено"
            lines.append(f"{icon} {b['Заезд']}→{b['Выезд']} — *{b['Гость']}* ({b['Людей']} чел.){debt_str}")
        text = f"🏠 *{room['name']}*\n\n" + "\n".join(lines)
    else:
        text = f"🟢 *{room['name']}*\n\nНет броней — номер свободен"
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Все номера", callback_data="info")]
    ]), parse_mode="Markdown")

async def calc_total(q, uid, price_per_person):
    data = get_data(uid)
    people = data["people"]
    nights = data["nights"]
    price_day = price_per_person * people
    total = price_day * nights
    update_data(uid, "price_per_person", price_per_person)
    update_data(uid, "price_day", price_day)
    update_data(uid, "total_suggested", total)
    set_state(uid, "ci_total_confirm")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Да — {total:,} сом", callback_data="ci_total_ok")],
        [InlineKeyboardButton("✏️ Другая сумма", callback_data="ci_total_custom")],
    ])
    await q.edit_message_text(
        f"💰 *Расчёт:*\n\n👥 {people} чел × {price_per_person:,} = *{price_day:,} сом/сутки*\n"
        f"🌙 {nights} ночей\n━━━━━━━━━━━━\n💰 *Итого: {total:,} сом*\n\nВерно?",
        reply_markup=kb, parse_mode="Markdown")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = get_state(uid)
    text = update.message.text.strip()

    # ===== ПОДОБРАТЬ НОМЕР =====
    if state == "search_people":
        try:
            people = int(text)
            update_data(uid, "search_people", people)
            set_state(uid, "search_date_in")
            await update.message.reply_text("📅 Дата заезда? (например: 19.06)")
        except Exception:
            await update.message.reply_text("Введи число")

    elif state == "search_date_in":
        try:
            t = text if len(text) > 5 else text + f".{date.today().year}"
            dt = datetime.strptime(t, "%d.%m.%Y")
            update_data(uid, "search_date_in", dt.strftime("%d.%m.%Y"))
            set_state(uid, "search_date_out")
            await update.message.reply_text("📅 Дата выезда? (например: 21.06)")
        except Exception:
            await update.message.reply_text("Неверный формат. Введи как: 19.06")

    elif state == "search_date_out":
        try:
            t = text if len(text) > 5 else text + f".{date.today().year}"
            dt_out = datetime.strptime(t, "%d.%m.%Y")
            data = get_data(uid)
            dt_in = datetime.strptime(data["search_date_in"], "%d.%m.%Y")
            nights = (dt_out - dt_in).days
            if nights <= 0:
                await update.message.reply_text("Дата выезда должна быть позже!")
                return
            update_data(uid, "search_date_out", dt_out.strftime("%d.%m.%Y"))
            update_data(uid, "search_nights", nights)
            people = data["search_people"]

            bookings = get_bookings()
            suitable = []
            for num, info in ROOMS.items():
                if num == 14:
                    continue
                if info["max"] < people:
                    continue
                if is_room_free_for_dates(num, dt_in.date(), dt_out.date(), bookings):
                    suitable.append((num, info))

            if not suitable:
                await update.message.reply_text(
                    f"😔 Нет свободных номеров на {data['search_date_in']} → {dt_out.strftime('%d.%m.%Y')} для {people} чел.",
                    reply_markup=back_kb())
                clear(uid)
                return

            kb = []
            row = []
            lines = [f"✅ *Свободные номера на {data['search_date_in']}→{dt_out.strftime('%d.%m.%Y')} ({people} чел.):*\n"]
            for num, info in suitable:
                lines.append(f"🟢 {info['name']} (до {info['max']} чел.)")
                row.append(InlineKeyboardButton(f"№{num}", callback_data=f"search_room_{num}"))
                if len(row) == 4:
                    kb.append(row)
                    row = []
            if row:
                kb.append(row)
            kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])

            set_state(uid, "search_select")
            await update.message.reply_text(
                "\n".join(lines) + "\n\nВыбери номер для бронирования:",
                reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        except Exception:
            await update.message.reply_text("Неверный формат. Введи как: 21.06")

    # ===== БРОНЬ — СНАЧАЛА ДАТЫ =====
    if state == "book_date_in":
        try:
            t = text if len(text) > 5 else text + f".{date.today().year}"
            dt = datetime.strptime(t, "%d.%m.%Y")
            update_data(uid, "date_in", dt.strftime("%d.%m.%Y"))
            set_state(uid, "book_date_out")
            await update.message.reply_text("📅 Дата выезда? (например: 21.06)")
        except Exception:
            await update.message.reply_text("Неверный формат. Введи как: 19.06")

    elif state == "book_date_out":
        try:
            t = text if len(text) > 5 else text + f".{date.today().year}"
            dt_out = datetime.strptime(t, "%d.%m.%Y")
            data = get_data(uid)
            dt_in = datetime.strptime(data["date_in"], "%d.%m.%Y")
            nights = (dt_out - dt_in).days
            if nights <= 0:
                await update.message.reply_text("Дата выезда должна быть позже!")
                return
            update_data(uid, "date_out", dt_out.strftime("%d.%m.%Y"))
            update_data(uid, "nights", nights)
            room_num = data["room"]
            bookings = get_bookings()
            if not is_room_free_for_dates(room_num, dt_in.date(), dt_out.date(), bookings):
                # Ищем свободные альтернативы
                alternatives = []
                for num, info in ROOMS.items():
                    if num == 14 or num == room_num:
                        continue
                    if is_room_free_for_dates(num, dt_in.date(), dt_out.date(), bookings):
                        alternatives.append((num, info))
                if alternatives:
                    kb = []
                    row = []
                    alt_lines = []
                    for num, info in alternatives:
                        type_name = info["name"].split("— ")[1] if "— " in info["name"] else info["name"]
                        alt_lines.append(f"🟢 №{num} — {type_name} (до {info['max']} чел.)")
                        row.append(InlineKeyboardButton(f"№{num} — {info['max']} чел.", callback_data=f"ci_room_{num}"))
                        if len(row) == 3:
                            kb.append(row)
                            row = []
                    if row:
                        kb.append(row)
                    kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
                    await update.message.reply_text(
                        f"❌ *№{room_num} занят* на {data['date_in']} → {dt_out.strftime('%d.%m.%Y')}!\n\n"
                        f"✅ *Свободные варианты:*\n\n" + "\n".join(alt_lines) + "\n\nВыбери номер:",
                        reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
                else:
                    await update.message.reply_text(
                        f"❌ *№{room_num} занят* на {data['date_in']} → {dt_out.strftime('%d.%m.%Y')}!\n\n"
                        f"😔 На эти даты нет свободных номеров.",
                        reply_markup=back_kb(), parse_mode="Markdown")
                set_state(uid, "ci_room_selected")
                return
            # Свободен — переходим к имени гостя
            set_state(uid, "ci_guest")
            await update.message.reply_text(
                f"✅ *№{room_num} свободен!*\n"
                f"📅 {data['date_in']} → {dt_out.strftime('%d.%m.%Y')} ({nights} н.)\n\n"
                f"Введи имя гостя:", parse_mode="Markdown")
        except Exception:
            await update.message.reply_text("Неверный формат. Введи как: 21.06")

    # ===== ЗАСЕЛЕНИЕ/БРОНЬ — ИМЯ И ДАЛЕЕ =====
    elif state == "ci_guest":
        update_data(uid, "guest", text)
        set_state(uid, "ci_people")
        await update.message.reply_text("👥 Сколько человек?")

    elif state == "ci_people":
        try:
            update_data(uid, "people", int(text))
            set_state(uid, "ci_date_in")
            await update.message.reply_text("📅 Дата заезда? (например: 19.06)")
        except Exception:
            await update.message.reply_text("Введи число")

    elif state == "ci_date_in":
        try:
            t = text if len(text) > 5 else text + f".{date.today().year}"
            dt = datetime.strptime(t, "%d.%m.%Y")
            update_data(uid, "date_in", dt.strftime("%d.%m.%Y"))
            set_state(uid, "ci_date_out")
            await update.message.reply_text("📅 Дата выезда?")
        except Exception:
            await update.message.reply_text("Неверный формат. Введи как: 19.06")

    elif state == "ci_date_out":
        try:
            t = text if len(text) > 5 else text + f".{date.today().year}"
            dt_out = datetime.strptime(t, "%d.%m.%Y")
            dt_in = datetime.strptime(get_data(uid)["date_in"], "%d.%m.%Y")
            nights = (dt_out - dt_in).days
            if nights <= 0:
                await update.message.reply_text("Дата выезда должна быть позже!")
                return
            update_data(uid, "date_out", dt_out.strftime("%d.%m.%Y"))
            update_data(uid, "nights", nights)
            set_state(uid, "ci_price")
            await update.message.reply_text(f"🌙 Ночей: *{nights}*\n\nЦена за сутки с 1 человека:", reply_markup=price_kb(), parse_mode="Markdown")
        except Exception:
            await update.message.reply_text("Неверный формат. Введи как: 21.06")

    elif state == "ci_price_custom":
        try:
            price = int(text.replace(" ", "").replace(",", ""))
            data = get_data(uid)
            price_day = price * data["people"]
            total = price_day * data["nights"]
            update_data(uid, "price_per_person", price)
            update_data(uid, "price_day", price_day)
            update_data(uid, "total_suggested", total)
            set_state(uid, "ci_total_confirm")
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"✅ Да — {total:,} сом", callback_data="ci_total_ok")],
                [InlineKeyboardButton("✏️ Другая сумма", callback_data="ci_total_custom")],
            ])
            await update.message.reply_text(
                f"💰 *Расчёт:*\n\n👥 {data['people']} чел × {price:,} = *{price_day:,} сом/сутки*\n"
                f"🌙 {data['nights']} ночей\n━━━━━━━━━━━━\n💰 *Итого: {total:,} сом*\n\nВерно?",
                reply_markup=kb, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text("Введи сумму числом")

    elif state == "ci_total_custom":
        try:
            total = int(text.replace(" ", "").replace(",", ""))
            update_data(uid, "total", total)
            set_state(uid, "ci_prepay")
            await update.message.reply_text(
                f"💰 Итого: *{total:,} сом*\n\nСколько взял задаток?\n_(введи 0 если не брал)_",
                parse_mode="Markdown")
        except Exception:
            await update.message.reply_text("Введи сумму числом")

    elif state == "ci_prepay":
        try:
            prepay = int(text.replace(" ", "").replace(",", ""))
            update_data(uid, "prepay", prepay)
            if prepay == 0:
                data = get_data(uid)
                data["prepay"] = 0
                data["prepay_method"] = "—"
                data["debt"] = data["total"]
                save_booking(data)
                clear(uid)
                status = data.get("status", STATUS_OCCUPIED)
                icon = "🔵" if status == STATUS_BOOKED else "✅"
                title = "Бронь" if status == STATUS_BOOKED else "Заселение"
                await update.message.reply_text(
                    f"{icon} *{title} оформлено!*\n\n"
                    f"🏠 {ROOMS[data['room']]['name']}\n👤 {data['guest']}\n"
                    f"📅 {data['date_in']} → {data['date_out']}\n"
                    f"💰 Итого: *{data['total']:,} сом*\n⚠️ Долг: *{data['total']:,} сом*",
                    reply_markup=back_kb(), parse_mode="Markdown")
            else:
                set_state(uid, "ci_prepay_method")
                await update.message.reply_text(
                    f"✅ Задаток: *{prepay:,} сом*\n\nКак оплатил?",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("💵 Наличка", callback_data="ci_prepay_cash"),
                        InlineKeyboardButton("💳 Карта", callback_data="ci_prepay_card"),
                    ]]), parse_mode="Markdown")
        except Exception:
            await update.message.reply_text("Введи сумму числом")

    # ===== ОПЛАТА ПРИ ЗАСЕЛЕНИИ =====
    elif state == "checkin_pay_amount":
        try:
            amount = int(text.replace(" ", "").replace(",", ""))
            update_data(uid, "checkin_pay_amount", amount)
            set_state(uid, "checkin_paymethod")
            await update.message.reply_text(
                f"💳 Сумма: *{amount:,} сом*\n\nКак оплатил?",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💵 Наличка", callback_data="checkin_paymethod_cash"),
                    InlineKeyboardButton("💳 Карта", callback_data="checkin_paymethod_card"),
                ]]), parse_mode="Markdown")
        except Exception:
            await update.message.reply_text("Введи сумму числом")

    # ===== ОПЛАТА ПРИ ВЫСЕЛЕНИИ =====
    elif state == "co_pay_amount":
        try:
            amount = int(text.replace(" ", "").replace(",", ""))
            update_data(uid, "co_pay_amount", amount)
            set_state(uid, "co_paymethod")
            await update.message.reply_text(
                f"💳 Сумма: *{amount:,} сом*\n\nКак оплатил?",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💵 Наличка", callback_data="co_paymethod_cash"),
                    InlineKeyboardButton("💳 Карта", callback_data="co_paymethod_card"),
                ]]), parse_mode="Markdown")
        except Exception:
            await update.message.reply_text("Введи сумму числом")

    # ===== ПРИНЯТЬ ОПЛАТУ =====
    elif state == "pay_amount":
        try:
            amount = int(text.replace(" ", "").replace(",", ""))
            update_data(uid, "pay_amount", amount)
            set_state(uid, "pay_method")
            await update.message.reply_text(
                f"💳 Сумма: *{amount:,} сом*\n\nКак оплатил?",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💵 Наличка", callback_data="pay_method_cash"),
                    InlineKeyboardButton("💳 Карта", callback_data="pay_method_card"),
                ]]), parse_mode="Markdown")
        except Exception:
            await update.message.reply_text("Введи сумму числом")

    # ===== ИЗМЕНИТЬ =====
    elif state == "edit_value":
        data = get_data(uid)
        field = data.get("edit_field")
        row = data["edit_row"]
        booking = data["edit_booking"]
        col_map = {"guest": 3, "people": 4, "date_in": 5, "date_out": 6, "total": 9, "prepay": 10}
        col = col_map.get(field)
        try:
            if field in ["total", "prepay"]:
                val = int(text.replace(" ", "").replace(",", ""))
                # Пересчёт долга при изменении итого или задатка
                total_val = val if field == "total" else int(booking.get("Итого", 0))
                prepay_val = val if field == "prepay" else int(booking.get("Задаток", 0))
                extra_val = int(booking.get("Доплата", 0))
                new_debt = max(0, total_val - prepay_val - extra_val)
                update_cell_ws(row, 14, new_debt)
                update_cell_ws(row, 15, "Оплачено ✅" if new_debt == 0 else "Долг ⚠️")
            elif field == "people":
                val = int(text)
            elif field in ["date_in", "date_out"]:
                t = text if len(text) > 5 else text + f".{date.today().year}"
                datetime.strptime(t, "%d.%m.%Y")
                val = t
                clear_calendar(booking["Номер"], booking["Заезд"], booking["Выезд"])
                new_in = val if field == "date_in" else booking["Заезд"]
                new_out = val if field == "date_out" else booking["Выезд"]
                update_calendar(booking["Номер"], booking["Гость"], new_in, new_out, get_room_status(booking))
            else:
                val = text
                if field == "guest":
                    clear_calendar(booking["Номер"], booking["Заезд"], booking["Выезд"])
                    update_calendar(booking["Номер"], val, booking["Заезд"], booking["Выезд"], get_room_status(booking))
            if col:
                update_cell_ws(row, col, val)
            names = {"guest": "Имя", "people": "Людей", "date_in": "Дата заезда", "date_out": "Дата выезда", "total": "Итого", "prepay": "Задаток"}
            clear(uid)
            await update.message.reply_text(f"✅ *{names.get(field, field)}* изменено на *{val}*", reply_markup=back_kb(), parse_mode="Markdown")
        except Exception:
            await update.message.reply_text("Неверный формат, попробуй ещё раз")

    elif state == "cancel_kept_amount":
        try:
            kept = int(text.replace(" ", "").replace(",", ""))
            data = get_data(uid)
            row = data["cancel_row"]
            booking = data["cancel_booking"]
            cancel_booking(row, booking, kept_amount=kept)
            returned = max(0, int(booking.get("Задаток", 0)) - kept)
            clear(uid)
            await update.message.reply_text(
                f"❌ *Бронь №{booking['Номер']} отменена*\n\n"
                f"👤 {booking['Гость']}\n"
                f"✂️ Удержано: *{kept:,} сом*\n"
                f"💰 Возвращено гостю: *{returned:,} сом*",
                reply_markup=back_kb(), parse_mode="Markdown")
        except Exception:
            await update.message.reply_text("Введи сумму числом")

    else:
        await update.message.reply_text("🏠 Нажми /start")

# ===== ВЕБ СЕРВЕР =====
class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *a):
        pass

ADMIN_ID = 489387868

async def send_deposit_reminders(app):
    """Каждый день в 11:00 — напоминание о бронях без задатка"""
    import asyncio
    while True:
        try:
            now = datetime.now()
            # Считаем секунды до следующего 11:00
            target = now.replace(hour=11, minute=0, second=0, microsecond=0)
            if now >= target:
                target = target + timedelta(days=1)
            wait_seconds = (target - now).total_seconds()
            await asyncio.sleep(wait_seconds)

            # Ищем брони без задатка
            bookings = get_bookings()
            for b in bookings:
                s = get_room_status(b)
                if s == STATUS_BOOKED and int(b.get("Задаток", 0)) == 0:
                    text = (
                        f"⏰ *Напоминание о задатке!*\n\n"
                        f"🏠 №{b['Номер']} — {b['Гость']}\n"
                        f"📅 {b['Заезд']} → {b['Выезд']}\n"
                        f"💰 Итого: {int(b['Итого']):,} сом\n"
                        f"⚠️ Задаток не получен!\n\n"
                        f"Гость отправил задаток?"
                    )
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ Да, получили", callback_data=f"remind_yes_{b['Номер']}"),
                         InlineKeyboardButton("❌ Нет", callback_data=f"remind_no_{b['Номер']}")],
                        [InlineKeyboardButton("🗑 Убрать бронь", callback_data=f"remind_cancel_{b['Номер']}")],
                    ])
                    await app.bot.send_message(ADMIN_ID, text, reply_markup=kb, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"deposit reminder error: {e}")

def sync_statuses_daily():
    """Раз в сутки проверяет статусы. МАКСИМАЛЬНО консервативно — никогда не трогает
    Отменён/Убрано/Отменено, и при любой неопределённости лучше ничего не делает."""
    import time
    # Первый запуск откладываем на 60 секунд, чтобы дать боту стабильно подняться
    time.sleep(60)
    while True:
        try:
            ws = get_ws()
            if ws:
                records = ws.get_all_records()
                logger.info(f"sync_statuses_daily: проверяю {len(records)} записей")
                for i, r in enumerate(records):
                    row = i + 2
                    current_status_raw = str(r.get("Статус", "")).strip()
                    pay_status_raw = str(r.get("Статус оплаты", "")).strip()
                    current_status = norm_status(current_status_raw)
                    pay_status = norm_status(pay_status_raw)

                    # ЗАЩИТА: если ЛЮБОЕ из двух полей похоже на "отменено/отменён/убрано" — пропускаем
                    cancelled_words = [norm_status("Отменён"), norm_status("Отменено"), norm_status("Отменено (частично)")]
                    is_final = (
                        current_status == _N_CLEANED or
                        any(current_status.startswith(w) for w in cancelled_words) or
                        any(pay_status.startswith(w) for w in cancelled_words)
                    )
                    if is_final:
                        continue

                    try:
                        today = date.today()
                        dt_in = datetime.strptime(r["Заезд"], "%d.%m.%Y").date()
                        dt_out = datetime.strptime(r["Выезд"], "%d.%m.%Y").date()
                        if today < dt_in:
                            correct_status = STATUS_BOOKED
                        elif dt_in <= today < dt_out:
                            correct_status = STATUS_OCCUPIED
                        else:
                            correct_status = STATUS_FREE

                        if current_status_raw != correct_status:
                            # Доп. проверка прямо перед записью — перечитываем именно эту ячейку
                            live_check = norm_status(ws.cell(row, 16).value)
                            live_pay_check = norm_status(ws.cell(row, 15).value)
                            if (any(live_check.startswith(w) for w in cancelled_words) or
                                any(live_pay_check.startswith(w) for w in cancelled_words) or
                                live_check == _N_CLEANED):
                                logger.warning(f"sync: row={row} на самом деле уже финальный ('{live_check}'/'{live_pay_check}'), пропускаю")
                                continue
                            ws.update_cell(row, 16, correct_status)
                            if correct_status == STATUS_OCCUPIED:
                                update_calendar(r["Номер"], r["Гость"], r["Заезд"], r["Выезд"], STATUS_OCCUPIED)
                            elif correct_status == STATUS_FREE:
                                clear_calendar(r["Номер"], r["Заезд"], r["Выезд"])
                                set_cleaning_status(r["Номер"], STATUS_CLEAN_NEEDED)
                            logger.info(f"Синхронизация: row={row} №{r['Номер']} '{current_status_raw}' -> '{correct_status}'")
                    except Exception as e:
                        logger.error(f"Sync row error (row={row}): {e}")
            logger.info("sync_statuses_daily: цикл завершён, жду 24 часа")
        except Exception as e:
            logger.error(f"sync_statuses_daily error: {e}")
        time.sleep(86400)  # 24 часа

def run_web():
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), Health).serve_forever()

def main():
    threading.Thread(target=run_web, daemon=True).start()
    threading.Thread(target=sync_statuses_daily, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("resetcleaning", reset_cleaning_cmd))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    async def post_init(application):
        import asyncio
        asyncio.create_task(send_deposit_reminders(application))

    app.post_init = post_init
    print("Бот запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
