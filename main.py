import os
import logging
import re
import uuid
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp
from googleapiclient.discovery import build
import psycopg2
from dotenv import load_dotenv

# تحميل المتغيرات البيئية
load_dotenv()

# التحقق من المتغيرات المطلوبة
required_env_vars = ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHANNEL_ID', 'DATABASE_URL', 'YOUTUBE_API_KEY']
missing_vars = [var for var in required_env_vars if not os.getenv(var)]
if missing_vars:
    raise ValueError(f"Missing environment variables: {', '.join(missing_vars)}")

# الإعدادات
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')
DATABASE_URL = os.getenv('DATABASE_URL')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
COOKIES_CONTENT = os.getenv('COOKIES_CONTENT', '')
DOWNLOADS_DIR = os.path.abspath('downloads')

# تسجيل الأخطاء
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# دوال التنظيف والتحويل
def sanitize_filename(filename):
    return re.sub(r'[\\/*?:"<>|]', "_", filename)

def extract_video_id(url):
    regex = r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|\S*?[?&]v=)|youtu\.be\/)([a-zA-Z0-9_-]{11})'
    match = re.search(regex, url)
    return match.group(1) if match else None

def download_youtube_audio(url):
    try:
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        cookies_file = None

        if COOKIES_CONTENT:
            cookies_file = os.path.join(DOWNLOADS_DIR, 'cookies.txt')
            with open(cookies_file, 'w') as f:
                f.write(COOKIES_CONTENT)

        # إعدادات yt-dlp مع تصحيح ffmpeg_location
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'ffmpeg_location': '/usr/bin/ffmpeg',  # ✅ في الإعدادات الرئيسية
            'outtmpl': os.path.join(DOWNLOADS_DIR, '%(title)s.%(ext)s'),
            'no-check-certificate': True,
            'force_generic_extractor': True,
            'cookiefile': cookies_file,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            },
            'verbose': True  # لعرض تفاصيل التحويل
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            original_filename = ydl.prepare_filename(info_dict)
            
            # معالجة اسم الملف
            safe_filename = sanitize_filename(original_filename)
            os.rename(original_filename, safe_filename)
            
            # تحويل الامتداد إلى MP3
            new_file = os.path.join(DOWNLOADS_DIR, f"{uuid.uuid4()}.mp3")
            os.rename(f"{os.path.splitext(safe_filename)[0]}.mp3", new_file)
            
            return new_file

    except Exception as e:
        logger.error(f"حدث خطأ: {str(e)}", exc_info=True)
        return None

    finally:
        # حذف الملفات المؤقتة
        if cookies_file and os.path.exists(cookies_file):
            os.remove(cookies_file)
        for fname in os.listdir(DOWNLOADS_DIR):
            if fname.endswith(('.part', '.ytdl', '.webm')):
                os.remove(os.path.join(DOWNLOADS_DIR, fname))

# وظائف قاعدة البيانات
def connect_to_db():
    try:
        return psycopg2.connect(DATABASE_URL, sslmode='require')
    except Exception as e:
        logger.error(f"Database error: {e}")
        raise

def create_table():
    try:
        conn = connect_to_db()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audio_files (
                id SERIAL PRIMARY KEY,
                youtube_url TEXT UNIQUE NOT NULL,
                file_id TEXT NOT NULL,
                file_name TEXT NOT NULL
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Error creating table: {e}")

def save_to_db(youtube_url, file_id, file_name):
    try:
        conn = connect_to_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO audio_files (youtube_url, file_id, file_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (youtube_url) DO NOTHING;
        """, (youtube_url, file_id, file_name))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Error saving to DB: {e}")

def check_db(youtube_url):
    try:
        conn = connect_to_db()
        cur = conn.cursor()
        cur.execute("SELECT file_id FROM audio_files WHERE youtube_url = %s;", (youtube_url,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"Error checking DB: {e}")
        return None

# معالجة الرسائل
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    youtube_url = update.message.text.strip()
    if not youtube_url:
        await update.message.reply_text("يرجى إرسال رابط يوتيوب صالح.")
        return

    video_id = extract_video_id(youtube_url)
    if not video_id:
        await update.message.reply_text("رابط اليوتيوب غير صالح.")
        return

    file_id = check_db(youtube_url)
    if file_id:
        await update.message.reply_text(f"الملف موجود بالفعل: https://t.me/{TELEGRAM_CHANNEL_ID}/{file_id}")
        return

    audio_file = download_youtube_audio(youtube_url)
    if not audio_file:
        await update.message.reply_text("فشل في تحميل الملف من اليوتيوب.")
        return

    try:
        file_id = await send_audio_to_channel(context, audio_file)
        save_to_db(youtube_url, file_id, os.path.basename(audio_file))
        await update.message.reply_text(f"تم تحميل الملف: https://t.me/{TELEGRAM_CHANNEL_ID}/{file_id}")
    except Exception as e:
        logger.error(f"Error sending to channel: {e}")
        await update.message.reply_text("حدث خطأ أثناء رفع الملف إلى القناة.")
    finally:
        if os.path.exists(audio_file):
            os.remove(audio_file)

async def send_audio_to_channel(context, audio_file):
    with open(audio_file, 'rb') as audio:
        message = await context.bot.send_audio(chat_id=TELEGRAM_CHANNEL_ID, audio=audio)
    return message.audio.file_id

# وظائف البوت
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('مرحبًا! أرسل رابط يوتيوب لتحميل الملف الصوتي.')

async def error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")

# الوظيفة الرئيسية
def main():
    create_table()

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error)

    application.run_polling()

if __name__ == '__main__':
    main()
