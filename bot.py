import sqlite3
import time
import requests
import asyncio
import os
import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, 
    LabeledPrice, ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    PreCheckoutQueryHandler, ContextTypes, MessageHandler, filters
)

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8640300552:AAFfkOURl7_8hZ71uebsDfWsk4Zwls00vLc")
FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "e76280d3408441a6891d1caf72998b1b")

CHANNEL_ID = -1003955525068
CHANNEL_LINK = "https://t.me/vidsnaphd"
ADMIN_USER_ID = 5287278470  # Admin Telegram ID

# Telegram Gift ID used for automated payouts (Replace with active Gift ID from Telegram)
TELEGRAM_GIFT_ID = "521111022838031523"

HOUSE_CUT_PERCENT = 0.20  # 20% Admin Profit
TIERS = [10, 50, 100, 500, 1000]

MATCHES_CACHE = {"timestamp": 0, "data": []}
CACHE_DURATION = 300

# --- MAIN PERSISTENT KEYBOARD MENU ---
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("⚽ View Matches"), KeyboardButton("🏆 Leaderboard")],
        [KeyboardButton("💰 My Balance"), KeyboardButton("📤 Withdraw Stars")],
        [KeyboardButton("❓ How to Play")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect("betiball.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            star_balance INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            match_id INTEGER,
            tier INTEGER,
            predicted_score TEXT,
            status TEXT DEFAULT 'PENDING'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_profits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def db_add_user(user_id, username):
    conn = sqlite3.connect("betiball.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username, star_balance) VALUES (?, ?, 0)", (user_id, username))
    conn.commit()
    conn.close()

def db_save_prediction(user_id, match_id, tier, score):
    conn = sqlite3.connect("betiball.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO predictions (user_id, match_id, tier, predicted_score) VALUES (?, ?, ?, ?)", 
                   (user_id, match_id, tier, score))
    
    profit = int(tier * HOUSE_CUT_PERCENT)
    cursor.execute("INSERT INTO admin_profits (amount) VALUES (?)", (profit,))
    
    conn.commit()
    conn.close()

# --- CHANNEL FORCE-SUB CHECK ---
async def is_user_subscribed(bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["creator", "administrator", "member"]
    except Exception as e:
        print(f"Sub Check Error (Ensure bot is ADMIN in channel!): {e}")
        return False

async def send_join_request_message(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📢 Join Channel First", url=CHANNEL_LINK)],
        [InlineKeyboardButton("✅ Verify Subscription", callback_data="check_sub")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = (
        "⚠️ **ACCESS DENIED!** ⚠️\n\n"
        "You must join our official Telegram Channel to use Football Betting Bot!\n\n"
        "1️⃣ Tap **'📢 Join Channel First'** below.\n"
        "2️⃣ Tap **'✅ Verify Subscription'** after joining!"
    )
    if hasattr(update_or_query, 'message') and update_or_query.message:
        await update_or_query.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

# --- MATCH API FETCHING ---
def get_today_matches():
    current_time = time.time()
    if current_time - MATCHES_CACHE["timestamp"] < CACHE_DURATION and MATCHES_CACHE["data"]:
        return MATCHES_CACHE["data"]

    today = datetime.date.today()
    next_week = today + datetime.timedelta(days=7)

    url = f"https://api.football-data.org/v4/matches?dateFrom={today}&dateTo={next_week}"
    headers = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            matches = response.json().get("matches", [])
            MATCHES_CACHE["timestamp"] = current_time
            MATCHES_CACHE["data"] = matches
            return matches
        return MATCHES_CACHE["data"]
    except Exception as e:
        print(f"Match Fetch Error: {e}")
        return MATCHES_CACHE["data"]

def calculate_points(pred_score, actual_h, actual_a):
    try:
        pred_h, pred_a = map(int, pred_score.split("-"))
    except ValueError:
        return 0

    if pred_h == actual_h and pred_a == actual_a:
        return 3
    
    pred_diff = pred_h - pred_a
    actual_diff = actual_h - actual_a
    if (pred_diff > 0 and actual_diff > 0) or (pred_diff < 0 and actual_diff < 0) or (pred_diff == 0 and actual_diff == 0):
        return 1
        
    return 0

# --- AUTOMATED SETTLEMENT & INSTANT GIFT PAYOUT JOB ---
async def auto_settle_and_payout_job(context: ContextTypes.DEFAULT_TYPE):
    matches = get_today_matches()
    finished_matches = {m["id"]: m["score"]["fullTime"] for m in matches if m["status"] == "FINISHED"}

    if not finished_matches:
        return

    conn = sqlite3.connect("betiball.db")
    cursor = conn.cursor()

    for match_id, actual in finished_matches.items():
        actual_h, actual_a = actual["home"], actual["away"]
        if actual_h is None or actual_a is None:
            continue

        for tier in TIERS:
            cursor.execute("""
                SELECT id, user_id, predicted_score 
                FROM predictions 
                WHERE match_id = ? AND tier = ? AND status = 'PENDING'
            """, (match_id, tier))
            pending = cursor.fetchall()

            if not pending:
                continue

            scores = []
            for pred_id, u_id, p_score in pending:
                pts = calculate_points(p_score, actual_h, actual_a)
                scores.append({"pred_id": pred_id, "user_id": u_id, "points": pts})

            max_pts = max([s["points"] for s in scores])

            if max_pts > 0:
                winners = [s for s in scores if s["points"] == max_pts]
                total_pool_stars = len(scores) * tier
                net_prize_pool = int(total_pool_stars * (1 - HOUSE_CUT_PERCENT))
                share_per_winner = net_prize_pool // len(winners)

                for w in winners:
                    user_id = w["user_id"]
                    cursor.execute("UPDATE predictions SET status = 'SETTLED_WIN' WHERE id = ?", (w["pred_id"],))

                    # AUTOMATED STAR GIFT TRANSFER
                    try:
                        await context.bot.send_gift(
                            user_id=user_id,
                            gift_id=TELEGRAM_GIFT_ID,
                            text=f"🏆 Congratulations! You won {share_per_winner} Stars in the match pool!"
                        )
                        print(f"✅ Automated Gift sent to user {user_id}")
                    except Exception as e:
                        print(f"❌ Gift API Error, adding to balance fallback: {e}")
                        cursor.execute("UPDATE users SET star_balance = star_balance + ? WHERE user_id = ?", (share_per_winner, user_id))

                        try:
                            msg = (
                                f"🥳 **CONGRATULATIONS! YOU WON!** 🎉\n\n"
                                f"🏆 **Rank:** 1st Place (⭐ `{tier} Stars Room`)\n"
                                f"⚽ **Match ID:** `{match_id}`\n"
                                f"💰 **Prize Credit:** `{share_per_winner} Stars` added to your balance!\n\n"
                                f"Tap **💰 My Balance** to view total or **📤 Withdraw Stars** to claim!"
                            )
                            await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown")
                        except Exception as msg_err:
                            print(f"Error sending alert: {msg_err}")

            for s in scores:
                if s["points"] < max_pts or max_pts == 0:
                    cursor.execute("UPDATE predictions SET status = 'LOST' WHERE id = ?", (s["pred_id"],))

    conn.commit()
    conn.close()

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await is_user_subscribed(context.bot, user.id):
        await send_join_request_message(update, context)
        return

    db_add_user(user.id, user.username or user.first_name)

    welcome_text = (
        f"⚽ **Welcome {user.first_name} to Football Betting Bot!** ⭐\n\n"
        "Predict scorelines, join Star pools, and win automated Telegram Star Gifts!\n\n"
        "👇 **Tap '⚽ View Matches' below to start betting:**"
    )
    await update.message.reply_text(welcome_text, reply_markup=get_main_keyboard(), parse_mode="Markdown")

async def verify_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if await is_user_subscribed(context.bot, user_id):
        await query.answer("✅ Verification Successful! Welcome!", show_alert=True)
        db_add_user(user_id, query.from_user.username or query.from_user.first_name)
        
        welcome_text = (
            f"⚽ **Welcome {query.from_user.first_name}!** ⭐\n\n"
            "Predict match scores, climb leaderboards, and win Star prize pools!\n\n"
            "👇 Tap **'⚽ View Matches'** below to begin!"
        )
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_message(chat_id=user_id, text=welcome_text, reply_markup=get_main_keyboard(), parse_mode="Markdown")
    else:
        await query.answer("❌ You haven't joined @vidsnaphd yet! Join the channel then try again.", show_alert=True)

async def matches_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_user_subscribed(context.bot, user_id):
        await send_join_request_message(update, context)
        return

    matches = get_today_matches()
    if not matches:
        await update.message.reply_text("⚽ No scheduled matches found right now! Check back later.", reply_markup=get_main_keyboard())
        return

    await update.message.reply_text("⚽ **Upcoming Featured Matches:**\nTap a score button below to place your prediction!", parse_mode="Markdown")

    for m in matches[:5]:
        home = m.get("homeTeam", {}).get("name", "Home")
        away = m.get("awayTeam", {}).get("name", "Away")
        match_id = m.get("id")
        utc_date = m.get("utcDate", "")[:16].replace("T", " ")

        text = f"🏆 **{home}** vs **{away}**\n📅 Date: `{utc_date} UTC`\n🆔 Match ID: `{match_id}`"
        
        keyboard = [
            [InlineKeyboardButton("🎯 Pick 2-1", callback_data=f"pred_{match_id}_2-1"),
             InlineKeyboardButton("🎯 Pick 1-1", callback_data=f"pred_{match_id}_1-1")],
            [InlineKeyboardButton("🎯 Pick 1-0", callback_data=f"pred_{match_id}_1-0"),
             InlineKeyboardButton("🎯 Pick 0-2", callback_data=f"pred_{match_id}_0-2")]
        ]
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_prediction_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, match_id, score = query.data.split("_")

    keyboard = []
    for t in TIERS:
        keyboard.append([InlineKeyboardButton(f"⭐ Enter {t} Stars Tier Pool", callback_data=f"pay_{t}_{match_id}_{score}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(
        f"🎯 **Select Entry Pool Tier for Pick `{score}`:**",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_payment_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, tier_str, match_id, score = query.data.split("_")
    tier = int(tier_str)

    title = f"Football Prediction Pool"
    description = f"Match ID: {match_id} | Your Pick: {score}"
    payload = f"{match_id}:{tier}:{score}"

    # Native Telegram Stars Invoice Modal
    await context.bot.send_invoice(
        chat_id=query.message.chat_id,
        title=title,
        description=description,
        payload=payload,
        provider_token="",  # Must be empty string for Telegram Stars
        currency="XTR",      # Native Telegram Stars Code
        prices=[LabeledPrice(f"{tier} Telegram Stars", tier)]
    )

async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    payload = update.message.successful_payment.invoice_payload

    match_id, tier, score = payload.split(":")
    db_save_prediction(user.id, int(match_id), int(tier), score)

    await update.message.reply_text(
        f"🎉 **STARS PAYMENT RECEIVED! TICKET CONFIRMED!** 🎉\n\n"
        f"🆔 **Match ID:** `{match_id}`\n"
        f"⭐ **Entry Tier:** `{tier} Stars Pool`\n"
        f"🎯 **Your Prediction:** `{score}`\n\n"
        f"Good luck! Winner prize pools settle and distribute automatically at full-time!",
        parse_mode="Markdown"
    )

async def balance_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect("betiball.db")
    cursor = conn.cursor()
    cursor.execute("SELECT star_balance FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    balance = row[0] if row else 0
    await update.message.reply_text(
        f"💰 **Your Current Star Balance:** `{balance} Stars`\n\n"
        f"All fallback pool credits accumulate here!",
        parse_mode="Markdown"
    )

async def withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect("betiball.db")
    cursor = conn.cursor()
    cursor.execute("SELECT star_balance FROM users WHERE user_id = ?", (user.id,))
    row = cursor.fetchone()
    conn.close()

    balance = row[0] if row else 0
    if balance <= 0:
        await update.message.reply_text("❌ You currently have 0 Stars in your balance to withdraw!")
        return

    try:
        admin_alert = (
            f"🚨 **NEW WITHDRAWAL REQUEST!** 🚨\n\n"
            f"👤 **User:** @{user.username or user.first_name} (`ID: {user.id}`)\n"
            f"💰 **Amount Requested:** `{balance} Stars`\n\n"
            f"Send them Telegram Star Gifts directly!"
        )
        await context.bot.send_message(chat_id=ADMIN_USER_ID, text=admin_alert, parse_mode="Markdown")
    except Exception as e:
        print(f"Error alerting admin: {e}")

    await update.message.reply_text(
        f"📥 **Withdrawal Request Sent!**\n\n"
        f"Amount: `{balance} Stars`\n"
        f"Our admin team was notified and will send your Telegram Gifts shortly!",
        parse_mode="Markdown"
    )

async def leaderboard_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect("betiball.db")
    cursor = conn.cursor()
    cursor.execute("SELECT username, star_balance FROM users ORDER BY star_balance DESC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()

    text = "🏆 **Star Balance Leaderboard** 🏆\n\n"
    for idx, (username, bal) in enumerate(rows, 1):
        text += f"`{idx}.` **{username}** — `{bal} Stars`\n"

    await update.message.reply_text(text, parse_mode="Markdown")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "⚽ View Matches":
        await matches_menu(update, context)
    elif text == "🏆 Leaderboard":
        await leaderboard_menu(update, context)
    elif text == "💰 My Balance":
        await balance_menu(update, context)
    elif text == "📤 Withdraw Stars":
        await withdraw_menu(update, context)
    elif text == "❓ How to Play":
        await start(update, context)

# --- BOT INITIALIZATION ---
if __name__ == "__main__":
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(auto_settle_and_payout_job, interval=600, first=10)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(verify_sub_callback, pattern="^check_sub$"))
    app.add_handler(CallbackQueryHandler(handle_prediction_button, pattern="^pred_"))
    app.add_handler(CallbackQueryHandler(handle_payment_button, pattern="^pay_"))
    
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    app.run_polling()
