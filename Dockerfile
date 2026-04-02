# ---------------------------------------------------------------------------
# Stage: runtime
# Base : python:3.11-slim (Debian-based, lightweight, has apt)
# ---------------------------------------------------------------------------
FROM python:3.11-slim

# ---------- system dependencies --------------------------------------------
# poppler-utils : required by pdf2image at runtime (pdftoppm / pdfinfo)
# gcc / libffi  : needed to compile certain Python C-extension wheels
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        poppler-utils \
        gcc \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# ---------- directory layout -----------------------------------------------
#   /app/
#   ├── src/          ← WORKDIR; mirrors your local `cd src/` step
#   ├── configs/      ← document schema configs
#   └── temp/         ← transient PDF→image scratch space
RUN mkdir -p /app/temp

# ---------- Python dependencies --------------------------------------------
# Copy requirements first to exploit Docker layer caching:
# deps are only re-installed when requirements.txt changes.
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---------- application files ----------------------------------------------
COPY src/     ./src/
COPY configs/ ./configs/

# ---------- runtime configuration -----------------------------------------
# WORKDIR mirrors your local workflow: cd src/ → uvicorn api:app
WORKDIR /app/src

EXPOSE 8000

ENV PYTHONUNBUFFERED=1

# Overrides the two-level-up _PROJECT_ROOT calculation in helper.py so that
# temp files are written to /app/temp instead of the filesystem root (/).
# Falls back to the original path calculation when unset (local dev).
ENV TEMP_DIR=/app/temp

# Identical to your local command: uvicorn api:app --host 0.0.0.0 --port 8000
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]