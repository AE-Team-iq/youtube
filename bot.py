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
    raise ValueError(f"Missing env vars: {', '.join(missing_vars)}")

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

        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
                'ffmpeg_location': '/usr/bin/ffmpeg',
                'options': ['-loglevel', 'verbose']  # إضافة تفاصيل التحويل
            }],
            'outtmpl': os.path.join(DOWNLOADS_DIR, '%(title)s.%(ext)s'),
            'no-check-certificate': True,
            'force_generic_extractor': True,
            'cookiefile': cookies_file,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            original_filename = ydl.prepare_filename(info_dict)
            
            # معالجة اسم الملف
            safe_filename = sanitize_filename(original_filename)
            os.rename(original_filename, safe_filename)
            
            # التحويل إلى MP3
            new_file = os.path.join(DOWNLOADS_DIR, f"{uuid.uuid4()}.mp3")
            os.rename(f"{os.path.splitext(safe_filename)[0]}.mp3", new_file)
            
            return new_file

    except Exception as e:
        logger.error(f"حدث خطأ: {str(e)}", exc_info=True)
        return None

    finally:
        if cookies_file and os.path.exists(cookies_file):
            os.remove(cookies_file)
        for fname in os.listdir(DOWNLOADS_DIR):
            if fname.endswith('.part') or fname.endswith('.ytdl'):
                os.remove(os.path.join(DOWNLOADS_DIR, fname))

# بقية الدوال (الاتصال بقاعدة البيانات، إرسال الملف، إلخ) كما هي...
