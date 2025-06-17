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

# Validate required environment variables
for name, val in [
    ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
    ("GOOGLE_SHEET_NAME", GOOGLE_SHEET_NAME),
    ("GOOGLE_CREDS_JSON", GOOGLE_CREDS_JSON),
    ("AUTH_CODE", AUTH_CODE),
]:
    if not val:
        raise Exception(f"{name} is not set")

# Google Sheets setup
dict_creds = json.loads(GOOGLE_CREDS_JSON)
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
creds = ServiceAccountCredentials.from_json_keyfile_dict(dict_creds, scope)
client = gspread.authorize(creds)
sheet = client.open(GOOGLE_SHEET_NAME).sheet1  # sheet1 contains main data

# Cache for fast auth check
authorized_cache = set()

def log_user_auth(user_id: int):
    ws = client.open(GOOGLE_SHEET_NAME)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    uid = str(user_id)

    try:
        auth_ws = ws.worksheet("auth_log")
    except gspread.exceptions.WorksheetNotFound:
        auth_ws = ws.add_worksheet(title="auth_log", rows="100", cols="2")
        auth_ws.update("A1:B1", [["user_id", "last_login"]])

    records = auth_ws.get_all_records()
    ids = [str(r.get("user_id", "")).strip() for r in records]

    if uid in ids:
        row_index = ids.index(uid) + 2
        auth_ws.update(f"B{row_index}", now)
    else:
        auth_ws.append_row([uid, now])

    authorized_cache.add(uid)
    print(f"[AUTH] Auth logged for {uid}")

def is_user_authorized(user_id: int) -> bool:
    uid = str(user_id)
    if uid in authorized_cache:
        return True
    try:
        auth_ws = client.open(GOOGLE_SHEET_NAME).worksheet("auth_log")
        records = auth_ws.get_all_records()
        ids = [str(r.get("user_id", "")).strip() for r in records]
        if uid in ids:
            authorized_cache.add(uid)
            print(f"[AUTH] Found user_id {uid} in sheet")
            return True
    except gspread.exceptions.WorksheetNotFound:
        pass
    print(f"[AUTH] user_id {uid} not found")
    return False

def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 Lookup", callback_data="lookup"),
            InlineKeyboardButton("🔓 Authenticate", callback_data="auth"),
        ],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📍 Welcome to SheetSnitchBot!", reply_markup=main_menu())

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
            await update.message.reply_text("⚠️ Please retry /lookup in a moment.")
    else:
        await update.message.reply_text("❌ Invalid code. Try again.")

async def lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_user_authorized(user_id):
        await update.message.reply_text("🚫 You are not authorized. Use /auth <code> to gain access.")
        return

    query = " ".join(context.args).strip().lower()
    if not query:
        await update.message.reply_text("Usage: /lookup <name|customer|password>")
        return

    records = sheet.get_all_records()
    matches = []

    for row in records:
        name     = str(row.get("name", "")).strip().lower()
        customer = str(row.get("customer", "")).strip().lower()
        password = str(row.get("password", "")).strip().lower()

        if query in [name, customer, password]:
            details = "\n".join(f"{k}: {v}" for k, v in row.items())
            matches.append(f"🔹 Match:\n{details}")

    await update.message.reply_text("\n\n".join(matches) if matches else "🚫 No matches found.")

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "auth":
        await q.message.reply_text("🔐 Authenticate by sending: /auth <code>")
    elif q.data == "lookup":
        await q.message.reply_text("🔍 Lookup by sending: /lookup <name|customer|password>")
    elif q.data == "help":
        await q.message.reply_text(
            "ℹ️ *Help Menu*\n\n"
            "`/auth <code>` – Authenticate\n"
            "`/lookup <value>` – Lookup by name, customer, or password\n"
            "`/start` – Show menu again",
            parse_mode="Markdown"
        )

async def set_bot_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Show main menu"),
        BotCommand("auth", "Authenticate with code"),
        BotCommand("lookup", "Search user data"),
        BotCommand("help", "Show help menu"),
    ])

async def preload_auth_log():
    global authorized_cache
    try:
        auth_ws = client.open(GOOGLE_SHEET_NAME).worksheet("auth_log")
        records = auth_ws.get_all_records()
        for rec in records:
            uid = str(rec.get("user_id", "")).strip()
            if uid:
                authorized_cache.add(uid)
        print(f"[AUTH] Preloaded {len(authorized_cache)} users into cache")
    except gspread.exceptions.WorksheetNotFound:
        print("[AUTH] No auth_log sheet found on preload")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("auth", auth))
    app.add_handler(CommandHandler("lookup", lookup))
    app.add_handler(CallbackQueryHandler(menu_handler))
    app.post_init = set_bot_commands

    asyncio.run(preload_auth_log())

    print("✅ Bot is running...")
    app.run_polling()
