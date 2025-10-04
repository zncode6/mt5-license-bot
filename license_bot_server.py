import os
from dotenv import load_dotenv
import logging
import sqlite3
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask, request, jsonify
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes


# Load environment variables from .env
load_dotenv()
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
ADMIN_USER_ID = int(os.environ.get('ADMIN_USER_ID', '0'))

# Flask app for the web server (for EA verification)
app = Flask(__name__)

# Database functions (updated to include mt5_account)
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

init_db()  # Initialize DB

# Flask endpoint for EA license verification (called by MQL5 WebRequest)
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

# Telegram bot handlers
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

# Admin command example: list all licenses
async def list_licenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text('Not authorized.')
        return
    conn = sqlite3.connect('licenses.db')
    c = conn.cursor()
    c.execute('SELECT mt5_account, license_key, expiration, status FROM licenses')
    rows = c.fetchall()
    conn.close()
    msg = '\n'.join([f'{r[0]}: {r[1]}, {r[2]}, {r[3]}' for r in rows]) or 'No licenses.'
    await update.message.reply_text(msg)

# Run Telegram bot in a separate thread
def run_bot():
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN not set in environment.")
        return
    app_bot = Application.builder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("register", register))
    app_bot.add_handler(CommandHandler("check", check))
    app_bot.add_handler(CommandHandler("deactivate", deactivate))
    app_bot.add_handler(CommandHandler("list", list_licenses))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app_bot.run_polling()

if __name__ == '__main__':
    # Start Telegram bot in thread
    bot_thread = Thread(target=run_bot)
    bot_thread.start()
    # Run Flask server
    app.run(host='0.0.0.0', port=5000, debug=True)
