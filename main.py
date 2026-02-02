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

# Список моделей, між якими будемо перемикатись
# Я зібрав тут ті, що були в твоєму списку + стандартні
AVAILABLE_MODELS = {
    "gemini-2.5-flash": "⚡️ 2.5 Flash (20/day)",
    "gemini-2.5-flash-lite": "⚡️ 2.5 Flash-Lite (20/day)"
    "gemini-3-flash-preview": "⚡️ 3 Flash (20/day)"
    "gemini-2.5-flash-preview-tts": "⚡️ 2.5 Flash-tts (10/day)"
}

DEFAULT_MODEL = "gemini-2.5-flash"

system_instruction = """
Ти - розумний помічник. 
1. Ти ПАМ'ЯТАЄШ контекст розмови.
2. Використовуй Markdown.
3. Не використовуй LaTeX.
"""

safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# Словник для зберігання налаштувань користувачів
# user_data[chat_id] = {"model_name": "...", "chat_session": ...}
user_data = {}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# === ДОПОМІЖНА ФУНКЦІЯ: ОТРИМАТИ СЕСІЮ ===
def get_user_session(chat_id):
    if chat_id not in user_data:
        # Якщо користувача немає - створюємо з дефолтною моделлю
        model = genai.GenerativeModel(
            DEFAULT_MODEL,
            system_instruction=system_instruction,
            safety_settings=safety_settings
        )
        user_data[chat_id] = {
            "model_name": DEFAULT_MODEL,
            "session": model.start_chat(history=[])
        }
    return user_data[chat_id]

# === КОМАНДА /mode - ВИБІР МОДЕЛІ ===
async def mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    # Створюємо кнопки для кожної моделі
    for model_code, model_name in AVAILABLE_MODELS.items():
        keyboard.append([InlineKeyboardButton(model_name, callback_data=f"set_model|{model_code}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    current_model = get_user_session(update.effective_chat.id)["model_name"]
    await update.message.reply_text(
        f"🔧 **Поточна модель:** `{current_model}`\n\nОбери іншу, якщо ця не працює:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# === ОБРОБКА НАТИСКАННЯ КНОПОК ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Підтверджуємо натискання

    data = query.data.split("|")
    if data[0] == "set_model":
        new_model_name = data[1]
        chat_id = update.effective_chat.id
        
        # Створюємо нову сесію з новою моделлю
        try:
            model = genai.GenerativeModel(
                new_model_name,
                system_instruction=system_instruction,
                safety_settings=safety_settings
            )
            user_data[chat_id] = {
                "model_name": new_model_name,
                "session": model.start_chat(history=[])
            }
            
            await query.edit_message_text(f"✅ Готово! Модель змінено на: `{new_model_name}`\nКонтекст оновлено.")
        except Exception as e:
            await query.edit_message_text(f"❌ Не вдалося переключити: {e}")

# === КОМАНДА /new ===
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # Просто скидаємо сесію поточної моделі
    current = get_user_session(chat_id)
    model = genai.GenerativeModel(
        current["model_name"],
        system_instruction=system_instruction,
        safety_settings=safety_settings
    )
    user_data[chat_id]["session"] = model.start_chat(history=[])
    
    await update.message.reply_text("♻️ Контекст очищено!")

# === ОБРОБКА ПОВІДОМЛЕНЬ ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_session = get_user_session(chat_id)
    chat_session = user_session["session"]

    # Індикація дії
    action = 'upload_photo' if update.message.photo else 'typing'
    await context.bot.send_chat_action(chat_id=chat_id, action=action)

    try:
        response_text = ""
        user_input = []
        
        # Обробка фото
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

        # Відправка запиту
        response = chat_session.send_message(user_input)
        response_text = response.text

        # Відправка відповіді (з розбиттям)
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
        
        # Якщо помилка про ліміти або 404 - пропонуємо змінити модель
        if "429" in error_msg or "404" in error_msg:
             await update.message.reply_text("👇 Спробуй змінити модель командою /mode")

if __name__ == '__main__':
    keep_alive() 
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Реєструємо команди
    application.add_handler(CommandHandler("new", start_command))
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("mode", mode_command)) # Нова команда
    
    # Реєструємо обробник кнопок
    application.add_handler(CallbackQueryHandler(button_handler))

    filter_rules = (filters.TEXT | filters.PHOTO) & (~filters.COMMAND)
    application.add_handler(MessageHandler(filter_rules, handle_message))
    
    print("Бот мульти-модельний запущено!")
    application.run_polling()
