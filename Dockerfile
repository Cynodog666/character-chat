FROM python:3.12-slim

WORKDIR /app

# 先装依赖，利用镜像层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 只拷代码，不拷小说和数据（见 .dockerignore）
COPY app ./app
COPY web ./web

ENV PORT=8000 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# 数据目录交给平台挂卷；没挂卷也不会崩，只是重启后角色卡片和记忆会重置
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
