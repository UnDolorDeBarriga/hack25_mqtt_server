FROM python:3.11-slim

WORKDIR /app
COPY fetch_flights.py .
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "fetch_flights.py"]

