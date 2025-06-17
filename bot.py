import os
import json
import gspread
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()

# Credentials from env
creds_json = os.getenv("GOOGLE_CREDS_JSON")
if not creds_json:
    raise Exception("GOOGLE_CREDS_JSON not found")
creds_dict = json.loads(creds_json)

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

sheet_name = os.getenv("GOOGLE_SHEET_NAME")
sheet = client.open(sheet_name).sheet1

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args).strip().lower()
    if not query:
        await update.message.reply_text("Usage: /lookup <keyword>")
        return

    records = sheet.get_all_records()
    for row in records:
        if row["keyword"].lower() == query:
            await update.message.reply_text(row["response"])
            return

    await update.message.reply_text("No match found.")

app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
app.add_handler(CommandHandler("lookup", lookup))

print("Bot running...")
app.run_polling()
