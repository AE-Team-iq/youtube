from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import yt_dlp
import os

TOKEN = "1857327834:AAGruFRs4w3GJ0hG481G7ixHEQm_oYewV7E"

async def start(update: Update, context):
    await update.message.reply_text("Send me a YouTube link to convert to MP3!")

async def download_mp3(update: Update, context):
    url = update.message.text
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        file_name = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')
    
    await update.message.reply_audio(audio=open(file_name, 'rb'))
    os.remove(file_name)

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download_mp3))

app.run_polling()
