import os
import json
import gspread
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")

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

# Auth system
AUTH_CODE = "batman"
AUTHORIZED_USERS = set()

async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = ' '.join(context.args).strip()

    if code == AUTH_CODE:
        AUTHORIZED_USERS.add(user_id)
        await update.message.reply_text("✅ Auth successful! You can now use /lookup.")
    else:
        await update.message.reply_text("❌ Invalid code. Try again.")

async def lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("🚫 You are not authorized. Use /auth <code> to gain access.")
        return

    query = ' '.join(context.args).strip().lower()
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

# Bot setup
app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
app.add_handler(CommandHandler("auth", auth))
app.add_handler(CommandHandler("lookup", lookup))

print("✅ Bot running...")
app.run_polling()
