// Conecta WhatsApp por código QR (Baileys, no oficial) con tu servidor Python.
// Correr con: node whatsapp_qr.js
// Necesita que tu servidor Python (main.py) ya esté corriendo en el puerto 8000.

// Algunas versiones de Node no exponen "crypto" como objeto global (Baileys lo
// necesita sí o sí). Este parche lo soluciona sin importar la versión de Node.
if (typeof global.crypto === 'undefined') {
    global.crypto = require('crypto').webcrypto;
}

const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion } = require('@whiskeysockets/baileys');
const qrcodeTerminal = require('qrcode-terminal');
const qrcodeImagen = require('qrcode');
const axios = require('axios');
const path = require('path');
const fs = require('fs');

const URL_PYTHON = 'http://localhost:8000/api/baileys-webhook';
const CARPETA_STATIC = path.join(__dirname, 'static');
const RUTA_QR = path.join(CARPETA_STATIC, 'qr_actual.png');

if (!fs.existsSync(CARPETA_STATIC)) fs.mkdirSync(CARPETA_STATIC, { recursive: true });

async function iniciarBot() {
    const { state, saveCreds } = await useMultiFileAuthState('sesion_whatsapp');
    const { version } = await fetchLatestBaileysVersion();
    console.log('Usando versión de WhatsApp Web:', version.join('.'));

    const sock = makeWASocket({
        auth: state,
        version,
        printQRInTerminal: false, // usamos qrcode-terminal manualmente para verlo más grande
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            console.log('\n📱 Escanea este código QR con tu WhatsApp (Dispositivos vinculados):\n');
            qrcodeTerminal.generate(qr, { small: true });
            qrcodeImagen.toFile(RUTA_QR, qr, { width: 400 }, (err) => {
                if (err) console.error('No se pudo guardar la imagen del QR:', err.message);
                else console.log('🖼️  QR también disponible como imagen en /qr');
            });
        }

        if (connection === 'close') {
            const codigo = lastDisconnect?.error?.output?.statusCode;
            const debeReconectar = codigo !== DisconnectReason.loggedOut;
            console.log('❌ Conexión cerrada.', debeReconectar ? 'Reintentando en 5s...' : 'Sesión cerrada (borra la carpeta sesion_whatsapp y vuelve a escanear el QR).');
            if (debeReconectar) setTimeout(iniciarBot, 5000);
        } else if (connection === 'open') {
            console.log('✅ ¡WhatsApp conectado exitosamente por QR!');
            if (fs.existsSync(RUTA_QR)) fs.unlinkSync(RUTA_QR);
        }
    });

    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        if (type !== 'notify') return;
        const msg = messages[0];
        if (!msg.message || msg.key.fromMe) return;
        if (msg.key.remoteJid?.endsWith('@g.us')) return; // ignora mensajes de grupos

        const telefono = msg.key.remoteJid.replace('@s.whatsapp.net', '');
        const nombre = msg.pushName || 'Cliente';
        const texto = msg.message.conversation || msg.message.extendedTextMessage?.text || '';

        let lat = null, lon = null;
        if (msg.message.locationMessage) {
            lat = msg.message.locationMessage.degreesLatitude;
            lon = msg.message.locationMessage.degreesLongitude;
        }

        try {
            const res = await axios.post(URL_PYTHON, {
                telefono, nombre, texto, lat, lon,
                tipo: lat !== null ? 'ubicacion' : 'texto',
            });

            if (res.data && res.data.texto) {
                await sock.sendMessage(msg.key.remoteJid, { text: res.data.texto });
            }
        } catch (err) {
            console.error('⚠️  Error al conectar con Python (¿está corriendo main.py en el puerto 8000?):', err.message);
        }
    });
}

iniciarBot();
