import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.filters import CommandStart
from aiogram import F
import asyncpg
from config import DB_CONFIG, BOT_TOKEN

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

user_phones = {}

# Клавиатура для запроса номера телефона
contact_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📱 Отправить номер телефона", request_contact=True)]
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
    input_field_placeholder="Нажмите кнопку ниже"
)

# Клавиатура для отображения KPI
kpi_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Показать KPI")],
        [KeyboardButton(text="🔁 Перезапустить бота")]
    ],
    resize_keyboard=True
)

@dp.message(CommandStart())
async def send_welcome(message: types.Message):
    await message.answer(
        "Привет! Пожалуйста, отправь свой номер телефона.\n" +
        "Нажмите кнопку ниже 👇",
        reply_markup=contact_kb
    )

@dp.message(lambda msg: msg.contact is not None)
async def handle_contact(message: types.Message):
    phone = message.contact.phone_number
    user_phones[message.from_user.id] = phone
    print(f"📞 Получен номер телефона: {phone}")
    await message.answer("Спасибо! Теперь нажмите «Показать KPI».", reply_markup=kpi_kb)

@dp.message(F.text == "📊 Показать KPI")
async def show_kpi(message: types.Message):
    phone = user_phones.get(message.from_user.id)
    if not phone:
        await message.answer("Сначала отправьте номер телефона через /start.")
        return

    kpis = await get_kpis_by_phone(phone)
    if kpis:
        text = "Ваши KPI:\n" + "\n".join([f"📌 {name}: {value}" for name, value in kpis])
        await message.answer(text)
    else:
        await message.answer("KPI не найдены для вашего номера.")

@dp.message(F.text == "🔁 Перезапустить бота")
async def restart_bot(message: types.Message):
    user_phones.pop(message.from_user.id, None)
    await send_welcome(message)

# ❗ Игнор всех текстовых сообщений до получения контакта
@dp.message(lambda msg: not user_phones.get(msg.from_user.id))
async def block_text_input(message: types.Message):
    await message.answer(
        "Пожалуйста, отправьте номер телефона через кнопку.\n" +
        "Нажмите /start, чтобы начать сначала."
    )

async def get_kpis_by_phone(phone: str):
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        rows = await conn.fetch("SELECT kpi_name, value FROM bot.employees WHERE phone = $1", phone)
        return [(row['kpi_name'], row['value']) for row in rows]
    finally:
        await conn.close()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
