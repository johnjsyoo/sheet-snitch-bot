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
from gspread.exceptions import APIError, WorksheetNotFound

# Load env vars
load_dotenv()
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_SHEET_NAME   = os.getenv("GOOGLE_SHEET_NAME")
GOOGLE_CREDS_JSON   = os.getenv("GOOGLE_CREDS_JSON")
AUTH_CODES          = json.loads(os.getenv("AUTH_CODES", '{}'))

if not (TELEGRAM_BOT_TOKEN and GOOGLE_SHEET_NAME and GOOGLE_CREDS_JSON and AUTH_CODES):
    raise Exception("Missing one or more required environment variables.")

# Google Sheets setup
dict_creds = json.loads(GOOGLE_CREDS_JSON)
scope      = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds      = ServiceAccountCredentials.from_json_keyfile_dict(dict_creds, scope)
client     = gspread.authorize(creds)

# Cache
authorized_cache = {}  # user_id -> role
sheet_cache      = []  # full sheet contents
sheet_loaded_at  = None

# Refresh sheet data to avoid API overuse
def refresh_sheet_cache():
    global sheet_cache, sheet_loaded_at
    try:
        sheet_cache = client.open(GOOGLE_SHEET_NAME).sheet1.get_all_records()
        sheet_loaded_at = datetime.utcnow()
        print("[CACHE] Sheet data refreshed.")
    except APIError as e:
        print(f"[ERROR] Failed to refresh sheet cache: {e}")
        raise

# Logging auth
def log_user_auth(user_id: int, role: str):
    uid = str(user_id)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    try:
        ws = client.open(GOOGLE_SHEET_NAME)
        try:
            auth_ws = ws.worksheet("auth_log")
        except WorksheetNotFound:
            auth_ws = ws.add_worksheet("auth_log", rows="100", cols="3")
            auth_ws.update("A1:C1", [["user_id", "last_login", "role"]])

        records = auth_ws.get_all_records()
        ids = [str(r.get("user_id", "")).strip() for r in records]

        if uid in ids:
            row = ids.index(uid) + 2
            auth_ws.update(f"B{row}", now)
            auth_ws.update(f"C{row}", role)
        else:
            auth_ws.append_row([uid, now, role])

        authorized_cache[uid] = role
    except Exception as e:
        print(f"[ERROR] Auth logging failed: {e}")

# Authorization check
def get_user_role(user_id: int) -> str | None:
    uid = str(user_id)
    if uid in authorized_cache:
        return authorized_cache[uid]
    try:
        ws = client.open(GOOGLE_SHEET_NAME).worksheet("auth_log")
        records = ws.get_all_records()
        for row in records:
            if str(row.get("user_id", "")).strip() == uid:
                role = row.get("role", "").strip()
                authorized_cache[uid] = role
                return role
    except Exception as e:
        print(f"[AUTH] Sheet check failed: {e}")
    return None

# Inline menu
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Lookup", callback_data="lookup"),
         InlineKeyboardButton("🔓 Authenticate", callback_data="auth")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")],
    ])

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📍 Welcome to SheetSnitchBot!", reply_markup=main_menu())

# /auth
async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code    = " ".join(context.args).strip().lower()

    role = AUTH_CODES.get(code)
    if not role:
        await update.message.reply_text("❌ Invalid code. Try again.")
        return

    log_user_auth(user_id, role)
    await asyncio.sleep(1.5)
    if get_user_role(user_id):
        await update.message.reply_text(f"✅ Auth successful as {role}. You can now use /lookup.")
    else:
        await update.message.reply_text("⚠️ Please retry /lookup in a moment.")

# /lookup
async def lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role    = get_user_role(user_id)
    if not role:
        await update.message.reply_text("🚫 You are not authorized. Use /auth <code> to gain access.")
        return

    query = " ".join(context.args).strip().lower()
    if not query:
        await update.message.reply_text("Usage: /lookup <name|customer|password>")
        return

    try:
        if not sheet_cache:
            refresh_sheet_cache()
        matches = []
        for row in sheet_cache:
            name      = str(row.get("name", "")).strip().lower()
            customer  = str(row.get("customer", "")).strip().lower()
            password  = str(row.get("password", "")).strip().lower()

            if (query == name or query == customer or query == password):
                result = [
                    f"👤 Name: {row.get('name')}",
                    f"🆔 Customer: {row.get('customer')}",
                    f"🔐 Password: {row.get('password') if (query == password or role == 'admin') else '••••••'}",
                    f"🧾 Notes: {row.get('player_notes', 'N/A')}",
                ]
                matches.append("\n".join(result))

        await update.message.reply_text("\n\n".join(matches) if matches else "🚫 No matches found.")
    except APIError as e:
        await update.message.reply_text("⚠️ Error accessing sheet: API quota exceeded. Try again soon.")
        print(f"[ERROR] {e}")

# Menu button handler
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
            "`/auth <code>` – Authenticate as user/admin\n"
            "`/lookup <query>` – Lookup by name, customer, or password\n"
            "`/start` – Show this menu",
            parse_mode="Markdown"
        )

# Set slash commands
async def set_bot_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Show main menu"),
        BotCommand("auth",  "Authenticate with code"),
        BotCommand("lookup", "Search data"),
        BotCommand("help",  "Show help menu"),
    ])

# Preload auth log
async def preload_auth_log():
    try:
        auth_ws = client.open(GOOGLE_SHEET_NAME).worksheet("auth_log")
        records = auth_ws.get_all_records()
        for rec in records:
            uid  = str(rec.get("user_id", "")).strip()
            role = rec.get("role", "").strip()
            if uid and role:
                authorized_cache[uid] = role
        print(f"[AUTH] Preloaded {len(authorized_cache)} users.")
    except WorksheetNotFound:
        print("[AUTH] No auth_log found.")

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
