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
    if not ws:
        return []
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
        if s in ["Надо убрать", "Убрано", "Отменён"]:
            return s
        if today < dt_in:
            return "Бронь"
        if dt_in <= today < dt_out:
            return "Занят"
        if today >= dt_out:
            return "Надо убрать"
        return s
    except:
        return b.get("Статус", "")

def find_booking(room_num):
    records = get_bookings()
    for i, r in enumerate(records):
        if str(r.get("Номер")) == str(room_num) and r.get("Статус") not in ["Убрано", "Отменён"]:
            return i + 2, r
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
        0, "—", data.get("debt", 0), pay_status, data.get("status", "Бронь"),
        datetime.now().strftime("%d.%m.%Y %H:%M")])
    update_calendar(data["room"], data["guest"], data["date_in"], data["date_out"], data.get("status", "Бронь"))

def set_status(row, status):
    ws = get_ws()
    if ws:
        ws.update_cell(row, 16, status)

def update_cell_ws(row, col, value):
    ws = get_ws()
    if ws:
        ws.update_cell(row, col, value)

def add_payment(row, booking, amount, method):
    ws = get_ws()
    if not ws:
        return 0
    new_extra = int(booking.get("Доплата", 0)) + amount
    new_debt = max(0, int(booking.get("Долг", 0)) - amount)
    ws.update_cell(row, 12, new_extra)
    ws.update_cell(row, 13, method)
    ws.update_cell(row, 14, new_debt)
    ws.update_cell(row, 15, "Оплачено ✅" if new_debt == 0 else "Долг ⚠️")
    return new_debt

# ===== КАЛЕНДАРЬ (по 2 недели) =====
CALENDAR_START = date(2026, 6, 16)
CALENDAR_END   = date(2026, 8, 31)

def get_calendar_sheets():
    """Возвращает список (название листа, начало, конец) по 2 недели"""
    sheets = []
    d = CALENDAR_START
    while d <= CALENDAR_END:
        end = min(d + timedelta(days=13), CALENDAR_END)
        name = f"{d.strftime('%d.%m')}—{end.strftime('%d.%m')}"
        sheets.append((name, d, end))
        d = end + timedelta(days=1)
    return sheets

def get_or_create_calendar_sheet(book, sheet_name, start, end):
    try:
        try:
            ws = book.worksheet(sheet_name)
            return ws
        except:
            pass
        # Создаём новый лист
        days = (end - start).days + 1
        ws = book.add_worksheet(sheet_name, 25, days + 1)
        # Заголовок
        dates = [(start + timedelta(days=i)).strftime("%d.%m") for i in range(days)]
        ws.append_row(["Номер"] + dates)
        # Номера
        room_nums = [n for n in ROOMS if n != 14]
        rows = []
        for num in room_nums:
            rows.append([f"№{num}"] + [""] * days)
        ws.append_rows(rows)
        # Красим все ячейки зелёным
        try:
            last_col = chr(ord('A') + days)
            ws.format(f"B2:{last_col}{len(room_nums)+1}", {"backgroundColor": COLOR_GREEN})
        except:
            pass
        return ws
    except Exception as e:
        logger.error(f"Calendar sheet error: {e}")
        return None

def update_calendar(room, guest, date_in_str, date_out_str, status):
    try:
        book = get_book()
        if not book:
            return
        dt_in = datetime.strptime(date_in_str, "%d.%m.%Y").date()
        dt_out = datetime.strptime(date_out_str, "%d.%m.%Y").date()
        color = COLOR_BLUE if status == "Бронь" else COLOR_RED
        sheet_list = get_calendar_sheets()
        for sheet_name, start, end in sheet_list:
            if dt_out <= start or dt_in > end:
                continue
            ws = get_or_create_calendar_sheet(book, sheet_name, start, end)
            if not ws:
                continue
            header = ws.row_values(1)
            all_vals = ws.get_all_values()
            room_row = None
            for i, r in enumerate(all_vals):
                if r and r[0] == f"№{room}":
                    room_row = i + 1
                    break
            if not room_row:
                continue
            d = max(dt_in, start)
            while d < dt_out and d <= end:
                date_str = d.strftime("%d.%m")
                if date_str in header:
                    col = header.index(date_str) + 1
                    ws.update_cell(room_row, col, guest)
                    cell_addr = ws.cell(room_row, col).address
                    ws.format(cell_addr, {"backgroundColor": color, "textFormat": {"bold": True}})
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
        sheet_list = get_calendar_sheets()
        for sheet_name, start, end in sheet_list:
            if dt_out <= start or dt_in > end:
                continue
            try:
                ws = book.worksheet(sheet_name)
            except:
                continue
            header = ws.row_values(1)
            all_vals = ws.get_all_values()
            room_row = None
            for i, r in enumerate(all_vals):
                if r and r[0] == f"№{room}":
                    room_row = i + 1
                    break
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

def get_state(uid): return user_states.get(uid, "menu")
def set_state(uid, s): user_states[uid] = s
def get_data(uid): return user_data.get(uid, {})
def update_data(uid, k, v):
    if uid not in user_data: user_data[uid] = {}
    user_data[uid][k] = v
def clear(uid):
    user_states.pop(uid, None)
    user_data.pop(uid, None)

# ===== КЛАВИАТУРЫ =====
def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔵 Бронь", callback_data="book"),
         InlineKeyboardButton("✅ Заселить", callback_data="checkin")],
        [InlineKeyboardButton("🚪 Выселить", callback_data="checkout"),
         InlineKeyboardButton("💰 Принять оплату", callback_data="payment")],
        [InlineKeyboardButton("🟢 Свободные", callback_data="free"),
         InlineKeyboardButton("🔴 Занятые", callback_data="occupied")],
        [InlineKeyboardButton("🔍 Инфо по номеру", callback_data="info"),
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

def rooms_kb(prefix, only_free=True):
    bookings = get_bookings()
    occupied = set()
    today = date.today()
    for b in bookings:
        s = get_room_status(b)
        if s in ["Занят","Надо убрать"]:
            occupied.add(str(b["Номер"]))
        elif s == "Бронь":
            # Показываем как занятый только если заезд сегодня или раньше
            try:
                dt_in = datetime.strptime(b["Заезд"], "%d.%m.%Y").date()
                if dt_in <= today:
                    occupied.add(str(b["Номер"]))
            except:
                occupied.add(str(b["Номер"]))
    kb = []
    row = []
    for num in ROOMS:
        if num == 14: continue
        if only_free and str(num) in occupied: continue
        icon = ""
        if not only_free:
            s = None
            for b in bookings:
                if str(b["Номер"]) == str(num):
                    s = get_room_status(b)
                    break
            icon = {"Занят":"🔴","Бронь":"🔵","Надо убрать":"🧹"}.get(s,"🟢")
        row.append(InlineKeyboardButton(f"{icon}№{num}", callback_data=f"{prefix}_{num}"))
        if len(row) == 4:
            kb.append(row)
            row = []
    if row: kb.append(row)
    kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
    return InlineKeyboardMarkup(kb)

def active_rooms_kb(prefix):
    bookings = get_bookings()
    kb = []
    row = []
    for b in bookings:
        s = get_room_status(b)
        if s in ["Занят","Бронь","Надо убрать"]:
            icon = {"Занят":"🔴","Бронь":"🔵","Надо убрать":"🧹"}.get(s,"")
            row.append(InlineKeyboardButton(f"{icon}№{b['Номер']}", callback_data=f"{prefix}_{b['Номер']}"))
            if len(row) == 4:
                kb.append(row)
                row = []
    if row: kb.append(row)
    kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
    return InlineKeyboardMarkup(kb)

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

    # МЕНЮ
    if d == "menu":
        clear(uid)
        await q.edit_message_text("🏠 *Управление квартирами*\n\nВыбери действие:", reply_markup=main_kb(), parse_mode="Markdown")

    # СВОБОДНЫЕ
    elif d == "free":
        bookings = get_bookings()
        occupied = {str(b["Номер"]) for b in bookings if get_room_status(b) in ["Занят","Бронь","Надо убрать"]}
        lines = [f"🟢 {info['name']}" for num, info in ROOMS.items() if num != 14 and str(num) not in occupied]
        text = ("🟢 *Свободные номера:*\n\n" + "\n".join(lines)) if lines else "❌ Все номера заняты"
        await q.edit_message_text(text, reply_markup=back_kb(), parse_mode="Markdown")

    # ЗАНЯТЫЕ
    elif d == "occupied":
        bookings = get_bookings()
        lines = []
        for b in bookings:
            s = get_room_status(b)
            if s in ["Занят","Бронь","Надо убрать"]:
                icon = {"Занят":"🔴","Бронь":"🔵","Надо убрать":"🧹"}.get(s,"")
                debt = int(b.get("Долг",0))
                ds = f" | Долг: {debt:,} сом ⚠️" if debt > 0 else " | ✅ Оплачено"
                lines.append(f"{icon} №{b['Номер']} — {b['Гость']} ({b['Людей']} чел.)\n    {b['Заезд']} → {b['Выезд']}{ds}")
        text = ("*Занятые и забронированные:*\n\n" + "\n\n".join(lines)) if lines else "✅ Все номера свободны!"
        await q.edit_message_text(text, reply_markup=back_kb(), parse_mode="Markdown")

    # БРОНЬ
    elif d == "book":
        user_data[uid] = {"status": "Бронь", "prepay": 0, "prepay_method": "—", "debt": 0, "price_day": 0, "total": 0, "nights": 0}
        set_state(uid, "ci_guest")
        await q.edit_message_text("🔵 *Бронирование*\n\nВыбери номер:", reply_markup=rooms_kb("ci_room"), parse_mode="Markdown")

    # ЗАСЕЛЕНИЕ
    elif d == "checkin":
        user_data[uid] = {"status": "Занят"}
        set_state(uid, "ci_guest")
        await q.edit_message_text("✅ *Заселение*\n\nВыбери свободный номер:", reply_markup=rooms_kb("ci_room"), parse_mode="Markdown")

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
        if data.get("status") == "Бронь":
            data = get_data(uid)
            data["total"] = data["total_suggested"]
            data["debt"] = data["total_suggested"]
            save_booking(data)
            clear(uid)
            await q.edit_message_text(
                f"🔵 *Бронь оформлена!*\n\n🏠 {ROOMS[data['room']]['name']}\n"
                f"👤 {data['guest']} ({data['people']} чел.)\n"
                f"📅 {data['date_in']} → {data['date_out']} ({data['nights']} н.)\n"
                f"💰 Итого: *{data['total_suggested']:,} сом*\n⚠️ Оплата при заселении",
                reply_markup=back_kb(), parse_mode="Markdown")
        else:
            set_state(uid, "ci_prepay")
            await q.edit_message_text(f"💰 Итого: *{data['total_suggested']:,} сом*\n\nСколько взял задаток?", parse_mode="Markdown")

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
        pay_text = "🎉 *Оплачено полностью!*" if debt == 0 else f"⚠️ *Долг: {debt:,} сом*"
        clear(uid)
        await q.edit_message_text(
            f"✅ *Заселение оформлено!*\n\n🏠 {ROOMS[data['room']]['name']}\n"
            f"👤 {data['guest']} ({data['people']} чел.)\n"
            f"📅 {data['date_in']} → {data['date_out']} ({data['nights']} н.)\n"
            f"━━━━━━━━━━━━\n💰 Итого: *{data['total']:,} сом*\n"
            f"✅ Задаток: *{data['prepay']:,} сом* ({method})\n{pay_text}",
            reply_markup=back_kb(), parse_mode="Markdown")

    # ВЫСЕЛЕНИЕ
    elif d == "checkout":
        bookings = get_bookings()
        active = [b for b in bookings if get_room_status(b) == "Занят"]
        if not active:
            await q.edit_message_text("Нет активных заселений.", reply_markup=back_kb())
        else:
            kb = []
            row = []
            for b in active:
                row.append(InlineKeyboardButton(f"🔴№{b['Номер']}", callback_data=f"co_room_{b['Номер']}"))
                if len(row) == 4: kb.append(row); row = []
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
        debt = int(booking.get("Долг",0))
        pay_text = f"⚠️ Долг: *{debt:,} сом*" if debt > 0 else "✅ Оплачено полностью"
        await q.edit_message_text(
            f"🚪 *Выселение №{num}*\n\n👤 {booking['Гость']} ({booking['Людей']} чел.)\n"
            f"📅 {booking['Заезд']} → {booking['Выезд']}\n━━━━━━━━━━━━\n"
            f"💰 Итого: *{int(booking['Итого']):,} сом*\n"
            f"✅ Задаток: *{int(booking['Задаток']):,} сом* ({booking.get('Способ задатка','—')})\n"
            f"💳 Доплата: *{int(booking.get('Доплата',0)):,} сом*\n{pay_text}\n\nПодтвердить?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Выселить", callback_data="co_confirm")],
                [InlineKeyboardButton("◀️ Меню", callback_data="menu")]
            ]), parse_mode="Markdown")

    elif d == "co_confirm":
        data = get_data(uid)
        booking = data["co_booking"]
        set_status(data["co_row"], "Надо убрать")
        clear(uid)
        await q.edit_message_text(f"✅ *№{booking['Номер']} выселен!*\n\n🧹 Нужна уборка!", reply_markup=back_kb(), parse_mode="Markdown")

    # ИНФО
    elif d == "info":
        bookings = get_bookings()
        status_map = {}
        for b in bookings:
            s = get_room_status(b)
            if s not in ["Убрано", "Отменён"]:
                n = str(b["Номер"])
                if n not in status_map:
                    status_map[n] = s
        kb = []
        row = []
        lines = []
        for num, info in ROOMS.items():
            if num == 14:
                continue
            s = status_map.get(str(num), "Свободен")
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

    elif d.startswith("info_room_"):
        num = int(d.split("_")[-1])
        room = ROOMS[num]
        bookings = get_bookings()
        room_bookings = []
        for b in bookings:
            if str(b.get("Номер")) == str(num) and b.get("Статус") not in ["Убрано", "Отменён"]:
                room_bookings.append(b)
        try:
            room_bookings.sort(key=lambda x: datetime.strptime(x["Заезд"], "%d.%m.%Y"))
        except:
            pass
        if room_bookings:
            lines2 = []
            for b in room_bookings:
                s = get_room_status(b)
                icon = icon_for(s)
                debt = int(b.get("Долг", 0))
                debt_str = f" | Долг: {debt:,} сом ⚠️" if debt > 0 else " | ✅ Оплачено"
                lines2.append(f"{icon} {b['Заезд']}→{b['Выезд']} — *{b['Гость']}* ({b['Людей']} чел.){debt_str}")
            text = f"🏠 *{room['name']}*\n\n" + "\n".join(lines2)
        else:
            text = f"🟢 *{room['name']}*\n\nНет броней — номер свободен"
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ Все номера", callback_data="info")]
        ]), parse_mode="Markdown")

    # ОПЛАТА
    elif d == "payment":
        bookings = get_bookings()
        with_debt = [b for b in bookings if get_room_status(b) in ["Занят","Бронь"] and int(b.get("Долг",0)) > 0]
        if not with_debt:
            await q.edit_message_text("✅ Все долги оплачены!", reply_markup=back_kb())
        else:
            kb = []
            row = []
            for b in with_debt:
                row.append(InlineKeyboardButton(f"№{b['Номер']} — {int(b['Долг']):,}с", callback_data=f"pay_room_{b['Номер']}"))
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
            f"💰 №{num} — {booking['Гость']}\n⚠️ Долг: *{int(booking['Долг']):,} сом*\n\nВведи сумму:",
            parse_mode="Markdown")

    elif d.startswith("pay_method_"):
        method = "💵 Наличка" if d == "pay_method_cash" else "💳 Карта"
        data = get_data(uid)
        new_debt = add_payment(data["pay_row"], data["pay_booking"], data["pay_amount"], method)
        pay_text = "🎉 Долг погашен!" if new_debt == 0 else f"⚠️ Остаток: *{new_debt:,} сом*"
        clear(uid)
        await q.edit_message_text(f"✅ Оплата принята!\n💳 {data['pay_amount']:,} сом ({method})\n{pay_text}",
            reply_markup=back_kb(), parse_mode="Markdown")

    # УБОРКА
    elif d == "cleaning":
        bookings = get_bookings()
        to_clean = [b for b in bookings if get_room_status(b) == "Надо убрать"]
        if not to_clean:
            await q.edit_message_text("✅ Все номера чистые!", reply_markup=back_kb())
        else:
            kb = []
            row = []
            for b in to_clean:
                row.append(InlineKeyboardButton(f"🧹№{b['Номер']}", callback_data=f"clean_{b['Номер']}"))
                if len(row) == 4: kb.append(row); row = []
            if row: kb.append(row)
            kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
            await q.edit_message_text("🧹 *Нужна уборка:*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("clean_"):
        num = int(d.split("_")[-1])
        row, booking = find_booking(num)
        if booking:
            set_status(row, "Убрано")
            clear_calendar(num, booking["Заезд"], booking["Выезд"])
        await q.edit_message_text(f"✅ *№{num} убран!*\n\n🟢 Готов к заселению.", reply_markup=back_kb(), parse_mode="Markdown")

    # ИЗМЕНИТЬ ДАННЫЕ
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
        icon = {"Занят":"🔴","Бронь":"🔵","Надо убрать":"🧹"}.get(s,"🟢")
        await q.edit_message_text(
            f"✏️ *{icon} №{num} — {booking['Гость']}*\n\n"
            f"📅 {booking['Заезд']} → {booking['Выезд']}\n"
            f"👥 {booking['Людей']} чел.\n"
            f"💰 Итого: {int(booking['Итого']):,} сом\n\n"
            f"Что хочешь изменить?",
            reply_markup=edit_fields_kb(), parse_mode="Markdown")

    elif d.startswith("ef_"):
        field = d[3:]
        field_names = {
            "guest": "имя гостя",
            "people": "количество людей",
            "date_in": "дату заезда (формат: 19.06)",
            "date_out": "дату выезда (формат: 21.06)",
            "total": "итоговую сумму",
            "prepay": "сумму задатка",
        }
        update_data(uid, "edit_field", field)
        if field == "status":
            set_state(uid, "edit_status")
            await q.edit_message_text("🔄 Выбери новый статус:", reply_markup=status_kb())
        else:
            set_state(uid, "edit_value")
            await q.edit_message_text(f"✏️ Введи новое {field_names.get(field, field)}:")

    elif d.startswith("es_"):
        new_status = d[3:]
        data = get_data(uid)
        row = data["edit_row"]
        set_status(row, new_status)
        booking = data["edit_booking"]
        clear(uid)
        await q.edit_message_text(
            f"✅ Статус №{booking['Номер']} изменён на *{new_status}*",
            reply_markup=back_kb(), parse_mode="Markdown")

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

    if state == "ci_guest":
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
            await update.message.reply_text("📅 Дата выезда? (например: 21.06)")
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
            data = get_data(uid)
            if data.get("status") == "Бронь":
                data["debt"] = total
                save_booking(data)
                clear(uid)
                await update.message.reply_text(
                    f"🔵 *Бронь оформлена!*\n\n🏠 {ROOMS[data['room']]['name']}\n"
                    f"👤 {data['guest']} ({data['people']} чел.)\n"
                    f"📅 {data['date_in']} → {data['date_out']}\n💰 Итого: *{total:,} сом*",
                    reply_markup=back_kb(), parse_mode="Markdown")
            else:
                set_state(uid, "ci_prepay")
                await update.message.reply_text(f"💰 Итого: *{total:,} сом*\n\nСколько взял задаток?", parse_mode="Markdown")
        except:
            await update.message.reply_text("Введи сумму числом")

    elif state == "ci_prepay":
        try:
            prepay = int(text.replace(" ","").replace(",",""))
            update_data(uid, "prepay", prepay)
            set_state(uid, "ci_prepay_method")
            await update.message.reply_text(f"✅ Задаток: *{prepay:,} сом*\n\nКак оплатил?", reply_markup=pay_method_kb("ci_prepay"), parse_mode="Markdown")
        except:
            await update.message.reply_text("Введи сумму числом")

    elif state == "pay_amount":
        try:
            amount = int(text.replace(" ","").replace(",",""))
            update_data(uid, "pay_amount", amount)
            set_state(uid, "pay_method")
            await update.message.reply_text(f"💳 Сумма: *{amount:,} сом*\n\nКак оплатил?", reply_markup=pay_method_kb("pay_method"), parse_mode="Markdown")
        except:
            await update.message.reply_text("Введи сумму числом")

    elif state == "edit_value":
        data = get_data(uid)
        field = data.get("edit_field")
        row = data["edit_row"]
        booking = data["edit_booking"]

        col_map = {"guest": 3, "people": 4, "date_in": 5, "date_out": 6, "total": 9, "prepay": 10}
        col = col_map.get(field)

        try:
            if field in ["total", "prepay"]:
                val = int(text.replace(" ","").replace(",",""))
            elif field == "people":
                val = int(text)
            elif field in ["date_in", "date_out"]:
                t = text if len(text) > 5 else text + f".{date.today().year}"
                datetime.strptime(t, "%d.%m.%Y")
                val = t
                # Обновляем календарь
                clear_calendar(booking["Номер"], booking["Заезд"], booking["Выезд"])
                new_date_in = val if field == "date_in" else booking["Заезд"]
                new_date_out = val if field == "date_out" else booking["Выезд"]
                update_calendar(booking["Номер"], booking["Гость"], new_date_in, new_date_out, get_room_status(booking))
            else:
                val = text
                if field == "guest":
                    clear_calendar(booking["Номер"], booking["Заезд"], booking["Выезд"])
                    update_calendar(booking["Номер"], val, booking["Заезд"], booking["Выезд"], get_room_status(booking))

            if col:
                update_cell_ws(row, col, val)

            field_names = {"guest":"Имя","people":"Людей","date_in":"Дата заезда","date_out":"Дата выезда","total":"Итого","prepay":"Задаток"}
            clear(uid)
            await update.message.reply_text(
                f"✅ *{field_names.get(field, field)}* изменено на *{val}*",
                reply_markup=back_kb(), parse_mode="Markdown")
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
