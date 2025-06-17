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

AUTHORIZED_CACHE = set()

def log_user_auth(user_id):
    sheet_file = client.open(GOOGLE_SHEET_NAME)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    uid = str(user_id)

    try:
        auth_sheet = sheet_file.worksheet("auth_log")
    except gspread.exceptions.WorksheetNotFound:
        auth_sheet = sheet_file.add_worksheet(title="auth_log", rows="100", cols="2")
        auth_sheet.update("A1:B1", [["user_id", "last_login"]])

    all_values = auth_sheet.get_all_values()
    rows = all_values[1:] if len(all_values) > 1 else []
    user_ids = [row[0] for row in rows]

    if uid in user_ids:
        row_index = user_ids.index(uid) + 2
        auth_sheet.update(f"B{row_index}", now)
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
        authorized_ids = [row[0] for row in rows if row]
        if uid in authorized_ids:
            AUTHORIZED_CACHE.add(uid)
            return True
        return False
    except gspread.exceptions.WorksheetNotFound:
        return False

def main_menu():
    keyboard = [
        [
            InlineKeyboardButton("\U0001F50D Lookup", callback_data="lookup"),
            InlineKeyboardButton("\U0001F513 Authenticate", callback_data="auth"),
        ],
        [InlineKeyboardButton("\u2139\ufe0f Help", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("\ud83d\udccd Welcome to SheetSnitchBot!", reply_markup=main_menu())

async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = " ".join(context.args).strip().lower()
    expected = AUTH_CODE.strip().lower()

    if code == expected:
        log_user_auth(user_id)
        await asyncio.sleep(1.5)
        if is_user_authorized(user_id):
            await update.message.reply_text("\u2705 Auth successful! You can now use /lookup.")
        else:
            await update.message.reply_text("\u26a0\ufe0f Auth delay. Try again shortly.")
    else:
        await update.message.reply_text("\u274c Invalid code. Try again.")

async def lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_user_authorized(user_id):
        await update.message.reply_text("\ud83d\udeab You are not authorized. Use /auth <code> to gain access.")
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
            matches.append(f"\U0001F464 User: {row['user']}\n\U0001F552 Last login: {last_login}\n\U0001F6F1 Agent: {agent}")

    if not matches:
        await update.message.reply_text("\ud83d\udeab No matches found.")
    else:
        await update.message.reply_text("\n\n".join(matches))

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "lookup":
        await query.message.reply_text("\U0001F50D To look up a user, type:\n`/lookup <username>`", parse_mode="Markdown")
    elif data == "auth":
        await query.message.reply_text("\U0001F512 To authenticate, type:\n`/auth <code>`", parse_mode="Markdown")
    elif data == "help":
        await query.message.reply_text(
            "\u2139\ufe0f *Help Menu*\n\n"
            "`/auth <code>` – Authenticate to use this bot\n"
            "`/lookup <user>` – Search the data\n"
            "`/start` – Show main menu",
            parse_mode="Markdown"
        )

async def set_bot_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Show main menu"),
        BotCommand("auth", "Authenticate with access code"),
        BotCommand("lookup", "Search user data"),
        BotCommand("help", "Show help menu"),
    ])

app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("auth", auth))
app.add_handler(CommandHandler("lookup", lookup))
app.add_handler(CallbackQueryHandler(menu_handler))
app.post_init = set_bot_commands

print("\u2705 Bot is running...")
app.run_polling()