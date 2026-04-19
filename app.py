import os
import time
import asyncio
import logging
from collections import defaultdict, deque

from fastapi import FastAPI, Request, Response
from telegram import (
    Update,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    ChatMemberHandler,
    CallbackQueryHandler,
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
REQUIRED_CHANNEL = os.environ["REQUIRED_CHANNEL"]  # 例如 @ai_r444

# 黑名单关键词：英文逗号分隔
# 例如：菠菜,兼职,日结,担保,代付,外围,送彩金,客服飞机
BLACKLIST_KEYWORDS = [
    x.strip().lower()
    for x in os.environ.get("BLACKLIST_KEYWORDS", "").split(",")
    if x.strip()
]

# 白名单用户ID：英文逗号分隔
# 例如：123456789,987654321
WHITELIST_USER_IDS = {
    int(x.strip())
    for x in os.environ.get("WHITELIST_USER_IDS", "").split(",")
    if x.strip().isdigit()
}

# 防刷配置
RATE_LIMIT_COUNT = int(os.environ.get("RATE_LIMIT_COUNT", "5"))       # 时间窗内最多消息数
RATE_LIMIT_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW", "10"))    # 时间窗秒数
FLOOD_MUTE_SECONDS = int(os.environ.get("FLOOD_MUTE_SECONDS", "300")) # 超频禁言秒数

bot_app = ApplicationBuilder().token(BOT_TOKEN).build()
app = FastAPI()

# 每个用户在群里的验证消息，只保留一条
VERIFY_MSG = defaultdict(set)

# 每个用户发言频率记录
USER_MESSAGE_LOGS = defaultdict(deque)


# ===== 工具函数 =====

def get_verify_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👉 关注频道", url=f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}")],
        [InlineKeyboardButton("✅ 已关注，点击解禁", callback_data="verify_subscription")]
    ])


def get_message_text(update: Update) -> str:
    if not update.message:
        return ""
    text = update.message.text or ""
    caption = update.message.caption or ""
    return f"{text}\n{caption}".strip().lower()


def is_whitelisted(user_id: int) -> bool:
    return user_id in WHITELIST_USER_IDS


def contains_ad_keywords(text: str) -> bool:
    if not text:
        return False

    # 自定义黑词
    for kw in BLACKLIST_KEYWORDS:
        if kw and kw in text:
            return True

    # 内置常见广告/引流模式
    common_spam_patterns = [
        "http://", "https://", "t.me/", "@",
        "wx", "vx", "飞机", "电报联系",
        "私聊", "加我", "联系我",
        "担保", "代付", "日结", "兼职",
        "返利", "代理", "推广", "合作",
        "客服", "咨询", "外围", "彩票",
        "菠菜", "担保群", "出入款", "通道"
    ]
    return any(p in text for p in common_spam_patterns)


async def delete_user_message(update: Update):
    if update.message:
        try:
            await update.message.delete()
        except Exception:
            pass


async def safe_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, msg_id: int):
    try:
        await context.bot.delete_message(chat_id, msg_id)
    except Exception:
        pass


async def delete_later(context: ContextTypes.DEFAULT_TYPE, chat_id: int, msg_id: int, seconds: int = 5):
    await asyncio.sleep(seconds)
    await safe_delete(context, chat_id, msg_id)


async def send_temp_text(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, seconds: int = 5):
    try:
        msg = await context.bot.send_message(chat_id, text)
        context.application.create_task(delete_later(context, chat_id, msg.message_id, seconds))
    except Exception:
        pass


async def is_sub(context: ContextTypes.DEFAULT_TYPE, uid: int) -> bool:
    try:
        member = await context.bot.get_chat_member(REQUIRED_CHANNEL, uid)
        return member.status in ("member", "administrator", "creator", "owner")
    except Exception as e:
        logger.warning("频道检查失败 uid=%s err=%s", uid, e)
        return False


async def mute(context: ContextTypes.DEFAULT_TYPE, cid: int, uid: int):
    await context.bot.restrict_chat_member(
        cid,
        uid,
        ChatPermissions(can_send_messages=False),
    )


async def mute_for_seconds(context: ContextTypes.DEFAULT_TYPE, cid: int, uid: int, seconds: int):
    until_date = int(time.time()) + seconds
    await context.bot.restrict_chat_member(
        cid,
        uid,
        ChatPermissions(can_send_messages=False),
        until_date=until_date,
    )


async def unmute(context: ContextTypes.DEFAULT_TYPE, cid: int, uid: int):
    await context.bot.restrict_chat_member(
        cid,
        uid,
        ChatPermissions(can_send_messages=True),
    )


async def ban_user(context: ContextTypes.DEFAULT_TYPE, cid: int, uid: int):
    await context.bot.ban_chat_member(cid, uid)


async def is_admin(context: ContextTypes.DEFAULT_TYPE, cid: int, uid: int) -> bool:
    try:
        member = await context.bot.get_chat_member(cid, uid)
        return member.status in ("administrator", "creator", "owner")
    except Exception:
        return False


async def send_verify(context: ContextTypes.DEFAULT_TYPE, cid: int, user):
    # 删除旧验证消息，只保留一条
    for mid in VERIFY_MSG[(cid, user.id)]:
        await safe_delete(context, cid, mid)
    VERIFY_MSG[(cid, user.id)].clear()

    msg = await context.bot.send_message(
        cid,
        f"请先关注频道：{REQUIRED_CHANNEL}",
        reply_markup=get_verify_keyboard(),
    )
    VERIFY_MSG[(cid, user.id)].add(msg.message_id)


async def clear_verify(context: ContextTypes.DEFAULT_TYPE, cid: int, uid: int):
    for mid in VERIFY_MSG[(cid, uid)]:
        await safe_delete(context, cid, mid)
    VERIFY_MSG.pop((cid, uid), None)


def hit_rate_limit(chat_id: int, user_id: int) -> bool:
    now = time.time()
    q = USER_MESSAGE_LOGS[(chat_id, user_id)]

    while q and now - q[0] > RATE_LIMIT_WINDOW:
        q.popleft()

    q.append(now)
    return len(q) > RATE_LIMIT_COUNT


# ===== 指令（全部隐藏） =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_user_message(update)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_user_message(update)


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_user_message(update)


async def verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_user_message(update)

    if not update.effective_user or not update.effective_chat:
        return

    user = update.effective_user
    cid = update.effective_chat.id

    if await is_sub(context, user.id):
        await unmute(context, cid, user.id)
        await clear_verify(context, cid, user.id)


# ===== 按钮验证 =====

async def verify_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.message:
        return

    await query.answer()

    user = query.from_user
    cid = query.message.chat.id

    if await is_sub(context, user.id):
        await unmute(context, cid, user.id)

        try:
            await query.message.delete()
        except Exception:
            pass

        await clear_verify(context, cid, user.id)
        await query.answer("已解禁", show_alert=False)
    else:
        await query.answer("请先关注频道", show_alert=True)


# ===== 新人入群 =====

async def handle_new_user(context: ContextTypes.DEFAULT_TYPE, cid: int, user):
    if user.is_bot:
        return

    if is_whitelisted(user.id):
        return

    # 已在频道中，不处理
    if await is_sub(context, user.id):
        return

    # 未关注：先禁言，再发验证
    await mute(context, cid, user.id)
    await send_verify(context, cid, user)


async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    # 删掉 Telegram 的入群系统消息
    try:
        await update.message.delete()
    except Exception:
        pass

    for user in update.message.new_chat_members:
        await handle_new_user(context, update.effective_chat.id, user)


async def chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.chat_member:
        return

    old_status = update.chat_member.old_chat_member.status
    new_status = update.chat_member.new_chat_member.status
    user = update.chat_member.new_chat_member.user
    cid = update.chat_member.chat.id

    # 新成员加入
    if old_status in ("left", "kicked") and new_status in ("member", "restricted", "administrator"):
        await handle_new_user(context, cid, user)


# ===== 主风控：公开入口补漏 + 广告 + 防刷 =====

async def guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user or not update.effective_chat:
        return

    user = update.effective_user
    cid = update.effective_chat.id

    if user.is_bot:
        return

    if is_whitelisted(user.id):
        return

    if await is_admin(context, cid, user.id):
        return

    # 1. 发言触发强制频道验证（补公开群入口的漏）
    if not await is_sub(context, user.id):
        try:
            await update.message.delete()
        except Exception:
            pass

        await mute(context, cid, user.id)
        await send_verify(context, cid, user)
        return

    # 用户已关注频道，清理旧验证消息
    await clear_verify(context, cid, user.id)

    # 2. 防广告
    text = get_message_text(update)
    if contains_ad_keywords(text):
        try:
            await update.message.delete()
        except Exception:
            pass

        try:
            await ban_user(context, cid, user.id)
        except Exception as e:
            logger.warning("封禁失败 uid=%s err=%s", user.id, e)

        await send_temp_text(context, cid, "已处理违规广告账号。", 5)
        return

    # 3. 防刷屏
    if hit_rate_limit(cid, user.id):
        try:
            await update.message.delete()
        except Exception:
            pass

        try:
            await mute_for_seconds(context, cid, user.id, FLOOD_MUTE_SECONDS)
        except Exception as e:
            logger.warning("限速禁言失败 uid=%s err=%s", user.id, e)

        await send_temp_text(context, cid, "发言过快，已临时限制。", 5)
        return


# ===== 注册 handlers =====

bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("help", help_command))
bot_app.add_handler(CommandHandler("rules", rules))
bot_app.add_handler(CommandHandler("verify", verify))

bot_app.add_handler(CallbackQueryHandler(verify_button, pattern="^verify_subscription$"))

bot_app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))
bot_app.add_handler(ChatMemberHandler(chat_member, ChatMemberHandler.CHAT_MEMBER))

# 所有非命令消息都走主风控
bot_app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, guard))


# ===== 启动 / 关闭 =====

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


@app.on_event("shutdown")
async def shutdown():
    await bot_app.stop()
    await bot_app.shutdown()


# ===== Webhook =====

@app.post("/webhook")
async def webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        return {"ok": False}

    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return {"ok": True}


@app.get("/")
async def home():
    return {"ok": True}


@app.head("/")
async def head():
    return Response(status_code=200)
