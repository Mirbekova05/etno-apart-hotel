import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ===================== НАСТРОЙКИ =====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8915798465:AAGVK96P4Y9fnomCPQWWF1EFsHRHIDAEbnU")
SHEET_ID = os.getenv("SHEET_ID", "1hLNcIosjOy_4sGw1hrYNFRHG7bmN4-V9JolaVtLyTME")
CREDS_FILE = "credentials.json"

# ===================== КОМНАТЫ =====================
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

# ===================== GOOGLE SHEETS =====================
def get_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID)

def get_bookings_sheet():
    book = get_sheet()
    try:
        return book.worksheet("Бронирования")
    except:
        ws = book.add_worksheet("Бронирования", 1000, 17)
        ws.append_row([
            "ID", "Номер", "Гость", "Людей", "Заезд", "Выезд",
            "Ночей", "Цена/сутки", "Итого",
            "Задаток", "Способ задатка",
            "Доплата", "Способ доплаты",
            "Долг", "Статус оплаты", "Статус номера", "Дата записи"
        ])
        return ws

def get_all_bookings():
    ws = get_bookings_sheet()
    return ws.get_all_records()

def find_active_booking(room_num):
    records = get_all_bookings()
    for i, r in enumerate(records):
        if str(r.get("Номер")) == str(room_num) and r.get("Статус номера") in ["Занят", "Уборка"]:
            return i + 2, r
    return None, None

def add_booking(data):
    ws = get_bookings_sheet()
    booking_id = len(ws.get_all_records()) + 1
    pay_status = "Оплачено полностью ✅" if data["debt"] == 0 else "Есть долг ⚠️"
    ws.append_row([
        booking_id,
        data["room"],
        data["guest"],
        data["people"],
        data["date_in"],
        data["date_out"],
        data["nights"],
        data["price_day"],
        data["total"],
        data["prepay"],
        data["prepay_method"],
        0,
        "—",
        data["debt"],
        pay_status,
        "Занят",
        datetime.now().strftime("%d.%m.%Y %H:%M")
    ])

def update_room_status(row_index, status):
    ws = get_bookings_sheet()
    ws.update_cell(row_index, 16, status)

def update_payment(row_index, booking, amount, method):
    ws = get_bookings_sheet()
    old_extra = int(booking.get("Доплата", 0))
    new_extra = old_extra + amount
    new_debt = max(0, int(booking.get("Долг", 0)) - amount)
    pay_status = "Оплачено полностью ✅" if new_debt == 0 else "Есть долг ⚠️"
    ws.update_cell(row_index, 12, new_extra)
    ws.update_cell(row_index, 13, method)
    ws.update_cell(row_index, 14, new_debt)
    ws.update_cell(row_index, 15, pay_status)
    return new_debt

# ===================== СОСТОЯНИЯ =====================
(
    CHECKIN_ROOM, CHECKIN_GUEST, CHECKIN_PEOPLE,
    CHECKIN_DATE_IN, CHECKIN_DATE_OUT,
    CHECKIN_PRICE, CHECKIN_PRICE_CUSTOM,
    CHECKIN_TOTAL_CONFIRM, CHECKIN_TOTAL_CUSTOM,
    CHECKIN_PREPAY, CHECKIN_PREPAY_METHOD,
    CHECKOUT_ROOM, CHECKOUT_CONFIRM,
    INFO_ROOM,
    PAYMENT_ROOM, PAYMENT_AMOUNT, PAYMENT_METHOD,
    CLEANING_ROOM,
) = range(18)

# ===================== ГЛАВНОЕ МЕНЮ =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("✅ Заселить", callback_data="menu_checkin"),
         InlineKeyboardButton("🚪 Выселить", callback_data="menu_checkout")],
        [InlineKeyboardButton("🟢 Свободные", callback_data="menu_free"),
         InlineKeyboardButton("🔴 Занятые", callback_data="menu_occupied")],
        [InlineKeyboardButton("🔍 Инфо по номеру", callback_data="menu_info"),
         InlineKeyboardButton("💰 Принять оплату", callback_data="menu_payment")],
        [InlineKeyboardButton("🧹 Уборка", callback_data="menu_cleaning")],
    ]
    text = "🏠 *Управление квартирами*\n\nВыбери действие:"
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "menu_checkin":
        return await checkin_start(update, context)
    elif data == "menu_checkout":
        return await checkout_start(update, context)
    elif data == "menu_free":
        return await show_free(update, context)
    elif data == "menu_occupied":
        return await show_occupied(update, context)
    elif data == "menu_info":
        return await info_start(update, context)
    elif data == "menu_payment":
        return await payment_start(update, context)
    elif data == "menu_cleaning":
        return await cleaning_start(update, context)
    elif data == "main_menu":
        await start(update, context)
        return ConversationHandler.END

def back_button():
    return [[InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")]]

def payment_method_keyboard(prefix):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 Наличка", callback_data=f"{prefix}_cash"),
         InlineKeyboardButton("💳 Карта", callback_data=f"{prefix}_card")],
    ])

def room_status(room_num, bookings):
    for b in bookings:
        if str(b.get("Номер")) == str(room_num):
            s = b.get("Статус номера", "")
            if s == "Занят":
                return "🔴"
            elif s == "Уборка":
                return "🧹"
    return "🟢"

# ===================== СВОБОДНЫЕ =====================
async def show_free(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    bookings = get_all_bookings()
    occupied = {str(b["Номер"]) for b in bookings if b.get("Статус номера") in ["Занят", "Уборка"]}
    lines = []
    for num, info in ROOMS.items():
        if num == 14:
            continue
        if str(num) not in occupied:
            lines.append(f"🟢 {info['name']}")
    text = ("🟢 *Свободные номера:*\n\n" + "\n".join(lines)) if lines else "❌ Все номера заняты"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(back_button()), parse_mode="Markdown")

# ===================== ЗАНЯТЫЕ =====================
async def show_occupied(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    bookings = get_all_bookings()
    active = [b for b in bookings if b.get("Статус номера") in ["Занят", "Уборка"]]
    if active:
        lines = []
        for b in active:
            icon = "🔴" if b.get("Статус номера") == "Занят" else "🧹"
            debt = int(b.get("Долг", 0))
            debt_str = f" | Долг: {debt:,} сом ⚠️" if debt > 0 else " | ✅ Оплачено"
            lines.append(f"{icon} №{b['Номер']} — {b['Гость']} ({b['Людей']} чел.)\n    Выезд: {b['Выезд']}{debt_str}")
        text = "🔴 *Занятые номера:*\n\n" + "\n\n".join(lines)
    else:
        text = "✅ Все номера свободны!"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(back_button()), parse_mode="Markdown")

# ===================== ЗАСЕЛЕНИЕ =====================
async def checkin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    bookings = get_all_bookings()
    occupied = {str(b["Номер"]) for b in bookings if b.get("Статус номера") in ["Занят", "Уборка"]}
    keyboard = []
    row = []
    for num, info in ROOMS.items():
        if num == 14:
            continue
        if str(num) not in occupied:
            row.append(InlineKeyboardButton(f"№{num}", callback_data=f"ci_room_{num}"))
            if len(row) == 4:
                keyboard.append(row)
                row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="main_menu")])
    await query.edit_message_text("✅ *Заселение*\n\nВыбери свободный номер:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return CHECKIN_ROOM

async def checkin_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    num = int(query.data.split("_")[-1])
    context.user_data["ci"] = {"room": num}
    await query.edit_message_text(f"✅ Номер *{ROOMS[num]['name']}*\n\nВведи имя гостя:", parse_mode="Markdown")
    return CHECKIN_GUEST

async def checkin_guest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["ci"]["guest"] = update.message.text.strip()
    await update.message.reply_text("👥 Сколько человек заселяется?")
    return CHECKIN_PEOPLE

async def checkin_people(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["ci"]["people"] = int(update.message.text.strip())
        await update.message.reply_text("📅 Дата заезда? (например: 15.06)")
        return CHECKIN_DATE_IN
    except:
        await update.message.reply_text("Введи число, например: 3")
        return CHECKIN_PEOPLE

async def checkin_date_in(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        if len(text) <= 5:
            text += f".{date.today().year}"
        dt = datetime.strptime(text, "%d.%m.%Y")
        context.user_data["ci"]["date_in"] = dt.strftime("%d.%m.%Y")
        await update.message.reply_text("📅 Дата выезда? (например: 18.06)")
        return CHECKIN_DATE_OUT
    except:
        await update.message.reply_text("Неверный формат. Введи как: 15.06")
        return CHECKIN_DATE_IN

async def checkin_date_out(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        if len(text) <= 5:
            text += f".{date.today().year}"
        dt_out = datetime.strptime(text, "%d.%m.%Y")
        dt_in = datetime.strptime(context.user_data["ci"]["date_in"], "%d.%m.%Y")
        nights = (dt_out - dt_in).days
        if nights <= 0:
            await update.message.reply_text("Дата выезда должна быть позже даты заезда!")
            return CHECKIN_DATE_OUT
        context.user_data["ci"]["date_out"] = dt_out.strftime("%d.%m.%Y")
        context.user_data["ci"]["nights"] = nights
        keyboard = [
            [InlineKeyboardButton("1,500 сом", callback_data="ci_price_1500"),
             InlineKeyboardButton("2,500 сом", callback_data="ci_price_2500")],
            [InlineKeyboardButton("✏️ Ввести свою цену", callback_data="ci_price_custom")],
        ]
        await update.message.reply_text(
            f"🌙 Ночей: *{nights}*\n\nЦена за сутки с 1 человека:",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
        return CHECKIN_PRICE
    except:
        await update.message.reply_text("Неверный формат. Введи как: 18.06")
        return CHECKIN_DATE_OUT

async def checkin_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "ci_price_custom":
        await query.edit_message_text("✏️ Введи цену за сутки с 1 человека:")
        return CHECKIN_PRICE_CUSTOM
    price = int(query.data.split("_")[-1])
    return await checkin_calc_total(query, context, price)

async def checkin_price_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.strip().replace(" ", "").replace(",", ""))
        return await checkin_calc_total(update, context, price, is_message=True)
    except:
        await update.message.reply_text("Введи сумму числом, например: 2000")
        return CHECKIN_PRICE_CUSTOM

async def checkin_calc_total(update_or_query, context, price_per_person, is_message=False):
    ci = context.user_data["ci"]
    ci["price_per_person"] = price_per_person
    people = ci["people"]
    nights = ci["nights"]
    price_day = price_per_person * people
    total = price_day * nights
    ci["price_day"] = price_day
    ci["total_suggested"] = total
    text = (
        f"💰 *Расчёт:*\n\n"
        f"👥 Людей: *{people}*\n"
        f"🌙 Ночей: *{nights}*\n"
        f"💵 {price_per_person:,} × {people} чел = *{price_day:,} сом/сутки*\n"
        f"━━━━━━━━━━━━\n"
        f"💰 *Итого: {total:,} сом*\n\n"
        f"Верно?"
    )
    keyboard = [
        [InlineKeyboardButton(f"✅ Да — {total:,} сом", callback_data="ci_total_ok")],
        [InlineKeyboardButton("✏️ Ввести другую сумму", callback_data="ci_total_custom")],
    ]
    if is_message:
        await update_or_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update_or_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return CHECKIN_TOTAL_CONFIRM

async def checkin_total_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "ci_total_custom":
        await query.edit_message_text("✏️ Введи итоговую сумму:")
        return CHECKIN_TOTAL_CUSTOM
    context.user_data["ci"]["total"] = context.user_data["ci"]["total_suggested"]
    await query.edit_message_text(
        f"💰 Итого: *{context.user_data['ci']['total']:,} сом*\n\nСколько взял задаток?",
        parse_mode="Markdown"
    )
    return CHECKIN_PREPAY

async def checkin_total_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        total = int(update.message.text.strip().replace(" ", "").replace(",", ""))
        context.user_data["ci"]["total"] = total
        await update.message.reply_text(f"💰 Итого: *{total:,} сом*\n\nСколько взял задаток?", parse_mode="Markdown")
        return CHECKIN_PREPAY
    except:
        await update.message.reply_text("Введи сумму числом")
        return CHECKIN_TOTAL_CUSTOM

async def checkin_prepay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        prepay = int(update.message.text.strip().replace(" ", "").replace(",", ""))
        context.user_data["ci"]["prepay"] = prepay
        await update.message.reply_text(
            f"✅ Задаток: *{prepay:,} сом*\n\nКак оплатил?",
            reply_markup=payment_method_keyboard("ci_prepay"),
            parse_mode="Markdown"
        )
        return CHECKIN_PREPAY_METHOD
    except:
        await update.message.reply_text("Введи сумму числом")
        return CHECKIN_PREPAY

async def checkin_prepay_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = "💵 Наличка" if query.data == "ci_prepay_cash" else "💳 Карта"
    ci = context.user_data["ci"]
    ci["prepay_method"] = method
    total = ci["total"]
    prepay = ci["prepay"]
    debt = max(0, total - prepay)
    ci["debt"] = debt
    add_booking(ci)

    pay_text = "🎉 *Оплачено полностью!*" if debt == 0 else f"⚠️ *Долг: {debt:,} сом*"

    await query.edit_message_text(
        f"✅ *Заселение оформлено!*\n\n"
        f"🏠 {ROOMS[ci['room']]['name']}\n"
        f"👤 Гость: *{ci['guest']}*\n"
        f"👥 Людей: *{ci['people']}*\n"
        f"📅 Заезд: *{ci['date_in']}*\n"
        f"📅 Выезд: *{ci['date_out']}*\n"
        f"🌙 Ночей: *{ci['nights']}*\n"
        f"━━━━━━━━━━━━\n"
        f"💰 Итого: *{total:,} сом*\n"
        f"✅ Задаток: *{prepay:,} сом* ({method})\n"
        f"{pay_text}",
        reply_markup=InlineKeyboardMarkup(back_button()),
        parse_mode="Markdown"
    )
    context.user_data.clear()
    return ConversationHandler.END

# ===================== ВЫСЕЛЕНИЕ =====================
async def checkout_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    bookings = get_all_bookings()
    active = [b for b in bookings if b.get("Статус номера") == "Занят"]
    if not active:
        await query.edit_message_text("Нет активных заселений.", reply_markup=InlineKeyboardMarkup(back_button()))
        return ConversationHandler.END
    keyboard = []
    row = []
    for b in active:
        row.append(InlineKeyboardButton(f"№{b['Номер']}", callback_data=f"co_room_{b['Номер']}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="main_menu")])
    await query.edit_message_text("🚪 *Выселение*\n\nВыбери номер:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return CHECKOUT_ROOM

async def checkout_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    room_num = int(query.data.split("_")[-1])
    row_index, booking = find_active_booking(room_num)
    if not booking:
        await query.edit_message_text("Номер не найден.")
        return ConversationHandler.END
    context.user_data["co_row"] = row_index
    context.user_data["co_booking"] = booking
    debt = int(booking.get("Долг", 0))
    pay_text = f"⚠️ Долг: *{debt:,} сом*" if debt > 0 else "✅ Оплачено полностью"
    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить выселение", callback_data="co_confirm")],
        [InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]
    ]
    await query.edit_message_text(
        f"🚪 *Выселение №{room_num}*\n\n"
        f"👤 Гость: *{booking['Гость']}*\n"
        f"📅 Заезд: *{booking['Заезд']}*\n"
        f"📅 Выезд: *{booking['Выезд']}*\n"
        f"━━━━━━━━━━━━\n"
        f"💰 Итого: *{int(booking['Итого']):,} сом*\n"
        f"✅ Задаток: *{int(booking['Задаток']):,} сом* ({booking.get('Способ задатка','—')})\n"
        f"💳 Доплата: *{int(booking.get('Доплата',0)):,} сом* ({booking.get('Способ доплаты','—')})\n"
        f"{pay_text}\n\n"
        f"Подтвердить выселение?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CHECKOUT_CONFIRM

async def checkout_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    row_index = context.user_data["co_row"]
    booking = context.user_data["co_booking"]
    update_room_status(row_index, "Уборка")
    await query.edit_message_text(
        f"✅ *№{booking['Номер']} — гость выселен!*\n\n"
        f"🧹 Номер переведён в статус *«Нужна уборка»*",
        reply_markup=InlineKeyboardMarkup(back_button()),
        parse_mode="Markdown"
    )
    context.user_data.clear()
    return ConversationHandler.END

# ===================== ИНФО ПО НОМЕРУ =====================
async def info_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    bookings = get_all_bookings()
    keyboard = []
    row = []
    for num in ROOMS:
        if num == 14:
            continue
        icon = room_status(num, bookings)
        row.append(InlineKeyboardButton(f"{icon}№{num}", callback_data=f"info_room_{num}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="main_menu")])
    await query.edit_message_text(
        "🔍 *Инфо по номеру*\n\n🟢 Свободен  🔴 Занят  🧹 Уборка\n\nВыбери номер:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return INFO_ROOM

async def info_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    room_num = int(query.data.split("_")[-1])
    room = ROOMS[room_num]
    _, booking = find_active_booking(room_num)

    if booking:
        debt = int(booking.get("Долг", 0))
        status = booking.get("Статус номера", "")
        status_text = "🧹 Нужна уборка" if status == "Уборка" else "🔴 Занят"
        pay_text = "🎉 Оплачено полностью!" if debt == 0 else f"⚠️ Долг: *{debt:,} сом*"
        text = (
            f"{status_text} — *{room['name']}*\n\n"
            f"👤 Гость: *{booking['Гость']}*\n"
            f"👥 Людей: *{booking['Людей']}*\n"
            f"📅 Заезд: *{booking['Заезд']}*\n"
            f"📅 Выезд: *{booking['Выезд']}*\n"
            f"🌙 Ночей: *{booking['Ночей']}*\n"
            f"━━━━━━━━━━━━\n"
            f"💰 Итого: *{int(booking['Итого']):,} сом*\n"
            f"✅ Задаток: *{int(booking['Задаток']):,} сом* ({booking.get('Способ задатка','—')})\n"
            f"💳 Доплата: *{int(booking.get('Доплата',0)):,} сом* ({booking.get('Способ доплаты','—')})\n"
            f"{pay_text}"
        )
    else:
        text = f"🟢 *{room['name']}* — СВОБОДЕН"

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(back_button()), parse_mode="Markdown")
    return ConversationHandler.END

# ===================== ПРИНЯТЬ ОПЛАТУ =====================
async def payment_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    bookings = get_all_bookings()
    with_debt = [b for b in bookings if b.get("Статус номера") == "Занят" and int(b.get("Долг", 0)) > 0]
    if not with_debt:
        await query.edit_message_text("✅ Все долги оплачены!", reply_markup=InlineKeyboardMarkup(back_button()))
        return ConversationHandler.END
    keyboard = []
    row = []
    for b in with_debt:
        row.append(InlineKeyboardButton(f"№{b['Номер']} — {int(b['Долг']):,} с", callback_data=f"pay_room_{b['Номер']}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="main_menu")])
    await query.edit_message_text("💰 *Принять оплату*\n\nНомера с долгом:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return PAYMENT_ROOM

async def payment_room(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    room_num = int(query.data.split("_")[-1])
    row_index, booking = find_active_booking(room_num)
    context.user_data["pay_row"] = row_index
    context.user_data["pay_booking"] = booking
    await query.edit_message_text(
        f"💰 *Оплата №{room_num}*\n\n"
        f"👤 {booking['Гость']}\n"
        f"💰 Итого: *{int(booking['Итого']):,} сом*\n"
        f"✅ Задаток: *{int(booking['Задаток']):,} сом* ({booking.get('Способ задатка','—')})\n"
        f"⚠️ Долг: *{int(booking['Долг']):,} сом*\n\n"
        f"Введи сумму доплаты:",
        parse_mode="Markdown"
    )
    return PAYMENT_AMOUNT

async def payment_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = int(update.message.text.strip().replace(" ", "").replace(",", ""))
        context.user_data["pay_amount"] = amount
        await update.message.reply_text(
            f"💳 Сумма: *{amount:,} сом*\n\nКак оплатил?",
            reply_markup=payment_method_keyboard("pay"),
            parse_mode="Markdown"
        )
        return PAYMENT_METHOD
    except:
        await update.message.reply_text("Введи сумму числом")
        return PAYMENT_AMOUNT

async def payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = "💵 Наличка" if query.data == "pay_cash" else "💳 Карта"
    amount = context.user_data["pay_amount"]
    booking = context.user_data["pay_booking"]
    row_index = context.user_data["pay_row"]
    new_debt = update_payment(row_index, booking, amount, method)
    pay_text = "🎉 *Долг полностью погашен!*" if new_debt == 0 else f"⚠️ Остаток долга: *{new_debt:,} сом*"
    await query.edit_message_text(
        f"✅ *Оплата принята!*\n\n"
        f"💳 Получено: *{amount:,} сом* ({method})\n"
        f"{pay_text}",
        reply_markup=InlineKeyboardMarkup(back_button()),
        parse_mode="Markdown"
    )
    context.user_data.clear()
    return ConversationHandler.END

# ===================== УБОРКА =====================
async def cleaning_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    bookings = get_all_bookings()
    to_clean = [b for b in bookings if b.get("Статус номера") == "Уборка"]
    if not to_clean:
        await query.edit_message_text("✅ Все номера чистые!", reply_markup=InlineKeyboardMarkup(back_button()))
        return ConversationHandler.END
    keyboard = []
    row = []
    for b in to_clean:
        row.append(InlineKeyboardButton(f"🧹 №{b['Номер']}", callback_data=f"clean_room_{b['Номер']}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="main_menu")])
    await query.edit_message_text("🧹 *Уборка*\n\nНомера которые нужно убрать:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return CLEANING_ROOM

async def cleaning_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    room_num = int(query.data.split("_")[-1])
    row_index, booking = find_active_booking(room_num)
    if booking:
        update_room_status(row_index, "Убран")
    await query.edit_message_text(
        f"✅ *Номер №{room_num} убран!*\n\n🟢 Номер свободен и готов к заселению.",
        reply_markup=InlineKeyboardMarkup(back_button()),
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# ===================== ЗАПУСК =====================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')
    def log_message(self, format, *args):
        pass

def run_health_server():
    server = HTTPServer(('0.0.0.0', int(os.environ.get('PORT', 8080))), HealthHandler)
    server.serve_forever()

def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    logging.basicConfig(level=logging.INFO)
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(main_menu_callback, pattern="^menu_")],
        states={
            CHECKIN_ROOM:          [CallbackQueryHandler(checkin_room, pattern="^ci_room_")],
            CHECKIN_GUEST:         [MessageHandler(filters.TEXT & ~filters.COMMAND, checkin_guest)],
            CHECKIN_PEOPLE:        [MessageHandler(filters.TEXT & ~filters.COMMAND, checkin_people)],
            CHECKIN_DATE_IN:       [MessageHandler(filters.TEXT & ~filters.COMMAND, checkin_date_in)],
            CHECKIN_DATE_OUT:      [MessageHandler(filters.TEXT & ~filters.COMMAND, checkin_date_out)],
            CHECKIN_PRICE:         [CallbackQueryHandler(checkin_price, pattern="^ci_price_")],
            CHECKIN_PRICE_CUSTOM:  [MessageHandler(filters.TEXT & ~filters.COMMAND, checkin_price_custom)],
            CHECKIN_TOTAL_CONFIRM: [CallbackQueryHandler(checkin_total_confirm, pattern="^ci_total_")],
            CHECKIN_TOTAL_CUSTOM:  [MessageHandler(filters.TEXT & ~filters.COMMAND, checkin_total_custom)],
            CHECKIN_PREPAY:        [MessageHandler(filters.TEXT & ~filters.COMMAND, checkin_prepay)],
            CHECKIN_PREPAY_METHOD: [CallbackQueryHandler(checkin_prepay_method, pattern="^ci_prepay_")],
            CHECKOUT_ROOM:         [CallbackQueryHandler(checkout_room, pattern="^co_room_")],
            CHECKOUT_CONFIRM:      [CallbackQueryHandler(checkout_confirm, pattern="^co_confirm$")],
            INFO_ROOM:             [CallbackQueryHandler(info_room, pattern="^info_room_")],
            PAYMENT_ROOM:          [CallbackQueryHandler(payment_room, pattern="^pay_room_")],
            PAYMENT_AMOUNT:        [MessageHandler(filters.TEXT & ~filters.COMMAND, payment_amount)],
            PAYMENT_METHOD:        [CallbackQueryHandler(payment_method, pattern="^pay_")],
            CLEANING_ROOM:         [CallbackQueryHandler(cleaning_done, pattern="^clean_room_")],
        },
        fallbacks=[
            CallbackQueryHandler(start, pattern="^main_menu$"),
            CommandHandler("start", start),
        ],
        per_message=False
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    print("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()

# This code is already at the end, so we need to insert before main
