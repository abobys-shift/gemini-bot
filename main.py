import logging
import io
import os
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, CallbackQueryHandler, filters
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from keep_alive import keep_alive 

# === НАЛАШТУВАННЯ ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

genai.configure(api_key=GOOGLE_API_KEY)

# Твій список моделей (без змін)
AVAILABLE_MODELS = {
    "gemini-2.5-flash": "⚡️ 2.5 Flash (20/day)",
    "gemini-2.5-flash-lite": "⚡️ 2.5 Flash-Lite (20/day)",
    "gemini-3-flash-preview": "⚡️ 3 Flash (20/day)",
    "gemini-2.5-flash-preview-tts": "⚡️ 2.5 Flash-tts (10/day)",
    "gemma-3-27b-it": "мусор який працює завжди"
}

DEFAULT_MODEL = "gemini-2.5-flash"

system_instruction = """
Ти - розумний помічник у Telegram-боті.
1. Ти ПАМ'ЯТАЄШ контекст розмови.
2. Використовуй Markdown для форматування.
3. КАТЕГОРИЧНО НЕ ВИКОРИСТОВУЙ LaTeX.
4. Математичні формули пиши Unicode.
"""

safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# Словник для зберігання налаштувань користувачів
user_data = {}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# === ФІКС ДЛЯ GEMMA ===
# Ця функція дивиться: якщо модель gemma - не дає їй system_instruction
def create_model(model_name):
    if "gemma" in model_name:
        return genai.GenerativeModel(
            model_name,
            safety_settings=safety_settings
        )
    else:
        return genai.GenerativeModel(
            model_name,
            system_instruction=system_instruction,
            safety_settings=safety_settings
        )

# === ОТРИМАТИ СЕСІЮ ===
def get_user_session(chat_id):
    if chat_id not in user_data:
        # Створення через нашу функцію
        try:
            model = create_model(DEFAULT_MODEL)
            user_data[chat_id] = {
                "model_name": DEFAULT_MODEL,
                "session": model.start_chat(history=[])
            }
        except Exception as e:
            # Резерв на випадок помилки дефолтної
            fallback = "gemini-2.5-flash"
            user_data[chat_id] = {
                "model_name": fallback,
                "session": create_model(fallback).start_chat(history=[])
            }
    return user_data[chat_id]

# === КОМАНДА /mode ===
async def mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    for model_code, model_name in AVAILABLE_MODELS.items():
        keyboard.append([InlineKeyboardButton(model_name, callback_data=f"set_model|{model_code}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Отримуємо поточну модель безпечно
    current_model = user_data.get(update.effective_chat.id, {}).get("model_name", DEFAULT_MODEL)
    
    await update.message.reply_text(
        f"🔧 **Поточна модель:** `{current_model}`\n\nОбери іншу, якщо ця не працює:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# === ОБРОБКА КНОПОК ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split("|")
    if data[0] == "set_model":
        new_model_name = data[1]
        chat_id = update.effective_chat.id
        
        try:
            # Використовуємо create_model
            model = create_model(new_model_name)
            
            user_data[chat_id] = {
                "model_name": new_model_name,
                "session": model.start_chat(history=[])
            }
            
            # Гарна назва для кнопки
            pretty_name = AVAILABLE_MODELS.get(new_model_name, new_model_name)
            await query.edit_message_text(f"✅ Готово! Модель змінено на: `{pretty_name}`\nКонтекст оновлено.")
        except Exception as e:
            await query.edit_message_text(f"❌ Не вдалося переключити: {e}")

# === КОМАНДА /new ===
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id in user_data:
        current_name = user_data[chat_id]["model_name"]
        # Перезапускаємо через create_model
        model = create_model(current_name)
        user_data[chat_id]["session"] = model.start_chat(history=[])
    else:
        get_user_session(chat_id)
    
    await update.message.reply_text("♻️ Контекст очищено!")

# === ОБРОБКА ПОВІДОМЛЕНЬ ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_session = get_user_session(chat_id)
    chat_session = user_session["session"]

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
            prompt = update.message.caption if update.message.caption else "опиши це"
            user_input.append(prompt)
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
        error_msg = str(e)
        
        await update.message.reply_text(f"⚠️ **Помилка:** `{error_msg}`", parse_mode=ParseMode.MARKDOWN)
        
        if "429" in error_msg or "404" in error_msg or "400" in error_msg:
             await update.message.reply_text("👇 Спробуй змінити модель командою /mode")

if __name__ == '__main__':
    keep_alive() 
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("new", start_command))
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("mode", mode_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    filter_rules = (filters.TEXT | filters.PHOTO) & (~filters.COMMAND)
    application.add_handler(MessageHandler(filter_rules, handle_message))
    
    print("Бот мульти-модельний запущено!")
    application.run_polling()
