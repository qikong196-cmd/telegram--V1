import os
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    ChatMemberHandler,
    filters,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]

bot_app = ApplicationBuilder().token(BOT_TOKEN).build()
app = FastAPI()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("机器人已启动 ✅")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "可用指令：\n"
            "/start\n"
            "/help\n"
            "/rules"
        )


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "群规：\n"
            "1. 禁止广告\n"
            "2. 禁止私聊拉人\n"
            "3. 禁止刷屏"
        )


async def keyword_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if "资源" in text:
        await update.message.reply_text("资源入口稍后补上，你也可以先看置顶消息。")
    elif "客服" in text:
        await update.message.reply_text("如需帮助，请联系管理员。")


async def welcome_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_member_update = update.chat_member
    if not chat_member_update:
        return

    old_status = chat_member_update.old_chat_member.status
    new_status = chat_member_update.new_chat_member.status
    user = chat_member_update.new_chat_member.user

    joined = old_status in ("left", "kicked") and new_status in ("member", "administrator", "restricted")

    if joined:
        await context.bot.send_message(
            chat_id=chat_member_update.chat.id,
            text=(
                f"欢迎 {user.first_name} 🔥\n\n"
                "请先查看群规 /rules\n"
                "发送【资源】获取内容"
            ),
        )


bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("help", help_command))
bot_app.add_handler(CommandHandler("rules", rules))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, keyword_reply))
bot_app.add_handler(ChatMemberHandler(welcome_chat_member, ChatMemberHandler.CHAT_MEMBER))


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
