# Image for the API (FastAPI + the agent).
# Build and run it through docker compose; see README.md.

FROM python:3.12-slim

# Don't write .pyc files, and print logs straight away instead of buffering them.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

# Install the Python packages first. Docker reuses this step from its cache
# until requirements.txt changes, so code edits rebuild in seconds.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only what the API needs at runtime. Tests, scripts and the website stay out,
# and .dockerignore keeps .env (your secrets) out of the image altogether.
COPY app/ ./app/
COPY metadata/ ./metadata/

# Run as an ordinary user, not root, so a break-in has less to work with.
# The files stay owned by root and are made read-only for that user: the app
# can read its own code but cannot change it.
RUN useradd --system --uid 10001 --no-create-home appuser \
    && chmod -R a=rX /srv/app /srv/metadata
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
