FROM python:3.13-slim

WORKDIR /app

# WeasyPrint needs: pango, cairo, gdk-pixbuf, fontconfig, fonts
RUN apt-get update && apt-get install -y \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-xlib-2.0-0 \
    libffi-dev \
    libharfbuzz0b \
    shared-mime-info \
    fonts-liberation \
    fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application
COPY . .

# Create necessary directories
RUN mkdir -p uploads/documents uploads/students

# Render.com sets PORT env var; fallback to 5000 for local/Docker
EXPOSE 10000

# Run application - bind to $PORT (Render) or 5000 (local)
CMD gunicorn --bind "0.0.0.0:${PORT:-5000}" --workers 2 --timeout 120 --access-logfile - --error-logfile - wsgi:app
