FROM python:3.11-slim

WORKDIR /code

COPY app/requirements.txt ./app/requirements.txt
RUN pip install --no-cache-dir -r app/requirements.txt

# app/main.py imports sibling top-level packages directly (storage, tracker,
# resume, scraper, geocoding, orchestrator, matching, stats, qualifications,
# rag) -- it's the API integration point, not a self-contained module. So the
# build context is the repo root (see docker-compose.yml), same reasoning as
# orchestrator/Dockerfile for the scheduler service.
COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5000", "--reload"]
