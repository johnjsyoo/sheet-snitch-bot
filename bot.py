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
AUTH_CODE = os.getenv("AUTH_CODE", "batman")  # Default code

if not GOOGLE_CREDS_JSON:
    raise Exception("GOOGLE_CREDS_JSON not found")

# Google Sheets auth
creds_dict = json.loads(GOOGLE_CREDS_JSON)
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sheet = client.open(GOOGLE_SHEET_NAME).sheet1

# Track authorized users
AUTHORIZED_USERS = set()

# Inline main menu
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
    await update.message.reply_text(
        "📍 Welcome to SheetSnitchBot!", reply_markup=main_menu()
    )

# /auth <code>
async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = " ".join(context.args).strip().lower()
    expected = AUTH_CODE.strip().lower()

    if code == expected:
        AUTHORIZED_USERS.add(user_id)
        await update.message.reply_text("✅ Auth successful! You can now use /lookup.")
    else:
        await update.message.reply_text("❌ Invalid code. Try again.")

# /lookup <username>
async def lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text(
            "🚫 You are not authorized. Use /auth <code> to gain access."
        )
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

# Button click handler
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "lookup":
        await query.message.reply_text(
            "🔍 To look up a user, type:\n`/lookup <username>`", parse_mode="Markdown"
        )
    elif data == "auth":
        await query.message.reply_text(
            "🔐 To authenticate, type:\n`/auth batman`", parse_mode="Markdown"
        )
    elif data == "help":
        await query.message.reply_text(
            "ℹ️ *Help Menu*\n\n"
            "`/auth <code>` – Authenticate to use this bot\n"
            "`/lookup <user>` – Search the data\n"
            "`/start` – Return to this menu",
            parse_mode="Markdown"
        )

# Telegram command hints (BotFather-style)
async def set_bot_commands(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Show main menu"),
        BotCommand("auth", "Authenticate with access code"),
        BotCommand("lookup", "Search user data"),
        BotCommand("help", "Show help menu"),
    ])

# Build app
app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

# Register handlers
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("auth", auth))
app.add_handler(CommandHandler("lookup", lookup))
app.add_handler(CallbackQueryHandler(menu_handler))

# Run setup on boot
app.post_init = set_bot_commands

print("✅ Bot is running...")
app.run_polling()
