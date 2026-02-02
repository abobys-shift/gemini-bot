import logging
import io
import os # Щоб читати змінні оточення
from PIL import Image
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
import google.generativeai as genai
from keep_alive import keep_alive # Імпортуємо наш трюк

# ==========================================
# 🛑 ТЕПЕР КЛЮЧІ БЕРЕМО З СЕРВЕРА (НЕ ПИШИ ЇХ ТУТ!)
# ==========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

genai.configure(api_key=GOOGLE_API_KEY)

system_instruction = """
Ти - розумний помічник у Telegram-боті.
1. Ти ПАМ'ЯТАЄШ контекст розмови.
2. Використовуй Markdown для форматування.
3. КАТЕГОРИЧНО НЕ ВИКОРИСТОВУЙ LaTeX.
4. Математичні формули пиши Unicode.
"""

model = genai.GenerativeModel(
    'gemini-2.5-flash',
    system_instruction=system_instruction
)

user_chats = {}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_chats[chat_id] = model.start_chat(history=[])
    await update.message.reply_text("♻️ Контекст оновлено!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_chats:
        user_chats[chat_id] = model.start_chat(history=[])
    
    chat_session = user_chats[chat_id]
    action = 'upload_photo' if update.message.photo else 'typing'
    await context.bot.send_chat_action(chat_id=chat_id, action=action)

    try:
        response_text = ""
        user_input = []
        
        if update.message.photo:
            photo_file = await update.message.photo[-1].get_file()
            image_stream = io.BytesIO()
            await photo_file.download_to_memory(out=image_stream)
            image_stream.seek(0)
            img = Image.open(image_stream)
            user_input.append(img)
            if update.message.caption:
                user_input.append(update.message.caption)
        elif update.message.text:
            user_input.append(update.message.text)

        response = chat_session.send_message(user_input)
        response_text = response.text

        if len(response_text) > 4000:
            for x in range(0, len(response_text), 4000):
                chunk = response_text[x:x+4000]
                try:
                    await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
                except:
                    await update.message.reply_text(chunk)
        else:
            try:
                await update.message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN)
            except:
                await update.message.reply_text(response_text)

    except Exception as e:
        print(f"Помилка: {e}")
        await update.message.reply_text("⚠️ Помилка.")

if __name__ == '__main__':
    # === ЗАПУСКАЄМО МІНІ-САЙТ ===
    keep_alive() 
    
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("new", start_command))
    application.add_handler(CommandHandler("start", start_command))
    
    filter_rules = (filters.TEXT | filters.PHOTO) & (~filters.COMMAND)
    application.add_handler(MessageHandler(filter_rules, handle_message))
    
    print("Бот запущено на сервері!")
    application.run_polling()