# استخدام صورة أساسية تحتوي على Python
FROM python:3.9-slim

# تثبيت ffmpeg
RUN apt-get update && apt-get install -y ffmpeg

# تعيين مجلد العمل
WORKDIR /app

# نسخ ملفات المشروع إلى الحاوية
COPY . .

# تثبيت المتطلبات
RUN pip install --no-cache-dir -r requirements.txt

# تشغيل البوت
CMD ["python", "bot.py"]
