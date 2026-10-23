FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir ".[ui]" \
    && useradd --create-home --uid 1000 app

USER app
EXPOSE 8000

# Settings come from DOC_ALTTEXT_* environment variables, e.g. DOC_ALTTEXT_BASE_URL and DOC_ALTTEXT_MODEL.
CMD ["doc-alttext", "serve", "--host", "0.0.0.0", "--port", "8000"]
