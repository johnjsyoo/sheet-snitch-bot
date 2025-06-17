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
GOOGLE_SHEET_NAME  = os.getenv("GOOGLE_SHEET_NAME")
GOOGLE_CREDS_JSON  = os.getenv("GOOGLE_CREDS_JSON")
AUTH_CODES = json.loads(os.getenv("AUTH_CODES", "{}"))

# Validate env vars
for key, val in [
    ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
    ("GOOGLE_SHEET_NAME", GOOGLE_SHEET_NAME),
    ("GOOGLE_CREDS_JSON", GOOGLE_CREDS_JSON),
]:
    if not val:
        raise Exception(f"{key} is not set")

# Google Sheets setup
creds = ServiceAccountCredentials.from_json_keyfile_dict(
    json.loads(GOOGLE_CREDS_JSON),
    ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
)
client = gspread.authorize(creds)
sheet = client.open(GOOGLE_SHEET_NAME).sheet1

# Cache for auth state
auth_cache = {}

def log_user_auth(user_id: int, role: str):
    ws = client.open(GOOGLE_SHEET_NAME)
    uid = str(user_id)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    try:
        auth_ws = ws.worksheet("auth_log")
    except gspread.exceptions.WorksheetNotFound:
        auth_ws = ws.add_worksheet(title="auth_log", rows="100", cols="3")
        auth_ws.update("A1:C1", [["user_id", "last_login", "role"]])

    records = auth_ws.get_all_records()
    ids = [str(r.get("user_id", "")).strip() for r in records]

    if uid in ids:
        row = ids.index(uid) + 2
        auth_ws.update(f"B{row}", now)
        auth_ws.update(f"C{row}", role)
    else:
        auth_ws.append_row([uid, now, role])

    auth_cache[uid] = role
    print(f"[AUTH] Logged {uid} as {role}")

def get_user_role(user_id: int) -> str:
    uid = str(user_id)
    if uid in auth_cache:
        return auth_cache[uid]
    try:
        auth_ws = client.open(GOOGLE_SHEET_NAME).worksheet("auth_log")
        for rec in auth_ws.get_all_records():
            if str(rec.get("user_id", "")).strip() == uid:
                role = rec.get("role", "user")
                auth_cache[uid] = role
                return role
    except gspread.exceptions.WorksheetNotFound:
        pass
    return ""

# Bot UI
def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Lookup", callback_data="lookup"),
         InlineKeyboardButton("🔓 Authenticate", callback_data="auth")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")],
    ])

# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📍 Welcome to SheetSnitchBot!", reply_markup=main_menu())

async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = " ".join(context.args).strip().lower()

    role = AUTH_CODES.get(code)
    if role:
        log_user_auth(user_id, role)
        await asyncio.sleep(1)
        if get_user_role(user_id):
            await update.message.reply_text("✅ Auth successful! You can now use /lookup.")
        else:
            await update.message.reply_text("⚠️ Try again shortly.")
    else:
        await update.message.reply_text("❌ Invalid code. Try again.")

async def lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = get_user_role(user_id)

    if not role:
        await update.message.reply_text("🚫 You are not authorized. Use /auth <code> to gain access.")
        return

    query = " ".join(context.args).strip().lower()
    if not query:
        await update.message.reply_text("Usage: /lookup <name/customer/password>")
        return

    records = sheet.get_all_records()
    matches = []

    for row in records:
        name = str(row.get("name", "")).strip().lower()
        customer = str(row.get("customer", "")).strip().lower()
        password = str(row.get("password", "")).strip().lower()

        if query == name or query == customer or query == password:
            show_password = (query == password or role == "admin")
            display_pw = password if show_password else "********"
            match_str = (
                f"👤 Name: {row.get('name', 'N/A')}\n"
                f"🧾 Customer: {customer}\n"
                f"🔑 Password: {display_pw}\n"
                f"🕒 Last Login: {row.get('last_login', 'N/A')}\n"
                f"📎 Agent: {row.get('agent', 'N/A')}"
            )
            matches.append(match_str)

    await update.message.reply_text("\n\n".join(matches) if matches else "🚫 No matches found.")

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "auth":
        await q.message.reply_text("🔐 Authenticate with: /auth <code>")
    elif q.data == "lookup":
        await q.message.reply_text("🔍 Lookup like: /lookup john smith")
    elif q.data == "help":
        await q.message.reply_text(
            "ℹ️ *Help Menu*\n\n"
            "`/auth <code>` – Authenticate access\n"
            "`/lookup <query>` – Search user data\n"
            "`/start` – Show main menu",
            parse_mode="Markdown"
        )

async def preload_auth_log():
    try:
        auth_ws = client.open(GOOGLE_SHEET_NAME).worksheet("auth_log")
        for rec in auth_ws.get_all_records():
            uid = str(rec.get("user_id", "")).strip()
            role = rec.get("role", "user")
            if uid:
                auth_cache[uid] = role
        print(f"[AUTH] Preloaded {len(auth_cache)} users")
    except gspread.exceptions.WorksheetNotFound:
        print("[AUTH] No auth_log found")

async def set_bot_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Show menu"),
        BotCommand("auth", "Authenticate"),
        BotCommand("lookup", "Search user"),
        BotCommand("help", "Help info"),
    ])

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
