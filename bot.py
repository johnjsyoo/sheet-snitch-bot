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
GOOGLE_SHEET_NAME  = os.getenv("GOOGLE_SHEET_NAME")
GOOGLE_CREDS_JSON  = os.getenv("GOOGLE_CREDS_JSON")
AUTH_CODE          = os.getenv("AUTH_CODE")  # e.g. 'batman'

for name, val in [
    ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
    ("GOOGLE_SHEET_NAME",  GOOGLE_SHEET_NAME),
    ("GOOGLE_CREDS_JSON",  GOOGLE_CREDS_JSON),
    ("AUTH_CODE",          AUTH_CODE),
]:
    if not val:
        raise Exception(f"{name} is not set")

# Authenticate with Google Sheets
dict_creds = json.loads(GOOGLE_CREDS_JSON)
scope      = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
creds  = ServiceAccountCredentials.from_json_keyfile_dict(dict_creds, scope)
client = gspread.authorize(creds)
# Main data sheet (user, last_login, agent)
sheet  = client.open(GOOGLE_SHEET_NAME).sheet1

# In-memory cache for quick auth checks
authorized_cache = set()

# Log or update auth in the 'auth_log' sheet
def log_user_auth(user_id: int):
    ws  = client.open(GOOGLE_SHEET_NAME)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    uid = str(user_id)

    try:
        auth_ws = ws.worksheet("auth_log")
    except gspread.exceptions.WorksheetNotFound:
        auth_ws = ws.add_worksheet(title="auth_log", rows="100", cols="2")
        auth_ws.update("A1:B1", [["user_id", "last_login"]])

    # Retrieve all auth_log records
    records = auth_ws.get_all_records()
    ids     = [str(r.get("user_id", "")).strip() for r in records]

    if uid in ids:
        # Update the existing row's timestamp
        row_index = ids.index(uid) + 2  # account for header row
        auth_ws.update(f"B{row_index}", now)
        print(f"[AUTH] Updated last_login for {uid} at row {row_index}")
    else:
        # Append a new row
        auth_ws.append_row([uid, now])
        print(f"[AUTH] Added new auth_log entry for {uid}")

    authorized_cache.add(uid)

# Check auth: memory first, then sheet
def is_user_authorized(user_id: int) -> bool:
    uid = str(user_id)
    if uid in authorized_cache:
        print(f"[AUTH] {uid} found in cache")
        return True

    try:
        auth_ws = client.open(GOOGLE_SHEET_NAME).worksheet("auth_log")
        records = auth_ws.get_all_records()
        ids     = [str(r.get("user_id", "")).strip() for r in records]
        print(f"[AUTH] IDs in sheet: {ids}")
        if uid in ids:
            authorized_cache.add(uid)
            print(f"[AUTH] {uid} loaded from sheet into cache")
            return True
    except gspread.exceptions.WorksheetNotFound:
        print("[AUTH] auth_log sheet not found")

    return False

# Build main inline menu (prefills only lookup/auth)
def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 Lookup",       switch_inline_query_current_chat="/lookup "),
            InlineKeyboardButton("🔓 Authenticate", switch_inline_query_current_chat="/auth "),
        ],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")],
    ])

# /start handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📍 Welcome to SheetSnitchBot!", reply_markup=main_menu())

# /auth handler\ nasync def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code    = " ".join(context.args).strip().lower()
    expected= AUTH_CODE.strip().lower()

    if code == expected:
        log_user_auth(user_id)
        await asyncio.sleep(1.5)  # wait for sheet sync
        if is_user_authorized(user_id):
            await update.message.reply_text("✅ Auth successful! You can now use /lookup.")
        else:
            await update.message.reply_text("⚠️ Auth recorded; retry lookup in a moment.")
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
        if row.get("user","").strip().lower() == query:
            last  = row.get("last_login", "N/A")
            agent = row.get("agent",      "N/A")
            matches.append(
                f"👤 User: {row['user']}\n⏰ Last login: {last}\n🌐 Agent: {agent}"
            )

    if matches:
        await update.message.reply_text("\n\n".join(matches))
    else:
        await update.message.reply_text("🚫 No matches found.")

# Inline callback for Help button
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "help":
        await q.message.reply_text(
            "ℹ️ *Help Menu*\n\n"
            "`/auth <code>` – Authenticate\n"
            "`/lookup <user>` – Lookup data\n"
            "`/start` – Show menu",
            parse_mode="Markdown"
        )

# Register slash-commands in the Telegram UI
async def set_bot_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start",  "Show main menu"),
        BotCommand("auth",   "Authenticate with code"),
        BotCommand("lookup", "Search user data"),
        BotCommand("help",   "Show help menu"),
    ])

# Prevent duplicate polling sessions
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("auth",    auth))
    app.add_handler(CommandHandler("lookup",  lookup))
    app.add_handler(CallbackQueryHandler(menu_handler))
    app.post_init = set_bot_commands

    print("✅ Bot is running...")
    app.run_polling()