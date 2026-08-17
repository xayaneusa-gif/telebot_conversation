import asyncio
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path

from telegram import BotCommand, BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, ReplyKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

from bot_config import (
    BOT_CHAT_ENDED_TEXT,
    BOT_ALREADY_SEARCHING_TEXT,
    BOT_EMERGENCY_MATCH_TEXT,
    BOT_END_PARTNER_TEMPLATE,
    BOT_MATCH_TEMPLATE,
    BOT_QUEUE_TEXT,
    BOT_WELCOME_TEXT,
    EMERGENCY_CITY_STATE_PAIRS,
    EMERGENCY_CITY_POOL,
    EMERGENCY_COURSE_POOL,
    EMERGENCY_STATE_POOL,
    EMERGENCY_AUTO_LEAVE_MESSAGES,
    EMERGENCY_FIRST_REPLY_TIMEOUT_SECONDS,
    EMERGENCY_IDLE_TIMEOUT_SECONDS,
    EMERGENCY_NAME_POOL,
    EMERGENCY_REPLY_BANK,
    EMERGENCY_TIMEOUT_SECONDS,
    PERSONA_POOL,
)
from matchmaker import (
    add_feedback_prompt,
    add_pending_media,
    add_reality_score,
    clear_profile,
    clear_pair_media_state,
    ensure_user,
    end_match,
    get_feedback_prompt,
    get_profile,
    get_user,
    get_waiting_users,
    get_emergency_mode_enabled,
    get_abuse_protection_enabled,
    get_media_permission,
    get_pending_media,
    get_reality_score,
    get_verified_badge,
    get_vip_enabled,
    get_vip_mode_enabled,
    get_vip_expiry,
    get_referral_count,
    get_not_in_chat_warning_enabled,
    init_db,
    is_verified,
    log_message,
    get_all_user_ids,
    get_queue_joined_at,
    match_waiting_user,
    pop_feedback_prompt,
    pop_pending_media,
    request_verification,
    remove_from_queue,
    record_referral,
    set_media_permission,
    set_emergency_mode_enabled,
    set_abuse_protection_enabled,
    set_not_in_chat_warning_enabled,
    set_user_age,
    set_user_gender,
    set_user_partner_age_range,
    set_user_preferred_gender,
    set_verified,
    set_verified_only,
    set_vip_enabled,
    set_vip_mode_enabled,
    grant_vip,
    record_vip_payment,
    set_waiting,
    set_emergency_match,
    clear_emergency_match,
    is_emergency_match,
)


TELEGRAM_BOT_TOKEN = "8880549145:AAE1AqjwpeQVWcUMNdliA7WAlyCKGnz3amU"

GENDER_OPTIONS = [
    ("Male", "male"),
    ("Female", "female"),
    ("Non-binary", "nonbinary"),
    ("Unspecified", "unspecified"),
]

PREFERRED_GENDER_OPTIONS = [
    ("Male", "male"),
    ("Female", "female"),
    ("Non-binary", "nonbinary"),
    ("Any", "any"),
]

MENU_FIND = "🎲 Find a Partner"
MENU_NEXT = "⏭ Next Partner"
MENU_END = "👋 End Chat"
MENU_SETTINGS = "⚙️ Settings"
MENU_FIND_MALE = "🚹 Find Male"
MENU_FIND_FEMALE = "🚺 Find Female"
MENU_VIP = "💎 VIP"
MENU_VERIFY = "🛡 Verify Me"
MENU_BUTTONS = [
    [MENU_FIND, MENU_SETTINGS],
    [MENU_NEXT, MENU_END],
    [MENU_VERIFY],
]
MENU_BUTTONS_VIP = [
    [MENU_FIND_MALE, MENU_FIND_FEMALE],
    [MENU_VIP],
]

GENDER_VISUALS = {
    "male": ("🚹", "Male"),
    "female": ("🚺", "Female"),
    "nonbinary": ("⚧️", "Non-binary"),
    "any": ("🌈", "Any"),
    "unspecified": ("👤", "Unknown"),
}

EMERGENCY_TASK_KEY = "emergency_tasks"
EMERGENCY_IDLE_TASK_KEY = "emergency_idle_tasks"
EMERGENCY_REPLY_TASK_KEY = "emergency_reply_tasks"
EMERGENCY_SESSION_KEY = "emergency_sessions"
EMERGENCY_LEAVE_TASK_KEY = "emergency_leave_tasks"
TRAFFIC_DUMMY_OPENINGS = ("Hi", "Hey", "Hello", "M or F", "M?", "M", "F?", "from?", "From?", "hyyy", None)
VIP_PLANS = {
    "25": {
        "payload": "vip_7_days_25_stars",
        "stars": 25,
        "days": 7,
        "label": "25 Stars · 7 days",
    },
    "75": {
        "payload": "vip_30_days_75_stars",
        "stars": 75,
        "days": 30,
        "label": "75 Stars · 30 days",
    },
}
RUNTIME_STATE_PATH = Path(__file__).with_name("runtime_state.json")
PUBLIC_COMMANDS = [
    BotCommand("start", "👋 Join the random matching queue"),
    BotCommand("next", "🔁 Find a new partner"),
    BotCommand("end", "❌ Leave the current chat"),
    BotCommand("stop", "✋ Stop current search"),
    BotCommand("vip", "💎 Show VIP status"),
    BotCommand("findmale", "🚹 Find male partners"),
    BotCommand("findfemale", "🚺 Find female partners"),
    BotCommand("settings", "⚙️ Open profile settings"),
    BotCommand("status", "📍 Show your current state"),
    BotCommand("verify", "🛡 Request verification"),
    BotCommand("help", "❓ Show help"),
    BotCommand("cancel", "🚫 Cancel current input"),
    BotCommand("referral", "🔗 Share referral link"),
    
]


def display_name(update: Update) -> str:
    user = update.effective_user
    if not user:
        return "Anonymous"
    full_name = " ".join(part for part in [user.first_name, user.last_name] if part)
    return full_name or user.username or f"User {user.id}"


def _parse_iso_datetime(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _format_duration(total_seconds: int) -> str:
    total_seconds = max(0, int(total_seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    pieces = []
    if hours:
        pieces.append(f"{hours}h")
    if minutes or hours:
        pieces.append(f"{minutes}m")
    pieces.append(f"{seconds}s")
    return " ".join(pieces)


def _wait_duration(joined_at: str | None) -> str:
    joined = _parse_iso_datetime(joined_at)
    if joined is None:
        return "just a moment"
    seconds = int((datetime.now(timezone.utc) - joined).total_seconds())
    return _format_duration(seconds)


def _gender_visual(gender: str | None) -> tuple[str, str]:
    value = (gender or "unspecified").strip().lower()
    return GENDER_VISUALS.get(value, GENDER_VISUALS["unspecified"])


def _partner_visual_line(user_id: int) -> str:
    profile = get_profile(user_id)
    gender = profile["gender"] if profile else None
    icon, label = _gender_visual(gender)
    return f"{icon} {label} match"


def _vip_access_allowed(user_id: int) -> bool:
    if not get_vip_mode_enabled():
        return True
    return get_vip_enabled(user_id)


def _referral_link(username: str, user_id: int) -> str:
    safe_username = username.lstrip("@")
    return f"https://t.me/{safe_username}?start=ref_{user_id}"


async def _sync_command_menu(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> None:
    commands = [
        BotCommand("start", "👋 Join the random matching queue"),
        BotCommand("next", "🔁 Find a new partner"),
        BotCommand("end", "❌ Leave the current chat"),
        BotCommand("stop", "✋ Stop current search"),
        BotCommand("settings", "⚙️ Open profile settings"),
        BotCommand("status", "📍 Show your current state"),
        BotCommand("verify", "🛡 Request verification"),
        BotCommand("help", "❓ Show help"),
        BotCommand("cancel", "🚫 Cancel current input"),
    ]
    if get_vip_mode_enabled():
        commands.extend(
            [
                BotCommand("vip", "💎 Show VIP status"),
                BotCommand("referral", "🔗 Share referral link"),
                BotCommand("findmale", "🚹 Find male partners"),
                BotCommand("findfemale", "🚺 Find female partners"),
            ]
        )
    try:
        await context.bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id))
    except Exception:
        pass


async def _show_vip_purchase_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user = update.effective_user
    if user is None:
        return
    await vip_status_command(update, context)


def _get_reply_tasks(owner) -> dict[int, asyncio.Task]:
    application = getattr(owner, "application", owner)
    return application.bot_data.setdefault(EMERGENCY_REPLY_TASK_KEY, {})


def _cancel_reply_task(owner, user_id: int) -> None:
    tasks = _get_reply_tasks(owner)
    task = tasks.pop(user_id, None)
    if task is not None and task is not asyncio.current_task():
        task.cancel()


def _vip_required_text() -> str:
    return "Choose a secure Telegram Stars payment below.\nChoose a plan to get vip."


def _vip_feature_locked_text() -> str:
    return "Only vip user can use this feature.\nUse /vip to get vip"


def _not_in_chat_text() -> str:
    return "You are not matched yet. Use /start to join the queue."


def _media_pending_text() -> str:
    return "Your media was not delivered yet. Waiting for your partner to accept it."


def _normalize_question_text(text: str) -> str:
    lowered = (text or "").lower()
    lowered = re.sub(r"(?<!\w)u(?!\w)", "you", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


def _is_abusive_text(text: str) -> bool:
    lowered = _normalize_question_text(text)
    abusive_words = (
        "fuck",
        "shit",
        "bitch",
        "asshole",
        "bastard",
        "idiot",
        "stupid",
        "dumb",
        "moron",
        "loser",
        "trash",
        "pussy",
        "dick",
    )
    return any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in abusive_words)


def _vip_keyboard() -> InlineKeyboardMarkup | None:
    if not get_vip_mode_enabled():
        return None
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 25 Stars · 7 days", callback_data="vip:buy:25")],
        [InlineKeyboardButton("💎 75 Stars · 30 days", callback_data="vip:buy:75")],
    ])


def _preferred_gender_rows(user_id: int):
    return PREFERRED_GENDER_OPTIONS


async def _cancel_all_emergency_mode_tasks(owner) -> None:
    tasks = _get_emergency_tasks(owner)
    for task in tasks.values():
        task.cancel()
    tasks.clear()


async def _cancel_all_emergency_idle_tasks(owner) -> None:
    tasks = _get_emergency_idle_tasks(owner)
    for task in tasks.values():
        task.cancel()
    tasks.clear()


async def _cancel_all_emergency_leave_tasks(owner) -> None:
    tasks = _get_emergency_leave_tasks(owner)
    for task in tasks.values():
        task.cancel()
    tasks.clear()


async def _end_emergency_chat(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    notify_user_as_partner_left: bool = False,
    send_user_message: bool = True,
) -> None:
    _cancel_emergency_task(context, user_id)
    _cancel_emergency_idle_task(context, user_id)
    _cancel_emergency_leave_task(context, user_id)
    _cancel_reply_task(context, user_id)
    _clear_emergency_session(context, user_id)
    partner_id = end_match(user_id)
    remove_from_queue(user_id)
    if partner_id is not None:
        _cancel_emergency_task(context, partner_id)
        _cancel_emergency_idle_task(context, partner_id)
        _cancel_emergency_leave_task(context, partner_id)
        _cancel_reply_task(context, partner_id)
        _clear_emergency_session(context, partner_id)
        clear_pair_media_state(user_id, partner_id)
        await _send_partner_left_notice(context, partner_id)
    if notify_user_as_partner_left:
        await _send_partner_left_notice(context, user_id)
        return
    if not send_user_message:
        return
    await context.bot.send_message(chat_id=user_id, text=_user_left_text())


def _get_emergency_tasks(owner) -> dict[int, asyncio.Task]:
    application = getattr(owner, "application", owner)
    return application.bot_data.setdefault(EMERGENCY_TASK_KEY, {})


def _get_emergency_idle_tasks(owner) -> dict[int, asyncio.Task]:
    application = getattr(owner, "application", owner)
    return application.bot_data.setdefault(EMERGENCY_IDLE_TASK_KEY, {})


def _get_emergency_sessions(owner) -> dict[int, dict]:
    application = getattr(owner, "application", owner)
    return application.bot_data.setdefault(EMERGENCY_SESSION_KEY, {})


def _get_emergency_leave_tasks(owner) -> dict[int, asyncio.Task]:
    application = getattr(owner, "application", owner)
    return application.bot_data.setdefault(EMERGENCY_LEAVE_TASK_KEY, {})


def _clear_emergency_session(owner, user_id: int) -> None:
    _get_emergency_sessions(owner).pop(user_id, None)


def _cancel_emergency_task(owner, user_id: int) -> None:
    tasks = _get_emergency_tasks(owner)
    task = tasks.pop(user_id, None)
    if task is not None:
        task.cancel()


def _cancel_emergency_idle_task(owner, user_id: int) -> None:
    tasks = _get_emergency_idle_tasks(owner)
    task = tasks.pop(user_id, None)
    if task is not None:
        task.cancel()


def _cancel_emergency_leave_task(owner, user_id: int) -> None:
    tasks = _get_emergency_leave_tasks(owner)
    task = tasks.pop(user_id, None)
    if task is not None:
        task.cancel()


def _schedule_emergency_leave_task(owner, user_id: int, delay_seconds: float) -> None:
    _cancel_emergency_leave_task(owner, user_id)
    application = getattr(owner, "application", owner)

    async def _runner() -> None:
        try:
            await asyncio.sleep(max(0.0, float(delay_seconds)))
            row = get_user(user_id)
            if row is None or row["status"] != "matched" or not bool(row["is_emergency"]):
                return
            await _send_partner_left_notice(application, user_id)
            await asyncio.sleep(0.5)
            await _end_emergency_chat(application, user_id, send_user_message=False)
        finally:
            _get_emergency_leave_tasks(owner).pop(user_id, None)

    tasks = _get_emergency_leave_tasks(owner)
    tasks[user_id] = asyncio.create_task(_runner())


def _schedule_emergency_idle_task(owner, user_id: int, delay_seconds: int = EMERGENCY_IDLE_TIMEOUT_SECONDS) -> None:
    _cancel_emergency_idle_task(owner, user_id)
    application = getattr(owner, "application", owner)

    async def _runner() -> None:
        try:
            await asyncio.sleep(max(0, delay_seconds))
            row = get_user(user_id)
            if row is None or row["status"] != "matched" or not bool(row["is_emergency"]):
                return
            await _end_emergency_chat(application, user_id, notify_user_as_partner_left=True)
        finally:
            _get_emergency_idle_tasks(owner).pop(user_id, None)

    tasks = _get_emergency_idle_tasks(owner)
    tasks[user_id] = asyncio.create_task(_runner())


def _schedule_emergency_task(owner, user_id: int, delay_seconds: int = EMERGENCY_TIMEOUT_SECONDS) -> None:
    if not get_emergency_mode_enabled():
        _cancel_emergency_task(owner, user_id)
        return
    if get_vip_enabled(user_id):
        _cancel_emergency_task(owner, user_id)
        return
    _cancel_emergency_task(owner, user_id)
    application = getattr(owner, "application", owner)

    async def _runner() -> None:
        try:
            await asyncio.sleep(max(0, delay_seconds))
            row = get_user(user_id)
            if row is None or row["status"] != "waiting" or not get_emergency_mode_enabled():
                return
            waited_for = f"{random.randint(20, 30)}s"
            fake_gender = random.choice(("male", "female", "nonbinary", "unspecified"))
            gender_icon, gender_label = _gender_visual(fake_gender)
            fake_uid = random.randint(1000000000, 9999999999)
            set_emergency_match(user_id)
            traffic_session = _get_emergency_sessions(application)[user_id] = {
                "dummy": True,
                "dummy_uid": fake_uid,
                "dummy_gender": fake_gender,
                "waited_for": waited_for,
            }
            bot = application.bot
            await bot.send_message(
                chat_id=user_id,
                text=_traffic_match_text(gender_icon, gender_label, fake_uid, waited_for),
                parse_mode=ParseMode.HTML,
            )
            opening = random.choice(TRAFFIC_DUMMY_OPENINGS)
            if opening:
                await asyncio.sleep(random.uniform(0.8, 1.5))
                current_session = _get_emergency_sessions(application).get(user_id)
                if current_session is None or current_session.get("dummy_uid") != fake_uid:
                    return
                await bot.send_message(chat_id=user_id, text=str(opening))
            leave_delay = random.uniform(3.0, 7.0)
            _schedule_emergency_leave_task(application, user_id, delay_seconds=leave_delay)
        finally:
            _get_emergency_tasks(owner).pop(user_id, None)

    tasks = _get_emergency_tasks(owner)
    tasks[user_id] = asyncio.create_task(_runner())


def _match_found_text(waited_for: str) -> str:
    return BOT_MATCH_TEMPLATE.format(
        user_id="unknown",
        gender_icon="👤",
        gender_label="Unknown",
        age_text="Unknown",
        waited_for=waited_for,
    )


def _traffic_match_text(gender_icon: str, gender_label: str, dummy_uid: int, waited_for: str) -> str:
    return (
        "✨ <b>It's a match!</b> ✨\n\n"
        "<b>Partner found:</b>\n"
        f"🔹 <b>Gender:</b> {gender_icon} {gender_label}\n"
        "🔹 <b>Age:</b> Unknown\n\n"
        f"<b>💬#{dummy_uid}</b>\n\n"
        "<b>💬 Chat ready</b>\n"
        f"⏱️ <b>Waited:</b> {waited_for}"
    )


def _chat_ended_text(partner_id: int | None = None) -> str:
    if partner_id is None:
        return BOT_CHAT_ENDED_TEXT

    profile = get_profile(partner_id)
    gender = profile["gender"] if profile else None
    icon, label = _gender_visual(gender)
    return BOT_END_PARTNER_TEMPLATE.format(gender_icon=icon, gender_label=label)


def _user_left_text() -> str:
    return "You Left the chat. Use /start to find new match."


def _partner_left_text() -> str:
    return "Your partner Left the chat. Use /start to find new match.."


async def _send_partner_left_notice(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    await context.bot.send_message(chat_id=user_id, text=_partner_left_text())


def _queue_text() -> str:
    return BOT_QUEUE_TEXT


def _clear_queue_notice(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    try:
        context.user_data.pop("queue_notice_shown", None)
    except Exception:
        pass


def _mark_queue_notice(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        context.user_data["queue_notice_shown"] = True
    except Exception:
        pass


def _verified_line(user_id: int) -> str:
    badge = get_verified_badge(user_id)
    if badge.startswith("✪"):
        return "✪ Verified"
    return ""


def _verified_only_enabled(user_id: int) -> bool:
    profile = get_profile(user_id)
    return bool(profile and profile["verified_only"] and profile["verified"])


def _match_banner(user_id: int, waited_for: str) -> str:
    profile = get_profile(user_id) or {}
    gender_icon, gender_label = _gender_visual(profile["gender"])
    age_value = profile["age"]
    age_text = str(age_value) if age_value is not None else "Unknown"
    return BOT_MATCH_TEMPLATE.format(
        user_id=user_id,
        gender_icon=gender_icon,
        gender_label=gender_label,
        age_text=age_text,
        waited_for=waited_for,
    )


async def _safe_edit_message(message, text: str, reply_markup=None) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise


def _media_prompt_text() -> str:
    return (
        "📎 Your Partner wants to send media.\n\n"
        "What is this?\n\n"
        "Allow or deny?"
    )


def _feedback_prompt_text() -> str:
    return (
        "⭐ Reality Check\n\n"
        "How real did this chat feel?"
    )


def _feedback_keyboard(target_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Real", callback_data=f"feedback:real:{target_id}"),
            ],
            [
                InlineKeyboardButton("❌ Not real", callback_data=f"feedback:not_real:{target_id}"),
            ],
            [
                InlineKeyboardButton("⚪ Dont know", callback_data=f"feedback:unknown:{target_id}"),
            ],
        ]
    )


def _media_keyboard(sender_id: int, recipient_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Allow", callback_data=f"media:allow:{sender_id}:{recipient_id}"),
                InlineKeyboardButton("Deny", callback_data=f"media:deny:{sender_id}:{recipient_id}"),
            ]
        ]
    )


def _profile_text(user_id: int) -> str:
    profile = get_profile(user_id)
    age = profile["age"] if profile and profile["age"] is not None else "Not set"
    gender = profile["gender"] if profile else "unspecified"
    preferred_gender = profile["preferred_gender"] if profile else "any"
    if profile and profile["partner_age_min"] is not None and profile["partner_age_max"] is not None:
        partner_age = f'{profile["partner_age_min"]}-{profile["partner_age_max"]}'
    else:
        partner_age = "Any"
    return (
        "👤 Your Profile\n\n"
        f"Age: {age}\n"
        f"Gender: {gender}\n"
        f"Preferred partner gender: {preferred_gender}\n"
        f"Preferred partner age: {partner_age}"
    )


def _verified_toggle_label(user_id: int) -> str:
    profile = get_profile(user_id)
    if profile and profile["verified_only"] and profile["verified"]:
        return "✪ Verified-only: ON"
    return "✪ Verified-only: OFF"


def _settings_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👤 My Age", callback_data="settings:age"),
                InlineKeyboardButton("⚧️ My Gender", callback_data="settings:gender"),
            ],
            [
                InlineKeyboardButton("🎯 Preferred Gender", callback_data="settings:pref_gender"),
                InlineKeyboardButton("🎚 Partner Age Range", callback_data="settings:age_range"),
            ],
            [
                InlineKeyboardButton(_verified_toggle_label(user_id), callback_data="settings:verified_only"),
                InlineKeyboardButton("🛡 Verify Me", callback_data="settings:verify_me"),
            ],
            [InlineKeyboardButton("✅ Done", callback_data="settings:close")],
        ]
    )


def _main_keyboard(user_id: int | None = None) -> ReplyKeyboardMarkup:
    buttons = [row[:] for row in MENU_BUTTONS]
    if get_vip_mode_enabled():
        buttons = [row[:] for row in MENU_BUTTONS_VIP] + buttons
    return ReplyKeyboardMarkup(
        buttons,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Choose an action",
        selective=False,
    )


async def _show_main_keyboard(update: Update, text: str = "Menu opened.") -> None:
    if update.message:
        user = update.effective_user
        await update.message.reply_text(text, reply_markup=_main_keyboard(user.id if user else None))


def _gender_keyboard(prefix: str, rows, back_data: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(label, callback_data=f"settings:set:{prefix}:{value}")]
        for label, value in rows
    ]
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=back_data)])
    return InlineKeyboardMarkup(buttons)


def _settings_panel_text(user_id: int) -> str:
    profile = get_profile(user_id)
    age = profile["age"] if profile and profile["age"] is not None else "Not set"
    gender = profile["gender"] if profile else "unspecified"
    preferred_gender = profile["preferred_gender"] if profile else "any"
    verified_only = "On" if _verified_only_enabled(user_id) else "Off"
    vip_enabled = "On" if get_vip_enabled(user_id) else "Off"
    referral_count = int(profile["referral_count"] or 0) if profile else 0
    global_vip = "On" if get_vip_mode_enabled() else "Off"
    score = int(profile["reality_score"] or 0) if profile else 0
    verified_badge = "✪ Verified" if profile and profile["verified"] else "👤 Unverified"
    if profile and profile["partner_age_min"] is not None and profile["partner_age_max"] is not None:
        age_range = f'{profile["partner_age_min"]}-{profile["partner_age_max"]}'
    else:
        age_range = "Any"

    return (
        "⚙️ Settings Panel\n\n"
        "Tune your matching vibe:\n\n"
        f"👤 Age: {age}\n"
        f"⚧️ Gender: {gender}\n"
        f"🎯 Preferred partner gender: {preferred_gender}\n"
        f"🎚 Partner age range: {age_range}\n\n"
        f"✪ Verified-only matches: {verified_only}\n"
        f"💎 VIP Access: {vip_enabled}\n"
        f"🔐 Global VIP Mode: {global_vip}\n"
        f"🎁 Referrals: {referral_count}/3\n"
        f"⭐ Reality score: {score}\n"
        f"{verified_badge}\n\n"
        "Pick a card below to update your profile."
    )


def _age_prompt_text() -> str:
    return (
        "👤 Set Your Age\n\n"
        "Send a whole number like `24`.\n"
        "This helps the matcher pair you more smartly."
    )


def _age_range_prompt_text() -> str:
    return (
        "🎚 Partner Age Range\n\n"
        "Send a range like `18-25`, `21-30`, or `18+`.\n"
        "Ill use this to filter better matches."
    )


async def _send_settings_panel(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False) -> None:
    user = update.effective_user
    if not user:
        return

    text = _settings_panel_text(user.id)
    keyboard = _settings_keyboard(user.id)
    if edit and update.callback_query and update.callback_query.message:
        await _safe_edit_message(update.callback_query.message, text, reply_markup=keyboard)
    elif update.message:
        await update.message.reply_text(text, reply_markup=keyboard)


async def _send_submenu(update: Update, text: str, keyboard: InlineKeyboardMarkup) -> None:
    if update.callback_query and update.callback_query.message:
        await _safe_edit_message(update.callback_query.message, text, reply_markup=keyboard)


async def _send_feedback_prompt(context: ContextTypes.DEFAULT_TYPE, rater_id: int, target_id: int) -> None:
    add_feedback_prompt(rater_id, target_id)
    await context.bot.send_message(
        chat_id=rater_id,
        text=_feedback_prompt_text(),
        reply_markup=_feedback_keyboard(target_id),
    )


async def _deliver_media(context: ContextTypes.DEFAULT_TYPE, sender_id: int, recipient_id: int) -> None:
    media = pop_pending_media(sender_id, recipient_id)
    if media is None:
        return

    media_type = media["media_type"]
    file_id = media["file_id"]
    caption = media["caption"]
    if media_type == "photo":
        await context.bot.send_photo(chat_id=recipient_id, photo=file_id, caption=caption)
    elif media_type == "document":
        await context.bot.send_document(chat_id=recipient_id, document=file_id, caption=caption)
    elif media_type == "video":
        await context.bot.send_video(chat_id=recipient_id, video=file_id, caption=caption)


async def _route_media_upload(
    context: ContextTypes.DEFAULT_TYPE,
    sender_id: int,
    recipient_id: int,
    media_type: str,
    file_id: str,
    caption: str | None,
) -> None:
    if get_media_permission(sender_id, recipient_id):
        if media_type == "photo":
            await context.bot.send_photo(chat_id=recipient_id, photo=file_id, caption=caption)
        elif media_type == "document":
            await context.bot.send_document(chat_id=recipient_id, document=file_id, caption=caption)
        elif media_type == "video":
            await context.bot.send_video(chat_id=recipient_id, video=file_id, caption=caption)
        return

    if get_pending_media(sender_id, recipient_id) is not None:
        return

    add_pending_media(sender_id, recipient_id, media_type, file_id, caption)
    try:
        await context.bot.send_message(
            chat_id=sender_id,
            text=_media_pending_text(),
            reply_markup=_main_keyboard(sender_id),
        )
    except Exception:
        pass
    await context.bot.send_message(
        chat_id=recipient_id,
        text=_media_prompt_text(),
        reply_markup=_media_keyboard(sender_id, recipient_id),
    )


async def send_pair_intro(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    partner_id: int,
    user_waited_for: str,
    partner_waited_for: str,
) -> None:
    await context.bot.send_message(
        chat_id=user_id,
        text=_match_banner(partner_id, user_waited_for),
        parse_mode=ParseMode.HTML,
        reply_markup=_main_keyboard(user_id),
    )
    await context.bot.send_message(
        chat_id=partner_id,
        text=_match_banner(user_id, partner_waited_for),
        parse_mode=ParseMode.HTML,
        reply_markup=_main_keyboard(partner_id),
    )
    _cancel_emergency_task(context, user_id)
    _cancel_emergency_task(context, partner_id)
    _cancel_emergency_leave_task(context, user_id)
    _cancel_emergency_leave_task(context, partner_id)


async def join_or_match(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if not user or not update.message:
        return

    user_name = display_name(update)
    context.bot_data.setdefault("names", {})[user.id] = user_name
    ensure_user(user.id, user_name)
    if chat is not None:
        await _sync_command_menu(context, chat.id, user.id)

    current = get_user(user.id)
    if current is not None:
        if current["status"] == "matched" and bool(current["is_emergency"]):
            _clear_queue_notice(context, user.id)
            await update.message.reply_text(
                "You are already in Chat.\nUse /next for a new match or /end to leave.",
                reply_markup=_main_keyboard(user.id),
            )
            return
        if current["status"] == "matched" and current["partner_id"] is not None:
            _clear_queue_notice(context, user.id)
            await update.message.reply_text(
                "You are already in Chat.\nUse /next for a new partner or /end to leave.",
                reply_markup=_main_keyboard(user.id),
            )
            return
        if current["status"] == "waiting":
            if get_emergency_mode_enabled() and not get_vip_enabled(user.id):
                _schedule_emergency_task(context, user.id)
            if not context.user_data.get("queue_notice_shown"):
                _mark_queue_notice(context)
                await update.message.reply_text(
                    BOT_QUEUE_TEXT,
                    parse_mode=ParseMode.HTML,
                    reply_markup=_main_keyboard(user.id),
                )
            else:
                await update.message.reply_text(
                    BOT_ALREADY_SEARCHING_TEXT,
                    parse_mode=ParseMode.HTML,
                    reply_markup=_main_keyboard(user.id),
                )
            return

    payload = ""
    if context.args:
        payload = context.args[0].strip()
    else:
        parts = (update.message.text or "").split(maxsplit=1)
        if len(parts) > 1:
            payload = parts[1].strip()

    if payload.startswith("ref_"):
        referrer_text = payload.removeprefix("ref_")
        if referrer_text.isdigit():
            referrer_id = int(referrer_text)
            if referrer_id != user.id:
                new_count = record_referral(referrer_id, user.id)
                if new_count >= 3:
                    if update.effective_chat is not None:
                        try:
                            await _sync_command_menu(context, referrer_id, referrer_id)
                        except Exception:
                            pass
                    try:
                        await context.bot.send_message(
                            chat_id=referrer_id,
                            text="💎 3 referrals complete.\nYour VIP was extended by 1 day.",
                        )
                    except Exception:
                        pass

    set_waiting(user.id)
    result = match_waiting_user(user.id)

    if result is None:
        _mark_queue_notice(context)
        if get_emergency_mode_enabled():
            _schedule_emergency_task(context, user.id)
        await update.message.reply_text(_queue_text(), parse_mode=ParseMode.HTML, reply_markup=_main_keyboard(user.id))
        return

    partner_id = result["partner_id"]
    if partner_id is None:
        _mark_queue_notice(context)
        if get_emergency_mode_enabled():
            _schedule_emergency_task(context, user.id)
        await update.message.reply_text(_queue_text(), parse_mode=ParseMode.HTML, reply_markup=_main_keyboard(user.id))
        return

    _clear_queue_notice(context, user.id)

    await send_pair_intro(
        context,
        user.id,
        partner_id,
        _wait_duration(result.get("user_joined_at")),
        _wait_duration(result.get("partner_joined_at")),
    )


async def next_match(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if not user or not update.message:
        return

    user_name = display_name(update)
    context.bot_data.setdefault("names", {})[user.id] = user_name
    ensure_user(user.id, user_name)
    if chat is not None:
        await _sync_command_menu(context, chat.id, user.id)
    _clear_queue_notice(context, user.id)
    current = get_user(user.id)
    if current is not None and current["status"] == "waiting":
        await update.message.reply_text(
            BOT_ALREADY_SEARCHING_TEXT,
            parse_mode=ParseMode.HTML,
            reply_markup=_main_keyboard(user.id),
        )
        return
    await stop_chat(update, context)
    await join_or_match(update, context)


async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if not user or not update.message:
        return

    user_name = display_name(update)
    context.bot_data.setdefault("names", {})[user.id] = user_name
    ensure_user(user.id, user_name)
    if chat is not None:
        await _sync_command_menu(context, chat.id, user.id)
    _clear_queue_notice(context, user.id)
    _cancel_emergency_task(context, user.id)
    _cancel_emergency_idle_task(context, user.id)
    _cancel_emergency_leave_task(context, user.id)
    _clear_emergency_session(context, user.id)
    partner_id = end_match(user.id)
    remove_from_queue(user.id)
    if partner_id is not None:
        _cancel_emergency_task(context, partner_id)
        _cancel_emergency_idle_task(context, partner_id)
        _cancel_emergency_leave_task(context, partner_id)
        _clear_emergency_session(context, partner_id)
        clear_pair_media_state(user.id, partner_id)

    if partner_id is not None:
        await context.bot.send_message(
            chat_id=partner_id,
            text=_partner_left_text(),
        )
        await _send_feedback_prompt(context, partner_id, user.id)

    await update.message.reply_text(_user_left_text())
    if partner_id is not None:
        await _send_feedback_prompt(context, user.id, partner_id)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if not user or not update.message:
        return
    if chat is not None:
        await _sync_command_menu(context, chat.id, user.id)

    row = get_user(user.id)
    if row is None:
        await update.message.reply_text("You are not registered yet. Use /start.")
        return

    profile = get_profile(user.id)
    score = int(profile["reality_score"] or 0) if profile else 0
    badge = "✪ Verified" if profile and profile["verified"] else "👤 Unverified"
    status_text = row["status"]
    if status_text == "matched" and bool(row["is_emergency"]):
        await update.message.reply_text(
            f"You are already in Chat.\n{badge}\n⭐ Reality score: {score}\nUse /next for a new partner or /end to leave.",
            reply_markup=_main_keyboard(user.id),
        )
    elif status_text == "matched" and row["partner_id"] is not None:
        await update.message.reply_text(
            f"You are already in Chat.\n{badge}\n⭐ Reality score: {score}\nUse /next for a new partner or /end to leave.",
            reply_markup=_main_keyboard(user.id),
        )
    elif status_text == "waiting":
        await update.message.reply_text(
            f"🕒 You are waiting for a random match.\n{badge}\n⭐ Reality score: {score}",
            reply_markup=_main_keyboard(user.id),
        )
    else:
        await update.message.reply_text(
            f"You are currently idle.\n{badge}\n⭐ Reality score: {score}",
            reply_markup=_main_keyboard(user.id),
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if not update.message:
        return
    if user is not None and chat is not None:
        await _sync_command_menu(context, chat.id, user.id)
    lines = [
        "📘 <b>Command Guide</b>",
        "",
        "<b>Core</b>",
        "• <code>/start</code> — Join the random matching queue",
        "• <code>/next</code> — Find a new partner",
        "• <code>/end</code> — Leave the current chat",
        "• <code>/stop</code> — Stop current search",
        "",
        "<b>Profile</b>",
        "• <code>/settings</code> — Open profile settings",
        "• <code>/status</code> — Show your current state",
        "• <code>/verify</code> — Request verification",
        "• <code>/cancel</code> — Cancel current input",
        "",
        "<b>VIP</b>",
        "• <code>/vip</code> — Show VIP status",
        "• <code>/findmale</code> — Find male partners",
        "• <code>/findfemale</code> — Find female partners",
    ]
    if user is not None and get_vip_mode_enabled():
        lines.extend(
            [
                "",
                "<b>Extras</b>",
                "• <code>/referral</code> — Share your referral link",
            ]
        )
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=_main_keyboard(user.id if user else None),
    )


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if not user or not update.message:
        return

    user_name = display_name(update)
    context.bot_data.setdefault("names", {})[user.id] = user_name
    ensure_user(user.id, user_name)
    if chat is not None:
        await _sync_command_menu(context, chat.id, user.id)
    await _send_settings_panel(update, context, edit=False)


async def handle_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    user = query.from_user
    if user is None:
        return

    data = query.data
    ensure_user(user.id, display_name(update))

    if data == "settings:close":
        context.user_data.pop("settings_mode", None)
        await _safe_edit_message(query.message, "✅ Settings closed.")
        return

    if data == "settings:verified_only":
        profile = get_profile(user.id)
        current = _verified_only_enabled(user.id)
        if not current and not (profile and profile["verified"]):
            set_verified_only(user.id, False)
            await query.message.reply_text("✪ Verified badge required.")
            await _send_settings_panel(update, context, edit=True)
            return
        set_verified_only(user.id, not current)
        await _send_settings_panel(update, context, edit=True)
        return

    if data == "settings:verify_me":
        if request_verification(user.id):
            await query.message.reply_text("✪ Verified badge unlocked.")
        else:
            score = get_reality_score(user.id)
            await query.message.reply_text(f"Need 10 reality points to verify. Current score: {score}.")
        await _send_settings_panel(update, context, edit=True)
        return

    if data == "settings:age":
        context.user_data["settings_mode"] = "age"
        await _send_submenu(
            update,
            _age_prompt_text(),
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Settings", callback_data="settings:back")]]),
        )
        return

    if data == "settings:age_range":
        context.user_data["settings_mode"] = "age_range"
        await _send_submenu(
            update,
            _age_range_prompt_text(),
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Settings", callback_data="settings:back")]]),
        )
        return

    if data == "settings:gender":
        await _send_submenu(
            update,
            "⚧️ My Gender\n\nPick the label that fits you best.",
            _gender_keyboard("gender", GENDER_OPTIONS, "settings:back"),
        )
        return

    if data == "settings:pref_gender":
        if get_vip_mode_enabled() and not get_vip_enabled(user.id):
            await query.message.reply_text(_vip_feature_locked_text())
            return
        await _send_submenu(
            update,
            "🎯 Preferred Partner Gender\n\nChoose who you want to be matched with.",
            _gender_keyboard("pref", _preferred_gender_rows(user.id), "settings:back"),
        )
        return

    if data == "settings:back":
        context.user_data.pop("settings_mode", None)
        await _send_settings_panel(update, context, edit=True)
        return

    if data.startswith("settings:set:"):
        _, _, prefix, value = data.split(":", 3)
        if prefix == "gender":
            set_user_gender(user.id, value)
            await _send_settings_panel(update, context, edit=True)
            await query.message.reply_text("✅ Gender updated.")
            return
        if prefix == "pref":
            if get_vip_mode_enabled() and not get_vip_enabled(user.id):
                await query.message.reply_text(_vip_feature_locked_text())
                return
            set_user_preferred_gender(user.id, value)
            await _send_settings_panel(update, context, edit=True)
            await query.message.reply_text("✅ Preferred partner gender updated.")
            return


async def handle_settings_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message or not message.text:
        return

    text = message.text.strip()

    if text == MENU_FIND:
        await join_or_match(update, context)
        return
    if text == MENU_FIND_MALE:
        if get_vip_mode_enabled() and not get_vip_enabled(user.id):
            await vip_status_command(update, context)
            await message.reply_text(_vip_feature_locked_text(), reply_markup=_main_keyboard(user.id))
            return
        set_user_preferred_gender(user.id, "male")
        await join_or_match(update, context)
        return
    if text == MENU_FIND_FEMALE:
        if get_vip_mode_enabled() and not get_vip_enabled(user.id):
            await vip_status_command(update, context)
            await message.reply_text(_vip_feature_locked_text(), reply_markup=_main_keyboard(user.id))
            return
        set_user_preferred_gender(user.id, "female")
        await join_or_match(update, context)
        return
    if text == MENU_VIP:
        await vip_status_command(update, context)
        return
    if text == MENU_NEXT:
        await next_match(update, context)
        return
    if text == MENU_END:
        await stop_chat(update, context)
        return
    if text == MENU_SETTINGS:
        await settings_command(update, context)
        return
    if text == MENU_VERIFY:
        await verify_command(update, context)
        return

    mode = context.user_data.get("settings_mode")
    if not mode:
        await relay_message(update, context)
        return

    if mode == "age":
        if not text.isdigit():
            await message.reply_text("Please send a valid age like 24.")
            return
        age = int(text)
        if age < 13 or age > 120:
            await message.reply_text("Please send an age between 13 and 120.")
            return
        set_user_age(user.id, age)
        context.user_data.pop("settings_mode", None)
        await message.reply_text(f"✅ Age saved: {age}")
        await message.reply_text(_settings_panel_text(user.id), reply_markup=_settings_keyboard(user.id))
        return

    if mode == "age_range":
        normalized = text.replace(" ", "")
        minimum = None
        maximum = None
        try:
            if normalized.endswith("+") and normalized[:-1].isdigit():
                minimum = int(normalized[:-1])
                maximum = None
            elif "-" in normalized:
                left, right = normalized.split("-", 1)
                if not left.isdigit() or not right.isdigit():
                    raise ValueError
                minimum = int(left)
                maximum = int(right)
                if minimum > maximum:
                    minimum, maximum = maximum, minimum
            elif normalized.isdigit():
                minimum = int(normalized)
                maximum = int(normalized)
            else:
                raise ValueError
        except ValueError:
            await message.reply_text("Send a range like 18-25, 21-30, or 18+.")
            return

        if minimum is not None and minimum < 13:
            await message.reply_text("Please keep the range at 13 or above.")
            return

        set_user_partner_age_range(user.id, minimum, maximum)
        context.user_data.pop("settings_mode", None)
        await message.reply_text("✅ Partner age range updated.")
        await message.reply_text(_settings_panel_text(user.id), reply_markup=_settings_keyboard(user.id))
        return


async def route_command_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip()
    if not text.startswith("/"):
        return

    command = text.split()[0].split("@", 1)[0].removeprefix("/")
    command_map = {
        "start": join_or_match,
        "next": next_match,
        "end": stop_chat,
        "stop": stop_search_command,
        "disconnect": stop_chat,
        "status": status,
        "verify": verify_command,
        "help": help_command,
        "settings": settings_command,
        "cancel": cancel_command,
        "findmale": find_male_command,
        "findfemale": find_female_command,
        "referral": referral_command,
        "vip": vip_status_command,
        "sudo_vip_enable": sudo_vip_enable_command,
        "sudo_vip_disable": sudo_vip_disable_command,
        "sudoenablevip": sudo_vip_enable_command,
        "sudodisablevip": sudo_vip_disable_command,
        "sudogivevip": sudo_give_vip_command,
        "sudogetruntime": sudo_get_runtime_command,
        "sudoenableemg": sudo_emg_enable_command,
        "sudodisableemg": sudo_emg_disable_command,
        "sudoenabletraffic": sudo_traffic_enable_command,
        "sudodisabletraffic": sudo_traffic_disable_command,
        "sudoenableabuseprotection": sudo_abuse_enable_command,
        "sudodisableabuseprotection": sudo_abuse_disable_command,
        "sudoenablenotinchat": sudo_notinchat_enable_command,
        "sudodisablenotinchat": sudo_notinchat_disable_command,
        "sudolistanoncommands": sudo_list_anon_commands_command,
    }
    handler = command_map.get(command)
    if handler is not None:
        await handler(update, context)


async def relay_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.message
    if not user or not message or not message.text:
        return

    row = get_user(user.id)
    if row is None or row["status"] != "matched":
        if get_not_in_chat_warning_enabled():
            await message.reply_text(_not_in_chat_text())
        return

    if bool(row["is_emergency"]) or int(row["partner_id"] or 0) < 0:
        return

    if row["partner_id"] in (None, 0):
        if get_not_in_chat_warning_enabled():
            await message.reply_text(_not_in_chat_text())
        return

    partner_id = row["partner_id"]
    if get_abuse_protection_enabled() and _is_abusive_text(message.text):
        await message.reply_text("Please use respectful language. Keep the chat friendly. \n Other wise you will be banned 🚫")
        return

    log_message(user.id, partner_id, message.text)
    await context.bot.send_message(
        chat_id=partner_id,
        text=message.text,
    )
    return


async def _handle_unmatched_media_notice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if get_not_in_chat_warning_enabled():
        await update.message.reply_text(_not_in_chat_text())


async def verify_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    user = update.effective_user
    if not user:
        return

    if request_verification(user.id):
        await update.message.reply_text("✪ Verified badge unlocked.", reply_markup=_main_keyboard(user.id))
    else:
        score = get_reality_score(user.id)
        remaining = max(0, 10 - score)
        await update.message.reply_text(
            f"You need {remaining} more reality points to unlock verification.",
            reply_markup=_main_keyboard(user.id),
        )


async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    user = update.effective_user
    if not message or not user or not message.photo:
        return

    row = get_user(user.id)
    if row is None or row["status"] != "matched" or row["partner_id"] in (None, 0):
        await _handle_unmatched_media_notice(update, context)
        return

    partner_id = row["partner_id"]
    await _route_media_upload(
        context,
        user.id,
        partner_id,
        "photo",
        message.photo[-1].file_id,
        message.caption,
    )


async def handle_document_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    user = update.effective_user
    if not message or not user or not message.document:
        return

    row = get_user(user.id)
    if row is None or row["status"] != "matched" or row["partner_id"] in (None, 0):
        await _handle_unmatched_media_notice(update, context)
        return

    await _route_media_upload(
        context,
        user.id,
        row["partner_id"],
        "document",
        message.document.file_id,
        message.caption or message.document.file_name,
    )


async def handle_animation_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    user = update.effective_user
    if not message or not user or not message.animation:
        return

    row = get_user(user.id)
    if row is None or row["status"] != "matched" or row["partner_id"] in (None, 0):
        await _handle_unmatched_media_notice(update, context)
        return

    await _route_media_upload(
        context,
        user.id,
        row["partner_id"],
        "video",
        message.animation.file_id,
        message.caption,
    )


async def handle_video_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    user = update.effective_user
    if not message or not user or not message.video:
        return

    row = get_user(user.id)
    if row is None or row["status"] != "matched" or row["partner_id"] in (None, 0):
        await _handle_unmatched_media_notice(update, context)
        return

    await _route_media_upload(
        context,
        user.id,
        row["partner_id"],
        "video",
        message.video.file_id,
        message.caption,
    )


async def handle_media_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    user = query.from_user
    if user is None:
        return

    parts = query.data.split(":")
    if len(parts) != 4:
        return

    _, action, sender_id_text, recipient_id_text = parts
    sender_id = int(sender_id_text)
    recipient_id = int(recipient_id_text)

    if user.id != recipient_id:
        return

    if action == "allow":
        set_media_permission(sender_id, recipient_id, True)
        await _deliver_media(context, sender_id, recipient_id)
        await _safe_edit_message(query.message, "✅ Media sharing allowed.")
        return

    if action == "deny":
        set_media_permission(sender_id, recipient_id, False)
        pop_pending_media(sender_id, recipient_id)
        await _safe_edit_message(query.message, "🚫 Media sharing denied.")
        return


async def handle_feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    user = query.from_user
    if user is None:
        return

    parts = query.data.split(":")
    if len(parts) != 3:
        return

    _, choice, target_id_text = parts
    target_id = int(target_id_text)
    prompt = get_feedback_prompt(user.id)
    if prompt is None or int(prompt["target_id"]) != target_id:
        return

    delta = 0
    if choice == "real":
        delta = 1
    elif choice == "not_real":
        delta = -1

    new_score = add_reality_score(target_id, delta)
    if new_score >= 10 and not is_verified(target_id):
        set_verified(target_id, True)

    pop_feedback_prompt(user.id)
    await _safe_edit_message(query.message, "⭐ Reality score saved.")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    context.user_data.pop("settings_mode", None)
    await update.message.reply_text("Cancelled.")


async def stop_search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user = update.effective_user
    row = get_user(user.id)
    if row is None:
        await update.message.reply_text("You are not registered yet. Use /start.")
        return

    if row["status"] == "waiting":
        remove_from_queue(user.id)
        _clear_queue_notice(context, user.id)
        await update.message.reply_text("✋ Search stopped. Use /start when you want to match again.")
        _cancel_emergency_task(context, user.id)
        _cancel_emergency_idle_task(context, user.id)
        _clear_emergency_session(context, user.id)
        return

    if row["status"] == "matched":
        await update.message.reply_text("You are already in a chat. Use /end if you want to leave it.")
        return

    await update.message.reply_text("There was no active search to stop.")


async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if not update.message or not user:
        return

    ensure_user(user.id, display_name(update))
    if chat is not None:
        await _sync_command_menu(context, chat.id, user.id)
    if not get_vip_mode_enabled():
        return
    bot_username = context.bot.username
    if not bot_username:
        await update.message.reply_text("Referral link is not ready yet.")
        return

    link = _referral_link(bot_username, user.id)
    await update.message.reply_text(
        f"🔗 Share this link:\n{link}\n\n"
        f"🎁 Referrals: {get_referral_count(user.id)}/3\n"
        "💎 Every 3 referrals gives 1 day VIP.\n"
        f"💎 VIP: {'On' if get_vip_enabled(user.id) else 'Off'}",
        reply_markup=_main_keyboard(user.id),
    )


async def sudo_give_vip_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    target_id: int | None = None
    if context.args and context.args[0].isdigit():
        target_id = int(context.args[0])
    else:
        parts = (update.message.text or "").split()
        if len(parts) >= 4 and parts[0].lower() == "sudo" and parts[1].lower() == "give" and parts[2].lower() == "vip" and parts[3].isdigit():
            target_id = int(parts[3])

    if target_id is None:
        await update.message.reply_text("Usage: sudo give vip <uid>")
        return

    ensure_user(target_id, f"User {target_id}")
    set_vip_enabled(target_id, True)
    try:
        await _sync_command_menu(context, target_id, target_id)
    except Exception:
        pass
    try:
        await context.bot.send_message(chat_id=target_id, text="💎 VIP unlocked.")
    except Exception:
        pass
    await update.message.reply_text(f"💎 VIP granted to {target_id}.")


async def sudo_get_runtime_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if not RUNTIME_STATE_PATH.exists():
        await update.message.reply_text("runtime_state.json is not available.")
        return
    with RUNTIME_STATE_PATH.open("rb") as runtime_file:
        await update.message.reply_document(
            document=runtime_file,
            filename="runtime_state.json",
            caption="runtime_state.json",
        )


async def handle_vip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = query.from_user if query else None
    if not query or not user or not query.data or not query.data.startswith("vip:buy:"):
        return
    await query.answer()
    if not get_vip_mode_enabled():
        await query.message.reply_text("VIP payments are currently unavailable.")
        return
    if get_vip_enabled(user.id):
        await query.message.reply_text("💎 You already have active VIP access.")
        return
    plan_key = query.data.split(":", 2)[2]
    plan = VIP_PLANS.get(plan_key)
    if plan is None:
        await query.message.reply_text("That VIP plan is not available.")
        return
    await context.bot.send_invoice(
        chat_id=user.id,
        title="VIP Access",
        description=f"VIP matching features for {plan['days']} days.",
        payload=plan["payload"],
        currency="XTR",
        prices=[LabeledPrice(f"VIP · {plan['days']} days", plan["stars"])],
        provider_token="",
    )


async def pre_checkout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.pre_checkout_query
    if query is None:
        return
    matched_plan = None
    for plan in VIP_PLANS.values():
        if query.invoice_payload == plan["payload"]:
            matched_plan = plan
            break
    valid = (
        get_vip_mode_enabled()
        and matched_plan is not None
        and query.currency == "XTR"
        and query.total_amount == matched_plan["stars"]
    )
    if valid:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="This VIP offer is no longer available.")


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    user = update.effective_user
    payment = message.successful_payment if message else None
    if not user or not payment or payment.currency != "XTR":
        return
    matched_plan = None
    for plan in VIP_PLANS.values():
        if payment.invoice_payload == plan["payload"] and payment.total_amount == plan["stars"]:
            matched_plan = plan
            break
    if matched_plan is None:
        return
    ensure_user(user.id, display_name(update))
    profile = get_profile(user.id)
    if profile and profile["last_payment_charge_id"] == payment.telegram_payment_charge_id:
        return
    expiry = grant_vip(
        user.id,
        days=matched_plan["days"],
        source="telegram_stars",
        charge_id=payment.telegram_payment_charge_id,
    )
    record_vip_payment(
        user.id,
        payment.telegram_payment_charge_id,
        payment.total_amount,
        payment.invoice_payload,
        vip_started_at=profile["vip_started_at"] if profile else None,
        vip_expires_at=expiry,
        vip_days=matched_plan["days"],
    )
    if update.effective_chat:
        await _sync_command_menu(context, update.effective_chat.id, user.id)
    expiry_text = expiry.replace("+00:00", " UTC")
    await message.reply_text(
        f"💎 VIP activated\n\n✨ {matched_plan['stars']} Stars received\n⏳ Active for {matched_plan['days']} days\n🗓 Expires: {expiry_text}",
        reply_markup=_main_keyboard(user.id),
    )


async def vip_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if not update.message or not user:
        return

    ensure_user(user.id, display_name(update))
    if chat is not None:
        await _sync_command_menu(context, chat.id, user.id)
    vip_enabled = get_vip_enabled(user.id)
    referral_count = get_referral_count(user.id)
    status_lines = [
        f"💎 {'You are VIP' if vip_enabled else 'You are not VIP'}",
        f"🎁 Referrals: {referral_count}/3",
        f"🔐 Global VIP Mode: {'On' if get_vip_mode_enabled() else 'Off'}",
    ]
    if vip_enabled:
        status_lines.append("✨ VIP features are ready.")
        expiry = get_vip_expiry(user.id)
        if expiry:
            status_lines.append(f"⏳ Expires: {expiry.replace('+00:00', ' UTC')}")
    else:
        status_lines.append("🔒 Use /referral to unlock VIP.")
    if get_vip_mode_enabled() and not vip_enabled:
        status_lines.append("💫 Get VIP with Telegram Stars: 25 Stars (7 days)")
        status_lines.append("💫 Get VIP with Telegram Stars: 75 Stars (30 days)")
    await update.message.reply_text(
        "\n".join(status_lines),
        reply_markup=_main_keyboard(user.id),
    )
    if get_vip_mode_enabled() and not vip_enabled:
        await update.message.reply_text(
            _vip_required_text(),
            reply_markup=_vip_keyboard(),
        )


async def sudo_vip_enable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    set_vip_mode_enabled(True)
    if update.effective_chat and update.effective_user:
        await _sync_command_menu(context, update.effective_chat.id, update.effective_user.id)
    await update.message.reply_text("💎 VIP mode enabled.")


async def sudo_vip_disable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    set_vip_mode_enabled(False)
    if update.effective_chat and update.effective_user:
        await _sync_command_menu(context, update.effective_chat.id, update.effective_user.id)
    await update.message.reply_text("💎 VIP mode disabled.")


async def sudo_vip_enable_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    set_vip_mode_enabled(True)
    if update.effective_chat and update.effective_user:
        await _sync_command_menu(context, update.effective_chat.id, update.effective_user.id)
    await update.message.reply_text("💎 VIP mode enabled.")


async def sudo_vip_disable_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    set_vip_mode_enabled(False)
    if update.effective_chat and update.effective_user:
        await _sync_command_menu(context, update.effective_chat.id, update.effective_user.id)
    await update.message.reply_text("💎 VIP mode disabled.")


async def _rearm_waiting_emergency_matches(context: ContextTypes.DEFAULT_TYPE) -> None:
    for waiting_row in get_waiting_users():
        user_id = int(waiting_row["user_id"])
        joined_at = waiting_row["joined_at"]
        elapsed = 0
        joined = _parse_iso_datetime(joined_at)
        if joined is not None:
            elapsed = int((datetime.now(timezone.utc) - joined).total_seconds())
        _schedule_emergency_task(context, user_id, max(0, EMERGENCY_TIMEOUT_SECONDS - elapsed))


async def sudo_emg_enable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    set_emergency_mode_enabled(True)
    await update.message.reply_text("🚦 Traffic mode enabled.")


async def sudo_emg_disable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    set_emergency_mode_enabled(False)
    await _cancel_all_emergency_mode_tasks(context)
    await _cancel_all_emergency_idle_tasks(context)
    await _cancel_all_emergency_leave_tasks(context)
    await update.message.reply_text("🚦 Traffic mode disabled.")


async def sudo_emg_enable_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    set_emergency_mode_enabled(True)
    await update.message.reply_text("🚦 Traffic mode enabled.")


async def sudo_emg_disable_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    set_emergency_mode_enabled(False)
    await _cancel_all_emergency_mode_tasks(context)
    await _cancel_all_emergency_idle_tasks(context)
    await _cancel_all_emergency_leave_tasks(context)
    await update.message.reply_text("🚦 Traffic mode disabled.")


async def sudo_abuse_enable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    set_abuse_protection_enabled(True)
    await update.message.reply_text("🛡 Abuse protection enabled.")


async def sudo_abuse_disable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    set_abuse_protection_enabled(False)
    await update.message.reply_text("🛡 Abuse protection disabled.")


async def sudo_list_anon_commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "🔐 <b>Anonymous Commands</b>\n\n"
        "<b>Mode Control</b>\n"
        "• <code>sudo enable vip</code> — Enable VIP mode\n"
        "• <code>sudo disable vip</code> — Disable VIP mode\n"
        "• <code>sudo enable traffic</code> — Enable traffic fallback\n"
        "• <code>sudo disable traffic</code> — Disable traffic fallback\n"
        "• <code>sudo enable abuse protection</code> — Leave on abusive words\n"
        "• <code>sudo disable abuse protection</code> — Talk normally on abusive words\n"
        "• <code>sudo enable notinchat</code> — Show not in chat warning\n"
        "• <code>sudo disable notinchat</code> — Hide not in chat warning\n\n"
        "<b>VIP Admin</b>\n"
        "• <code>sudo give vip &lt;uid&gt;</code> — Grant VIP to a user\n"
        "• <code>sudo get runtime_state.json</code> — Download runtime state\n\n"
        "<b>Utility</b>\n"
        "• <code>sudo list anon commands</code> — Show this list",
        parse_mode=ParseMode.HTML,
    )


async def sudo_notinchat_enable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    set_not_in_chat_warning_enabled(True)
    await update.message.reply_text("💬 Not in chat warning enabled.")


async def sudo_notinchat_disable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    set_not_in_chat_warning_enabled(False)
    await update.message.reply_text("💬 Not in chat warning disabled.")


async def sudo_traffic_enable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    set_emergency_mode_enabled(True)
    await update.message.reply_text("🚦 Traffic mode enabled.")


async def sudo_traffic_disable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    set_emergency_mode_enabled(False)
    await _cancel_all_emergency_mode_tasks(context)
    await _cancel_all_emergency_idle_tasks(context)
    await _cancel_all_emergency_leave_tasks(context)
    await update.message.reply_text("🚦 Traffic mode disabled.")


async def find_male_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    user = update.effective_user
    if not _vip_access_allowed(user.id):
        await vip_status_command(update, context)
        return
    set_user_preferred_gender(user.id, "male")
    await join_or_match(update, context)


async def find_female_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    user = update.effective_user
    if not _vip_access_allowed(user.id):
        await vip_status_command(update, context)
        return
    set_user_preferred_gender(user.id, "female")
    await join_or_match(update, context)


async def post_init(application: Application) -> None:
    await application.bot.set_my_commands(PUBLIC_COMMANDS)
    application.bot_data.setdefault(EMERGENCY_TASK_KEY, {})
    application.bot_data.setdefault(EMERGENCY_IDLE_TASK_KEY, {})
    application.bot_data.setdefault(EMERGENCY_LEAVE_TASK_KEY, {})
    if get_emergency_mode_enabled():
        for user_id in get_all_user_ids():
            row = get_user(user_id)
            if row is None:
                continue
            if row["status"] == "waiting":
                if get_vip_enabled(user_id):
                    continue
                joined_at = row["joined_at"]
                elapsed = 0
                joined = _parse_iso_datetime(joined_at)
                if joined is not None:
                    elapsed = int((datetime.now(timezone.utc) - joined).total_seconds())
                _schedule_emergency_task(application, user_id, max(0, EMERGENCY_TIMEOUT_SECONDS - elapsed))
            elif row["status"] == "matched" and bool(row["is_emergency"]):
                _schedule_emergency_leave_task(application, user_id, random.uniform(3.0, 7.0))


def main() -> None:
    token = TELEGRAM_BOT_TOKEN or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN in telegram_bot.py before starting the bot.")
    if token == "PASTE_YOUR_BOTFATHER_TOKEN_HERE":
        raise RuntimeError("Replace PASTE_YOUR_BOTFATHER_TOKEN_HERE in telegram_bot.py with your bot token.")

    init_db()
    app = Application.builder().token(token).post_init(post_init).build()
    app.bot_data["names"] = {}

    app.add_handler(CommandHandler("start", join_or_match))
    app.add_handler(CommandHandler("next", next_match))
    app.add_handler(CommandHandler("end", stop_chat))
    app.add_handler(CommandHandler("stop", stop_search_command))
    app.add_handler(CommandHandler("disconnect", stop_chat))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("verify", verify_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("findmale", find_male_command))
    app.add_handler(CommandHandler("findfemale", find_female_command))
    app.add_handler(CommandHandler("referral", referral_command))
    app.add_handler(CommandHandler("vip", vip_status_command))
    app.add_handler(CommandHandler("sudo_vip_enable", sudo_vip_enable_command))
    app.add_handler(CommandHandler("sudo_vip_disable", sudo_vip_disable_command))
    app.add_handler(CommandHandler("sudoenablevip", sudo_vip_enable_command))
    app.add_handler(CommandHandler("sudodisablevip", sudo_vip_disable_command))
    app.add_handler(CommandHandler("sudogivevip", sudo_give_vip_command))
    app.add_handler(CommandHandler("sudogetruntime", sudo_get_runtime_command))
    app.add_handler(CommandHandler("sudoenableemg", sudo_emg_enable_command))
    app.add_handler(CommandHandler("sudodisableemg", sudo_emg_disable_command))
    app.add_handler(
        PreCheckoutQueryHandler(
            pre_checkout_callback,
            pattern=rf"^(?:{re.escape(VIP_PLANS['25']['payload'])}|{re.escape(VIP_PLANS['75']['payload'])})$",
        )
    )
    app.add_handler(MessageHandler(filters.Regex(r"^sudo\s+enable\s+vip$"), sudo_vip_enable_text))
    app.add_handler(MessageHandler(filters.Regex(r"^sudo\s+disable\s+vip$"), sudo_vip_disable_text))
    app.add_handler(MessageHandler(filters.Regex(r"^sudo\s+give\s+vip\s+\d+$"), sudo_give_vip_command))
    app.add_handler(MessageHandler(filters.Regex(r"^sudo\s+get\s+runtime_state\.json$"), sudo_get_runtime_command))
    app.add_handler(MessageHandler(filters.Regex(r"^sudo\s+enable\s+emg$"), sudo_emg_enable_text))
    app.add_handler(MessageHandler(filters.Regex(r"^sudo\s+disable\s+emg$"), sudo_emg_disable_text))
    app.add_handler(MessageHandler(filters.Regex(r"^sudo\s+enable\s+traffic$"), sudo_traffic_enable_command))
    app.add_handler(MessageHandler(filters.Regex(r"^sudo\s+disable\s+traffic$"), sudo_traffic_disable_command))
    app.add_handler(MessageHandler(filters.Regex(r"^sudo\s+enable\s+abuse\s+protection$"), sudo_abuse_enable_command))
    app.add_handler(MessageHandler(filters.Regex(r"^sudo\s+disable\s+abuse\s+protection$"), sudo_abuse_disable_command))
    app.add_handler(MessageHandler(filters.Regex(r"^sudo\s+list\s+anon\s+commands$"), sudo_list_anon_commands_command))
    app.add_handler(MessageHandler(filters.COMMAND, route_command_text))
    app.add_handler(CallbackQueryHandler(handle_settings_callback, pattern=r"^settings:"))
    app.add_handler(CallbackQueryHandler(handle_media_callback, pattern=r"^media:"))
    app.add_handler(CallbackQueryHandler(handle_feedback_callback, pattern=r"^feedback:"))
    app.add_handler(CallbackQueryHandler(handle_vip_callback, pattern=r"^vip:"))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_settings_input))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document_message))
    app.add_handler(MessageHandler(filters.ANIMATION, handle_animation_message))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video_message))

    public_url = os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if public_url:
        webhook_path = os.getenv("BOT_WEBHOOK_PATH", "telegram")
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.getenv("PORT", "10000")),
            url_path=webhook_path,
            webhook_url=f"{public_url.rstrip('/')}/{webhook_path}",
            drop_pending_updates=True,
        )
        return

    app.run_polling(poll_interval=2.0, timeout=30, drop_pending_updates=True)


if __name__ == "__main__":
    main()
