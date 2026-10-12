FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home app && chown -R app:app /app
USER app

EXPOSE 11001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "11001"]

