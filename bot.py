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

# Load and validate environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_SHEET_NAME   = os.getenv("GOOGLE_SHEET_NAME")
GOOGLE_CREDS_JSON   = os.getenv("GOOGLE_CREDS_JSON")
AUTH_CODE           = os.getenv("AUTH_CODE")

for var, val in [
    ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
    ("GOOGLE_SHEET_NAME",   GOOGLE_SHEET_NAME),
    ("GOOGLE_CREDS_JSON",   GOOGLE_CREDS_JSON),
    ("AUTH_CODE",           AUTH_CODE),
]:
    if not val:
        raise Exception(f"{var} is not set")

# Google Sheets setup
creds_dict = json.loads(GOOGLE_CREDS_JSON)
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
creds  = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sheet  = client.open(GOOGLE_SHEET_NAME).sheet1

# In-memory cache for instant auth
AUTHORIZED_CACHE = set()

def log_user_auth(user_id: int):
    """Record or update user_id and timestamp in auth_log, and cache it."""
    ws  = client.open(GOOGLE_SHEET_NAME)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    uid = str(user_id)

    try:
        auth_ws = ws.worksheet("auth_log")
    except gspread.exceptions.WorksheetNotFound:
        auth_ws = ws.add_worksheet(title="auth_log", rows="100", cols="2")
        auth_ws.update("A1:B1", [["user_id", "last_login"]])

    rows = auth_ws.get_all_values()[1:]  # skip header
    ids  = [r[0] for r in rows]

    if uid in ids:
        idx = ids.index(uid) + 2  # account for header row
        auth_ws.update(f"B{idx}", now)
    else:
        auth_ws.append_row([uid, now])

    AUTHORIZED_CACHE.add(uid)

def is_user_authorized(user_id: int) -> bool:
    """Check cache first, then sheet if needed."""
    uid = str(user_id)
    if uid in AUTHORIZED_CACHE:
        return True

    try:
        auth_ws = client.open(GOOGLE_SHEET_NAME).worksheet("auth_log")
        rows    = auth_ws.get_all_values()[1:]
        ids     = [r[0] for r in rows if r]
        if uid in ids:
            AUTHORIZED_CACHE.add(uid)
            return True
    except gspread.exceptions.WorksheetNotFound:
        pass

    return False

def main_menu() -> InlineKeyboardMarkup:
    """Inline menu with prefill buttons for lookup and auth."""
    keyboard = [
        [
            InlineKeyboardButton("🔍 Lookup",      switch_inline_query_current_chat="/lookup "),
            InlineKeyboardButton("🔓 Authenticate", switch_inline_query_current_chat="/auth "),
        ],
        [ InlineKeyboardButton("ℹ️ Help", callback_data="help") ],
    ]
    return InlineKeyboardMarkup(keyboard)

# Handlers

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📍 Welcome to SheetSnitchBot!", reply_markup=main_menu())

async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code    = " ".join(context.args).strip().lower()
    expected= AUTH_CODE.strip().lower()

    if code == expected:
        log_user_auth(user_id)
        # wait briefly for sheet write
        await asyncio.sleep(1.5)
        if is_user_authorized(user_id):
            await update.message.reply_text("✅ Auth successful! You can now use /lookup.")
        else:
            await update.message.reply_text("⚠️ Auth write delay—try again shortly.")
    else:
        await update.message.reply_text("❌ Invalid code. Try again.")

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
        if row.get("user","").strip().lower() == query:
            last  = row.get("last_login","N/A")
            agent = row.get("agent","N/A")
            matches.append(f"👤 User: {row['user']}\n⏰ Last login: {last}\n🌐 Agent: {agent}")

    if not matches:
        await update.message.reply_text("🚫 No matches found.")
    else:
        await update.message.reply_text("\n\n".join(matches))

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "help":
        await query.message.reply_text(
            "ℹ️ *Help Menu*\n\n"
            "`/auth <code>` – Authenticate to use this bot\n"
            "`/lookup <user>` – Search the data\n"
            "`/start` – Show this menu",
            parse_mode="Markdown"
        )

async def set_bot_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start",  "Show main menu"),
        BotCommand("auth",   "Authenticate with access code"),
        BotCommand("lookup", "Search user data"),
        BotCommand("help",   "Show help menu"),
    ])

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("auth",  auth))
    app.add_handler(CommandHandler("lookup",lookup))
    app.add_handler(CallbackQueryHandler(menu_handler))

    app.post_init = set_bot_commands

    print("✅ Bot is running...")
    app.run_polling()
