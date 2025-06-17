import os
import json
import gspread
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Load env variables from local .env or Railway
load_dotenv()

# Get environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")

if not GOOGLE_CREDS_JSON:
    raise Exception("GOOGLE_CREDS_JSON not found")

# Authenticate with Google Sheets
creds_dict = json.loads(GOOGLE_CREDS_JSON)
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sheet = client.open(GOOGLE_SHEET_NAME).sheet1

# /lookup <user> command — returns all matches
async def lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args).strip().lower()

    if not query:
        await update.message.reply_text("Usage: /lookup <user>")
        return

    records = sheet.get_all_records()
    matches = []

    for row in records:
        user_value = row.get("user", "").strip().lower()
        if user_value == query:
            last_login = row.get("last_login", "N/A")
            agent = row.get("agent", "N/A")
            matches.append(
                f"🧑 User: {row['user']}\n🕒 Last login: {last_login}\n🧭 Agent: {agent}"
            )

    if not matches:
        await update.message.reply_text("🚫 No matches found.")
    else:
        response = "\n\n".join(matches)
        await update.message.reply_text(response)

# Set up the Telegram bot
app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
app.add_handler(CommandHandler("lookup", lookup))

print("✅ Bot running...")
app.run_polling()
