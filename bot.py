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

# ── Load & validate env vars ───────────────────────────────────────────────
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_SHEET_NAME  = os.getenv("GOOGLE_SHEET_NAME")
GOOGLE_CREDS_JSON  = os.getenv("GOOGLE_CREDS_JSON")
AUTH_CODES_JSON    = os.getenv("AUTH_CODES")  # Should be a JSON string

for var in ("TELEGRAM_BOT_TOKEN", "GOOGLE_SHEET_NAME", "GOOGLE_CREDS_JSON", "AUTH_CODES"):
    if not locals()[var]:
        raise Exception(f"{var} is not set")

try:
    AUTH_CODES = json.loads(AUTH_CODES_JSON)
except json.JSONDecodeError:
    raise Exception("AUTH_CODES must be valid JSON, e.g. {\"batman\":\"user\",\"daddy\":\"admin\"}")

# ── Google Sheets setup ─────────────────────────────────────────────────────
creds_dict = json.loads(GOOGLE_CREDS_JSON)
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sheet  = client.open(GOOGLE_SHEET_NAME).sheet1

# ── In-memory cache of authenticated users ──────────────────────────────────
# Maps user_id string → role ("user" or "admin")
authorized_users = {}

# ── Auth logging helpers ────────────────────────────────────────────────────
def log_user_auth(user_id: int, role: str):
    uid = str(user_id)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    ws  = client.open(GOOGLE_SHEET_NAME)
    try:
        auth_ws = ws.worksheet("auth_log")
    except gspread.exceptions.WorksheetNotFound:
        auth_ws = ws.add_worksheet(title="auth_log", rows="100", cols="3")
        auth_ws.update("A1:C1", [["user_id", "last_login", "role"]])
    # Read existing IDs
    records = auth_ws.get_all_records()
    ids     = [str(r.get("user_id","")).strip() for r in records]
    if uid in ids:
        idx = ids.index(uid) + 2  # account for header row
        auth_ws.update(f"B{idx}:C{idx}", [[now, role]])
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
        for rec in auth_ws.get_all_records():
            if str(rec.get("user_id","")).strip() == uid:
                role = rec.get("role","user").strip().lower()
                authorized_users[uid] = role
                print(f"[AUTH] Found {uid} as {role}")
                return role
    except gspread.exceptions.WorksheetNotFound:
        pass
    return None

# ── Inline menu ─────────────────────────────────────────────────────────────
def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 Lookup",       callback_data="lookup"),
            InlineKeyboardButton("🔓 Authenticate", callback_data="auth"),
        ],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")],
    ])

# ── Command handlers ─────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📍 Welcome to SheetSnitchBot!", reply_markup=main_menu())

async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code    = " ".join(context.args).strip().lower()
    role    = AUTH_CODES.get(code)
    if role:
        log_user_auth(user_id, role)
        await update.message.reply_text(f"✅ Auth successful as *{role}*!", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Invalid code. Try again.")

async def lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role    = get_user_role(user_id)
    if not role:
        return await update.message.reply_text("🚫 You are not authorized. Use /auth <code>.")
    query = " ".join(context.args).strip().lower()
    if not query:
        return await update.message.reply_text("Usage: /lookup <value>")

    records = sheet.get_all_records()
    matches = []

    for row in records:
        name     = str(row.get("name","")).strip().lower()
        customer = str(row.get("customer","")).strip().lower()
        password = str(row.get("password","")).strip().lower()

        # Exact match logic
        if query in (name, customer, password):
            # Mask password unless admin or looked up by password
            display_pw = row.get("password","")
            if role != "admin" and query != password:
                display_pw = "••••••••"

            matches.append(
                "🔹 Match:\n"
                f"👤 Name: {row.get('name','')}\n"
                f"🆔 Customer: {row.get('customer','')}\n"
                f"🔑 Password: {display_pw}\n"
                f"💰 Balance: {row.get('balance','')}\n"
                f"⏰ Last Login: {row.get('last_login','')}\n"
                f"📝 Notes: {row.get('player_notes','')}"
            )

    if not matches:
        return await update.message.reply_text("🚫 No matches found.")

    # Telegram limits to 4096 chars
    text = "\n\n".join(matches)
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        await update.message.reply_text(chunk)

# ── Callback query handler ─────────────────────────────────────────────────
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "auth":
        await q.message.reply_text("🔐 Authenticate by sending: /auth <code>")
    elif q.data == "lookup":
        await q.message.reply_text("🔍 Lookup by sending: /lookup <value>")
    else:
        await q.message.reply_text(
            "ℹ️ *Help Menu*\n\n"
            "`/auth <code>` – Authenticate\n"
            "`/lookup <value>` – Lookup data\n"
            "`/start` – Show this menu",
            parse_mode="Markdown"
        )

# ── post_init: preload auth_log & set slash commands ────────────────────────
async def on_startup(app):
    # Preload auth_log
    try:
        auth_ws = client.open(GOOGLE_SHEET_NAME).worksheet("auth_log")
        for rec in auth_ws.get_all_records():
            uid  = str(rec.get("user_id","")).strip()
            role = rec.get("role","user").strip().lower()
            if uid:
                authorized_users[uid] = role
        print(f"[AUTH] Preloaded {len(authorized_users)} users.")
    except gspread.exceptions.WorksheetNotFound:
        print("[AUTH] No auth_log sheet found.")

    # Register commands in Telegram UI
    await app.bot.set_my_commands([
        BotCommand("start",  "Show main menu"),
        BotCommand("auth",   "Authenticate with code"),
        BotCommand("lookup", "Search user data"),
        BotCommand("help",   "Show help menu"),
    ])

# ── Entrypoint ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("auth",    auth))
    app.add_handler(CommandHandler("lookup",  lookup))
    app.add_handler(CallbackQueryHandler(menu_handler))

    # Hook up our startup logic
    app.post_init = on_startup

    # Start polling (no asyncio.run() needed here)
    print("✅ Bot is running…")
    app.run_polling()
