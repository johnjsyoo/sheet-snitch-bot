import os
import json
import gspread
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
AUTH_CODE = os.getenv("AUTH_CODE")

# Validate env vars
if not TELEGRAM_BOT_TOKEN:
    raise Exception("TELEGRAM_BOT_TOKEN is not set")
if not GOOGLE_SHEET_NAME:
    raise Exception("GOOGLE_SHEET_NAME is not set")
if not GOOGLE_CREDS_JSON:
    raise Exception("GOOGLE_CREDS_JSON is not set")
if not AUTH_CODE:
    raise Exception("AUTH_CODE is not set")

# Google Sheets setup
creds_dict = json.loads(GOOGLE_CREDS_JSON)
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sheet = client.open(GOOGLE_SHEET_NAME).sheet1

# In-memory cache
AUTHORIZED_CACHE = set()

# Persist auth_log with user_id + timestamp
def log_user_auth(user_id):
    ws = client.open(GOOGLE_SHEET_NAME)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    uid = str(user_id)

    try:
        auth_sheet = ws.worksheet("auth_log")
    except gspread.exceptions.WorksheetNotFound:
        auth_sheet = ws.add_worksheet(title="auth_log", rows="100", cols="2")
        auth_sheet.update("A1:B1", [["user_id", "last_login"]])

    all_vals = auth_sheet.get_all_values()
    rows = all_vals[1:] if len(all_vals) > 1 else []
    ids = [row[0] for row in rows]

    if uid in ids:
        idx = ids.index(uid) + 2  # header row offset
        auth_sheet.update(f"B{idx}", now)
    else:
        auth_sheet.append_row([uid, now])

    AUTHORIZED_CACHE.add(uid)

def is_user_authorized(user_id):
    uid = str(user_id)
    if uid in AUTHORIZED_CACHE:
        return True

    try:
        auth_sheet = client.open(GOOGLE_SHEET_NAME).worksheet("auth_log")
        rows = auth_sheet.get_all_values()[1:]
        ids = [row[0] for row in rows if row]
        if uid in ids:
            AUTHORIZED_CACHE.add(uid)
            return True
    except gspread.exceptions.WorksheetNotFound:
        pass

    return False

# Build the inline menu
def main_menu():
    keyboard = [
        [
            InlineKeyboardButton("🔍 Lookup", callback_data="lookup"),
            InlineKeyboardButton("🔓 Authenticate", callback_data="auth"),
        ],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)

# /start handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📍 Welcome to SheetSnitchBot!", reply_markup=main_menu())

# /auth handler
async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = " ".join(context.args).strip().lower()
    expected = AUTH_CODE.strip().lower()

    if code == expected:
        log_user_auth(user_id)
        await asyncio.sleep(1.5)
        if is_user_authorized(user_id):
            await update.message.reply_text("✅ Auth successful! You can now use /lookup.")
        else:
            await update.message.reply_text("⚠️ Auth write delay—try again in a moment.")
    else:
        await update.message.reply_text("❌ Invalid code. Try again.")

# /lookup handler
async def lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_user_authorized(user_id):
        await update.message.reply_text("🚫 You are not authorized. Use /auth <code> to gain access.")
        return

    query = " ".join(context.args).strip().lower()
    if not query:
        await update.message.reply_text("Usage: /lookup <user>")
        return

    records = sheet.get_all_records()
    matches = []
    for row in records:
        if row.get("user", "").strip().lower() == query:
            last = row.get("last_login", "N/A")
            agent = row.get("agent", "N/A")
            matches.append(f"👤 User: {row['user']}\n⏰ Last login: {last}\n🌐 Agent: {agent}")

    if not matches:
        await update.message.reply_text("🚫 No matches found.")
    else:
        await update.message.reply_text("\n\n".join(matches))

# Button callback handler
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "lookup":
        await query.message.reply_text("🔍 To look up a user, type:\n`/lookup <username>`", parse_mode="Markdown")
    elif data == "auth":
        await query.message.reply_text("🔐 To authenticate, type:\n`/auth <code>`", parse_mode="Markdown")
    elif data == "help":
        await query.message.reply_text(
            "ℹ️ *Help Menu*\n\n"
            "`/auth <code>` – Authenticate to use this bot\n"
            "`/lookup <user>` – Search the data\n"
            "`/start` – Show this menu",
            parse_mode="Markdown"
        )

# BotFather-style command list
async def set_bot_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Show main menu"),
        BotCommand("auth", "Authenticate with access code"),
        BotCommand("lookup", "Search user data"),
        BotCommand("help", "Show help menu"),
    ])

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("auth", auth))
    app.add_handler(CommandHandler("lookup", lookup))
    app.add_handler(CallbackQueryHandler(menu_handler))
    app.post_init = set_bot_commands

    print("✅ Bot is running...")
    app.run_polling()
