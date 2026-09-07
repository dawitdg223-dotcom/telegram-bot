import os
import logging
import asyncio
from threading import Thread
from flask import Flask

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Config: Set your Telegram Bot Token here or via Environment Variable
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE")

# --- 1. FLASK KEEP-ALIVE SERVER (Runs on Top Port 8080) ---
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is awake and running 24/7!"

def run_web_server():
    # Listens on port 8080 (Change port if required by your host)
    web_app.run(host="0.0.0.0", port=8080)

def keep_alive():
    t = Thread(target=run_web_server)
    t.daemon = True
    t.start()

# --- 2. TELEGRAM BOT HANDLERS ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message."""
    await update.message.reply_text(
        "👋 Welcome! Send me any social media video link (YouTube, TikTok, Instagram, Twitter/X, etc.), "
        "and I will download and send it to you."
    )

async def handle_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Downloads video/audio using yt-dlp and sends it to the user."""
    url = update.message.text.strip()
    status_msg = await update.message.reply_text("🔄 Processing link... Please wait.")

    # Options for yt-dlp (Downloads best available quality under 50MB for Telegram)
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': 'downloads/%(id)s.%(ext)s',
        'max_filesize': 50 * 1024 * 1024,  # Telegram's standard bot upload limit is 50MB
        'quiet': True,
    }

    loop = asyncio.get_event_loop()

    def process_url():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            return filename, info.get('title', 'Video')

    try:
        # Run yt-dlp download in a separate thread so it doesn't block the bot
        file_path, title = await loop.run_in_executor(None, process_url)

        await status_msg.edit_text("📤 Uploading media to Telegram...")
        
        # Send the file back to the Telegram chat
        with open(file_path, 'rb') as video_file:
            await update.message.reply_video(video=video_file, caption=f"🎬 {title}")
            
        await status_msg.delete()

        # Clean up local file after sending
        if os.path.exists(file_path):
            os.remove(file_path)

    except yt_dlp.utils.DownloadError:
        await status_msg.edit_text("❌ Download failed. Make sure the URL is valid or public.")
    except Exception as e:
        logger.error(f"Error handling download: {e}")
        await status_msg.edit_text(f"❌ An error occurred: {str(e)}")

# --- 3. MAIN APPLICATION ROUTINE ---
def main():
    # Start the Flask Web Server in the background to keep the container/repl alive
    logger.info("Starting web server for 24/7 uptime...")
    keep_alive()

    # Create local downloads folder
    os.makedirs("downloads", exist_ok=True)

    # Build Telegram Bot application
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands & Message Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_download))

    # Run Telegram Bot
    logger.info("Bot is starting polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
