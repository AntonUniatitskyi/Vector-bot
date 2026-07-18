FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data && \
    useradd --create-home --shell /bin/bash botuser && \
    chown -R botuser:botuser /app

USER botuser

CMD ["python", "vector_bot.py"]

