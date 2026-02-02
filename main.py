import logging
import io
import os
from PIL import Image
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
import google.generativeai as genai
# Імпортуємо типи для налаштування безпеки
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from keep_alive import keep_alive 

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

# === НОВЕ: ВИМИКАЄМО ФІЛЬТРИ БЕЗПЕКИ ===
# Це дозволить боту відповідати на все і не падати через помилкові спрацьовування
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

model = genai.GenerativeModel(
    'gemini-1.5-flash',
    system_instruction=system_instruction,
    safety_settings=safety_settings  # <-- Додали налаштування сюди
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
    
    # Інколи сесія "ламається" після помилки, тому якщо сталась біда - перестворюємо її
    try:
        if update.message.photo:
            await context.bot.send_chat_action(chat_id=chat_id, action='upload_photo')
            photo_file = await update.message.photo[-1].get_file()
            image_stream = io.BytesIO()
            await photo_file.download_to_memory(out=image_stream)
            image_stream.seek(0)
            img = Image.open(image_stream)
            
            prompt = update.message.caption if update.message.caption else "що на фото?"
            response = chat_session.send_message([prompt, img])
            
        elif update.message.text:
            await context.bot.send_chat_action(chat_id=chat_id, action='typing')
            response = chat_session.send_message(update.message.text)

        response_text = response.text

        # Відправка відповіді
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
        # === НОВЕ: ВИВОДИМО ТЕКСТ ПОМИЛКИ ===
        # Тепер бот скаже тобі, що саме пішло не так
        error_message = f"⚠️ Сталася помилка: {str(e)}"
        await update.message.reply_text(error_message)
        
        # Якщо помилка критична - скидаємо сесію автоматично
        user_chats[chat_id] = model.start_chat(history=[])
        await update.message.reply_text("♻️ Я автоматично скинув контекст, спробуй ще раз.")

if __name__ == '__main__':
    keep_alive() 
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("new", start_command))
    application.add_handler(CommandHandler("start", start_command))
    filter_rules = (filters.TEXT | filters.PHOTO) & (~filters.COMMAND)
    application.add_handler(MessageHandler(filter_rules, handle_message))
    application.run_polling()


