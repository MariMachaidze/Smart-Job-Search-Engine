FROM python:3.11-slim

WORKDIR /code

COPY orchestrator/requirements.txt ./orchestrator/requirements.txt
RUN pip install --no-cache-dir -r orchestrator/requirements.txt

# Unlike scraper/ and app/, this service's scheduled_jobs.py imports sibling
# top-level packages directly (storage, qualifications, notifications, and
# transitively rag/stats/tracker/app.llm) -- it IS the integration point for
# the daily batch jobs, not a self-contained module. So the build context is
# the repo root (see docker-compose.yml), and the whole tree is copied in,
# rather than just this directory.
COPY . .

CMD ["python", "-m", "orchestrator.scheduler_service"]
