FROM python:3.12-slim

WORKDIR /app
ENV APP_ENV=production

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py Frontend.html ./
COPY img ./img
COPY database/schema.sql ./database/schema.sql

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
