import logging
import os
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, abort
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask app
app = Flask(__name__)

# Database functions (same as before)
def init_db():
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS licenses
                 (mt5_account TEXT PRIMARY KEY, telegram_user_id INTEGER, license_key TEXT UNIQUE, expiration DATE, status TEXT)''')
    conn.commit()
    conn.close()

def generate_license(telegram_user_id, mt5_account):
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    key = f"LC-{mt5_account}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    expiration = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
    c.execute("INSERT OR REPLACE INTO licenses (mt5_account, telegram_user_id, license_key, expiration, status) VALUES (?, ?, ?, ?, ?)",
              (mt5_account, telegram_user_id, key, expiration, 'active'))
    conn.commit()
    conn.close()
    return key

def check_license(mt5_account):
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    c.execute("SELECT license_key, expiration, status FROM licenses WHERE mt5_account = ?", (mt5_account,))
    result = c.fetchone()
    conn.close()
    if result:
        key, exp, status = result
        if status == 'active' and datetime.strptime(exp, '%Y-%m-%d') > datetime.now():
            return f"Active license: {key} (Expires: {exp})"
        else:
            return "License expired or inactive."
    return "No license found for this MT5 account."

def deactivate_license(mt5_account):
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    c.execute("UPDATE licenses SET status = 'inactive' WHERE mt5_account = ?", (mt5_account,))
    conn.commit()
    conn.close()
    return "License deactivated."

init_db()

# Flask endpoint for EA license verification (unchanged)
@app.route('/verify', methods=['GET'])
def verify_license():
    mt5_account = request.args.get('mt5_account')
    license_key = request.args.get('license_key')
    if not mt5_account or not license_key:
        return "invalid", 400

    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    c.execute("SELECT expiration, status FROM licenses WHERE mt5_account = ? AND license_key = ?", (mt5_account, license_key))
    result = c.fetchone()
    conn.close()

    if result:
        exp, status = result
        if status == 'active' and datetime.strptime(exp, '%Y-%m-%d') > datetime.now():
            return "valid", 200
        else:
            return "invalid", 403
    return "invalid", 404

# Telegram bot handlers (unchanged)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Welcome! Use /register <MT5_account_number> to get a license key.\n/check <MT5_account_number> to view status.\n/deactivate <MT5_account_number> to revoke.')

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text('Please provide your MT5 account number, e.g., /register 12345678')
        return
    mt5_account = context.args[0]
    user_id = update.effective_user.id
    key = generate_license(user_id, mt5_account)
    await update.message.reply_text(f'License generated for MT5 account {mt5_account}: {key}\nValid for 30 days. Input this key in your EA settings.')

async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text('Please provide MT5 account number, e.g., /check 12345678')
        return
    mt5_account = context.args[0]
    status = check_license(mt5_account)
    await update.message.reply_text(status)

async def deactivate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text('Please provide MT5 account number, e.g., /deactivate 12345678')
        return
    mt5_account = context.args[0]
    result = deactivate_license(mt5_account)
    await update.message.reply_text(result)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Use /register, /check, or /deactivate with MT5 account number.')

# Webhook endpoint for Telegram updates
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_json()
        update = Update.de_json(json_string, app_bot.bot)
        app_bot.process_update(update)
        return 'ok'
    else:
        abort(403)

# Main: Set up and run
if __name__ == '__main__':
    TOKEN = os.environ.get('TOKEN')  # Set this as environment variable on Render
    if not TOKEN:
        raise ValueError("Missing TOKEN environment variable")

    # Get Render's external URL
    EXTERNAL_URL = os.environ.get('RENDER_EXTERNAL_URL', 'https://your-app-name.onrender.com')  # Render sets this automatically
    WEBHOOK_URL = f"{EXTERNAL_URL}/webhook"

    # Build the application
    app_bot = Application.builder().token(TOKEN).build()

    # Add handlers
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("register", register))
    app_bot.add_handler(CommandHandler("check", check))
    app_bot.add_handler(CommandHandler("deactivate", deactivate))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Set webhook (delete any old one first)
    app_bot.bot.delete_webhook(drop_pending_updates=True)
    app_bot.bot.set_webhook(url=WEBHOOK_URL)

    logger.info(f"Webhook set to {WEBHOOK_URL}")

    # Bind to PORT for Render
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
