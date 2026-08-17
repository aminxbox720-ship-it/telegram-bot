import os
import json
import time
import logging
import asyncio
from typing import Dict, Any

from flask import Flask, request

from telegram import Update, ChatMemberUpdated
from telegram.error import TimedOut, NetworkError, RetryAfter
from telegram.ext import (
    ApplicationBuilder,
    Application,
    CommandHandler,
    ChatMemberHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# -------------------- تنظیمات ایمن --------------------

TOKEN = os.environ.get("BOT_TOKEN")

# ادمین‌ها
ADMINS = {5285345183}

# Rate limit
RATE_LIMIT_SECONDS = 15

# فایل‌ها
POINTS_FILE = "points.json"
TRIGGERS_FILE = "triggers.json"
GROUPS_FILE = "groups.json"

# Render
PORT = int(os.environ.get("PORT", 10000))
RENDER_EXTERNAL_URL = os.environ.get(
    "RENDER_EXTERNAL_URL",
    ""
).rstrip("/")

WEBHOOK_PATH = "/telegram"

# -------------------- لاگینگ --------------------

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)

log = logging.getLogger("scorebot")

# -------------------- کمکی فایل --------------------

def _safe_load(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _safe_save(path: str, data: Any):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


# -------------------- امتیازها --------------------

def load_points() -> Dict[str, Dict[str, Any]]:
    data = _safe_load(POINTS_FILE, {})

    changed = False

    for uid, val in list(data.items()):

        if isinstance(val, int):
            data[uid] = {
                "points": val,
                "username": f"User{uid[-4:]}"
            }
            changed = True

        elif not isinstance(val, dict) or "points" not in val:
            data[uid] = {
                "points": 0,
                "username": f"User{uid[-4:]}"
            }
            changed = True

    if changed:
        _safe_save(POINTS_FILE, data)

    return data


def save_points(data: Dict[str, Dict[str, Any]]):
    _safe_save(POINTS_FILE, data)


# -------------------- محرک‌ها --------------------

def load_triggers() -> Dict[str, int]:

    data = _safe_load(TRIGGERS_FILE, {})

    # مهاجرت از لیست
    if isinstance(data, list):
        data = {w: 1 for w in data}
        _safe_save(TRIGGERS_FILE, data)

    changed = False
    cleaned = {}

    for k, v in data.items():

        try:
            cleaned[str(k)] = int(v)
        except Exception:
            continue

    if cleaned != data:
        _safe_save(TRIGGERS_FILE, cleaned)

    return cleaned


def save_triggers(data: Dict[str, int]):
    _safe_save(TRIGGERS_FILE, data)


# -------------------- گروه‌ها --------------------

def load_groups() -> list:

    data = _safe_load(GROUPS_FILE, [])

    # مهاجرت از dict
    if isinstance(data, dict):
        data = [int(k) for k in data.keys()]
        _safe_save(GROUPS_FILE, data)

    uniq = sorted({int(x) for x in data})

    if uniq != data:
        _safe_save(GROUPS_FILE, uniq)

    return uniq


def save_groups(groups: list):

    uniq = sorted({int(x) for x in groups})

    _safe_save(GROUPS_FILE, uniq)


# -------------------- ابزار امتیاز --------------------

def display_name(u) -> str:
    return (
        u.username
        or u.first_name
        or "کاربر"
    )


def add_points(
    user_id: int,
    delta: int,
    username: str
):

    pts = load_points()

    key = str(user_id)

    if key not in pts:
        pts[key] = {
            "points": 0,
            "username": username
        }

    pts[key]["points"] = (
        int(pts[key].get("points", 0))
        + int(delta)
    )

    pts[key]["username"] = username

    save_points(pts)


# -------------------- Rate limit --------------------

last_action_at: Dict[int, float] = {}


def check_rate_limit(giver_id: int) -> bool:

    now = time.time()

    last = last_action_at.get(
        giver_id,
        0
    )

    if now - last < RATE_LIMIT_SECONDS:
        return False

    last_action_at[giver_id] = now

    return True


# -------------------- ثبت/حذف گروه --------------------

async def register_current_chat(update: Update):

    chat_id = update.effective_chat.id

    groups = load_groups()

    if chat_id not in groups:

        groups.append(chat_id)

        save_groups(groups)


async def my_chat_member(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    upd: ChatMemberUpdated = update.my_chat_member

    chat_id = upd.chat.id

    new_status = upd.new_chat_member.status

    groups = load_groups()

    if new_status in (
        "member",
        "administrator"
    ):

        if chat_id not in groups:

            groups.append(chat_id)

            save_groups(groups)

            log.info(
                f"Joined new chat: {chat_id}"
            )

    elif new_status in (
        "left",
        "kicked"
    ):

        if chat_id in groups:

            groups.remove(chat_id)

            save_groups(groups)

            log.info(
                f"Left chat: {chat_id}"
            )


# -------------------- دستورات --------------------

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await register_current_chat(update)

    await update.message.reply_text(
        "سلام 👋\n"
        "برای امتیازدهی روی پیام یک نفر ریپلای کن "
        "و بنویس +1 یا -1.\n"
        "کلمات محرک را با /addtrigger اضافه کن.\n"
        "لیدربورد: /leaderboard"
    )


async def leaderboard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    pts = load_points()

    if not pts:

        await update.message.reply_text(
            "هنوز امتیازی ثبت نشده."
        )

        return

    top = sorted(
        pts.items(),
        key=lambda kv: kv[1]["points"],
        reverse=True
    )[:10]

    lines = ["🏆 لیدربورد:"]

    for i, (uid, data) in enumerate(
        top,
        1
    ):

        name = (
            data.get("username")
            or f"User{uid[-4:]}"
        )

        lines.append(
            f"{i}. {name}: "
            f"{data['points']} امتیاز"
        )

    await update.message.reply_text(
        "\n".join(lines)
    )


async def triggers_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    tr = load_triggers()

    if not tr:

        await update.message.reply_text(
            "هیچ کلمه محرکی ثبت نشده."
        )

        return

    lines = [
        "📌 کلمات محرک (کلمه → امتیاز):"
    ]

    for k, v in tr.items():

        lines.append(
            f"• {k} → {v}"
        )

    await update.message.reply_text(
        "\n".join(lines)
    )


def _is_admin_user(
    user_id: int
) -> bool:

    return user_id in ADMINS


# -------------------- افزودن محرک --------------------

async def addtrigger(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not _is_admin_user(
        update.message.from_user.id
    ):

        await update.message.reply_text(
            "⛔️ فقط ادمین می‌تواند محرک جدید اضافه کند."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "مثال: /addtrigger مرسی 1"
        )

        return

    *phrase_parts, maybe_val = context.args

    try:

        val = int(maybe_val)

        phrase = " ".join(
            phrase_parts
        ).strip()

        if not phrase:

            await update.message.reply_text(
                "فرمت اشتباه. مثال: "
                "/addtrigger دمت گرم 2"
            )

            return

    except ValueError:

        phrase = " ".join(
            context.args
        ).strip()

        val = 1

    tr = load_triggers()

    tr[phrase] = val

    save_triggers(tr)

    await update.message.reply_text(
        f"✔️ محرک '{phrase}' "
        f"با امتیاز {val} ثبت شد."
    )


# -------------------- حذف محرک --------------------

async def removetrigger(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not _is_admin_user(
        update.message.from_user.id
    ):

        await update.message.reply_text(
            "⛔️ فقط ادمین می‌تواند محرک حذف کند."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "مثال: /removetrigger مرسی"
        )

        return

    phrase = " ".join(
        context.args
    ).strip()

    tr = load_triggers()

    if phrase in tr:

        del tr[phrase]

        save_triggers(tr)

        await update.message.reply_text(
            f"🗑️ '{phrase}' حذف شد."
        )

    else:

        await update.message.reply_text(
            "این کلمه در فهرست نبود."
        )


# -------------------- Broadcast --------------------

async def broadcast(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not _is_admin_user(
        update.message.from_user.id
    ):

        await update.message.reply_text(
            "⛔️ فقط ادمین‌ها می‌توانند Broadcast بفرستند."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "متن را بعد از /broadcast وارد کن."
        )

        return

    msg = " ".join(
        context.args
    )

    groups = load_groups()

    sent = 0

    for chat_id in groups:

        try:

            await context.bot.send_message(
                chat_id=chat_id,
                text=msg
            )

            sent += 1

        except Exception as e:

            log.warning(
                f"Broadcast to {chat_id} failed: {e}"
            )

    await update.message.reply_text(
        f"✅ ارسال به {sent} گروه انجام شد."
    )


# -------------------- امتیازدهی پیام‌ها --------------------

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await register_current_chat(update)

    if (
        not update.message
        or not update.message.text
    ):
        return

    text = update.message.text.strip()

    user = update.message.from_user

    # +1 / -1
    if (
        update.message.reply_to_message
        and text in {"+1", "-1"}
    ):

        target = (
            update.message
            .reply_to_message
            .from_user
        )

        if target.id == user.id:

            await update.message.reply_text(
                "❌ نمی‌تونی به خودت امتیاز بدی!"
            )

            return

        if not check_rate_limit(
            user.id
        ):

            await update.message.reply_text(
                "⏳ یکم صبر کن، بعد دوباره امتیاز بده."
            )

            return

        delta = (
            1
            if text == "+1"
            else -1
        )

        add_points(
            target.id,
            delta,
            display_name(target)
        )

        pts = load_points()[
            str(target.id)
        ]["points"]

        await update.message.reply_text(
            f"{'✅' if delta > 0 else '➖'} "
            f"برای {display_name(target)} "
            f"اعمال شد. مجموع: {pts}"
        )

        return

    # کلمات محرک
    tr = load_triggers()

    if tr:

        total = 0

        lowered = text

        for phrase, val in tr.items():

            if phrase and phrase in lowered:

                total += int(val)

        if total != 0:

            if not check_rate_limit(
                user.id
            ):

                await update.message.reply_text(
                    "⏳ یکم صبر کن، بعد دوباره امتیاز بگیر."
                )

                return

            add_points(
                user.id,
                total,
                display_name(user)
            )

            pts = load_points()[
                str(user.id)
            ]["points"]

            sign = (
                "+"
                if total > 0
                else ""
            )

            await update.message.reply_text(
                f"✨ درود بر شما هموطن"
                f"{sign}{total}: {pts}"
            )


# -------------------- خطا --------------------

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
) -> None:

    err = context.error

    if isinstance(
        err,
        (TimedOut, NetworkError)
    ):

        log.warning(
            f"Network issue: {err}"
        )

        return

    if isinstance(
        err,
        RetryAfter
    ):

        wait = int(
            getattr(
                err,
                "retry_after",
                5
            )
        )

        log.warning(
            f"Rate limited by Telegram, "
            f"sleeping {wait}s"
        )

        await asyncio.sleep(wait)

        return

    log.exception(
        f"Unhandled error: {err}"
    )


# =====================================================
# Telegram Application
# =====================================================

if not TOKEN:

    raise RuntimeError(
        "❌ BOT_TOKEN تنظیم نشده."
    )


application: Application = (
    ApplicationBuilder()
    .token(TOKEN)
    .connect_timeout(30)
    .read_timeout(30)
    .write_timeout(30)
    .build()
)


# دستورات
application.add_handler(
    CommandHandler("start", start)
)

application.add_handler(
    CommandHandler(
        "leaderboard",
        leaderboard
    )
)

application.add_handler(
    CommandHandler(
        "triggers",
        triggers_cmd
    )
)

application.add_handler(
    CommandHandler(
        "addtrigger",
        addtrigger
    )
)

application.add_handler(
    CommandHandler(
        "removetrigger",
        removetrigger
    )
)

application.add_handler(
    CommandHandler(
        "broadcast",
        broadcast
    )
)


# عضویت/خروج
application.add_handler(
    ChatMemberHandler(
        my_chat_member,
        ChatMemberHandler.MY_CHAT_MEMBER
    )
)


# پیام‌ها
application.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        text_handler
    )
)


# خطا
application.add_error_handler(
    error_handler
)


# =====================================================
# Flask Webhook Server
# =====================================================

web = Flask(__name__)


@web.get("/")
def home():

    return "🤖 ScoreBot is running!", 200


@web.get("/health")
def health():

    return "OK", 200


@web.post(WEBHOOK_PATH)
async def telegram_webhook():

    data = request.get_json(
        force=True
    )

    update = Update.de_json(
        data,
        application.bot
    )

    await application.process_update(
        update
    )

    return "OK", 200


# =====================================================
# Startup
# =====================================================

async def initialize_bot():

    await application.initialize()

    await application.start()

    webhook_url = (
        f"{RENDER_EXTERNAL_URL}"
        f"{WEBHOOK_PATH}"
    )

    log.info(
        f"Setting webhook: {webhook_url}"
    )

    await application.bot.set_webhook(
        url=webhook_url,
        allowed_updates=[
            "message",
            "my_chat_member"
        ]
    )

    log.info(
        "✅ Telegram webhook successfully set."
    )


if __name__ == "__main__":

    if not RENDER_EXTERNAL_URL:

        raise RuntimeError(
            "❌ RENDER_EXTERNAL_URL تنظیم نشده."
        )

    asyncio.run(
        initialize_bot()
    )

    log.info(
        f"🤖 Bot is running on port {PORT}"
    )

    web.run(
        host="0.0.0.0",
        port=PORT
    )
