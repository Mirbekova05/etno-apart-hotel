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
        import gspread as gs
        return gs.authorize(creds)
    except Exception as e:
        logger.error(f"Auth error: {e}")
        return None

def get_book():
    client = get_client()
    if not client: return None
    try:
        return client.open_by_key(SHEET_ID)
    except Exception as e:
        logger.error(f"Book error: {e}")
        return None

def get_ws():
    book = get_book()
    if not book: return None
    try:
        try:
            return book.worksheet("Бронирования")
        except:
            ws = book.add_worksheet("Бронирования", 1000, 17)
            ws.append_row(["ID","Номер","Гость","Людей","Заезд","Выезд","Ночей",
                "Цена/сутки","Итого","Задаток","Способ задатка",
                "Доплата","Способ доплаты","Долг","Статус оплаты","Статус","Дата записи"])
            return ws
    except Exception as e:
        logger.error(f"WS error: {e}")
        return None

def get_bookings():
    ws = get_ws()
    if not ws: return []
    try:
        return ws.get_all_records()
    except:
        return []

def get_room_status(b):
    try:
        today = date.today()
        dt_in = datetime.strptime(b["Заезд"], "%d.%m.%Y").date()
        dt_out = datetime.strptime(b["Выезд"], "%d.%m.%Y").date()
        s = b.get("Статус", "")
        if s in ["Уборка", "Убран", "Отменён"]: return s
        if today < dt_in: return "Бронь"
        if dt_in <= today < dt_out: return "Занят"
        if today >= dt_out: return "Убран"
        return s
    except:
        return b.get("Статус", "")

def is_room_free_for_dates(room_num, date_in, date_out, bookings):
    """Проверяет свободен ли номер на указанные даты"""
    for b in bookings:
        if str(b.get("Номер")) != str(room_num): continue
        s = b.get("Статус", "")
        if s in ["Убран", "Отменён"]: continue
        try:
            b_in = datetime.strptime(b["Заезд"], "%d.%m.%Y").date()
            b_out = datetime.strptime(b["Выезд"], "%d.%m.%Y").date()
            if date_in < b_out and date_out > b_in:
                return False
        except:
            pass
    return True

def find_booking(room_num):
    records = get_bookings()
    for i, r in enumerate(records):
        if str(r.get("Номер")) == str(room_num) and r.get("Статус") not in ["Убран", "Отменён"]:
            return i + 2, r
    return None, None

def save_booking(data):
    ws = get_ws()
    if not ws: return
    bid = len(ws.get_all_records()) + 1
    pay_status = "Оплачено ✅" if data.get("debt", 0) == 0 else "Долг ⚠️"
    ws.append_row([bid, data["room"], data["guest"], data["people"],
        data["date_in"], data["date_out"], data["nights"], data.get("price_day", 0),
        data.get("total", 0), data.get("prepay", 0), data.get("prepay_method", "—"),
        0, "—", data.get("debt", 0), pay_status, data.get("status", "Бронь"),
        datetime.now().strftime("%d.%m.%Y %H:%M")])
    update_calendar(data["room"], data["guest"], data["date_in"], data["date_out"], data.get("status", "Бронь"))

def set_status(row, status):
    ws = get_ws()
    if ws: ws.update_cell(row, 16, status)

def update_cell_ws(row, col, value):
    ws = get_ws()
    if ws: ws.update_cell(row, col, value)

def add_payment(row, booking, amount, method):
    ws = get_ws()
    if not ws: return 0
    new_extra = int(booking.get("Доплата", 0)) + amount
    new_debt = max(0, int(booking.get("Долг", 0)) - amount)
    ws.update_cell(row, 12, new_extra)
    ws.update_cell(row, 13, method)
    ws.update_cell(row, 14, new_debt)
    ws.update_cell(row, 15, "Оплачено ✅" if new_debt == 0 else "Долг ⚠️")
    return new_debt

# ===== КАЛЕНДАРЬ =====
CALENDAR_START = date(2026, 6, 16)
CALENDAR_END   = date(2026, 8, 31)

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
        if not book: return
        dt_in = datetime.strptime(date_in_str, "%d.%m.%Y").date()
        dt_out = datetime.strptime(date_out_str, "%d.%m.%Y").date()
        color = COLOR_BLUE if status == "Бронь" else COLOR_RED
        for sheet_name, start, end in get_calendar_sheets():
            if dt_out <= start or dt_in > end: continue
            try:
                ws = book.worksheet(sheet_name)
            except:
                days = (end - start).days + 1
                ws = book.add_worksheet(sheet_name, 25, days + 1)
                dates = [(start + timedelta(days=i)).strftime("%d.%m") for i in range(days)]
                ws.append_row(["Номер"] + dates)
                room_nums = [n for n in ROOMS if n != 14]
                ws.append_rows([[f"№{n}"] + [""] * days for n in room_nums])
                try:
                    last_col = chr(ord('A') + days)
                    ws.format(f"B2:{last_col}{len(room_nums)+1}", {"backgroundColor": COLOR_GREEN})
                except: pass
            header = ws.row_values(1)
            all_vals = ws.get_all_values()
            room_row = next((i+1 for i, r in enumerate(all_vals) if r and r[0] == f"№{room}"), None)
            if not room_row: continue
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
        if not book: return
        dt_in = datetime.strptime(date_in_str, "%d.%m.%Y").date()
        dt_out = datetime.strptime(date_out_str, "%d.%m.%Y").date()
        for sheet_name, start, end in get_calendar_sheets():
            if dt_out <= start or dt_in > end: continue
            try:
                ws = book.worksheet(sheet_name)
            except: continue
            header = ws.row_values(1)
            all_vals = ws.get_all_values()
            room_row = next((i+1 for i, r in enumerate(all_vals) if r and r[0] == f"№{room}"), None)
            if not room_row: continue
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

def get_state(uid): return user_states.get(uid, "menu")
def set_state(uid, s): user_states[uid] = s
def get_data(uid): return user_data.get(uid, {})
def update_data(uid, k, v):
    if uid not in user_data: user_data[uid] = {}
    user_data[uid][k] = v
def clear(uid):
    user_states.pop(uid, None)
    user_data.pop(uid, None)

def icon_for(s):
    return {"Занят":"🔴","Бронь":"🔵","Уборка":"🧹","Убран":"🟢"}.get(s,"🟢")

# ===== КЛАВИАТУРЫ =====
def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 Подобрать номер", callback_data="search")],
        [InlineKeyboardButton("🔵 Бронь", callback_data="book"),
         InlineKeyboardButton("✅ Заселить", callback_data="checkin")],
        [InlineKeyboardButton("🚪 Выселить", callback_data="checkout"),
         InlineKeyboardButton("💰 Принять оплату", callback_data="payment")],
        [InlineKeyboardButton("🔍 Инфо", callback_data="info"),
         InlineKeyboardButton("🧹 Уборка", callback_data="cleaning")],
        [InlineKeyboardButton("✏️ Изменить данные", callback_data="edit")],
    ])

def back_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="menu")]])

def price_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1,500 сом", callback_data="ci_price_1500"),
         InlineKeyboardButton("2,500 сом", callback_data="ci_price_2500")],
        [InlineKeyboardButton("✏️ Своя цена", callback_data="ci_price_custom")],
    ])

def pay_method_kb(prefix):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💵 Наличка", callback_data=f"{prefix}_cash"),
        InlineKeyboardButton("💳 Карта", callback_data=f"{prefix}_card"),
    ]])

def free_rooms_kb(prefix, bookings=None):
    if bookings is None: bookings = get_bookings()
    today = date.today()
    occupied = set()
    for b in bookings:
        s = get_room_status(b)
        if s in ["Занят","Уборка"]: occupied.add(str(b["Номер"]))
        elif s == "Бронь":
            try:
                if datetime.strptime(b["Заезд"], "%d.%m.%Y").date() <= today:
                    occupied.add(str(b["Номер"]))
            except: occupied.add(str(b["Номер"]))
    kb = []
    row = []
    for num in ROOMS:
        if num == 14: continue
        if str(num) not in occupied:
            row.append(InlineKeyboardButton(f"№{num}", callback_data=f"{prefix}_{num}"))
            if len(row) == 4: kb.append(row); row = []
    if row: kb.append(row)
    kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
    return InlineKeyboardMarkup(kb)

def active_rooms_kb(prefix):
    bookings = get_bookings()
    kb = []
    row = []
    for b in bookings:
        s = get_room_status(b)
        if s in ["Занят","Бронь","Уборка"]:
            row.append(InlineKeyboardButton(f"{icon_for(s)}№{b['Номер']}", callback_data=f"{prefix}_{b['Номер']}"))
            if len(row) == 4: kb.append(row); row = []
    if row: kb.append(row)
    kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
    return InlineKeyboardMarkup(kb)

def info_filter_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔵 Брони", callback_data="info_filter_Бронь"),
         InlineKeyboardButton("🔴 Занятые", callback_data="info_filter_Занят")],
        [InlineKeyboardButton("🧹 Уборка", callback_data="info_filter_Уборка"),
         InlineKeyboardButton("📋 Все", callback_data="info_filter_Все")],
        [InlineKeyboardButton("◀️ Меню", callback_data="menu")],
    ])

def edit_fields_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Имя гостя", callback_data="ef_guest"),
         InlineKeyboardButton("👥 Кол-во людей", callback_data="ef_people")],
        [InlineKeyboardButton("📅 Дата заезда", callback_data="ef_date_in"),
         InlineKeyboardButton("📅 Дата выезда", callback_data="ef_date_out")],
        [InlineKeyboardButton("💰 Итоговая сумма", callback_data="ef_total"),
         InlineKeyboardButton("✅ Задаток", callback_data="ef_prepay")],
        [InlineKeyboardButton("🔄 Статус", callback_data="ef_status")],
        [InlineKeyboardButton("◀️ Меню", callback_data="menu")],
    ])

def status_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔵 Бронь", callback_data="es_Бронь"),
         InlineKeyboardButton("🔴 Занят", callback_data="es_Занят")],
        [InlineKeyboardButton("🧹 Уборка", callback_data="es_Уборка"),
         InlineKeyboardButton("✅ Убран", callback_data="es_Убран")],
        [InlineKeyboardButton("◀️ Назад", callback_data="edit")],
    ])

# ===== ХЭНДЛЕРЫ =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    clear(uid)
    await update.message.reply_text("🏠 *Управление квартирами*\n\nВыбери действие:", reply_markup=main_kb(), parse_mode="Markdown")

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    d = q.data

    if d == "menu":
        clear(uid)
        await q.edit_message_text("🏠 *Управление квартирами*\n\nВыбери действие:", reply_markup=main_kb(), parse_mode="Markdown")

    # ===== ПОДОБРАТЬ НОМЕР =====
    elif d == "search":
        user_data[uid] = {"mode": "search"}
        set_state(uid, "search_people")
        await q.edit_message_text("🔎 *Подобрать номер*\n\nСколько человек?", parse_mode="Markdown")

    # ===== СВОБОДНЫЕ =====
    elif d == "free":
        bookings = get_bookings()
        today = date.today()
        occupied = set()
        for b in bookings:
            s = get_room_status(b)
            if s in ["Занят","Уборка"]: occupied.add(str(b["Номер"]))
            elif s == "Бронь":
                try:
                    if datetime.strptime(b["Заезд"], "%d.%m.%Y").date() <= today:
                        occupied.add(str(b["Номер"]))
                except: pass
        lines = [f"🟢 {info['name']}" for num, info in ROOMS.items() if num != 14 and str(num) not in occupied]
        text = ("🟢 *Свободные номера:*\n\n" + "\n".join(lines)) if lines else "❌ Все номера заняты"
        await q.edit_message_text(text, reply_markup=back_kb(), parse_mode="Markdown")

    # ===== БРОНЬ =====
    elif d == "book":
        user_data[uid] = {"status": "Бронь"}
        set_state(uid, "ci_guest")
        await q.edit_message_text("🔵 *Бронирование*\n\nВыбери номер:", reply_markup=free_rooms_kb("ci_room"), parse_mode="Markdown")

    # ===== ЗАСЕЛЕНИЕ =====
    elif d == "checkin":
        bookings = get_bookings()
        # Проверяем есть ли брони которые можно заселить
        booked = [b for b in bookings if get_room_status(b) in ["Бронь", "Занят"]]
        kb_rows = []
        if booked:
            kb_rows.append([InlineKeyboardButton("🔵 Заселить из брони", callback_data="checkin_from_book")])
        kb_rows.append([InlineKeyboardButton("✅ Новое заселение", callback_data="checkin_new")])
        kb_rows.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
        await q.edit_message_text("✅ *Заселение*\n\nВыбери тип:", reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode="Markdown")

    elif d == "checkin_new":
        user_data[uid] = {"status": "Занят"}
        set_state(uid, "ci_guest")
        await q.edit_message_text("✅ *Новое заселение*\n\nВыбери номер:", reply_markup=free_rooms_kb("ci_room"), parse_mode="Markdown")

    elif d == "checkin_from_book":
        bookings = get_bookings()
        booked = [b for b in bookings if get_room_status(b) == "Бронь"]
        if not booked:
            await q.edit_message_text("Нет активных броней.", reply_markup=back_kb())
            return
        kb = []
        row = []
        for b in booked:
            row.append(InlineKeyboardButton(f"🔵№{b['Номер']} — {b['Гость']}", callback_data=f"checkin_book_{b['Номер']}"))
            if len(row) == 2: kb.append(row); row = []
        if row: kb.append(row)
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data="checkin")])
        await q.edit_message_text("🔵 *Выбери бронь для заселения:*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("checkin_book_"):
        num = int(d.split("_")[-1])
        row, booking = find_booking(num)
        if not booking:
            await q.edit_message_text("Бронь не найдена.", reply_markup=back_kb())
            return
        debt = int(booking.get("Долг", 0))
        prepay = int(booking.get("Задаток", 0))
        update_data(uid, "checkin_row", row)
        update_data(uid, "checkin_booking", booking)
        set_state(uid, "checkin_payment")
        await q.edit_message_text(
            f"✅ *Заселение №{num}*\n\n"
            f"👤 {booking['Гость']} ({booking['Людей']} чел.)\n"
            f"📅 {booking['Заезд']} → {booking['Выезд']}\n"
            f"━━━━━━━━━━━━\n"
            f"💰 Итого: *{int(booking['Итого']):,} сом*\n"
            f"✅ Задаток: *{prepay:,} сом* ({booking.get('Способ задатка','—')})\n"
            f"⚠️ Долг: *{debt:,} сом*\n\n"
            f"Принять оплату при заселении?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 Принять оплату", callback_data="checkin_pay_now")],
                [InlineKeyboardButton("✅ Заселить без оплаты", callback_data="checkin_no_pay")],
                [InlineKeyboardButton("◀️ Назад", callback_data="checkin_from_book")]
            ]), parse_mode="Markdown")

    elif d == "checkin_pay_now":
        data = get_data(uid)
        booking = data["checkin_booking"]
        set_state(uid, "checkin_pay_amount")
        await q.edit_message_text(
            f"💰 Долг: *{int(booking['Долг']):,} сом*\n\nВведи сумму оплаты:",
            parse_mode="Markdown")

    elif d == "checkin_no_pay":
        data = get_data(uid)
        row = data["checkin_row"]
        booking = data["checkin_booking"]
        set_status(row, "Занят")
        update_calendar(booking["Номер"], booking["Гость"], booking["Заезд"], booking["Выезд"], "Занят")
        clear(uid)
        await q.edit_message_text(
            f"✅ *№{booking['Номер']} заселён!*\n\n👤 {booking['Гость']}\n⚠️ Долг: *{int(booking['Долг']):,} сом*",
            reply_markup=back_kb(), parse_mode="Markdown")

    elif d.startswith("checkin_paymethod_"):
        method = "💵 Наличка" if d == "checkin_paymethod_cash" else "💳 Карта"
        data = get_data(uid)
        row = data["checkin_row"]
        booking = data["checkin_booking"]
        amount = data["checkin_pay_amount"]
        new_debt = add_payment(row, booking, amount, method)
        set_status(row, "Занят")
        update_calendar(booking["Номер"], booking["Гость"], booking["Заезд"], booking["Выезд"], "Занят")
        pay_text = "🎉 Оплачено полностью!" if new_debt == 0 else f"⚠️ Остаток долга: *{new_debt:,} сом*"
        clear(uid)
        await q.edit_message_text(
            f"✅ *№{booking['Номер']} заселён!*\n\n"
            f"💳 Принято: *{amount:,} сом* ({method})\n{pay_text}",
            reply_markup=back_kb(), parse_mode="Markdown")

    elif d.startswith("ci_room_"):
        num = int(d.split("_")[-1])
        update_data(uid, "room", num)
        set_state(uid, "ci_guest")
        await q.edit_message_text(f"*{ROOMS[num]['name']}*\n\nВведи имя гостя:", parse_mode="Markdown")

    elif d.startswith("ci_price_"):
        if d == "ci_price_custom":
            set_state(uid, "ci_price_custom")
            await q.edit_message_text("✏️ Введи цену за сутки с 1 человека:")
        else:
            await calc_total(q, uid, int(d.split("_")[-1]))

    elif d == "ci_total_ok":
        data = get_data(uid)
        update_data(uid, "total", data["total_suggested"])
        set_state(uid, "ci_prepay")
        await q.edit_message_text(
            f"💰 Итого: *{data['total_suggested']:,} сом*\n\n"
            f"Сколько взял задаток?\n_(введи 0 если не брал)_",
            parse_mode="Markdown")

    elif d == "ci_total_custom":
        set_state(uid, "ci_total_custom")
        await q.edit_message_text("✏️ Введи итоговую сумму:")

    elif d.startswith("ci_prepay_"):
        method = "💵 Наличка" if d == "ci_prepay_cash" else "💳 Карта"
        data = get_data(uid)
        data["prepay_method"] = method
        debt = max(0, data["total"] - data["prepay"])
        data["debt"] = debt
        save_booking(data)
        status = data.get("status", "Занят")
        icon = "🔵" if status == "Бронь" else "✅"
        title = "Бронь оформлена!" if status == "Бронь" else "Заселение оформлено!"
        pay_text = "🎉 *Оплачено полностью!*" if debt == 0 else f"⚠️ *Долг: {debt:,} сом*"
        clear(uid)
        await q.edit_message_text(
            f"{icon} *{title}*\n\n🏠 {ROOMS[data['room']]['name']}\n"
            f"👤 {data['guest']} ({data['people']} чел.)\n"
            f"📅 {data['date_in']} → {data['date_out']} ({data['nights']} н.)\n"
            f"━━━━━━━━━━━━\n💰 Итого: *{data['total']:,} сом*\n"
            f"✅ Задаток: *{data['prepay']:,} сом* ({method})\n{pay_text}",
            reply_markup=back_kb(), parse_mode="Markdown")

    # ===== ПОДОБРАТЬ - выбор из найденных =====
    elif d.startswith("search_room_"):
        num = int(d.split("_")[-1])
        data = get_data(uid)
        # Переходим в бронь с уже заполненными данными
        user_data[uid] = {
            "status": "Бронь",
            "room": num,
            "people": data.get("search_people", 1),
            "date_in": data.get("search_date_in", ""),
            "date_out": data.get("search_date_out", ""),
            "nights": data.get("search_nights", 1),
        }
        set_state(uid, "ci_guest")
        await q.edit_message_text(
            f"🔵 *Бронирование №{num}*\n"
            f"📅 {data['search_date_in']} → {data['search_date_out']}\n\n"
            f"Введи имя гостя:", parse_mode="Markdown")

    # ===== ВЫСЕЛЕНИЕ =====
    elif d == "checkout":
        bookings = get_bookings()
        active = [b for b in bookings if get_room_status(b) == "Занят"]
        if not active:
            await q.edit_message_text("Нет активных заселений.", reply_markup=back_kb())
        else:
            kb = []
            row = []
            for b in active:
                row.append(InlineKeyboardButton(f"🔴№{b['Номер']} — {b['Гость']}", callback_data=f"co_room_{b['Номер']}"))
                if len(row) == 2: kb.append(row); row = []
            if row: kb.append(row)
            kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
            await q.edit_message_text("🚪 *Выселение*\n\nВыбери номер:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("co_room_"):
        num = int(d.split("_")[-1])
        row, booking = find_booking(num)
        if not booking:
            await q.edit_message_text("Номер не найден.", reply_markup=back_kb())
            return
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
            f"🚪 *Выселение №{num}*\n\n👤 {booking['Гость']} ({booking['Людей']} чел.)\n"
            f"📅 {booking['Заезд']} → {booking['Выезд']}\n━━━━━━━━━━━━\n"
            f"💰 Итого: *{int(booking['Итого']):,} сом*\n"
            f"✅ Задаток: *{int(booking['Задаток']):,} сом* ({booking.get('Способ задатка','—')})\n"
            f"💳 Доплата: *{int(booking.get('Доплата',0)):,} сом*\n{pay_text}",
            reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d == "co_pay_and_out":
        data = get_data(uid)
        booking = data["co_booking"]
        set_state(uid, "co_pay_amount")
        await q.edit_message_text(
            f"💰 Долг: *{int(booking['Долг']):,} сом*\n\nВведи сумму оплаты:",
            parse_mode="Markdown")

    elif d.startswith("co_paymethod_"):
        method = "💵 Наличка" if d == "co_paymethod_cash" else "💳 Карта"
        data = get_data(uid)
        new_debt = add_payment(data["co_row"], data["co_booking"], data["co_pay_amount"], method)
        set_status(data["co_row"], "Уборка")
        booking = data["co_booking"]
        clear(uid)
        pay_text = "🎉 Долг погашен!" if new_debt == 0 else f"⚠️ Остаток: *{new_debt:,} сом*"
        await q.edit_message_text(
            f"✅ *№{booking['Номер']} выселен!*\n\n"
            f"💳 Принято: *{data['co_pay_amount']:,} сом* ({method})\n{pay_text}\n\n🧹 Нужна уборка!",
            reply_markup=back_kb(), parse_mode="Markdown")

    elif d == "co_confirm":
        data = get_data(uid)
        booking = data["co_booking"]
        set_status(data["co_row"], "Уборка")
        clear(uid)
        await q.edit_message_text(f"✅ *№{booking['Номер']} выселен!*\n\n🧹 Нужна уборка!", reply_markup=back_kb(), parse_mode="Markdown")

    # ===== ИНФО =====
    elif d == "info":
        await q.edit_message_text("🔍 *Инфо по номерам*\n\nВыбери фильтр:", reply_markup=info_filter_kb(), parse_mode="Markdown")

    elif d.startswith("info_filter_"):
        f = d[12:]
        bookings = get_bookings()
        lines = []
        kb_rooms = []
        row = []
        for b in bookings:
            s = get_room_status(b)
            if f == "Все" or s == f:
                icon = icon_for(s)
                lines.append(f"{icon} №{b['Номер']} — {b['Гость']} ({b['Заезд']}→{b['Выезд']})")
                row.append(InlineKeyboardButton(f"{icon}№{b['Номер']}", callback_data=f"info_room_{b['Номер']}"))
                if len(row) == 4: kb_rooms.append(row); row = []
        if row: kb_rooms.append(row)
        if not lines:
            await q.edit_message_text("Ничего не найдено.", reply_markup=info_filter_kb())
            return
        kb_rooms.append([InlineKeyboardButton("◀️ Фильтр", callback_data="info")])
        text = f"*{'Все номера' if f=='Все' else f}:*\n\n" + "\n".join(lines)
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rooms), parse_mode="Markdown")

    elif d.startswith("info_room_"):
        num = int(d.split("_")[-1])
        _, booking = find_booking(num)
        if booking:
            s = get_room_status(booking)
            icon = icon_for(s)
            debt = int(booking.get("Долг", 0))
            pay_text = "🎉 Оплачено!" if debt == 0 else f"⚠️ Долг: *{debt:,} сом*"
            text = (f"{icon} *{ROOMS[num]['name']}* — {s}\n\n"
                f"👤 {booking['Гость']} ({booking['Людей']} чел.)\n"
                f"📅 {booking['Заезд']} → {booking['Выезд']} ({booking['Ночей']} н.)\n"
                f"━━━━━━━━━━━━\n"
                f"💰 Итого: *{int(booking['Итого']):,} сом*\n"
                f"✅ Задаток: *{int(booking['Задаток']):,} сом* ({booking.get('Способ задатка','—')})\n"
                f"💳 Доплата: *{int(booking.get('Доплата',0)):,} сом* ({booking.get('Способ доплаты','—')})\n"
                f"{pay_text}")
        else:
            text = f"🟢 *{ROOMS[num]['name']}* — СВОБОДЕН"
        await q.edit_message_text(text, reply_markup=back_kb(), parse_mode="Markdown")

    # ===== ОПЛАТА =====
    elif d == "payment":
        bookings = get_bookings()
        with_debt = [b for b in bookings if get_room_status(b) in ["Занят","Бронь"] and int(b.get("Долг",0)) > 0]
        if not with_debt:
            await q.edit_message_text("✅ Все долги оплачены!", reply_markup=back_kb())
        else:
            kb = []
            row = []
            for b in with_debt:
                row.append(InlineKeyboardButton(f"{icon_for(get_room_status(b))}№{b['Номер']} — {int(b['Долг']):,}с", callback_data=f"pay_room_{b['Номер']}"))
                if len(row) == 2: kb.append(row); row = []
            if row: kb.append(row)
            kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
            await q.edit_message_text("💰 *Принять оплату*\n\nНомера с долгом:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("pay_room_"):
        num = int(d.split("_")[-1])
        row, booking = find_booking(num)
        update_data(uid, "pay_row", row)
        update_data(uid, "pay_booking", booking)
        set_state(uid, "pay_amount")
        await q.edit_message_text(
            f"💰 №{num} — {booking['Гость']}\n"
            f"💰 Итого: *{int(booking['Итого']):,} сом*\n"
            f"✅ Задаток: *{int(booking['Задаток']):,} сом*\n"
            f"⚠️ Долг: *{int(booking['Долг']):,} сом*\n\nВведи сумму оплаты:",
            parse_mode="Markdown")

    elif d.startswith("pay_method_"):
        method = "💵 Наличка" if d == "pay_method_cash" else "💳 Карта"
        data = get_data(uid)
        new_debt = add_payment(data["pay_row"], data["pay_booking"], data["pay_amount"], method)
        pay_text = "🎉 Долг погашен!" if new_debt == 0 else f"⚠️ Остаток: *{new_debt:,} сом*"
        clear(uid)
        await q.edit_message_text(f"✅ Оплата принята!\n💳 {data['pay_amount']:,} сом ({method})\n{pay_text}",
            reply_markup=back_kb(), parse_mode="Markdown")

    # ===== УБОРКА =====
    elif d == "cleaning":
        bookings = get_bookings()
        to_clean = [b for b in bookings if get_room_status(b) == "Уборка"]
        if not to_clean:
            await q.edit_message_text("✅ Все номера чистые!", reply_markup=back_kb())
        else:
            kb = []
            row = []
            for b in to_clean:
                row.append(InlineKeyboardButton(f"🧹№{b['Номер']} — {b['Гость']}", callback_data=f"clean_{b['Номер']}"))
                if len(row) == 2: kb.append(row); row = []
            if row: kb.append(row)
            kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
            await q.edit_message_text("🧹 *Нужна уборка:*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("clean_"):
        num = int(d.split("_")[-1])
        row, booking = find_booking(num)
        if booking:
            set_status(row, "Убран")
            clear_calendar(num, booking["Заезд"], booking["Выезд"])
        await q.edit_message_text(f"✅ *№{num} убран!*\n\n🟢 Готов к заселению.", reply_markup=back_kb(), parse_mode="Markdown")

    # ===== ИЗМЕНИТЬ =====
    elif d == "edit":
        await q.edit_message_text("✏️ *Изменить данные*\n\nВыбери номер:", reply_markup=active_rooms_kb("edit_room"), parse_mode="Markdown")

    elif d.startswith("edit_room_"):
        num = int(d.split("_")[-1])
        row, booking = find_booking(num)
        if not booking:
            await q.edit_message_text("Бронь не найдена.", reply_markup=back_kb())
            return
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

    elif d.startswith("ef_"):
        field = d[3:]
        update_data(uid, "edit_field", field)
        if field == "status":
            set_state(uid, "edit_status")
            await q.edit_message_text("🔄 Выбери новый статус:", reply_markup=status_kb())
        else:
            prompts = {"guest":"имя гостя","people":"количество людей","date_in":"дату заезда (19.06)","date_out":"дату выезда (21.06)","total":"итоговую сумму","prepay":"сумму задатка"}
            set_state(uid, "edit_value")
            await q.edit_message_text(f"✏️ Введи новое {prompts.get(field, field)}:")

    elif d.startswith("es_"):
        new_status = d[3:]
        data = get_data(uid)
        set_status(data["edit_row"], new_status)
        booking = data["edit_booking"]
        if new_status in ["Занят","Бронь"]:
            update_calendar(booking["Номер"], booking["Гость"], booking["Заезд"], booking["Выезд"], new_status)
        clear(uid)
        await q.edit_message_text(f"✅ Статус №{booking['Номер']} изменён на *{new_status}*", reply_markup=back_kb(), parse_mode="Markdown")

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
        except:
            await update.message.reply_text("Введи число")

    elif state == "search_date_in":
        try:
            t = text if len(text) > 5 else text + f".{date.today().year}"
            dt = datetime.strptime(t, "%d.%m.%Y")
            update_data(uid, "search_date_in", dt.strftime("%d.%m.%Y"))
            set_state(uid, "search_date_out")
            await update.message.reply_text("📅 Дата выезда? (например: 21.06)")
        except:
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

            # Ищем подходящие номера
            bookings = get_bookings()
            suitable = []
            for num, info in ROOMS.items():
                if num == 14: continue
                if info["max"] < people: continue
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
                if len(row) == 4: kb.append(row); row = []
            if row: kb.append(row)
            kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])

            set_state(uid, "search_select")
            await update.message.reply_text(
                "\n".join(lines) + "\n\nВыбери номер для бронирования:",
                reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        except:
            await update.message.reply_text("Неверный формат. Введи как: 21.06")

    # ===== ЗАСЕЛЕНИЕ/БРОНЬ =====
    elif state == "ci_guest":
        update_data(uid, "guest", text)
        set_state(uid, "ci_people")
        await update.message.reply_text("👥 Сколько человек?")

    elif state == "ci_people":
        try:
            update_data(uid, "people", int(text))
            set_state(uid, "ci_date_in")
            await update.message.reply_text("📅 Дата заезда? (например: 19.06)")
        except:
            await update.message.reply_text("Введи число")

    elif state == "ci_date_in":
        try:
            t = text if len(text) > 5 else text + f".{date.today().year}"
            dt = datetime.strptime(t, "%d.%m.%Y")
            update_data(uid, "date_in", dt.strftime("%d.%m.%Y"))
            set_state(uid, "ci_date_out")
            await update.message.reply_text("📅 Дата выезда?")
        except:
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
        except:
            await update.message.reply_text("Неверный формат. Введи как: 21.06")

    elif state == "ci_price_custom":
        try:
            price = int(text.replace(" ","").replace(",",""))
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
        except:
            await update.message.reply_text("Введи сумму числом")

    elif state == "ci_total_custom":
        try:
            total = int(text.replace(" ","").replace(",",""))
            update_data(uid, "total", total)
            set_state(uid, "ci_prepay")
            await update.message.reply_text(
                f"💰 Итого: *{total:,} сом*\n\nСколько взял задаток?\n_(введи 0 если не брал)_",
                parse_mode="Markdown")
        except:
            await update.message.reply_text("Введи сумму числом")

    elif state == "ci_prepay":
        try:
            prepay = int(text.replace(" ","").replace(",",""))
            update_data(uid, "prepay", prepay)
            set_state(uid, "ci_prepay_method")
            if prepay == 0:
                # Без задатка — сразу сохраняем
                data = get_data(uid)
                data["prepay"] = 0
                data["prepay_method"] = "—"
                data["debt"] = data["total"]
                save_booking(data)
                clear(uid)
                status = data.get("status", "Занят")
                icon = "🔵" if status == "Бронь" else "✅"
                await update.message.reply_text(
                    f"{icon} *{'Бронь' if status=='Бронь' else 'Заселение'} оформлено!*\n\n"
                    f"🏠 {ROOMS[data['room']]['name']}\n👤 {data['guest']}\n"
                    f"📅 {data['date_in']} → {data['date_out']}\n"
                    f"💰 Итого: *{data['total']:,} сом*\n⚠️ Долг: *{data['total']:,} сом*",
                    reply_markup=back_kb(), parse_mode="Markdown")
            else:
                await update.message.reply_text(
                    f"✅ Задаток: *{prepay:,} сом*\n\nКак оплатил?",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("💵 Наличка", callback_data="ci_prepay_cash"),
                        InlineKeyboardButton("💳 Карта", callback_data="ci_prepay_card"),
                    ]]), parse_mode="Markdown")
        except:
            await update.message.reply_text("Введи сумму числом")

    # ===== ОПЛАТА ПРИ ЗАСЕЛЕНИИ =====
    elif state == "checkin_pay_amount":
        try:
            amount = int(text.replace(" ","").replace(",",""))
            update_data(uid, "checkin_pay_amount", amount)
            set_state(uid, "checkin_paymethod")
            await update.message.reply_text(
                f"💳 Сумма: *{amount:,} сом*\n\nКак оплатил?",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💵 Наличка", callback_data="checkin_paymethod_cash"),
                    InlineKeyboardButton("💳 Карта", callback_data="checkin_paymethod_card"),
                ]]), parse_mode="Markdown")
        except:
            await update.message.reply_text("Введи сумму числом")

    # ===== ОПЛАТА ПРИ ВЫСЕЛЕНИИ =====
    elif state == "co_pay_amount":
        try:
            amount = int(text.replace(" ","").replace(",",""))
            update_data(uid, "co_pay_amount", amount)
            set_state(uid, "co_paymethod")
            await update.message.reply_text(
                f"💳 Сумма: *{amount:,} сом*\n\nКак оплатил?",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💵 Наличка", callback_data="co_paymethod_cash"),
                    InlineKeyboardButton("💳 Карта", callback_data="co_paymethod_card"),
                ]]), parse_mode="Markdown")
        except:
            await update.message.reply_text("Введи сумму числом")

    # ===== ПРИНЯТЬ ОПЛАТУ =====
    elif state == "pay_amount":
        try:
            amount = int(text.replace(" ","").replace(",",""))
            update_data(uid, "pay_amount", amount)
            set_state(uid, "pay_method")
            await update.message.reply_text(
                f"💳 Сумма: *{amount:,} сом*\n\nКак оплатил?",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💵 Наличка", callback_data="pay_method_cash"),
                    InlineKeyboardButton("💳 Карта", callback_data="pay_method_card"),
                ]]), parse_mode="Markdown")
        except:
            await update.message.reply_text("Введи сумму числом")

    # ===== ИЗМЕНИТЬ =====
    elif state == "edit_value":
        data = get_data(uid)
        field = data.get("edit_field")
        row = data["edit_row"]
        booking = data["edit_booking"]
        col_map = {"guest":3,"people":4,"date_in":5,"date_out":6,"total":9,"prepay":10}
        col = col_map.get(field)
        try:
            if field in ["total","prepay"]:
                val = int(text.replace(" ","").replace(",",""))
            elif field == "people":
                val = int(text)
            elif field in ["date_in","date_out"]:
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
            names = {"guest":"Имя","people":"Людей","date_in":"Дата заезда","date_out":"Дата выезда","total":"Итого","prepay":"Задаток"}
            clear(uid)
            await update.message.reply_text(f"✅ *{names.get(field,field)}* изменено на *{val}*", reply_markup=back_kb(), parse_mode="Markdown")
        except:
            await update.message.reply_text("Неверный формат, попробуй ещё раз")

    else:
        await update.message.reply_text("🏠 Нажми /start")

# ===== ВЕБ СЕРВЕР =====
class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *a): pass

def run_web():
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), Health).serve_forever()

def main():
    threading.Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    print("Бот запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
