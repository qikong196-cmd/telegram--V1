import os
import logging
from fastapi import FastAPI, Request, Response
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    ChatMemberHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

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
            "/start - 启动机器人\n"
            "/help - 查看帮助\n"
            "/rules - 查看群规\n\n"
            "也可以直接发送：资源 / 客服"
        )


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "群规：\n"
            "1. 禁止广告\n"
            "2. 禁止私聊拉人\n"
            "3. 禁止刷屏\n"
            "4. 违规将处理"
        )


async def keyword_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if "资源" in text:
        await update.message.reply_text("资源入口稍后补上，你也可以先查看置顶消息。")
    elif "客服" in text:
        await update.message.reply_text("如需帮助，请联系管理员。")


# 方式1：通过 message.new_chat_members 欢迎
async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return

    logger.info("收到 new_chat_members 事件")

    for user in update.message.new_chat_members:
        await update.message.reply_text(
            f"欢迎 {user.first_name} 🔥\n\n"
            "请先查看群规 /rules\n"
            "发送【资源】获取内容\n"
            "发送【客服】联系管理员"
        )


# 方式2：通过 chat_member 更新欢迎
async def welcome_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.chat_member:
        return

    logger.info("收到 chat_member 事件: %s", update.chat_member)

    old_status = update.chat_member.old_chat_member.status
    new_status = update.chat_member.new_chat_member.status
    user = update.chat_member.new_chat_member.user
    chat_id = update.chat_member.chat.id

    joined = old_status in ("left", "kicked") and new_status in (
        "member",
        "administrator",
        "restricted",
    )

    if joined:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"欢迎 {user.first_name} 🔥\n\n"
                "请先查看群规 /rules\n"
                "发送【资源】获取内容\n"
                "发送【客服】联系管理员"
            ),
        )


bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("help", help_command))
bot_app.add_handler(CommandHandler("rules", rules))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, keyword_reply))
bot_app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_members))
bot_app.add_handler(ChatMemberHandler(welcome_chat_member, ChatMemberHandler.CHAT_MEMBER))


@app.on_event("startup")
async def startup():
    await bot_app.initialize()
    await bot_app.start()

    await bot_app.bot.set_webhook(
        url=WEBHOOK_URL,
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )

    logger.info("Webhook 已设置: %s", WEBHOOK_URL)


@app.on_event("shutdown")
async def shutdown():
    await bot_app.bot.delete_webhook()
    await bot_app.stop()
    await bot_app.shutdown()


@app.get("/")
async def home():
    return {"ok": True, "status": "running"}


@app.head("/")
async def home_head():
    return Response(status_code=200)


@app.post("/webhook")
async def telegram_webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        return {"ok": False, "error": "invalid secret"}

    data = await request.json()
    update = Update.de_json(data, bot_app.bot)

    logger.info("收到 update: %s", update)

    await bot_app.process_update(update)
    return {"ok": True}
