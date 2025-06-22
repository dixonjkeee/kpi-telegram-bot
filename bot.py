import asyncio
import asyncpg
from aiogram import Bot, Dispatcher, types
from aiogram.types import (
    KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import CommandStart
from aiogram import F
from datetime import datetime
from config import DB_CONFIG, BOT_TOKEN

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

user_phones = {}
user_states = {}  # user_id -> phone
user_years = {}   # user_id -> selected year

contact_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📱 Отправить номер телефона", request_contact=True)]
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
    input_field_placeholder="Нажмите кнопку ниже"
)

kpi_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Показать KPI")],
        [KeyboardButton(text="🔁 Перезапустить бота")]
    ],
    resize_keyboard=True
)

# 📅 Месяцы на русском
RU_MONTHS = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
}


@dp.message(CommandStart())
async def send_welcome(message: types.Message):
    await message.answer(
        "Привет! Пожалуйста, отправь свой номер телефона.\n"
        "Формат: 7933XXXXXXX\n"
        "Нажмите кнопку ниже 👇",
        reply_markup=contact_kb
    )


@dp.message(lambda msg: msg.contact is not None)
async def handle_contact(message: types.Message):
    phone = message.contact.phone_number.lstrip('+')
    user_phones[message.from_user.id] = phone
    await message.answer("Спасибо! Теперь нажмите «Показать KPI».", reply_markup=kpi_kb)


@dp.message(F.text == "📊 Показать KPI")
async def choose_year(message: types.Message):
    user_id = message.from_user.id
    phone = user_phones.get(user_id)

    if not phone:
        await message.answer("Сначала отправьте номер телефона через /start.")
        return

    years = await get_available_years(phone)
    if not years:
        await message.answer("Нет доступных данных для выбора года.")
        return

    buttons = [
        InlineKeyboardButton(text=str(year), callback_data=f"year_{year}") for year in years
    ]
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    )

    await message.answer("Выберите год:", reply_markup=keyboard)


@dp.callback_query(lambda c: c.data.startswith("year_"))
async def choose_month(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    phone = user_phones.get(user_id)
    year = int(callback.data.split("_")[1])
    user_years[user_id] = year

    months = await get_available_months(phone, year)
    if not months:
        await callback.message.answer("Нет доступных месяцев.")
        return

    # Сортировка месяцев по убыванию
    months.sort(reverse=True)

    buttons = [
        InlineKeyboardButton(
            text=f"{RU_MONTHS[m.month]} {m.year}",
            callback_data=f"month_{m.month}"
        )
        for m in months
    ]
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    )

    await callback.message.answer("Выберите месяц:", reply_markup=keyboard)


@dp.callback_query(lambda c: c.data.startswith("month_"))
async def show_kpi(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    phone = user_phones.get(user_id)
    year = user_years.get(user_id)
    month = int(callback.data.split("_")[1])

    date_obj = datetime(year, month, 1).date()
    row = await get_kpis_by_phone_and_date(phone, date_obj)

    if row:
        text = (
            f"📊 *Ваши KPI за {RU_MONTHS[month]} {year}:*\n"
            f"👤 Сотрудник: {row['name']}\n"
            f"📞 Телефон: {row['user.phone']}\n"
            f"💰 Выручка за услуги: {row['Выручка за услуги, руб'] or 0} руб\n"
            f"🧴 Выручка за продукты: {row['Выручка за продукты, руб'] or 0} руб\n"
            f"💼 Кол-во оказанных услуг: {row['Количество оказанных услуг'] or 0}\n"
            f"👥 Общее количество клиентов: {row['Общее количество клиентов'] or 0}\n"
            f"💳 Средний чек: {row['Средний чек'] or 0} руб\n"
            f"🔁 Повторные клиенты: {row['Повторные клиенты'] or 0}\n"
            f"🆕 Новые клиенты: {row['Новые клиенты'] or 0}\n"
            f"📈 Возвращаемость клиентов: {row['Возвращаемость клиентов'] or 0}%\n"
            f"💸 Зарплата: {row['Зарплата, руб'] or 0} руб"
        )
        await callback.message.answer(text, parse_mode="Markdown")
    else:
        await callback.message.answer("KPI не найдены для выбранного месяца.")


@dp.message(F.text == "🔁 Перезапустить бота")
async def restart_bot(message: types.Message):
    user_id = message.from_user.id
    user_phones.pop(user_id, None)
    user_years.pop(user_id, None)
    await send_welcome(message)


# 🔒 Блокируем текстовые сообщения, если не отправлен контакт
@dp.message(lambda msg: not user_phones.get(msg.from_user.id))
async def block_text_input(message: types.Message):
    await message.answer(
        "Пожалуйста, отправьте номер телефона через кнопку.\n"
        "Нажмите /start, чтобы начать сначала."
    )


# 📦 Получение KPI
async def get_kpis_by_phone_and_date(phone: str, date: datetime.date):
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        row = await conn.fetchrow("""
            SELECT 
                "name", 
                "user.phone", 
                "Выручка за услуги, руб", 
                "Выручка за продукты, руб", 
                "Количество оказанных услуг", 
                "Общее количество клиентов", 
                "Средний чек", 
                "Повторные клиенты", 
                "Новые клиенты", 
                "Возвращаемость клиентов", 
                "Зарплата, руб"
            FROM bot.v_monada_staff_kpi_by_month
            WHERE "user.phone" = $1 AND "Месяц" = $2
        """, phone, date)
        return row
    finally:
        await conn.close()


# 📆 Получение доступных годов
async def get_available_years(phone: str):
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        rows = await conn.fetch("""
            SELECT DISTINCT EXTRACT(YEAR FROM "Месяц") AS year
            FROM bot.v_monada_staff_kpi_by_month
            WHERE "user.phone" = $1
            ORDER BY year DESC
        """, phone)
        return [int(row["year"]) for row in rows]
    finally:
        await conn.close()


# 📅 Получение месяцев по году
async def get_available_months(phone: str, year: int):
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        rows = await conn.fetch("""
            SELECT DISTINCT "Месяц"
            FROM bot.v_monada_staff_kpi_by_month
            WHERE "user.phone" = $1 AND EXTRACT(YEAR FROM "Месяц") = $2
            ORDER BY "Месяц"
        """, phone, year)
        return [row["Месяц"] for row in rows]
    finally:
        await conn.close()


async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
