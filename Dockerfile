FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# 安装本包，使容器内可用 ai-stock 命令(便于 cron 定时更新数据/扫描)
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

