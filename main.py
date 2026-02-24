import asyncio
import sqlite3
import io
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.utils.keyboard import InlineKeyboardBuilder
from faster_whisper import WhisperModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# 1. Получаем токен из секретов Hugging Face
TOKEN = os.getenv("BOT_TOKEN")

# 2. Настройка сессии с явным указанием базового URL (помогает при проблемах с DNS)
session = AiohttpSession()
bot = Bot(token=TOKEN, session=session)
dp = Dispatcher()

# Инициализация модели Whisper (tiny - самая быстрая для CPU)
#model = WhisperModel("tiny", device="cpu", compute_type="int8")
model = WhisperModel("tiny", device="cpu", compute_type="int8", cpu_threads=1, download_root="./model_cache")
# --- РАБОТА С БАЗОЙ ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("tasks.db")
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS tasks 
                   (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                    user_id INTEGER, 
                    task_text TEXT, 
                    is_done INTEGER DEFAULT 0,
                    created_at TEXT)''')
    conn.commit()
    conn.close()

def add_task(user_id, text):
    conn = sqlite3.connect("tasks.db")
    cur = conn.cursor()
    now = datetime.now().strftime("%d.%m %H:%M")
    cur.execute("INSERT INTO tasks (user_id, task_text, created_at) VALUES (?, ?, ?)", (user_id, text, now))
    conn.commit()
    conn.close()

def get_tasks(user_id):
    conn = sqlite3.connect("tasks.db")
    cur = conn.cursor()
    cur.execute("SELECT id, task_text, created_at FROM tasks WHERE user_id = ? AND is_done = 0", (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def complete_task(task_id):
    conn = sqlite3.connect("tasks.db")
    cur = conn.cursor()
    cur.execute("UPDATE tasks SET is_done = 1 WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()

def clear_all_tasks(user_id):
    conn = sqlite3.connect("tasks.db")
    cur = conn.cursor()
    cur.execute("UPDATE tasks SET is_done = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_all_users_with_tasks():
    conn = sqlite3.connect("tasks.db")
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT user_id FROM tasks WHERE is_done = 0")
    users = [row[0] for row in cur.fetchall()]
    conn.close()
    return users

# --- КЛАВИАТУРА ---
def get_tasks_keyboard(user_id):
    tasks = get_tasks(user_id)
    builder = InlineKeyboardBuilder()
    for t_id, text, dt in tasks:
        builder.button(text=f"☐ {text}", callback_data=f"done_{t_id}")
    builder.adjust(1)
    if tasks:
        builder.row(types.InlineKeyboardButton(text="🗑 Очистить всё", callback_data="clear_all"))
    return builder.as_markup()

# --- НАПОМИНАНИЯ ---
async def send_daily_reminder():
    user_ids = get_all_users_with_tasks()
    for user_id in user_ids:
        try:
            await bot.send_message(
                user_id, 
                "☀️ Доброе утро! Твои невыполненные задачи:", 
                reply_markup=get_tasks_keyboard(user_id)
            )
        except Exception as e:
            print(f"Ошибка рассылки для {user_id}: {e}")

# --- ОБРАБОТЧИКИ ---
@dp.message(F.text == "/start")
async def cmd_start(message: types.Message):
    await message.answer("🎤 Привет! Пришли голосовое сообщение, и я превращу его в список дел.")

@dp.message(F.voice)
async def handle_voice(message: types.Message):
    status_msg = await message.answer("📝 Распознаю голос...")
    
    file_id = message.voice.file_id
    file = await bot.get_file(file_id)
    file_obj = io.BytesIO()
    await bot.download_file(file.file_path, destination=file_obj)
    file_obj.seek(0)
    
    segments, _ = model.transcribe(file_obj, language="ru")
    full_text = " ".join(segment.text for segment in segments).strip()
    
    if not full_text:
        await status_msg.edit_text("Не удалось разобрать слова. Попробуй еще раз.")
        return

    # Разбиваем на задачи по союзу "и", запятым и точкам
    raw_tasks = full_text.replace(" и ", ",").replace(".", ",").split(",")
    for task in raw_tasks:
        clean = task.strip().capitalize()
        if len(clean) > 1:
            add_task(message.from_user.id, clean)
            
    await status_msg.delete()
    await message.answer("✅ Добавлено в список:", reply_markup=get_tasks_keyboard(message.from_user.id))

@dp.callback_query(F.data.startswith("done_"))
async def process_done(callback: types.CallbackQuery):
    task_id = int(callback.data.split("_")[1])
    complete_task(task_id)
    kb = get_tasks_keyboard(callback.from_user.id)
    if kb.inline_keyboard:
        await callback.message.edit_reply_markup(reply_markup=kb)
    else:
        await callback.message.edit_text("🎉 Все задачи выполнены!")
    await callback.answer()

@dp.callback_query(F.data == "clear_all")
async def process_clear(callback: types.CallbackQuery):
    clear_all_tasks(callback.from_user.id)
    await callback.message.edit_text("🗑 Список очищен.")
    await callback.answer()

# --- ЗАПУСК ---
async def main():
    init_db()
    
    # Настройка планировщика (9:00 по МСК)
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(send_daily_reminder, "cron", hour=9, minute=0) 
    scheduler.start()

    # Запуск бота
    try:
        print("Бот запущен...")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
