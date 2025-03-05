import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from pytube import YouTube
import psycopg2
from dotenv import load_dotenv

# تحميل المتغيرات البيئية من ملف .env
load_dotenv()

# إعدادات البوت
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')

# إعدادات قاعدة البيانات
DATABASE_URL = os.getenv('DATABASE_URL')

# إعدادات التسجيل
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# وظيفة لتحميل الملف من اليوتيوب
def download_youtube_audio(url):
    yt = YouTube(url)
    audio = yt.streams.filter(only_audio=True).first()
    output_file = audio.download(output_path="downloads")
    base, ext = os.path.splitext(output_file)
    new_file = base + '.mp3'
    os.rename(output_file, new_file)
    return new_file

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
    await update.message.reply_text('يا هلا بابن عمي الذهب دزلي الرابط يا ذخب خل انزلك الفيديو صوت وتدلل ضلعي .')

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
