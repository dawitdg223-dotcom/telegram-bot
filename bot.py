import os
from threading import Thread
from flask import Flask

# --- KEEP ALIVE WEB SERVER ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()

keep_alive()
# ------------------------------

import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException
import yt_dlp

# Automatically download & add FFmpeg to system PATH for Render
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception as e:
    print(f"FFmpeg setup warning: {e}")

# ================= CONFIGURATION =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8984748799:AAGO7ebLuvqVreF6871Zo2sCFSU8XstOtUw")
CHANNEL_ID = -1003955525068
CHANNEL_URL = "https://t.me/vidsnaphd"
CHANNEL_USERNAME = "@vidsnaphd"
BOT_USERNAME = "@VidSnapHD_bot"
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
        "Just drop the video link here and I will download the video & audio for you!"
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

    status_msg = bot.reply_to(message, "⚡ *Downloading video & audio...*", parse_mode="Markdown")
    
    video_file = f"video_{message.chat.id}_{message.message_id}.mp4"
    audio_file = f"audio_{message.chat.id}_{message.message_id}.mp3"
    
    ydl_opts_video = {
        'format': 'best',
        'outtmpl': video_file,
        'quiet': True,
        'no_warnings': True,
        'max_filesize': 50 * 1024 * 1024,
    }

    ydl_opts_audio = {
        'format': 'bestaudio/best',
        'outtmpl': f"audio_{message.chat.id}_{message.message_id}",
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
        'no_warnings': True,
    }

    try:
        # 1. Download & Send Video
        with yt_dlp.YoutubeDL(ydl_opts_video) as ydl:
            ydl.download([url])

        if os.path.exists(video_file):
            with open(video_file, 'rb') as vf:
                bot.send_video(message.chat.id, vf, caption=f"⚡ Downloaded via {BOT_USERNAME}")

        # 2. Extract & Send Audio
        with yt_dlp.YoutubeDL(ydl_opts_audio) as ydl:
            ydl.download([url])

        if os.path.exists(audio_file):
            with open(audio_file, 'rb') as af:
                bot.send_audio(message.chat.id, af, caption=f"🎵 Audio Track via {BOT_USERNAME}")

        # Delete status message
        try:
            bot.delete_message(message.chat.id, status_msg.message_id)
        except Exception:
            pass

    except Exception as e:
        bot.edit_message_text(f"❌ Failed: {str(e)}", message.chat.id, status_msg.message_id)
        
    finally:
        # Cleanup files
        if os.path.exists(video_file):
            os.remove(video_file)
        if os.path.exists(audio_file):
            os.remove(audio_file)

if __name__ == "__main__":
    print("🚀 VidSnapHD Bot is running successfully!")
    bot.infinity_polling()
