import os
import logging
from fastapi import FastAPI, Request, Response
from telegram import Update, ChatPermissions
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
REQUIRED_CHANNEL = os.environ["REQUIRED_CHANNEL"]  # 例如：@ai_r444

bot_app = ApplicationBuilder().token(BOT_TOKEN).build()
app = FastAPI()


# ===== 工具函数 =====

def is_group_chat(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type in ("group", "supergroup"))


async def is_user_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """
    检查用户是否已加入指定频道
    """
    try:
        member = await context.bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status in ("member", "administrator", "creator", "owner")
    except Exception as e:
        logger.warning("检查频道订阅失败: %s", e)
        return False


async def mute_user(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int):
    """
    禁言用户
    """
    await context.bot.restrict_chat_member(
        chat_id=chat_id,
        user_id=user_id,
        permissions=ChatPermissions(
            can_send_messages=False,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_manage_topics=False,
        ),
    )


async def unmute_user(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int):
    """
    解禁用户
    """
    await context.bot.restrict_chat_member(
        chat_id=chat_id,
        user_id=user_id,
        permissions=ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_manage_topics=False,
        ),
    )


async def is_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator", "owner")
    except Exception:
        return False


# ===== 指令 =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("机器人已启动 ✅")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "可用指令：\n"
            "/start - 启动机器人\n"
            "/help - 查看帮助\n"
            "/rules - 查看群规\n"
            "/verify - 手动验证频道关注并解禁\n\n"
            "关键词：资源 / 客服"
        )


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "群规：\n"
            "1. 禁止广告\n"
            "2. 禁止私聊拉人\n"
            "3. 禁止刷屏\n"
            "4. 进群后需先关注指定频道\n"
            "5. 违规将处理"
        )


async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.effective_chat:
        return

    user = update.effective_user
    chat_id = update.effective_chat.id

    subscribed = await is_user_subscribed(context, user.id)

    if subscribed:
        await unmute_user(context, chat_id, user.id)
        if update.message:
            await update.message.reply_text(f"{user.first_name} ✅ 验证成功，已解除禁言。")
    else:
        if update.message:
            await update.message.reply_text(
                "你还没有关注频道。\n\n"
                f"请先加入频道：{REQUIRED_CHANNEL}\n"
                "加入后再发送 /verify"
            )


# ===== 关键词回复 =====

async def keyword_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if "资源" in text:
        await update.message.reply_text("资源入口稍后补上（这里替换成你的链接）")
    elif "客服" in text:
        await update.message.reply_text("如需帮助，请联系管理员。")


# ===== 欢迎 =====

async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return

    logger.info("收到 new_chat_members")

    for user in update.message.new_chat_members:
        if user.is_bot:
            continue

        subscribed = await is_user_subscribed(context, user.id)

        if not subscribed:
            try:
                await mute_user(context, update.effective_chat.id, user.id)
            except Exception as e:
                logger.warning("禁言失败: %s", e)

            await update.message.reply_text(
                f"欢迎 {user.first_name} 🔥\n\n"
                f"请先关注频道：{REQUIRED_CHANNEL}\n"
                "关注后回群随便发一句话，即可自动解禁。"
            )
        else:
            await update.message.reply_text(
                f"欢迎 {user.first_name} 🔥\n\n"
                "你已通过频道检查，可以正常发言。\n"
                "请先查看群规 /rules"
            )


async def welcome_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.chat_member:
        return

    logger.info("收到 chat_member 事件")

    old_status = update.chat_member.old_chat_member.status
    new_status = update.chat_member.new_chat_member.status
    user = update.chat_member.new_chat_member.user
    chat_id = update.chat_member.chat.id

    joined = old_status in ("left", "kicked") and new_status in (
        "member",
        "administrator",
        "restricted",
    )

    if joined and not user.is_bot:
        subscribed = await is_user_subscribed(context, user.id)

        if not subscribed:
            try:
                await mute_user(context, chat_id, user.id)
            except Exception as e:
                logger.warning("禁言失败: %s", e)

            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"欢迎 {user.first_name} 🔥\n\n"
                    f"请先关注频道：{REQUIRED_CHANNEL}\n"
                    "关注后回群随便发一句话，即可自动解禁。"
                ),
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"欢迎 {user.first_name} 🔥\n\n"
                    "你已通过频道检查，可以正常发言。\n"
                    "请先查看群规 /rules"
                ),
            )


# ===== 未关注频道时拦截发言 / 已关注自动解禁 =====

async def block_unsubscribed_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user or not update.effective_chat:
        return

    if not is_group_chat(update):
        return

    user = update.effective_user
    chat_id = update.effective_chat.id

    if user.is_bot:
        return

    if await is_admin(context, chat_id, user.id):
        return

    subscribed = await is_user_subscribed(context, user.id)

    if subscribed:
        try:
            await unmute_user(context, chat_id, user.id)
            await update.message.reply_text(
                f"{user.first_name} ✅ 已检测到你已关注频道，已自动解除禁言。"
            )
        except Exception as e:
            logger.warning("自动解禁失败: %s", e)
        return

    try:
        await update.message.delete()
    except Exception as e:
        logger.warning("删除消息失败: %s", e)

    try:
        await mute_user(context, chat_id, user.id)
    except Exception as e:
        logger.warning("禁言失败: %s", e)

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"{user.first_name} ❌ 你还没有关注频道\n"
            f"👉 请先加入：{REQUIRED_CHANNEL}\n"
            "加入后回群随便发一句话即可自动解禁"
        ),
    )


# ===== 注册 handler =====

bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("help", help_command))
bot_app.add_handler(CommandHandler("rules", rules))
bot_app.add_handler(CommandHandler("verify", verify))

bot_app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_members))
bot_app.add_handler(ChatMemberHandler(welcome_chat_member, ChatMemberHandler.CHAT_MEMBER))

bot_app.add_handler(
    MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL) & ~filters.COMMAND,
        block_unsubscribed_messages,
    )
)

bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, keyword_reply))


# ===== 启动 =====

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

    logger.info("Webhook 已设置成功")


# ===== 关闭 =====

@app.on_event("shutdown")
async def shutdown():
    await bot_app.stop()
    await bot_app.shutdown()


# ===== 健康检查 =====

@app.get("/")
async def home():
    return {"ok": True}


@app.head("/")
async def head():
    return Response(status_code=200)


# ===== webhook 接收 =====

@app.post("/webhook")
async def telegram_webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        return {"ok": False, "error": "invalid secret"}

    data = await request.json()
    update = Update.de_json(data, bot_app.bot)

    logger.info("收到 update")
    await bot_app.process_update(update)
    return {"ok": True}
