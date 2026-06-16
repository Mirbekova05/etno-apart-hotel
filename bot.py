import os
import logging
import threading
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, date
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
def get_ws():
    try:
        import gspread
        from oauth2client.service_account import ServiceAccountCredentials
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, scope)
        client = gspread.authorize(creds)
        book = client.open_by_key(SHEET_ID)
        try:
            return book.worksheet("Бронирования")
        except:
            ws = book.add_worksheet("Бронирования", 1000, 17)
            ws.append_row(["ID","Номер","Гость","Людей","Заезд","Выезд","Ночей","Цена/сутки","Итого","Задаток","Способ задатка","Доплата","Способ доплаты","Долг","Статус оплаты","Статус номера","Дата записи"])
            return ws
    except Exception as e:
        logger.error(f"Sheets error: {e}")
        return None

def get_bookings():
    ws = get_ws()
    if not ws:
        return []
    try:
        return ws.get_all_records()
    except:
        return []

def find_booking(room_num):
    records = get_bookings()
    for i, r in enumerate(records):
        if str(r.get("Номер")) == str(room_num) and r.get("Статус номера") in ["Занят", "Уборка"]:
            return i + 2, r
    return None, None

def save_booking(data):
    ws = get_ws()
    if not ws:
        return
    bid = len(ws.get_all_records()) + 1
    pay_status = "Оплачено ✅" if data["debt"] == 0 else "Долг ⚠️"
    ws.append_row([bid, data["room"], data["guest"], data["people"],
        data["date_in"], data["date_out"], data["nights"], data["price_day"],
        data["total"], data["prepay"], data["prepay_method"],
        0, "—", data["debt"], pay_status, "Занят",
        datetime.now().strftime("%d.%m.%Y %H:%M")])

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

# ===== СОСТОЯНИЯ ПОЛЬЗОВАТЕЛЕЙ =====
user_states = {}
user_data = {}

def get_state(uid):
    return user_states.get(uid, "menu")

def set_state(uid, state, data=None):
    user_states[uid] = state
    if data:
        user_data[uid] = data
    elif uid not in user_data:
        user_data[uid] = {}

def get_data(uid):
    return user_data.get(uid, {})

def update_data(uid, key, val):
    if uid not in user_data:
        user_data[uid] = {}
    user_data[uid][key] = val

def clear(uid):
    user_states.pop(uid, None)
    user_data.pop(uid, None)

# ===== КЛАВИАТУРЫ =====
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Заселить", callback_data="checkin"),
         InlineKeyboardButton("🚪 Выселить", callback_data="checkout")],
        [InlineKeyboardButton("🟢 Свободные", callback_data="free"),
         InlineKeyboardButton("🔴 Занятые", callback_data="occupied")],
        [InlineKeyboardButton("🔍 Инфо по номеру", callback_data="info"),
         InlineKeyboardButton("💰 Принять оплату", callback_data="payment")],
        [InlineKeyboardButton("🧹 Уборка", callback_data="cleaning")],
    ])

def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="menu")]])

def rooms_kb(occupied_set, prefix):
    kb = []
    row = []
    for num in ROOMS:
        if num == 14:
            continue
        if str(num) not in occupied_set:
            row.append(InlineKeyboardButton(f"№{num}", callback_data=f"{prefix}_{num}"))
            if len(row) == 4:
                kb.append(row)
                row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
    return InlineKeyboardMarkup(kb)

def occupied_rooms_kb(active, prefix):
    kb = []
    row = []
    for b in active:
        row.append(InlineKeyboardButton(f"№{b['Номер']}", callback_data=f"{prefix}_{b['Номер']}"))
        if len(row) == 4:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
    return InlineKeyboardMarkup(kb)

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

    # МЕНЮ
    if d == "menu":
        clear(uid)
        await q.edit_message_text("🏠 *Управление квартирами*\n\nВыбери действие:", reply_markup=main_keyboard(), parse_mode="Markdown")

    # СВОБОДНЫЕ
    elif d == "free":
        bookings = get_bookings()
        occupied = {str(b["Номер"]) for b in bookings if b.get("Статус номера") in ["Занят","Уборка"]}
        lines = [f"🟢 {info['name']}" for num, info in ROOMS.items() if num != 14 and str(num) not in occupied]
        text = ("🟢 *Свободные номера:*\n\n" + "\n".join(lines)) if lines else "❌ Все номера заняты"
        await q.edit_message_text(text, reply_markup=back_kb(), parse_mode="Markdown")

    # ЗАНЯТЫЕ
    elif d == "occupied":
        bookings = get_bookings()
        active = [b for b in bookings if b.get("Статус номера") in ["Занят","Уборка"]]
        if active:
            lines = []
            for b in active:
                icon = "🔴" if b.get("Статус номера") == "Занят" else "🧹"
                debt = int(b.get("Долг", 0))
                ds = f" | Долг: {debt:,} сом ⚠️" if debt > 0 else " | ✅ Оплачено"
                lines.append(f"{icon} №{b['Номер']} — {b['Гость']} ({b['Людей']} чел.)\n    Выезд: {b['Выезд']}{ds}")
            text = "🔴 *Занятые номера:*\n\n" + "\n\n".join(lines)
        else:
            text = "✅ Все номера свободны!"
        await q.edit_message_text(text, reply_markup=back_kb(), parse_mode="Markdown")

    # ЗАСЕЛЕНИЕ — выбор комнаты
    elif d == "checkin":
        bookings = get_bookings()
        occupied = {str(b["Номер"]) for b in bookings if b.get("Статус номера") in ["Занят","Уборка"]}
        set_state(uid, "ci_guest")
        await q.edit_message_text("✅ *Заселение*\n\nВыбери номер:", reply_markup=rooms_kb(occupied, "ci_room"), parse_mode="Markdown")

    elif d.startswith("ci_room_"):
        num = int(d.split("_")[-1])
        update_data(uid, "room", num)
        set_state(uid, "ci_guest")
        await q.edit_message_text(f"✅ *{ROOMS[num]['name']}*\n\nВведи имя гостя:", parse_mode="Markdown")

    # ЦЕНА
    elif d.startswith("ci_price_"):
        if d == "ci_price_custom":
            set_state(uid, "ci_price_custom")
            await q.edit_message_text("✏️ Введи цену за сутки с 1 человека (в сомах):")
        else:
            price = int(d.split("_")[-1])
            await handle_price(q, uid, price)

    # ИТОГО
    elif d == "ci_total_ok":
        data = get_data(uid)
        update_data(uid, "total", data["total_suggested"])
        set_state(uid, "ci_prepay")
        await q.edit_message_text(f"💰 Итого: *{data['total_suggested']:,} сом*\n\nСколько взял задаток?", parse_mode="Markdown")

    elif d == "ci_total_custom":
        set_state(uid, "ci_total_custom")
        await q.edit_message_text("✏️ Введи итоговую сумму:")

    # СПОСОБ ОПЛАТЫ ЗАДАТКА
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
            f"👤 Гость: *{data['guest']}*\n"
            f"👥 Людей: *{data['people']}*\n"
            f"📅 {data['date_in']} → {data['date_out']} ({data['nights']} ночей)\n"
            f"━━━━━━━━━━━━\n"
            f"💰 Итого: *{total:,} сом*\n"
            f"✅ Задаток: *{prepay:,} сом* ({method})\n"
            f"{pay_text}",
            reply_markup=back_kb(), parse_mode="Markdown")

    # ВЫСЕЛЕНИЕ
    elif d == "checkout":
        bookings = get_bookings()
        active = [b for b in bookings if b.get("Статус номера") == "Занят"]
        if not active:
            await q.edit_message_text("Нет активных заселений.", reply_markup=back_kb())
        else:
            set_state(uid, "checkout_room")
            await q.edit_message_text("🚪 *Выселение*\n\nВыбери номер:", reply_markup=occupied_rooms_kb(active, "co_room"), parse_mode="Markdown")

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
            f"{pay_text}\n\n"
            f"Подтвердить выселение?",
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
        occupied = {}
        for b in bookings:
            if b.get("Статус номера") in ["Занят","Уборка"]:
                occupied[str(b["Номер"])] = b.get("Статус номера")
        kb = []
        row = []
        for num in ROOMS:
            if num == 14:
                continue
            s = occupied.get(str(num), "free")
            icon = "🔴" if s == "Занят" else "🧹" if s == "Уборка" else "🟢"
            row.append(InlineKeyboardButton(f"{icon}№{num}", callback_data=f"info_room_{num}"))
            if len(row) == 4:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
        kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
        await q.edit_message_text("🔍 *Инфо по номеру*\n\n🟢 Свободен  🔴 Занят  🧹 Уборка",
            reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("info_room_"):
        num = int(d.split("_")[-1])
        _, booking = find_booking(num)
        if booking:
            debt = int(booking.get("Долг", 0))
            s = booking.get("Статус номера","")
            icon = "🧹 Уборка" if s == "Уборка" else "🔴 Занят"
            pay_text = "🎉 Оплачено!" if debt == 0 else f"⚠️ Долг: *{debt:,} сом*"
            text = (f"{icon} — *{ROOMS[num]['name']}*\n\n"
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
        with_debt = [b for b in bookings if b.get("Статус номера") == "Занят" and int(b.get("Долг",0)) > 0]
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
            if row:
                kb.append(row)
            kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
            set_state(uid, "pay_room")
            await q.edit_message_text("💰 *Принять оплату*\n\nНомера с долгом:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("pay_room_"):
        num = int(d.split("_")[-1])
        row, booking = find_booking(num)
        update_data(uid, "pay_row", row)
        update_data(uid, "pay_booking", booking)
        set_state(uid, "pay_amount")
        await q.edit_message_text(
            f"💰 №{num} — {booking['Гость']}\n"
            f"⚠️ Долг: *{int(booking['Долг']):,} сом*\n\nВведи сумму оплаты:",
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
        to_clean = [b for b in bookings if b.get("Статус номера") == "Уборка"]
        if not to_clean:
            await q.edit_message_text("✅ Все номера чистые!", reply_markup=back_kb())
        else:
            kb = []
            row = []
            for b in to_clean:
                row.append(InlineKeyboardButton(f"🧹 №{b['Номер']}", callback_data=f"clean_{b['Номер']}"))
                if len(row) == 4:
                    kb.append(row)
                    row = []
            if row:
                kb.append(row)
            kb.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
            await q.edit_message_text("🧹 *Нужна уборка:*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif d.startswith("clean_"):
        num = int(d.split("_")[-1])
        row, booking = find_booking(num)
        if booking:
            set_status(row, "Убран")
        await q.edit_message_text(f"✅ *№{num} убран!*\n\n🟢 Готов к заселению.", reply_markup=back_kb(), parse_mode="Markdown")

async def handle_price(q, uid, price):
    data = get_data(uid)
    data["price_per_person"] = price
    people = data["people"]
    nights = data["nights"]
    price_day = price * people
    total = price_day * nights
    data["price_day"] = price_day
    data["total_suggested"] = total
    set_state(uid, "ci_total_confirm")
    text = (f"💰 *Расчёт:*\n\n"
        f"👥 {people} чел × {price:,} = *{price_day:,} сом/сутки*\n"
        f"🌙 {nights} ночей\n"
        f"━━━━━━━━━━━━\n"
        f"💰 *Итого: {total:,} сом*\n\nВерно?")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Да — {total:,} сом", callback_data="ci_total_ok")],
        [InlineKeyboardButton("✏️ Другая сумма", callback_data="ci_total_custom")],
    ])
    if hasattr(q, 'edit_message_text'):
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await q.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = get_state(uid)
    text = update.message.text.strip()

    if state == "ci_guest":
        update_data(uid, "guest", text)
        set_state(uid, "ci_people")
        await update.message.reply_text("👥 Сколько человек заселяется?")

    elif state == "ci_people":
        try:
            people = int(text)
            update_data(uid, "people", people)
            set_state(uid, "ci_date_in")
            await update.message.reply_text("📅 Дата заезда? (например: 15.06)")
        except:
            await update.message.reply_text("Введи число, например: 2")

    elif state == "ci_date_in":
        try:
            t = text if len(text) > 5 else text + f".{date.today().year}"
            dt = datetime.strptime(t, "%d.%m.%Y")
            update_data(uid, "date_in", dt.strftime("%d.%m.%Y"))
            set_state(uid, "ci_date_out")
            await update.message.reply_text("📅 Дата выезда? (например: 18.06)")
        except:
            await update.message.reply_text("Неверный формат. Введи как: 15.06")

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
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("1,500 сом", callback_data="ci_price_1500"),
                 InlineKeyboardButton("2,500 сом", callback_data="ci_price_2500")],
                [InlineKeyboardButton("✏️ Своя цена", callback_data="ci_price_custom")],
            ])
            await update.message.reply_text(f"🌙 Ночей: *{nights}*\n\nЦена за сутки с 1 человека:", reply_markup=kb, parse_mode="Markdown")
        except:
            await update.message.reply_text("Неверный формат. Введи как: 18.06")

    elif state == "ci_price_custom":
        try:
            price = int(text.replace(" ","").replace(",",""))
            await handle_price(update, uid, price)
        except:
            await update.message.reply_text("Введи сумму числом")

    elif state == "ci_total_custom":
        try:
            total = int(text.replace(" ","").replace(",",""))
            update_data(uid, "total", total)
            set_state(uid, "ci_prepay")
            await update.message.reply_text(f"💰 Итого: *{total:,} сом*\n\nСколько взял задаток?", parse_mode="Markdown")
        except:
            await update.message.reply_text("Введи сумму числом")

    elif state == "ci_prepay":
        try:
            prepay = int(text.replace(" ","").replace(",",""))
            update_data(uid, "prepay", prepay)
            set_state(uid, "ci_prepay_method")
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("💵 Наличка", callback_data="ci_prepay_cash"),
                InlineKeyboardButton("💳 Карта", callback_data="ci_prepay_card"),
            ]])
            await update.message.reply_text(f"✅ Задаток: *{prepay:,} сом*\n\nКак оплатил?", reply_markup=kb, parse_mode="Markdown")
        except:
            await update.message.reply_text("Введи сумму числом")

    elif state == "pay_amount":
        try:
            amount = int(text.replace(" ","").replace(",",""))
            update_data(uid, "pay_amount", amount)
            set_state(uid, "pay_method")
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("💵 Наличка", callback_data="pay_method_cash"),
                InlineKeyboardButton("💳 Карта", callback_data="pay_method_card"),
            ]])
            await update.message.reply_text(f"💳 Сумма: *{amount:,} сом*\n\nКак оплатил?", reply_markup=kb, parse_mode="Markdown")
        except:
            await update.message.reply_text("Введи сумму числом")

    else:
        await update.message.reply_text("🏠 Нажми /start для начала")

# ===== ВЕБ СЕРВЕР =====
class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *a):
        pass

def run_web():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), Health).serve_forever()

# ===== ЗАПУСК =====
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
