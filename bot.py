import os
import json
import gspread
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

# Validate environment
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

# Auth log helpers
def is_user_authorized(user_id):
    try:
        auth_sheet = client.open(GOOGLE_SHEET_NAME).worksheet("auth_log")
        authorized_ids = [row[0] for row in auth_sheet.get_all_values()]
        return str(user_id) in authorized_ids
    except gspread.exceptions.WorksheetNotFound:
        return False

def log_user_auth(user_id):
    try:
        auth_sheet = client.open(GOOGLE_SHEET_NAME).worksheet("auth_log")
    except gspread.exceptions.WorksheetNotFound:
        auth_sheet = client.open(GOOGLE_SHEET_NAME).add_worksheet(title="auth_log", rows="100", cols="1")
        auth_sheet.append_row(["user_id"])
    auth_sheet.append_row([str(user_id)])

# Menu layout
def main_menu():
    keyboard = [
        [
            InlineKeyboardButton("🔍 Lookup", callback_data="lookup"),
            InlineKeyboardButton("🔓 Authenticate", callback_data="auth"),
        ],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📍 Welcome to SheetSnitchBot!", reply_markup=main_menu())

# /auth <code>
async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = " ".join(context.args).strip().lower()
    expected = AUTH_CODE.strip().lower()

    if code == expected:
        log_user_auth(user_id)
        await update.message.reply_text("✅ Auth successful! You can now use /lookup.")
    else:
        await update.message.reply_text("❌ Invalid code. Try again.")

# /lookup <user>
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
        user_val = row.get("user", "").strip().lower()
        if user_val == query:
            last_login = row.get("last_login", "N/A")
            agent = row.get("agent", "N/A")
            matches.append(
                f"🧑 User: {row['user']}\n🕒 Last login: {last_login}\n🧭 Agent: {agent}"
            )

    if not matches:
        await update.message.reply_text("🚫 No matches found.")
    else:
        await update.message.reply_text("\n\n".join(matches))

# Button handler
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "lookup":
        await query.message.reply_text("🔍 Type: `/lookup <username>`", parse_mode="Markdown")
    elif data == "auth":
        await query.message.reply_text("🔐 Type: `/auth <code>`", parse_mode="Markdown")
    elif data == "help":
        await query.message.reply_text(
            "ℹ️ *Help Menu*\n\n"
            "`/auth <code>` – Authenticate to use this bot\n"
            "`/lookup <user>` – Search the data\n"
            "`/start` – Show this menu",
            parse_mode="Markdown"
        )

# BotFather-style commands
async def set_bot_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Show main menu"),
        BotCommand("auth", "Authenticate with access code"),
        BotCommand("lookup", "Search user data"),
        BotCommand("help", "Show help menu"),
    ])

# Launch bot
app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("auth", auth))
app.add_handler(CommandHandler("lookup", lookup))
app.add_handler(CallbackQueryHandler(menu_handler))
app.post_init = set_bot_commands

print("✅ Bot is running...")
app.run_polling()
