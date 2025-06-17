import os
import json
import gspread
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
AUTH_CODES_JSON    = os.getenv("AUTH_CODES")

if not all([TELEGRAM_BOT_TOKEN, GOOGLE_SHEET_NAME, GOOGLE_CREDS_JSON, AUTH_CODES_JSON]):
    raise Exception("Missing required environment variables")

try:
    AUTH_CODES = json.loads(AUTH_CODES_JSON)
except json.JSONDecodeError:
    raise Exception("AUTH_CODES must be a valid JSON string (e.g. {\"batman\": \"user\", \"daddy\": \"admin\"})")

# Google Sheets setup
creds = ServiceAccountCredentials.from_json_keyfile_dict(
    json.loads(GOOGLE_CREDS_JSON),
    ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
)
client = gspread.authorize(creds)
sheet = client.open(GOOGLE_SHEET_NAME).sheet1  # assumes headers in row 1

# In-memory cache of authenticated users and their roles
authorized_users = {}

def log_user_auth(user_id: int, role: str):
    uid = str(user_id)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    try:
        auth_ws = client.open(GOOGLE_SHEET_NAME).worksheet("auth_log")
    except gspread.exceptions.WorksheetNotFound:
        auth_ws = client.open(GOOGLE_SHEET_NAME).add_worksheet(title="auth_log", rows="100", cols="3")
        auth_ws.update("A1:C1", [["user_id", "last_login", "role"]])

    records = auth_ws.get_all_records()
    ids = [str(r.get("user_id", "")).strip() for r in records]

    if uid in ids:
        row_index = ids.index(uid) + 2
        auth_ws.update(f"B{row_index}:C{row_index}", [[now, role]])
    else:
        auth_ws.append_row([uid, now, role])

    authorized_users[uid] = role
    print(f"[AUTH] Logged {uid} as {role}")

def get_user_role(user_id: int):
    uid = str(user_id)
    if uid in authorized_users:
        return authorized_users[uid]
    try:
        auth_ws = client.open(GOOGLE_SHEET_NAME).worksheet("auth_log")
        records = auth_ws.get_all_records()
        for row in records:
            if str(row.get("user_id", "")).strip() == uid:
                role = row.get("role", "user").strip().lower()
                authorized_users[uid] = role
                print(f"[AUTH] Found {uid} in sheet with role: {role}")
                return role
    except gspread.exceptions.WorksheetNotFound:
        pass
    print(f"[AUTH] {uid} not found in auth_log")
    return None

# Menu with no command prefill
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Lookup", callback_data="lookup"),
         InlineKeyboardButton("🔓 Authenticate", callback_data="auth")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📍 Welcome to SheetSnitchBot!", reply_markup=main_menu())

async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = " ".join(context.args).strip().lower()

    if code in AUTH_CODES:
        role = AUTH_CODES[code]
        log_user_auth(user_id, role)
        await update.message.reply_text(f"✅ Auth successful as *{role}*! You can now use /lookup.", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Invalid code. Try again.")

async def lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    query = " ".join(context.args).strip().lower()
    uid = str(user_id)

    role = get_user_role(user_id)
    if not role:
        await update.message.reply_text("🚫 You are not authorized. Use /auth <code> to gain access.")
        return

    if not query:
        await update.message.reply_text("Usage: /lookup <value>")
        return

    records = sheet.get_all_records()
    matches = []

    for row in records:
        name = str(row.get("name", "")).strip().lower()
        customer = str(row.get("customer", "")).strip().lower()
        password = str(row.get("password", "")).strip().lower()

        match = (
            query == customer or
            query == password or
            (len(query.split()) >= 2 and query == name)
        )

        if match:
            pw_display = row.get("password", "")
            if role != "admin" and query != password:
                pw_display = "••••••••"
            matches.append(
                f"👤 Name: {row.get('name','')}\n"
                f"🆔 Customer: {row.get('customer','')}\n"
                f"🔑 Password: {pw_display}\n"
                f"🕒 Last Login: {row.get('last_login','')}\n"
                f"📝 Notes: {row.get('player_notes','')}"
            )

    await update.message.reply_text("\n\n".join(matches) if matches else "🚫 No matches found.")

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "auth":
        await q.message.reply_text("🔐 Authenticate by sending: /auth <code>")
    elif q.data == "lookup":
        await q.message.reply_text("🔍 Lookup by sending: /lookup <value>")
    elif q.data == "help":
        await q.message.reply_text(
            "ℹ️ *Help Menu*\n\n"
            "`/auth <code>` – Authenticate\n"
            "`/lookup <value>` – Search users\n"
            "`/start` – Show this menu",
            parse_mode="Markdown"
        )

async def preload_auth_log():
    try:
        auth_ws = client.open(GOOGLE_SHEET_NAME).worksheet("auth_log")
        records = auth_ws.get_all_records()
        for row in records:
            uid = str(row.get("user_id", "")).strip()
            role = row.get("role", "user").strip().lower()
            if uid:
                authorized_users[uid] = role
        print(f"[AUTH] Preloaded {len(authorized_users)} users.")
    except gspread.exceptions.WorksheetNotFound:
        print("[AUTH] No auth_log sheet found")

async def set_bot_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start",  "Show main menu"),
        BotCommand("auth",   "Authenticate with code"),
        BotCommand("lookup", "Search user data"),
        BotCommand("help",   "Show help menu"),
    ])

# Unified entrypoint for clean asyncio
async def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("auth", auth))
    app.add_handler(CommandHandler("lookup", lookup))
    app.add_handler(CallbackQueryHandler(menu_handler))

    await preload_auth_log()
    await set_bot_commands(app)
    print("✅ Bot is running...")

    # ✅ Run polling inside the async function
    await app.run_polling()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())  # ✅ Single entry point

