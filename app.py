import os
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]

bot_app = ApplicationBuilder().token(BOT_TOKEN).build()
app = FastAPI()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("機器人已啟動 ✅")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "可用指令：\n"
        "/start\n"
        "/help\n"
        "/rules"
    )

async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "群規：\n"
        "1. 禁止廣告\n"
        "2. 禁止私聊拉人\n"
        "3. 禁止刷屏"
    )

bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("help", help_command))
bot_app.add_handler(CommandHandler("rules", rules))

@app.on_event("startup")
async def startup():
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.bot.set_webhook(
        url=WEBHOOK_URL,
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True,
    )

@app.on_event("shutdown")
async def shutdown():
    await bot_app.bot.delete_webhook()
    await bot_app.stop()
    await bot_app.shutdown()

@app.get("/")
async def home():
    return {"ok": True}

@app.post("/webhook")
async def telegram_webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        return {"ok": False, "error": "invalid secret"}
    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return {"ok": True}
