#!/bin/bash
# Arranca el bot de WhatsApp (Baileys, Node.js) en segundo plano,
# y el servidor principal (FastAPI) en primer plano.
set -e

echo "🍌 Iniciando Maduritos Asados..."

node whatsapp_qr.js &

exec uvicorn main:app --host 0.0.0.0 --port "$PORT"
