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

# ===== GOOGLE SHEETS =====
def get_client():
    try:
        import gspread
        from oauth2client.service_account import ServiceAccountCredentials
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        google_creds = os.environ.get("GOOGLE_CREDS")
        if google_creds:
            creds_dict = json.loads(google_creds)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
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
        except:
            ws = book.add_worksheet("Бронирования", 1000, 17)
            ws.append_row(["ID","Номер","Гость","Людей","Заезд","Выезд","Ночей","Цена/сутки","Итого","Задаток","Способ задатка","Доплата","Способ доплаты","Долг","Статус оплаты","Статус","Дата записи"])
            return ws
    except Exception as e:
        logger.error(f"Sheets error: {e}")
        return None

def get_calendar_ws():
    book = get_book()
    if not book:
        return None
    try:
        try:
            return book.worksheet("Календарь")
        except:
            return create_calendar(book)
    except Exception as e:
        logger.error(f"Calendar error: {e}")
        return None

def create_calendar(book):
    try:
        ws = book.add_worksheet("Календарь", 30, 200)
        # Даты с 16 июня по 31 августа 2026
        start = date(2026, 6, 16)
        end = date(2026, 8, 31)
        dates = []
        d = start
        while d <= end:
            dates.append(d)
            d += timedelta(days=1)

        # Заголовок - даты
        header = ["Номер"] + [d.strftime("%d.%m") for d in dates]
        ws.append_row(header)

        # Номера
        room_nums = [n for n in ROOMS if n != 14]
        for num in room_nums:
            ws.append_row([f"№{num}"] + [""] * len(dates))

        return ws
    except Exception as e:
        logger.error(f"Create calendar error: {e}")
        return None

def update_calendar(guest, date_in_str, date_out_str):
    try:
        ws = get_calendar_ws()
        if not ws:
            return
        
        # Получаем заголовок с датами
        header = ws.row_values(1)
        
        dt_in = datetime.strptime(date_in_str, "%d.%m.%Y").date()
        dt_out = datetime.strptime(date_out_str, "%d.%m.%Y").date()
        
        # Находим строку номера
        all_values = ws.get_all_values()
        room_row = None
        for i, row in enumerate(all_values):
            if row and row[0] == f"№{guest['room']}":
                room_row = i + 1
                break
        
        if not room_row:
            return

        # Заполняем ячейки
        updates = []
        d = dt_in
        while d < dt_out:
            date_str = d.strftime("%d.%m")
            if date_str in header:
                col = header.index(date_str) + 1
                updates.append({
                    'range': ws.cell(room_row, col).address,
                    'values': [[guest['guest']]]
                })
            d += timedelta(days=1)
        
        if updates:
            for u in updates:
                ws.update(u['range'], u['values'])
    except Exception as e:
        logger.error(f"Calendar update error: {e}")

def clear_calendar(room, date_in_str, date_out_str):
    try:
        ws = get_calendar_ws()
        if not ws:
            return
        header = ws.row_values(1)
        dt_in = datetime.strptime(date_in_str, "%d.%m.%Y").date()
        dt_out = datetime.strptime(date_out_str, "%d.%m.%Y").date()
        all_values = ws.get_all_values()
        room_row = None
        for i, row in enumerate(all_values):
            if row and row[0] == f"№{room}":
                room_row = i + 1
                break
        if not room_row:
            return
        d = dt_in
        while d < dt_out:
            date_str = d.strftime("%d.%m")
            if date_str in header:
                col = header.index(date_str) + 1
                ws.update_cell(room_row, col, "")
            d += timedelta(days=1)
    except Exception as e:
        logger.error(f"Calendar clear error: {e}")

def get_bookings():
    ws = get_ws()
    if not ws:
        return []
    try:
        return ws.get_all_records()
    except:
        return []

def get_room_status(booking):
    """Определяем статус номера по датам"""
    try:
        today = date.today()
        dt_in = datetime.strptime(booking["Заезд"], "%d.%m.%Y").date()
        dt_out = datetime.strptime(booking["Выезд"], "%d.%m.%Y").date()
        status = booking.get("Статус", "")
        
        if status == "Уборка":
            return "Уборка"
        elif status == "Отменён":
            return "Свободен"
        elif today < dt_in:
            return "Бронь"
        elif dt_in <= today < dt_out:
            return "Занят"
        elif today >= dt_out:
            return "Уборка"
        return status
    except:
        return booking.get("Статус", "")

def find_booking(room_num):
    records = get_bookings()
    for i, r in enumerate(records):
        if str(r.get("Номер")) == str(room_num) and r.get("Статус") not in ["Убран", "Отменён"]:
            return i + 2, r
    return None, None

def save_booking(data):
    ws = get_ws()
    if not ws:
        return
    bid = len(ws.get_all_records()) + 1
    pay_status = "Оплачено ✅" if data["debt"] == 0 else "Долг ⚠️"
    status = data.get("status", "Бронь")
    ws.append_row([bid, data["room"], data["guest"], data["people"],
        data["date_in"], data["date_out"], data["nights"], data["price_day"],
        data["total"], data["prepay"], data.get("prepay_method", "—"),
        0, "—", data["debt"], pay_status, status,
        datetime.now().strftime("%d.%m.%Y %H:%M")])
    # Обновляем календарь
    update_calendar(data, data["date_in"], data["date_out"])

def set_status(row, status):
    ws = get_ws()
    if ws:
        ws.update_cell(row, 16, status)

def add_payment(row, booking, amount, method):
    ws = get_ws()
    if not ws:
        return 0
    new_extra = int(booking.get("Доплата", 0)) + amount
    new_debt = max(0, int(booking.get("Долг", 0)) - amount)
    pay_status = "Оплачено ✅" if new_debt == 0 else "Долг ⚠️"
    ws.update_cell(row, 12, new_extra)
    ws.update_cell(row, 13, method)
    ws.update_cell(row, 14, new_debt)
    ws.update_cell(row, 15, pay_status)
    return new_debt

# ===== СОСТОЯНИЯ =====
user_states = {}
user_data = {}

def get_state(uid): return user_states.get(uid, "menu")
def set_state(uid, state): user_states[uid] = state
def get_data(uid): return user_data.get(uid, {})
def update_data(uid, key, val):
    if uid not in user_data: user_data[uid] = {}
    user_data[uid][key] = val
def clear(uid):
    user_states.pop(uid, None)
    user_data.pop(uid, None)

# ===== КЛАВИАТУРЫ =====
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔵 Бронь", callback_data="book"),
         InlineKeyboardButton("✅ Заселить", callback_data="checkin")],
        [InlineKeyboardButton("🚪 Выселить", callback_data="checkout"),
         InlineKeyboardButton("💰 Принять оплату", callback_data="payment")],
        [InlineKeyboardButton("🟢 Свободные", callback_data="free"),
         InlineKeyboardButton("🔴 Занятые", callback_data="occupied")],
        [InlineKeyboardButton("🔍 Инфо по номеру", callback_data="info"),
         InlineKeyboardButton("🧹 Уборка", callback_data="cleaning")],
    ])

def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="menu")]])

def free_rooms_kb(prefix):
    bookings = get_bookings()
    occupied = set()
    for b in bookings:
        s = get_room_status(b)
        if s in ["Занят", "Бронь", "Уборка"]:
            occupied.add(str(b["Номер"]))
    kb = []
    row = []
    for num in ROOMS:
        if num == 14: continue
        if str(num) not in occupied:
            row.append(InlineKeyboardButton(f"№{num}", callback_data=f"{prefix}_{num}"))
            if len(row) == 4:
                kb.append(row)
                row = []
    if row: kb.append(row)
    kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
    return InlineKeyboardMarkup(kb)

def active_rooms_kb(prefix, statuses=["Занят", "Бронь"]):
    bookings = get_bookings()
    kb = []
    row = []
    for b in bookings:
        s = get_room_status(b)
        if s in statuses:
            icon = "🔴" if s == "Занят" else "🔵"
            row.append(InlineKeyboardButton(f"{icon}№{b['Номер']}", callback_data=f"{prefix}_{b['Номер']}"))
            if len(row) == 4:
                kb.append(row)
                row = []
    if row: kb.append(row)
    kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
    return InlineKeyboardMarkup(kb)

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

def status_icon(s):
    return {"Занят": "🔴", "Бронь": "🔵", "Уборка": "🧹", "Убран": "🟢"}.get(s, "🟢")

# ===== ХЭНДЛЕРЫ =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    clear(uid)
    await update.message.reply_text("🏠 *Управление квартирами*\n\nВыбери действие:", reply_markup=main_keyboard(), parse_mode="Markdown")

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    d = q.data

    if d == "menu":
        clear(uid)
        await q.edit_message_text("🏠 *Управление квартирами*\n\nВыбери действие:", reply_markup=main_keyboard(), parse_mode="Markdown")

    elif d == "free":
        bookings = get_bookings()
        occupied = set()
        for b in bookings:
            s = get_room_status(b)
            if s in ["Занят", "Бронь", "Уборка"]:
                occupied.add(str(b["Номер"]))
        lines = [f"🟢 {info['name']}" for num, info in ROOMS.items() if num != 14 and str(num) not in occupied]
        text = ("🟢 *Свободные номера:*\n\n" + "\n".join(lines)) if lines else "❌ Все номера заняты"
        await q.edit_message_text(text, reply_markup=back_kb(), parse_mode="Markdown")

    elif d == "occupied":
        bookings = get_bookings()
        lines = []
        for b in bookings:
            s = get_room_status(b)
            if s in ["Занят", "Бронь", "Уборка"]:
                icon = status_icon(s)
                debt = int(b.get("Долг", 0))
                ds = f" | Долг: {debt:,} сом ⚠️" if debt > 0 else " | ✅ Оплачено"
                lines.append(f"{icon} №{b['Номер']} — {b['Гость']} ({b['Людей']} чел.)\n    {b['Заезд']} → {b['Выезд']}{ds}")
        text = ("*Занятые и забронированные:*\n\n" + "\n\n".join(lines)) if lines else "✅ Все номера свободны!"
        await q.edit_message_text(text, reply_markup=back_kb(), parse_mode="Markdown")

    # БРОНЬ
    elif d == "book":
        set_state(uid, "book_guest")
        user_data[uid] = {"status": "Бронь", "prepay": 0, "prepay_method": "—", "debt": 0, "price_day": 0, "total": 0, "nights": 0}
        await q.edit_message_text("🔵 *Бронирование*\n\nВыбери номер:", reply_markup=free_rooms_kb("ci_room"), parse_mode="Markdown")

    # ЗАСЕЛЕНИЕ
    elif d == "checkin":
        set_state(uid, "ci_room")
        user_data[uid] = {"status": "Занят"}
        await q.edit_message_text("✅ *Заселение*\n\nВыбери свободный номер:", reply_markup=free_rooms_kb("ci_room"), parse_mode="Markdown")

    elif d.startswith("ci_room_"):
        num = int(d.split("_")[-1])
        update_data(uid, "room", num)
        state = get_state(uid)
        if state == "book_guest":
            pass
        set_state(uid, "ci_guest")
        await q.edit_message_text(f"*{ROOMS[num]['name']}*\n\nВведи имя гостя:", parse_mode="Markdown")

    elif d.startswith("ci_price_"):
        if d == "ci_price_custom":
            set_state(uid, "ci_price_custom")
            await q.edit_message_text("✏️ Введи цену за сутки с 1 человека:")
        else:
            price = int(d.split("_")[-1])
            await calc_total(q, uid, price)

    elif d == "ci_total_ok":
        data = get_data(uid)
        update_data(uid, "total", data["total_suggested"])
        status = data.get("status", "Занят")
        if status == "Бронь":
            # Для брони сразу сохраняем без оплаты
            data = get_data(uid)
            data["total"] = data["total_suggested"]
            data["prepay"] = 0
            data["prepay_method"] = "—"
            data["debt"] = data["total_suggested"]
            save_booking(data)
            clear(uid)
            await q.edit_message_text(
                f"🔵 *Бронь оформлена!*\n\n"
                f"🏠 {ROOMS[data['room']]['name']}\n"
                f"👤 {data['guest']} ({data['people']} чел.)\n"
                f"📅 {data['date_in']} → {data['date_out']} ({data['nights']} н.)\n"
                f"💰 Итого: *{data['total_suggested']:,} сом*\n"
                f"⚠️ Оплата при заселении",
                reply_markup=back_kb(), parse_mode="Markdown")
        else:
            await q.edit_message_text(f"💰 Итого: *{data['total_suggested']:,} сом*\n\nСколько взял задаток?", parse_mode="Markdown")
            set_state(uid, "ci_prepay")

    elif d == "ci_total_custom":
        set_state(uid, "ci_total_custom")
        await q.edit_message_text("✏️ Введи итоговую сумму:")

    elif d.startswith("ci_prepay_"):
        method = "💵 Наличка" if d == "ci_prepay_cash" else "💳 Карта"
        data = get_data(uid)
        data["prepay_method"] = method
        total = data["total"]
        prepay = data["prepay"]
        debt = max(0, total - prepay)
        data["debt"] = debt
        save_booking(data)
        pay_text = "🎉 *Оплачено полностью!*" if debt == 0 else f"⚠️ *Долг: {debt:,} сом*"
        clear(uid)
        await q.edit_message_text(
            f"✅ *Заселение оформлено!*\n\n"
            f"🏠 {ROOMS[data['room']]['name']}\n"
            f"👤 {data['guest']} ({data['people']} чел.)\n"
            f"📅 {data['date_in']} → {data['date_out']} ({data['nights']} н.)\n"
            f"━━━━━━━━━━━━\n"
            f"💰 Итого: *{total:,} сом*\n"
            f"✅ Задаток: *{prepay:,} сом* ({method})\n"
            f"{pay_text}",
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
                if len(row) == 4:
                    kb.append(row)
                    row = []
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
        await q.edit_message_text(
            f"🚪 *Выселение №{num}*\n\n"
            f"👤 {booking['Гость']} ({booking['Людей']} чел.)\n"
            f"📅 {booking['Заезд']} → {booking['Выезд']}\n"
            f"━━━━━━━━━━━━\n"
            f"💰 Итого: *{int(booking['Итого']):,} сом*\n"
            f"✅ Задаток: *{int(booking['Задаток']):,} сом* ({booking.get('Способ задатка','—')})\n"
            f"💳 Доплата: *{int(booking.get('Доплата',0)):,} сом*\n"
            f"{pay_text}\n\nПодтвердить выселение?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Выселить", callback_data="co_confirm")],
                [InlineKeyboardButton("◀️ Меню", callback_data="menu")]
            ]), parse_mode="Markdown")

    elif d == "co_confirm":
        data = get_data(uid)
        set_status(data["co_row"], "Уборка")
        booking = data["co_booking"]
        clear(uid)
        await q.edit_message_text(
            f"✅ *№{booking['Номер']} выселен!*\n\n🧹 Нужна уборка!",
            reply_markup=back_kb(), parse_mode="Markdown")

    # ИНФО
    elif d == "info":
        bookings = get_bookings()
        status_map = {}
        for b in bookings:
            s = get_room_status(b)
            if s not in ["Убран", "Свободен"]:
                status_map[str(b["Номер"])] = s
        kb = []
        row = []
        for num in ROOMS:
            if num == 14: continue
            s = status_map.get(str(num), "Свободен")
            icon = status_icon(s)
            row.append(InlineKeyboardButton(f"{icon}№{num}", callback_data=f"info_room_{num}"))
            if len(row) == 4:
                kb.append(row)
                row = []
        if row: kb.append(row)
        kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
        await q.edit_message_text("🔍 *Инфо по номеру*\n\n🟢 Своб  🔵 Бронь  🔴 Занят  🧹 Уборка",
            reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("info_room_"):
        num = int(d.split("_")[-1])
        _, booking = find_booking(num)
        if booking:
            s = get_room_status(booking)
            icon = status_icon(s)
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
                if len(row) == 2:
                    kb.append(row)
                    row = []
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
            f"💰 №{num} — {booking['Гость']}\n⚠️ Долг: *{int(booking['Долг']):,} сом*\n\nВведи сумму оплаты:",
            parse_mode="Markdown")

    elif d.startswith("pay_method_"):
        method = "💵 Наличка" if d == "pay_method_cash" else "💳 Карта"
        data = get_data(uid)
        new_debt = add_payment(data["pay_row"], data["pay_booking"], data["pay_amount"], method)
        pay_text = "🎉 Долг погашен!" if new_debt == 0 else f"⚠️ Остаток: *{new_debt:,} сом*"
        clear(uid)
        await q.edit_message_text(
            f"✅ Оплата принята!\n💳 {data['pay_amount']:,} сом ({method})\n{pay_text}",
            reply_markup=back_kb(), parse_mode="Markdown")

    # УБОРКА
    elif d == "cleaning":
        bookings = get_bookings()
        to_clean = [b for b in bookings if get_room_status(b) == "Уборка"]
        if not to_clean:
            await q.edit_message_text("✅ Все номера чистые!", reply_markup=back_kb())
        else:
            kb = []
            row = []
            for b in to_clean:
                row.append(InlineKeyboardButton(f"🧹№{b['Номер']}", callback_data=f"clean_{b['Номер']}"))
                if len(row) == 4:
                    kb.append(row)
                    row = []
            if row: kb.append(row)
            kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
            await q.edit_message_text("🧹 *Нужна уборка:*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("clean_"):
        num = int(d.split("_")[-1])
        row, booking = find_booking(num)
        if booking:
            set_status(row, "Убран")
        await q.edit_message_text(f"✅ *№{num} убран!*\n\n🟢 Готов к заселению.", reply_markup=back_kb(), parse_mode="Markdown")

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
    text = (f"💰 *Расчёт:*\n\n"
        f"👥 {people} чел × {price_per_person:,} = *{price_day:,} сом/сутки*\n"
        f"🌙 {nights} ночей\n"
        f"━━━━━━━━━━━━\n"
        f"💰 *Итого: {total:,} сом*\n\nВерно?")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Да — {total:,} сом", callback_data="ci_total_ok")],
        [InlineKeyboardButton("✏️ Другая сумма", callback_data="ci_total_custom")],
    ])
    await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = get_state(uid)
    text = update.message.text.strip()

    if state in ["ci_guest", "book_guest"]:
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
            data = get_data(uid)
            dt_in = datetime.strptime(data["date_in"], "%d.%m.%Y")
            nights = (dt_out - dt_in).days
            if nights <= 0:
                await update.message.reply_text("Дата выезда должна быть позже!")
                return
            update_data(uid, "date_out", dt_out.strftime("%d.%m.%Y"))
            update_data(uid, "nights", nights)
            set_state(uid, "ci_price")
            await update.message.reply_text(
                f"🌙 Ночей: *{nights}*\n\nЦена за сутки с 1 человека:",
                reply_markup=price_kb(), parse_mode="Markdown")
        except:
            await update.message.reply_text("Неверный формат. Введи как: 21.06")

    elif state == "ci_price_custom":
        try:
            price = int(text.replace(" ","").replace(",",""))
            await calc_total_msg(update, uid, price)
        except:
            await update.message.reply_text("Введи сумму числом")

    elif state == "ci_total_custom":
        try:
            total = int(text.replace(" ","").replace(",",""))
            update_data(uid, "total", total)
            data = get_data(uid)
            if data.get("status") == "Бронь":
                data["prepay"] = 0
                data["prepay_method"] = "—"
                data["debt"] = total
                save_booking(data)
                clear(uid)
                await update.message.reply_text(
                    f"🔵 *Бронь оформлена!*\n\n"
                    f"🏠 {ROOMS[data['room']]['name']}\n"
                    f"👤 {data['guest']} ({data['people']} чел.)\n"
                    f"📅 {data['date_in']} → {data['date_out']}\n"
                    f"💰 Итого: *{total:,} сом*",
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
            await update.message.reply_text(
                f"✅ Задаток: *{prepay:,} сом*\n\nКак оплатил?",
                reply_markup=pay_method_kb("ci_prepay"), parse_mode="Markdown")
        except:
            await update.message.reply_text("Введи сумму числом")

    elif state == "pay_amount":
        try:
            amount = int(text.replace(" ","").replace(",",""))
            update_data(uid, "pay_amount", amount)
            set_state(uid, "pay_method")
            await update.message.reply_text(
                f"💳 Сумма: *{amount:,} сом*\n\nКак оплатил?",
                reply_markup=pay_method_kb("pay_method"), parse_mode="Markdown")
        except:
            await update.message.reply_text("Введи сумму числом")

    else:
        await update.message.reply_text("🏠 Нажми /start")

async def calc_total_msg(update, uid, price_per_person):
    data = get_data(uid)
    people = data["people"]
    nights = data["nights"]
    price_day = price_per_person * people
    total = price_day * nights
    update_data(uid, "price_per_person", price_per_person)
    update_data(uid, "price_day", price_day)
    update_data(uid, "total_suggested", total)
    set_state(uid, "ci_total_confirm")
    text = (f"💰 *Расчёт:*\n\n"
        f"👥 {people} чел × {price_per_person:,} = *{price_day:,} сом/сутки*\n"
        f"🌙 {nights} ночей\n"
        f"━━━━━━━━━━━━\n"
        f"💰 *Итого: {total:,} сом*\n\nВерно?")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Да — {total:,} сом", callback_data="ci_total_ok")],
        [InlineKeyboardButton("✏️ Другая сумма", callback_data="ci_total_custom")],
    ])
    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

# ===== ВЕБ СЕРВЕР =====
class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *a): pass

def run_web():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), Health).serve_forever()

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
