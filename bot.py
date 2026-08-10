import os
from threading import Thread
from flask import Flask

# --- KEEP ALIVE WEB SERVER ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()

keep_alive()
# ------------------------------

import os
import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException
import yt_dlp

# ================= CONFIGURATION =================
# Recommended: Set this as an environment variable in Render/PythonAnywhere
BOT_TOKEN = os.getenv("BOT_TOKEN", "8984748799:AAGO7ebLuvqVreF6871Zo2sCFSU8XstOtUw")
CHANNEL_ID = -1003955525068
CHANNEL_URL = "https://t.me/vidsnaphd"
CHANNEL_USERNAME = "@vidsnaphd"
# =================================================

bot = telebot.TeleBot(BOT_TOKEN)

def is_subscribed(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['creator', 'administrator', 'member']
    except ApiTelegramException:
        return False

def show_sub_prompt(chat_id):
    markup = types.InlineKeyboardMarkup()
    btn_sub = types.InlineKeyboardButton("📢 Join Official Channel", url=CHANNEL_URL)
    btn_check = types.InlineKeyboardButton("🔄 Verify Membership", callback_data="check_sub")
    markup.add(btn_sub)
    markup.add(btn_check)

    msg = (
        "⚠️ *Access Restricted!*\n\n"
        f"To use *VidSnapHD Bot*, you must first join our official update channel: {CHANNEL_USERNAME}.\n\n"
        "Click the button below to join, then press *Verify Membership* to start downloading!"
    )
    bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=['start', 'help'])
def start_command(message):
    user_id = message.from_user.id
    if not is_subscribed(user_id):
        show_sub_prompt(message.chat.id)
        return

    welcome_msg = (
        f"👋 Welcome *{message.from_user.first_name}* to *VidSnapHD*!\n\n"
        "⚡ Send me ANY video link from:\n"
        "• 📱 *TikTok* _(No Watermark)_\n"
        "• 📸 *Instagram* _(Reels, Posts, Stories)_\n"
        "• ▶️ *YouTube* _(Shorts & Videos)_\n\n"
        "Just drop the video link here and I will download it instantly!"
    )
    bot.send_message(message.chat.id, welcome_msg, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "check_sub")
def callback_verify_sub(call):
    user_id = call.from_user.id
    if is_subscribed(user_id):
        bot.answer_callback_query(call.id, "✅ Subscription confirmed! Enjoy downloads.", show_alert=True)
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        bot.send_message(call.message.chat.id, "🎉 *Access Unlocked!* Send me a video link now.", parse_mode="Markdown")
    else:
        bot.answer_callback_query(call.id, "❌ You haven't joined the channel yet!", show_alert=True)

@bot.message_handler(func=lambda message: True)
def process_video_link(message):
    user_id = message.from_user.id
    if not is_subscribed(user_id):
        show_sub_prompt(message.chat.id)
        return

    url = message.text.strip()
    if not url.startswith(("http://", "https://")):
        bot.reply_to(message, "❌ Please send a valid video URL link.")
        return

    status_msg = bot.reply_to(message, "⚡ *Downloading video... Please wait...*", parse_mode="Markdown")
    file_name = f"video_{message.chat.id}_{message.message_id}.mp4"
    
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': file_name,
        'quiet': True,
        'no_warnings': True,
        'max_filesize': 50 * 1024 * 1024,  # Restrict to 50MB limit for Telegram
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if os.path.exists(file_name):
            with open(file_name, 'rb') as video_file:
                bot.send_video(message.chat.id, video_file, caption="⚡ Downloaded via @vidsnaphd")
            bot.delete_message(message.chat.id, status_msg.message_id)
        else:
            bot.edit_message_text("❌ Failed to output media file.", message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.edit_message_text("❌ Error downloading video. Check if the link is public or under 50MB.", message.chat.id, status_msg.message_id)
    finally:
        # Guarantee cleanup of local file
        if os.path.exists(file_name):
            os.remove(file_name)

if __name__ == "__main__":
    print("🚀 VidSnapHD Bot is running successfully!")
    bot.infinity_polling()
