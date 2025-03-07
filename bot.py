import os
import logging
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp
from googleapiclient.discovery import build
import psycopg2
from dotenv import load_dotenv

# تحميل المتغيرات البيئية من ملف .env
load_dotenv()

# إعدادات البوت
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')

# إعدادات قاعدة البيانات
DATABASE_URL = os.getenv('DATABASE_URL')

# إعدادات YouTube Data API
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
if not YOUTUBE_API_KEY:
    raise ValueError("YouTube API key is missing. Please set YOUTUBE_API_KEY in .env file.")

# إعدادات التسجيل
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# وظيفة لاستخراج معرف الفيديو من رابط اليوتيوب
def extract_video_id(youtube_url):
    regex = r'(?:v=|\/)([0-9A-Za-z_-]{11}).*'
    match = re.search(regex, youtube_url)
    if match:
        return match.group(1)
    return None

# وظيفة للحصول على معلومات الفيديو باستخدام YouTube Data API
def get_video_info(video_id):
    youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
    request = youtube.videos().list(
        part="snippet,contentDetails",
        id=video_id
    )
    response = request.execute()
    if 'items' in response and response['items']:
        return response['items'][0]
    return None

# وظيفة لتحميل الملف من اليوتيوب باستخدام yt-dlp
def download_youtube_audio(url):
     ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'ffmpeg_location': '/usr/bin/ffmpeg',
        'cookiefile': 'cookies.txt',  # أضف هذا السطر
    }
     with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(url, download=True)
        file_path = ydl.prepare_filename(info_dict)
        return file_path

# وظيفة لإرسال الملف إلى القناة
async def send_audio_to_channel(context, audio_file):
    with open(audio_file, 'rb') as audio:
        message = await context.bot.send_audio(chat_id=TELEGRAM_CHANNEL_ID, audio=audio)
    return message.audio.file_id

# وظيفة للاتصال بقاعدة البيانات
def connect_to_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    return conn

# وظيفة لإنشاء الجدول إذا لم يكن موجودًا
def create_table():
    conn = connect_to_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audio_files (
            id SERIAL PRIMARY KEY,
            youtube_url TEXT NOT NULL,
            file_id TEXT NOT NULL,
            file_name TEXT NOT NULL
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

# وظيفة لحفظ المعلومات في قاعدة البيانات
def save_to_db(youtube_url, file_id, file_name):
    conn = connect_to_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO audio_files (youtube_url, file_id, file_name)
        VALUES (%s, %s, %s);
    """, (youtube_url, file_id, file_name))
    conn.commit()
    cur.close()
    conn.close()

# وظيفة للتحقق من وجود الملف في قاعدة البيانات
def check_db(youtube_url):
    conn = connect_to_db()
    cur = conn.cursor()
    cur.execute("SELECT file_id FROM audio_files WHERE youtube_url = %s;", (youtube_url,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result[0] if result else None

# وظيفة لمعالجة الرسائل
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    youtube_url = update.message.text

    # استخراج معرف الفيديو من الرابط
    video_id = extract_video_id(youtube_url)
    if not video_id:
        await update.message.reply_text("رابط اليوتيوب غير صالح.")
        return

    # الحصول على معلومات الفيديو باستخدام YouTube Data API
    video_info = get_video_info(video_id)
    if not video_info:
        await update.message.reply_text("تعذر الحصول على معلومات الفيديو.")
        return

    file_id = check_db(youtube_url)

    if file_id:
        await update.message.reply_text(f"الملف موجود بالفعل: https://t.me/{TELEGRAM_CHANNEL_ID}/{file_id}")
    else:
        try:
            audio_file = download_youtube_audio(youtube_url)
            file_id = await send_audio_to_channel(context, audio_file)
            save_to_db(youtube_url, file_id, os.path.basename(audio_file))
            await update.message.reply_text(f"تم تحميل الملف: https://t.me/{TELEGRAM_CHANNEL_ID}/{file_id}")
        except Exception as e:
            logger.error(f"Error: {e}")
            await update.message.reply_text("حدث خطأ أثناء تحميل الملف.")

# وظيفة لبدء البوت
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('مرحبًا! أرسل رابط يوتيوب لتحميل الملف الصوتي.')

# وظيفة لمعالجة الأخطاء
async def error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.warning(f'Update {update} caused error {context.error}')

# وظيفة رئيسية لتشغيل البوت
def main():
    # إنشاء الجدول إذا لم يكن موجودًا
    create_table()

    # بدء تشغيل البوت
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # إضافة handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # تشغيل البوت
    application.run_polling()

if __name__ == '__main__':
    main()
