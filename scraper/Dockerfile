FROM python:3.11-slim

WORKDIR /scraper

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium
RUN playwright install-deps chromium

COPY . .

CMD ["tail", "-f", "/dev/null"]