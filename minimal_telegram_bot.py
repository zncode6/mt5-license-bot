from telegram.ext import Application, CommandHandler
import logging
import os

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')

async def start(update, context):
    logging.info(f"Received /start from {update.effective_user.id}")
    await update.message.reply_text("Hello! Your minimal bot is working.")

if __name__ == '__main__':
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()
