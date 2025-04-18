import os
import logging
from typing import Dict, Optional
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    CallbackContext,
    CallbackQueryHandler,
    filters
)
from datetime import datetime
import psycopg2
from urllib.parse import urlparse, parse_qs

# تكوين السجل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# تكوين قاعدة البيانات
def get_db_connection():
    return psycopg2.connect(os.getenv('DATABASE_URL'))

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS audio_files (
            id SERIAL PRIMARY KEY,
            youtube_url TEXT UNIQUE NOT NULL,
            telegram_file_id TEXT,
            telegram_file_url TEXT,
            file_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# وظائف مساعدة
def extract_video_id(url: str) -> Optional[str]:
    """استخراج معرف فيديو اليوتيوب من الرابط"""
    query = urlparse(url)
    if query.hostname == 'youtu.be':
        return query.path[1:]
    if query.hostname in ('www.youtube.com', 'youtube.com'):
        if query.path == '/watch':
            p = parse_qs(query.query)
            return p['v'][0]
        if query.path.startswith('/embed/'):
            return query.path.split('/')[2]
        if query.path.startswith('/v/'):
            return query.path.split('/')[2]
    return None

def is_youtube_url(url: str) -> bool:
    """التحقق مما إذا كان الرابط رابط يوتيوب صالحًا"""
    return extract_video_id(url) is not None

# وظائف قاعدة البيانات
def check_existing_audio(youtube_url: str) -> Optional[Dict]:
    """التحقق مما إذا كان الملف موجودًا بالفعل في قاعدة البيانات"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT telegram_file_id, telegram_file_url, file_name 
        FROM audio_files 
        WHERE youtube_url = %s
    ''', (youtube_url,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            'file_id': result[0],
            'file_url': result[1],
            'file_name': result[2]
        }
    return None

def save_audio_info(youtube_url: str, file_id: str, file_url: str, file_name: str):
    """حفظ معلومات الملف في قاعدة البيانات"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO audio_files (youtube_url, telegram_file_id, telegram_file_url, file_name)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (youtube_url) DO UPDATE SET
            telegram_file_id = EXCLUDED.telegram_file_id,
            telegram_file_url = EXCLUDED.telegram_file_url,
            file_name = EXCLUDED.file_name
    ''', (youtube_url, file_id, file_url, file_name))
    conn.commit()
    conn.close()

# وظائف البوت
def start(update: Update, context: CallbackContext) -> None:
    """إرسال رسالة الترحيب"""
    user = update.effective_user
    update.message.reply_text(
        f"مرحبًا {user.first_name}!\n\n"
        "أرسل لي رابط فيديو يوتيوب وسأحوله لك إلى ملف صوتي MP3."
    )

def handle_message(update: Update, context: CallbackContext) -> None:
    """معالجة الرسائل الواردة"""
    text = update.message.text
    
    if not is_youtube_url(text):
        update.message.reply_text("الرجاء إرسال رابط يوتيوب صالح.")
        return
    
    youtube_url = text
    video_id = extract_video_id(youtube_url)
    
    # التحقق مما إذا كان الملف موجودًا بالفعل
    existing_audio = check_existing_audio(youtube_url)
    if existing_audio:
        update.message.reply_text(
            f"تم العثور على الملف مسبقًا:\n\n"
            f"🎵 {existing_audio['file_name']}\n\n"
            f"يمكنك تحميله من هنا:\n"
            f"{existing_audio['file_url']}",
            disable_web_page_preview=True
        )
        return
    
    # إذا لم يكن الملف موجودًا، قم بتحميله
    update.message.reply_text("جاري تحميل الملف، الرجاء الانتظار...")
    
    try:
        # استخدام خدمة خارجية لتحميل MP3
        download_url = f"https://ytmp3api.xyz/api/audio/?url={youtube_url}"
        
        # الحصول على معلومات الفيديو
        info_url = f"https://ytmp3api.xyz/api/info/?url={youtube_url}"
        info_response = requests.get(info_url)
        info_data = info_response.json()
        
        if not info_data.get('success', False):
            raise Exception("فشل في الحصول على معلومات الفيديو")
        
        video_title = info_data['data']['title']
        safe_filename = "".join(c for c in video_title if c.isalnum() or c in " -_")[:50] + ".mp3"
        
        # تحميل الملف
        response = requests.get(download_url, stream=True)
        if response.status_code != 200:
            raise Exception("فشل في تحميل الملف من يوتيوب")
        
        # إرسال الملف إلى القناة
        channel_id = os.getenv('TELEGRAM_CHANNEL_ID')
        if not channel_id:
            raise Exception("لم يتم تعيين معرف القناة")
        
        # حفظ الملف مؤقتًا
        temp_file = f"temp_{video_id}.mp3"
        with open(temp_file, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
        
        # إرسال الملف إلى القناة
        with open(temp_file, 'rb') as audio_file:
            sent_message = context.bot.send_audio(
                chat_id=channel_id,
                audio=audio_file,
                title=video_title,
                performer="YouTube",
                filename=safe_filename
            )
        
        # الحصول على رابط الملف
        file_id = sent_message.audio.file_id
        file_url = f"https://t.me/{sent_message.chat.username}/{sent_message.message_id}"
        
        # حفظ المعلومات في قاعدة البيانات
        save_audio_info(
            youtube_url=youtube_url,
            file_id=file_id,
            file_url=file_url,
            file_name=video_title
        )
        
        # إرسال الرابط إلى المستخدم
        update.message.reply_text(
            f"تم تحميل الملف بنجاح:\n\n"
            f"🎵 {video_title}\n\n"
            f"يمكنك تحميله من هنا:\n"
            f"{file_url}",
            disable_web_page_preview=True
        )
        
        # حذف الملف المؤقت
        os.remove(temp_file)
        
    except Exception as e:
        logger.error(f"Error processing YouTube URL: {e}")
        update.message.reply_text("حدث خطأ أثناء معالجة طلبك. الرجاء المحاولة لاحقًا.")

def error_handler(update: Update, context: CallbackContext) -> None:
    """معالجة الأخطاء"""
    logger.error(msg="حدث خطأ في البوت:", exc_info=context.error)
    
    if update.effective_message:
        update.effective_message.reply_text(
            "عذرًا، حدث خطأ غير متوقع. الرجاء المحاولة مرة أخرى لاحقًا."
        )

def main() -> None:
    """تشغيل البوت"""
    # تهيئة قاعدة البيانات
    init_db()
    
    # إنشاء البوت
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        raise ValueError("لم يتم تعيين رمز البوت في متغيرات البيئة")
    
    updater = Updater(token)
    dispatcher = updater.dispatcher
    
    # تسجيل المعالجات
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    dispatcher.add_error_handler(error_handler)
    
    # بدء البوت
    port = int(os.environ.get('PORT', 5000))
    updater.start_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=token,
        webhook_url=f"https://{os.getenv('RAILWAY_PROJECT_NAME')}.up.railway.app/{token}"
    )
    updater.idle()

if __name__ == '__main__':
    main()
