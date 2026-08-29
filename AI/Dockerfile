FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libv4l-0 \
    ffmpeg \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . /app
RUN mkdir -p /app/models

EXPOSE 8000

# 환경변수(필요 시 docker run -e로 오버라이드)
# ENV MODEL_PATH="./models/bestM.pt" DEVICE_INDEX=0 FRAME_W=640 FRAME_H=640 CONF_THRES=0.30 IMGSZ=640 EAR_THRESH=0.21 SMOOTH_N=5

# 서버 실행
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
