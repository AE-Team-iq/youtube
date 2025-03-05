FROM python:3.9-slim

# تثبيت ffmpeg
RUN apt-get update && apt-get install -y ffmpeg

# نسخ الكود إلى الحاوية
COPY . /app
WORKDIR /app

# تثبيت المتطلبات
RUN pip install --no-cache-dir -r requirements.txt

# تشغيل البوت
CMD ["python", "bot.py"]
