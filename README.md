# Random Chat Telegram Bot

This is a standalone Telegram bot for random stranger matching.

## What it does

- `/start` joins the queue
- `/next` skips to a new stranger
- `/end` disconnects
- `/status` shows current state
- `/settings` opens your profile panel
- `/verify` requests a verified badge
- Anonymous matching and anonymous chat relay
- Emoji-rich status messages for match and end events
- A persistent on-screen button menu for quick actions

## Match messages

The bot now uses emoji-rich status replies like:

- `🎉 Partner Found!`
- `👋 Chat Ended`
- `🔎 Finding a match...`

It also shows your wait time for a match when possible.

Matching stays anonymous:

- no partner name is shown
- no age or profile details are shown on match success
- sent messages are relayed without showing the sender name
- no success reply is sent after a message is delivered

Verified matches:

- users can rate the last chat with `Real`, `Not real`, or `Don’t know`
- reality scores increase or decrease from that feedback
- once a user reaches 10 reality points, they can unlock the verified badge with `/verify`
- verified users can turn on `Verified-only` matching in `/settings`

VIP payments:

- when global VIP mode is enabled, the `/vip` card shows `Get VIP by pay · 25 Stars (7 days)`
- Telegram Stars payments use the `XTR` currency and activate VIP only after Telegram confirms successful payment
- the payment is checked during pre-checkout and duplicate charge IDs are ignored
- VIP start time, expiry time, source, payment charge ID, and user profile data are saved in `runtime_state.json`
- the existing SQLite profile is also updated, so access survives a restart

Media sharing:

- photos are forwarded without resizing, compression, or AI processing
- the first media attempt asks the other person for approval
- if they allow it, media sharing stays enabled for that chat
- if they deny it, nothing is sent

## Settings panel

Use `/settings` to set:

- your age
- your gender
- preferred partner gender
- preferred partner age range
- verified-only matching

This is done with an inline button panel and quick text prompts for age fields.

## Button menu

The big button bar below the message box is added in code with `ReplyKeyboardMarkup`.

It shows these actions:

- `🎲 Find a Partner`
- `⚙️ Settings`
- `⏭ Next Partner`
- `👋 End Chat`
- `ℹ️ Status`
- `❓ Help`
- `🛡 Verify Me`

This is not something you set in BotFather. BotFather controls the slash-command list, while this button bar comes from the bot code.

## Bot commands

- `/start` - join the waiting queue or get matched
- `/next` - end the current chat and search again
- `/end` - leave the chat
- `/stop` - alias for `/end`
- `/disconnect` - alias for `/end`
- `/status` - show whether you are idle, waiting, or matched
- `/settings` - open the profile/settings panel
- `/verify` - request a verified badge
- `/help` - show the command list
- `/cancel` - cancel a settings input prompt
- `/vip` - show VIP status and, when global VIP mode is enabled, the Stars purchase option

Hidden maintenance command:

- `sudo get runtime_state.json` sends the current JSON state file as an attachment
- `/sudogetruntime` is an equivalent slash-command alias

The slash-command list is also registered in code with `set_my_commands`, so it appears automatically in Telegram clients.

## Local run

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Paste your bot token into `telegram_bot.py`:
   ```python
   TELEGRAM_BOT_TOKEN = "YOUR_REAL_BOT_TOKEN"
   ```

3. Start the bot:
   ```bash
   python telegram_bot.py
   ```

## Render deploy

Use this project as a Render worker service, not a Streamlit app.

- Root directory: `telegrambot`
- Build command: `pip install -r requirements.txt`
- Start command: `python telegram_bot.py`

## Notes

- SQLite is fine for a prototype.
- If you later want true always-on public hosting, a webhook setup is better than polling.
- Emergency fallback is available only after 30 seconds for users whose preferred partner gender is `Female`; other users stay in the human-match queue.
- Inactivity exit notices are sent before emergency chats are cleared, and conversation replies convert accidental HTML line-break tags to normal newlines.
