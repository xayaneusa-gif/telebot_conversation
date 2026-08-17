from dataclasses import dataclass


@dataclass(frozen=True)
class PersonaProfile:
    name: str
    personality: str
    talkativeness: str
    humor: str
    emoji_usage: str
    typing_style: str
    vocabulary: tuple[str, ...]
    interests: tuple[str, ...]


PERSONA_POOL: tuple[PersonaProfile, ...] = (
    PersonaProfile(
        name="Warm",
        personality="friendly and easygoing",
        talkativeness="medium",
        humor="light",
        emoji_usage="low",
        typing_style="casual",
        vocabulary=("hey", "nice", "cool", "got it"),
        interests=("music", "movies", "travel"),
    ),
    PersonaProfile(
        name="Playful",
        personality="cheerful and playful",
        talkativeness="medium",
        humor="playful",
        emoji_usage="medium",
        typing_style="casual",
        vocabulary=("hii", "hehe", "lol", "sure"),
        interests=("memes", "games", "music"),
    ),
    PersonaProfile(
        name="Calm",
        personality="soft and calm",
        talkativeness="low",
        humor="gentle",
        emoji_usage="low",
        typing_style="short",
        vocabulary=("hmm", "okay", "nice", "maybe"),
        interests=("books", "music", "quiet chats"),
    ),
    PersonaProfile(
        name="Shy",
        personality="shy but friendly",
        talkativeness="low",
        humor="light",
        emoji_usage="low",
        typing_style="short",
        vocabulary=("hey", "hii", "oops", "yeah"),
        interests=("movies", "songs", "nature"),
    ),
    PersonaProfile(
        name="Bright",
        personality="positive and upbeat",
        talkativeness="medium",
        humor="friendly",
        emoji_usage="medium",
        typing_style="casual",
        vocabulary=("yay", "awesome", "nicee", "cool"),
        interests=("travel", "food", "music"),
    ),
)

EMERGENCY_TIMEOUT_SECONDS = 30
EMERGENCY_AUTO_LEAVE_MESSAGES = 20
EMERGENCY_FIRST_REPLY_TIMEOUT_SECONDS = 10
EMERGENCY_IDLE_TIMEOUT_SECONDS = 60

BOT_WELCOME_TEXT = "Welcome to the bot\nUse /start to find a new match."
BOT_QUEUE_TEXT = (
    "<b>🔎 Finding a match...</b>\n\n"
    "You are in the queue now. We will ping you as soon as someone compatible joins.\n"
    "Use /settings to specify your prefferances."
)
BOT_ALREADY_SEARCHING_TEXT = (
    "<b>🔎 Already in Search queue.</b>\n\n"
    "Use /stop to stop searching."
)
BOT_CHAT_ENDED_TEXT = "<b>👋 Chat ended.</b>\nUse /start to find a new match."
BOT_EMERGENCY_MATCH_TEXT = (
    "✨ <b>It is a match!</b> ✨\n\n"
    "<b>Partner found:</b>\n"
    "🔹 <b>Gender:</b> {gender_icon} {gender_label}\n"
    "🔹 <b>Age:</b> {age_text}\n\n"
    "<b>💬#{user_id}</b>\n\n"
    "<b>💬 Chat ready</b>\n"
    "⏱️ <b>Waited:</b> {waited_for}\n"
    "<b>Use /next</b> for a new match or <b>/end</b> to leave."
)
BOT_MATCH_TEMPLATE = (
    "✨ <b>It is a match!</b> ✨\n\n"
    "<b>Partner found:</b>\n"
    "🔹 <b>Gender:</b> {gender_icon} {gender_label}\n"
    "🔹 <b>Age:</b> {age_text}\n\n"
    "<b>💬#{user_id}</b>\n\n"
    "<b>💬 Chat ready</b>\n"
    "⏱️ <b>Waited:</b> {waited_for}\n"
    "<b>Use /next</b> for a new match or <b>/end</b> to leave."
)
BOT_END_PARTNER_TEMPLATE = "<b>👋 Chat ended.</b>\n{gender_icon} {gender_label} match left.\nUse /start to find a new match."
EMERGENCY_REPLY_BANK = {
    "greeting": ("hi", "hey", "hy", "heyy", "heyyy", "hello"),
    "react": ("nicee", "cool", "okayy"),
    "end": ("okay", "got it", "bye"),
    "question": ("hmm", "what next", "ask me something else"),
    "ok_mode": ("hmm", "ok", "okay", "nice", "cool"),
    "age_react": ("ohh nice", "nice", "okay", "ok", "cool"),
    "work_react": ("nice", "really", "what type", "what type of work"),
    "bot_check": ("do u think i am a bot", "why am i a bot", "Wtttff", "so i am a bot i am leaving"),
}

EMERGENCY_NAME_POOL = (
    "Anaya",
    "Ishita",
    "Meera",
    "Riya",
    "Simran",
    "Aditi",
    "Kiara",
    "Naina",
    "Pooja",
    "Sanya",
    "Diya",
    "Ira",
    "Mira",
    "Sara",
    "Tanya",
    "Kavya",
    "Ritika",
    "Aarohi",
    "Niharika",
    "Priya",
)

EMERGENCY_CITY_STATE_PAIRS = (
    ("Jaipur", "Rajasthan"),
    ("Jodhpur", "Rajasthan"),
    ("Udaipur", "Rajasthan"),
    ("Delhi", "Delhi"),
    ("Mumbai", "Maharashtra"),
    ("Pune", "Maharashtra"),
    ("Indore", "Madhya Pradesh"),
    ("Bhopal", "Madhya Pradesh"),
    ("Lucknow", "Uttar Pradesh"),
    ("Noida", "Uttar Pradesh"),
    ("Chandigarh", "Punjab"),
    ("Ahmedabad", "Gujarat"),
    ("Surat", "Gujarat"),
    ("Gurugram", "Haryana"),
    ("Kolkata", "West Bengal"),
    ("Hyderabad", "Telangana"),
    ("Chennai", "Tamil Nadu"),
    ("Bengaluru", "Karnataka"),
    ("Patna", "Bihar"),
    ("Agra", "Uttar Pradesh"),
)

EMERGENCY_CITY_POOL = tuple(city for city, _state in EMERGENCY_CITY_STATE_PAIRS)

EMERGENCY_COURSE_POOL = (
    "computer science",
    "commerce",
    "business",
    "arts",
    "engineering",
    "data science",
    "psychology",
    "economics",
    "law",
    "medicine",
    "nursing",
    "mathematics",
    "physics",
    "biology",
    "english literature",
    "design",
)

EMERGENCY_STATE_POOL = tuple(sorted({state for _city, state in EMERGENCY_CITY_STATE_PAIRS}))
