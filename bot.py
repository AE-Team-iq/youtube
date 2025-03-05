import os
import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from pytube import YouTube
import requests
import psycopg2

# إعدادات قاعدة البيانات
DATABASE_URL = os.environ['DATABASE_URL']

# إعدادات البوت
TELEGRAM_BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
TELEGRAM_CHANNEL_ID = os.environ['TELEGRAM_CHANNEL_ID']

# إعدادات اليوتيوب
YOUTUBE_API_KEY = os.environ['YOUTUBE_API_KEY']

# إعدادات السيرفر
SERVER_URL = os.environ['SERVER_URL']

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
def send_audio_to_channel(context, audio_file):
    with open(audio_file, 'rb') as audio:
        message = context.bot.send_audio(chat_id=TELEGRAM_CHANNEL_ID, audio=audio)
    return message.audio.file_id

# وظيفة لحفظ المعلومات في قاعدة البيانات
def save_to_db(youtube_url, file_id, file_name):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("INSERT INTO audio_files (youtube_url, file_id, file_name) VALUES (%s, %s, %s)", (youtube_url, file_id, file_name))
    conn.commit()
    cur.close()
    conn.close()

# وظيفة للتحقق من وجود الملف في قاعدة البيانات
def check_db(youtube_url):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT file_id FROM audio_files WHERE youtube_url = %s", (youtube_url,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result[0] if result else None

# وظيفة لمعالجة الرسائل
def handle_message(update: Update, context: CallbackContext):
    youtube_url = update.message.text
    file_id = check_db(youtube_url)

    if file_id:
        context.bot.send_message(chat_id=update.message.chat_id, text=f"الملف موجود بالفعل: {SERVER_URL}/file/{file_id}")
    else:
        try:
            audio_file = download_youtube_audio(youtube_url)
            file_id = send_audio_to_channel(context, audio_file)
            save_to_db(youtube_url, file_id, os.path.basename(audio_file))
            context.bot.send_message(chat_id=update.message.chat_id, text=f"تم تحميل الملف: {SERVER_URL}/file/{file_id}")
        except Exception as e:
            logger.error(f"Error: {e}")
            context.bot.send_message(chat_id=update.message.chat_id, text="حدث خطأ أثناء تحميل الملف.")

# وظيفة لبدء البوت
def start(update: Update, context: CallbackContext):
    update.message.reply_text('مرحبًا! أرسل رابط يوتيوب لتحميل الملف الصوتي.')

# وظيفة لمعالجة الأخطاء
def error(update: Update, context: CallbackContext):
    logger.warning(f'Update {update} caused error {context.error}')

# وظيفة رئيسية لتشغيل البوت
def main():
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dp.add_error_handler(error)

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
