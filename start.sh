#!/bin/bash
# Arranca el bot de WhatsApp (Baileys, Node.js) en segundo plano,
# y el servidor principal (FastAPI) en primer plano.
set -e

export PATH="$(pwd)/node20/bin:$PATH"

echo "🍌 Iniciando Maduritos Asados..."
echo "Versión de Node: $(node --version)"

node whatsapp_qr.js &

exec uvicorn main:app --host 0.0.0.0 --port "$PORT"
