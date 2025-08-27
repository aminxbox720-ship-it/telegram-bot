import os, json, time, logging, asyncio
from typing import Dict, Any
from telegram import Update, ChatMemberUpdated
from telegram.error import TimedOut, NetworkError, RetryAfter
from telegram.ext import (
    ApplicationBuilder, Application, CommandHandler, MessageHandler,
    ChatMemberHandler, ContextTypes, filters
)

# -------------------- تنظیمات ایمن --------------------
# ترجیحاً توکن را در ENV بگذار:  set BOT_TOKEN=123:ABC...
TOKEN = "8107824962:AAHrrO3uq8ZltBcv8TD6DAhF5pSI7MWjFEI"
# ادمین‌ها (عددی). فقط این‌ها می‌توانند /broadcast و مدیریت محرک‌ها را انجام دهند.
ADMINS = {5285345183}  # آی‌دی خودت را اینجا بگذار، می‌توانی چندتا هم اضافه کنی: {1,2,3}

# Rate limit: هر کاربر هر چند ثانیه یک بار بتواند امتیاز بدهد
RATE_LIMIT_SECONDS = 15

# فایل‌ها
POINTS_FILE = "points.json"     # { "uid": {"points": int, "username": str} }
TRIGGERS_FILE = "triggers.json" # { "کلمه": int }  (اگر لیست باشد، مهاجرت می‌دهد به +1)
GROUPS_FILE = "groups.json"     # [chat_id, ...]

# -------------------- لاگینگ --------------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger("scorebot")

# -------------------- کمکیِ فایل --------------------
def _safe_load(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _safe_save(path: str, data: Any):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# امتیازها
def load_points() -> Dict[str, Dict[str, Any]]:
    data = _safe_load(POINTS_FILE, {})
    # مهاجرت: اگر مقدارها int بود، به ساختار جدید تبدیل کن
    changed = False
    for uid, val in list(data.items()):
        if isinstance(val, int):
            data[uid] = {"points": val, "username": f"User{uid[-4:]}"}
            changed = True
        elif not isinstance(val, dict) or "points" not in val:
            data[uid] = {"points": 0, "username": f"User{uid[-4:]}"}
            changed = True
    if changed:
        _safe_save(POINTS_FILE, data)
    return data

def save_points(data: Dict[str, Dict[str, Any]]):
    _safe_save(POINTS_FILE, data)

# محرک‌ها
def load_triggers() -> Dict[str, int]:
    data = _safe_load(TRIGGERS_FILE, {})
    # مهاجرت: اگر لیست بود => همه را +1 کن
    if isinstance(data, list):
        data = {w: 1 for w in data}
        _safe_save(TRIGGERS_FILE, data)
    # پاکسازی: فقط رشته→عدد
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

# گروه‌ها
def load_groups() -> list:
    data = _safe_load(GROUPS_FILE, [])
    # مهاجرت: اگر dict بود، به لیست تبدیل کن
    if isinstance(data, dict):
        data = [int(k) for k in data.keys()]
        _safe_save(GROUPS_FILE, data)
    # اطمینان از یکتایی و int بودن
    uniq = sorted({int(x) for x in data})
    if uniq != data:
        _safe_save(GROUPS_FILE, uniq)
    return uniq

def save_groups(groups: list):
    uniq = sorted({int(x) for x in groups})
    _safe_save(GROUPS_FILE, uniq)

# -------------------- ابزار امتیاز --------------------
def display_name(u) -> str:
    return (u.username or u.first_name or "کاربر")

def add_points(user_id: int, delta: int, username: str):
    pts = load_points()
    key = str(user_id)
    if key not in pts:
        pts[key] = {"points": 0, "username": username}
    pts[key]["points"] = int(pts[key].get("points", 0)) + int(delta)
    # آخرین نام/یوزرنیم شناخته‌شده را نگه داریم
    pts[key]["username"] = username
    save_points(pts)

# -------------------- Rate limit --------------------
last_action_at: Dict[int, float] = {}  # per-giver

def check_rate_limit(giver_id: int) -> bool:
    now = time.time()
    last = last_action_at.get(giver_id, 0)
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

async def my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # وقتی بات به گروه اضافه/حذف می‌شود
    upd: ChatMemberUpdated = update.my_chat_member
    chat_id = upd.chat.id
    new_status = upd.new_chat_member.status
    groups = load_groups()
    if new_status in ("member", "administrator"):
        if chat_id not in groups:
            groups.append(chat_id)
            save_groups(groups)
            log.info(f"Joined new chat: {chat_id}")
    elif new_status in ("left", "kicked"):
        if chat_id in groups:
            groups.remove(chat_id)
            save_groups(groups)
            log.info(f"Left chat: {chat_id}")

# -------------------- دستورات --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await register_current_chat(update)
    await update.message.reply_text(
        "سلام 👋\n"
        "برای امتیازدهی روی پیام یک نفر ریپلای کن و بنویس +1 یا -1.\n"
        "کلمات محرک را با /addtrigger اضافه کن. لیدربورد: /leaderboard"
    )

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pts = load_points()
    if not pts:
        await update.message.reply_text("هنوز امتیازی ثبت نشده.")
        return
    top = sorted(pts.items(), key=lambda kv: kv[1]["points"], reverse=True)[:10]
    lines = ["🏆 لیدربورد:"]
    for i, (uid, data) in enumerate(top, 1):
        name = data.get("username") or f"User{uid[-4:]}"
        lines.append(f"{i}. {name}: {data['points']} امتیاز")
    await update.message.reply_text("\n".join(lines))

async def triggers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tr = load_triggers()
    if not tr:
        await update.message.reply_text("هیچ کلمه محرکی ثبت نشده.")
        return
    lines = ["📌 کلمات محرک (کلمه → امتیاز):"]
    for k, v in tr.items():
        lines.append(f"• {k} → {v}")
    await update.message.reply_text("\n".join(lines))

def _is_admin_user(user_id: int) -> bool:
    return user_id in ADMINS

async def addtrigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # فقط ادمین‌های تعیین‌شده
    if not _is_admin_user(update.message.from_user.id):
        await update.message.reply_text("⛔️ فقط ادمین می‌تواند محرک جدید اضافه کند.")
        return
    if not context.args:
        await update.message.reply_text("مثال: /addtrigger مرسی 1")
        return
    # پارس: آخرین آرگومان اگر عدد بود => امتیاز؛ در غیراینصورت کل عبارت امتیاز +1
    *phrase_parts, maybe_val = context.args
    try:
        val = int(maybe_val)
        phrase = " ".join(phrase_parts).strip()
        if not phrase:
            await update.message.reply_text("فرمت اشتباه. مثال: /addtrigger دمت گرم 2")
            return
    except ValueError:
        phrase = " ".join(context.args).strip()
        val = 1
    tr = load_triggers()
    tr[phrase] = val
    save_triggers(tr)
    await update.message.reply_text(f"✔️ محرک '{phrase}' با امتیاز {val} ثبت شد.")

async def removetrigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin_user(update.message.from_user.id):
        await update.message.reply_text("⛔️ فقط ادمین می‌تواند محرک حذف کند.")
        return
    if not context.args:
        await update.message.reply_text("مثال: /removetrigger مرسی")
        return
    phrase = " ".join(context.args).strip()
    tr = load_triggers()
    if phrase in tr:
        del tr[phrase]
        save_triggers(tr)
        await update.message.reply_text(f"🗑️ '{phrase}' حذف شد.")
    else:
        await update.message.reply_text("این کلمه در فهرست نبود.")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin_user(update.message.from_user.id):
        await update.message.reply_text("⛔️ فقط ادمین‌ها می‌توانند Broadcast بفرستند.")
        return
    if not context.args:
        await update.message.reply_text("متن را بعد از /broadcast وارد کن.")
        return
    msg = " ".join(context.args)
    groups = load_groups()
    sent = 0
    for chat_id in groups:
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"📢 {msg}")
            sent += 1
        except Exception as e:
            log.warning(f"Broadcast to {chat_id} failed: {e}")
    await update.message.reply_text(f"✅ ارسال به {sent} گروه انجام شد.")

# -------------------- امتیازدهی پیام‌ها --------------------
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await register_current_chat(update)

    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    user = update.message.from_user

    # حالت ریپلای برای +1 / -1
    if update.message.reply_to_message and text in {"+1", "-1"}:
        target = update.message.reply_to_message.from_user

        if target.id == user.id:
            await update.message.reply_text("❌ نمی‌تونی به خودت امتیاز بدی!")
            return

        # rate limit روی امتیازدهنده
        if not check_rate_limit(user.id):
            await update.message.reply_text("⏳ یکم صبر کن، بعد دوباره امتیاز بده.")
            return

        delta = 1 if text == "+1" else -1
        add_points(target.id, delta, display_name(target))
        pts = load_points()[str(target.id)]["points"]
        await update.message.reply_text(
            f"{'✅' if delta>0 else '➖'} برای {display_name(target)} اعمال شد. مجموع: {pts}"
        )
        return

    # کلمات محرک (به خود فرستنده امتیاز بده)
    tr = load_triggers()
    if tr:
        total = 0
        lowered = text  # اگر خواستی حساسیت را کم کنی: text.lower()
        for phrase, val in tr.items():
            if phrase and phrase in lowered:
                total += int(val)
        if total != 0:
            if not check_rate_limit(user.id):
                await update.message.reply_text("⏳ یکم صبر کن، بعد دوباره امتیاز بگیر.")
                return
            add_points(user.id, total, display_name(user))
            pts = load_points()[str(user.id)]["points"]
            sign = "+" if total > 0 else ""
            await update.message.reply_text(
                f"✨ {display_name(user)} به خاطر پیامش {sign}{total} امتیاز گرفت. مجموع: {pts}"
            )

# -------------------- هندل خطاهای شبکه --------------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if isinstance(err, (TimedOut, NetworkError)):
        log.warning(f"Network issue: {err}. Will keep running.")
        await asyncio.sleep(2)
        return
    if isinstance(err, RetryAfter):
        wait = int(getattr(err, "retry_after", 5))
        log.warning(f"Rate limited by Telegram, sleeping {wait}s")
        await asyncio.sleep(wait)
        return
    log.exception(f"Unhandled error: {err}")

# -------------------- اجرای برنامه --------------------
def main():
    if not TOKEN or TOKEN.startswith("توکن_"):
        raise SystemExit("❌ BOT_TOKEN تنظیم نشده. در ENV یا داخل کد مقداردهی کن.")

    app: Application = (
        ApplicationBuilder()
        .token(TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .build()
    )

    # دستورات
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("triggers", triggers_cmd))
    app.add_handler(CommandHandler("addtrigger", addtrigger))
    app.add_handler(CommandHandler("removetrigger", removetrigger))
    app.add_handler(CommandHandler("broadcast", broadcast))

    # رویدادهای عضویت/خروج بات در گروه‌ها
    app.add_handler(ChatMemberHandler(my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    # پیام‌ها
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # خطاها
    app.add_error_handler(error_handler)

    print("🤖 Bot is running… (timeouts↑ & resilient)")

if __name__ == "__main__":
    main()
