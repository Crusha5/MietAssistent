FROM python:3.9-slim

WORKDIR /app

# Systemabhängigkeiten installieren
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    libcairo2 \
    libpangocairo-1.0-0 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz0b \
    libgobject-2.0-0 \
    libglib2.0-0 \
    libgirepository-1.0-1 \
    gobject-introspection \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    libxml2 \
    libxslt1-dev \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Python Abhängigkeiten kopieren und installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ZUERST Verzeichnisse erstellen
RUN mkdir -p data uploads app/routes app/templates

# Applikation kopieren - EXPLIZIT alle Verzeichnisse
COPY app/ ./app/
COPY run.py .
COPY requirements.txt .

# Berechtigungen setzen
RUN chmod -R 755 data uploads

# Prüfen ob Contract-Dateien vorhanden sind
RUN echo "=== Checking for contract files ===" && \
    find /app -name "*.py" | grep -E "(contract|protocol)" | head -10 && \
    echo "=== Template directories ===" && \
    find /app -type d -name "contracts" && \
    echo "=== All route files ===" && \
    ls -la /app/app/routes/

# Nicht als root User laufen
RUN useradd -m -u 1000 rentaluser && chown -R rentaluser:rentaluser /app
USER rentaluser

EXPOSE 5000

CMD ["python", "run.py"]