FROM python:3.10-slim

WORKDIR /app

# 日志实时输出；二维码与登录会话持久化到挂载的 data 目录
ENV PYTHONUNBUFFERED=1 \
    QRCODE_PATH=/app/data/qrcode.png \
    STORAGE_STATE_PATH=/app/data/storage_state.json

COPY requirements.txt .

# 安装 Python 依赖与 Playwright Chromium（--with-deps 会一并安装所需系统库，含 OpenCV 依赖）
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY app.py .
COPY src/ ./src/

EXPOSE 8000

CMD ["python", "app.py"]
