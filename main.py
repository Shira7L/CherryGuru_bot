import asyncio
from teams import dp, bot, init_db, schedule_reminders


async def main():
    await init_db()
    asyncio.create_task(schedule_reminders())
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())