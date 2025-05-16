from dotenv import load_dotenv
import os
import asyncio
import random
import urllib.parse
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
import aioschedule
from sqlalchemy import Column, Integer, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()
bot = Bot(os.getenv('TOKEN'))
dp = Dispatcher()

DATABASE_URL = "sqlite+aiosqlite:///cherry_bot.db"
engine = create_async_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=AsyncSession)
Base = declarative_base()
waiting_for_weather = set()
waiting_for_ball = set()
reminders = {}


class UserCherries(Base):
    __tablename__ = 'user_cherries'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True, index=True)
    cherries = Column(Integer, default=0)
    total_spent = Column(Integer, default=0)
    card_1 = Column(Integer, default=0)
    card_2 = Column(Integer, default=0)
    card_3 = Column(Integer, default=0)
    card_4 = Column(Integer, default=0)
    card_5 = Column(Integer, default=0)
    card_6 = Column(Integer, default=0)
    card_7 = Column(Integer, default=0)
    card_8 = Column(Integer, default=0)
    card_9 = Column(Integer, default=0)
    card_10 = Column(Integer, default=0)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def init_user(user_id):
    async with SessionLocal() as session:
        result = await session.execute(select(UserCherries).where(UserCherries.user_id == user_id))
        user = result.scalars().first()
        if not user:
            user = UserCherries(user_id=user_id, cherries=0, total_spent=0)
            session.add(user)
            await session.commit()


async def get_user(user_id):
    async with SessionLocal() as session:
        result = await session.execute(select(UserCherries).where(UserCherries.user_id == user_id))
        return result.scalars().first()


async def update_user(user):
    async with SessionLocal() as session:
        session.add(user)
        await session.commit()


async def add_cherries(user_id, amount):
    user = await get_user(user_id)
    if user:
        user.cherries += amount
        await update_user(user)


async def add_spent(user_id, amount):
    user = await get_user(user_id)
    if user:
        user.total_spent += amount
        user.cherries -= amount
        await update_user(user)


async def count_total_cards(user):
    total = 0
    for i in range(1, 11):
        total += getattr(user, f'card_{i}')
    return total


async def check_all_cards_collected(user):
    total = await count_total_cards(user)
    return total == 10


from sqlalchemy import and_

async def determine_user_place(user):
    async with SessionLocal() as session:
        filters = [getattr(UserCherries, f'card_{i}') == 1 for i in range(1, 11)]
        results = await session.execute(
            select(UserCherries).where(and_(*filters)).order_by(UserCherries.total_spent)
        )
        users = results.scalars().all()

        if not users:
            # Нет других пользователей, значит пользователь на 1 месте
            return 1

        for idx, u in enumerate(users, start=1):
            if u.user_id == user.user_id:
                return idx
        # Если пользователь не найден в списке (что маловероятно, если он собрал все карты)
        return len(users) + 1  # на следующем месте


async def update_user_cherries(user_id: int, count: int):
    async with SessionLocal() as session:
        result = await session.execute(select(UserCherries).where(UserCherries.user_id == user_id))
        user = result.scalars().first()
        if user:
            user.cherries += count
            session.add(user)
        else:
            new_user = UserCherries(user_id=user_id, cherries=count)
            session.add(new_user)
        await session.commit()


async def send_reminder(text, chat_id):
    await bot.send_message(chat_id, f"Напоминание: {text}")


async def schedule_reminders():
    while True:
        await aioschedule.run_pending()
        await asyncio.sleep(1)


# Обработчики команд и callback'ов
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

commands_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="/help"),
            KeyboardButton(text="/set_reminder")
        ],
        [
            KeyboardButton(text="/weather"),
            KeyboardButton(text="/ranking")
        ],
        [
            KeyboardButton(text="/stop")
        ]
    ],
    resize_keyboard=True
)


@dp.message(Command('start'))
async def start(message: types.Message):
    await init_user(message.from_user.id)
    await message.answer(
        f"Здравствуйте, {message.from_user.full_name}! Я CherryGuru_bot.\n"
        "Выберите команду ниже или введите /help.",
        reply_markup=commands_keyboard
    )


@dp.message(Command('help'))
async def help_command(message: types.Message):
    await message.reply(
        "/play - Играйте с ботом\n"
        "/set_reminder - Установить напоминание\n"
        "/cherrys - Узнать количество вишен\n"
        "/buy - Купить карту\n"
        "/card_count - Узнать количество карт\n"
        "/stop - Прервать все текущие действия\n"
        "/ball - Получить предсказание\n"
        "/weather - Узнать погоду\n"
        "/reset - Сбросить прогресс\n"
        "/ranking - Узнать место"
    )


@dp.message(Command('stop'))
async def stop_command(message: types.Message):
    user_id = message.from_user.id
    reminders.pop(user_id, None)
    waiting_for_weather.discard(user_id)
    waiting_for_ball.discard(user_id)
    await message.reply("Все текущие действия остановлены.")


@dp.message(Command('play'))
async def play_command(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='Камень, ножницы, бумага', callback_data='rps_game'),
            InlineKeyboardButton(text='Орёл или решка', callback_data='coin_flip_game')
        ]
    ])
    await message.answer("Выберите игру:", reply_markup=keyboard)


@dp.message(Command('cherrys'))
async def show_cherrys(message: types.Message):
    user = await get_user(message.from_user.id)
    if user:
        await message.reply(f"Количество вишен: {user.cherries} 🍒.")
    else:
        await message.reply("Пользователь не найден.")


@dp.message(Command('buy'))
async def buy_card(message: types.Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    if not user:
        await message.reply("Пользователь не найден.")
        return
    if user.cherries < 30:
        await message.reply("Недостаточно вишен. Нужно 30.")
        return
    total_cards = await count_total_cards(user)
    if total_cards >= 10:
        await message.reply("У вас уже собраны все карты.")
        return
    card_number = random.randint(1, 10)
    card_attr = f'card_{card_number}'
    user.cherries -= 30
    user.total_spent += 30
    if getattr(user, card_attr) == 0:
        setattr(user, card_attr, 1)
        file_path = (f'C:\\Users\\user\\PycharmProjects\\CherryGuru_bot\\cards\\photo{card_number}.jpg')
        if not os.path.isfile(file_path):
            await message.answer("Файл карты не найден.")
            return
        await message.answer_photo(photo=FSInputFile(file_path, filename=f'Карта {card_number}'))
        total = await count_total_cards(user)
        await message.reply(f"Вам досталась карта {card_number}. Всего карт: {total}/10.")
        if total == 10:
            place = await determine_user_place(user)
            await message.reply(f"Поздравляю! Вы собрали все карты и заняли {place} место.")
    else:
        await message.reply(f"Карта {card_number} уже есть.")
    await update_user(user)


@dp.message(Command('card_count'))
async def show_card_count(message: types.Message):
    user = await get_user(message.from_user.id)
    if user:
        total = await count_total_cards(user)
        await message.reply(f"Всего карт: {total}/10.")
    else:
        await message.reply("Пользователь не найден.")


@dp.message(Command('ranking'))
async def show_ranking(message: types.Message):
    user = await get_user(message.from_user.id)
    if user:
        all_collected = await check_all_cards_collected(user)
        if not all_collected:
            await message.reply("Соберите все карты, чтобы открыть эту функцию.")
            return
        place = await determine_user_place(user)
        if place > 0:
            await message.reply(f"Вы на {place} месте.")
        else:
            await message.reply("Ваше место не найдено в рейтинге.")
    else:
        await message.reply("Пользователь не найден.")


@dp.message(Command('reset'))
async def reset_progress(message: types.Message):
    user_id = message.from_user.id
    reminders[user_id] = {'action': 'reset'}
    await message.reply("Вы точно хотите сбросить прогресс? Напишите 'да' или 'нет'.")


@dp.message(lambda msg: msg.text and msg.text.lower() in ['да', 'нет'])
async def confirm_reset(msg: types.Message):
    user_id = msg.from_user.id
    if user_id in reminders and reminders[user_id].get('action') == 'reset':
        if msg.text.lower() == 'да':
            async with SessionLocal() as session:
                result = await session.execute(select(UserCherries).where(UserCherries.user_id == user_id))
                user = result.scalars().first()
                if user:
                    user.cherries = 0
                    user.total_spent = 0
                    for i in range(1, 11):
                        setattr(user, f'card_{i}', 0)
                    await session.commit()
                    await msg.reply("Ваш прогресс сброшен.")
                else:
                    await msg.reply("Пользователь не найден.")
        else:
            await msg.reply("Сброс отменен.")
        del reminders[user_id]


@dp.callback_query(lambda c: c.data == 'rps_game')
async def rps_game_callback(c: types.CallbackQuery):
    builder = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='Камень', callback_data='rps_rock'),
            InlineKeyboardButton(text='Ножницы', callback_data='rps_scissors'),
            InlineKeyboardButton(text='Бумага', callback_data='rps_paper')
        ]
    ])
    await c.answer()
    await c.message.answer("Выберите: камень, ножницы или бумага:", reply_markup=builder)


@dp.callback_query(lambda c: c.data == 'coin_flip_game')
async def coin_flip_callback(c: types.CallbackQuery):
    builder = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='Орел', callback_data='coin_head'),
            InlineKeyboardButton(text='Решка', callback_data='coin_tail')
        ]
    ])
    await c.answer()
    await c.message.answer("Выберите: орёл или решка:", reply_markup=builder)


@dp.callback_query(lambda c: c.data.startswith('rps_'))
async def rps_choice_callback(c: types.CallbackQuery):
    choices_map = {
        'rock': 'камень',
        'scissors': 'ножницы',
        'paper': 'бумага'
    }
    user_choice_key = c.data.split('_')[1]
    user_choice_ru = choices_map.get(user_choice_key)
    bot_choice_ru = random.choice(['камень', 'ножницы', 'бумага'])
    if (user_choice_ru == 'камень' and bot_choice_ru == 'ножницы') or \
            (user_choice_ru == 'ножницы' and bot_choice_ru == 'бумага') or \
            (user_choice_ru == 'бумага' and bot_choice_ru == 'камень'):
        user = await get_user(c.from_user.id)
        user.cherries += 1
        await update_user(user)
        await c.answer(f"Победа! Вы {user_choice_ru}, бот {bot_choice_ru}. +1 🍒")
    elif user_choice_ru == bot_choice_ru:
        await c.answer(f"Ничья! Оба выбрали {bot_choice_ru}.")
    else:
        await c.answer(f"Проигрыш! Вы {user_choice_ru}, бот {bot_choice_ru}.")


@dp.callback_query(lambda c: c.data.startswith('coin_'))
async def coin_choice_callback(c: types.CallbackQuery):
    choices_map = {
        'head': 'орёл',
        'tail': 'решка',
    }
    user_choice_key = c.data.split('_')[1]
    user_choice_ru = choices_map.get(user_choice_key)
    bot_choice_en = random.choice(['head', 'tail'])
    bot_choice_ru = choices_map[bot_choice_en]
    if user_choice_ru == bot_choice_ru:
        user = await get_user(c.from_user.id)
        user.cherries += 1
        await update_user(user)
        await c.answer(f"Победа! Вы {user_choice_ru}, выпало {bot_choice_ru}. +1 🍒")
    else:
        await c.answer(f"Проигрыш! Вы {user_choice_ru}, выпало {bot_choice_ru}.")


@dp.message(Command('set_reminder'))
async def set_reminder_cmd(message: types.Message):
    await message.reply(
        "Пожалуйста, укажите дату и время в формате: год месяц день часы:минуты. Например: 2025 05 21 23:23")
    reminders[message.from_user.id] = {'awaiting_datetime': True}


@dp.message(Command('weather'))
async def cmd_weather(message: types.Message):
    user_id = message.from_user.id
    waiting_for_weather.add(user_id)
    await message.reply("Введите название города на английском, чтобы получить погоду:")


@dp.message(Command('ball'))
async def cmd_ball(message: types.Message):
    user_id = message.from_user.id
    waiting_for_ball.add(user_id)
    await message.reply("Задайте свой вопрос, и я дам предсказание:")


@dp.message()
async def handle_messages(message: types.Message):
    user_id = message.from_user.id
    if user_id in waiting_for_weather:
        city = message.text.strip()
        city_encoded = urllib.parse.quote(city)
        url = f"https://yandex.ru/pogoda/{city_encoded}"
        await message.reply(f"Ссылка на погоду в городе {city}: {url}")
        waiting_for_weather.remove(user_id)
        return
    if user_id in waiting_for_ball:
        responses = [
            "Да, определенно!",
            "Скорее да, чем нет.",
            "Я бы на вашем месте не рассчитывал.",
            "Ответ туманен, попробуйте снова.",
            "Да, но только через некоторое время.",
            "Сомнительно.",
            "Определенно не!",
            "Да, конечно!",
            "Сейчас не лучший момент.",
            "Попробуйте позже.",
            "Не все так просто.",
            "Убедитесь в этом.",
            "Скорее всего, да.",
            "Считайте это знаком.",
            "Возможно, вы правы.",
            "Не торопитесь с выводами.",
            "Кажется, это благоприятный знак.",
            "Это может произойти.",
            "Не исключено.",
            "Всё указывает на то, что да.",
            "Вселенная говорит 'да'.",
            "Думайте дважды, прежде чем действовать."
        ]
        answer = random.choice(responses)
        await message.reply(answer)
        waiting_for_ball.remove(user_id)
        return
    if user_id in reminders:
        state = reminders[user_id]
        if state.get('awaiting_datetime'):
            try:
                parts = message.text.strip().split()
                if len(parts) != 4:
                    raise ValueError("Неверный формат")
                year, month, day, time_str = parts
                hour, minute = map(int, time_str.split(':'))
                dt = datetime(int(year), int(month), int(day), hour, minute)
                if dt < datetime.now():
                    await message.reply("Выберите время в будущем.")
                    return
                state['datetime'] = dt
                await message.reply("Что нужно напомнить?")
                state['awaiting_datetime'] = False
                state['awaiting_text'] = True
            except:
                await message.reply(
                    "Ошибка формата. Используйте: год месяц день часы:минуты. Например: 2025 05 21 23:23")
        elif state.get('awaiting_text'):
            text = message.text
            dt = state['datetime']
            time_str = dt.strftime("%H:%M")
            aioschedule.every().day.at(time_str).do(send_reminder, text, message.chat.id)
            await message.reply("Напоминание установлено!")
            del reminders[user_id]


async def main():
    await init_db()
    asyncio.create_task(schedule_reminders())
    await dp.start_polling(bot)
