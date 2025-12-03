#!/bin/bash

echo "=== MietAssistent Setup ==="

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker ist nicht installiert. Bitte installieren Sie Docker zuerst."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose ist nicht installiert. Bitte installieren Sie Docker Compose zuerst."
    exit 1
fi

echo "✅ Docker und Docker Compose gefunden"

# Create directories
mkdir -p data uploads/protocolls logs
chmod 755 data uploads uploads/protocolls logs

echo "✅ Verzeichnisse erstellt"

# Check port
if lsof -Pi :5000 -sTCP:LISTEN -t >/dev/null ; then
    echo "⚠️  Port 5000 ist bereits belegt. Bitte stellen Sie sicher, dass der Port frei ist."
    read -p "Möchten Sie trotzdem fortfahren? (j/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Jj]$ ]]; then
        exit 1
    fi
fi

# Start application
echo "🚀 Starte Anwendung..."
docker-compose up -d

echo "⏳ Warte auf Anwendungsstart..."
sleep 15

# Check if application is running
if curl -f http://localhost:5000/health >/dev/null 2>&1; then
    echo "✅ Anwendung läuft"
else
    echo "⚠️  Anwendung antwortet nicht direkt, fahre fort..."
fi

# Open browser
if command -v xdg-open &> /dev/null; then
    xdg-open "http://localhost:5000/setup"
elif command -v open &> /dev/null; then
    open "http://localhost:5000/setup"
else
    echo "📝 Öffnen Sie http://localhost:5000/setup in Ihrem Browser"
fi

echo "✅ Setup abgeschlossen!"
echo ""
echo "📋 Nächste Schritte:"
echo "1. Folgen Sie dem Setup-Assistenten im Browser"
echo "2. Legen Sie einen Admin-Benutzer an"
echo "3. Erstellen Sie Ihr erstes Gebäude"
echo "4. Fügen Sie Wohnungen/Einheiten hinzu"
echo "5. Das System richtet automatisch Standard-Zählertypen ein"