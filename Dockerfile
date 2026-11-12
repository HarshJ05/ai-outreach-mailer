FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# data/ and logs/ are mounted from the host so customer data and history stay outside the image
VOLUME ["/app/data", "/app/logs"]

ENTRYPOINT ["python", "-m", "src.main"]
CMD ["--help"]
