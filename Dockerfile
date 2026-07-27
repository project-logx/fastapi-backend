FROM python:3.12-slim


WORKDIR /app

RUN useradd --create-home --shell /bin/bash appuser

COPY backend/requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY backend/ .

RUN mkdir -p /data/attachments && chown -R appuser:appuser /app /data

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
