// Conecta WhatsApp por código QR (Baileys) con tu servidor Python.
// Correr con: node whatsapp_qr.js
// Necesita que tu servidor Python (main.py) ya esté corriendo.
//
// IMPORTANTE: se probó enviar botones/listas "reales" de WhatsApp por este
// canal (Baileys, no oficial) y en la práctica WhatsApp los descarta en
// silencio para muchas cuentas — el cliente no ve ninguna opción. Por eso
// aquí SIEMPRE se muestran las opciones como texto numerado, bien claro,
// dentro del mismo mensaje. El cliente puede responder con el número o
// escribiendo la opción con sus propias palabras (ambas funcionan).

if (typeof global.crypto === 'undefined') {
    global.crypto = require('crypto').webcrypto;
}

const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion } = require('@whiskeysockets/baileys');
const qrcodeTerminal = require('qrcode-terminal');
const qrcodeImagen = require('qrcode');
const axios = require('axios');
const path = require('path');
const fs = require('fs');

const PUERTO_PYTHON = process.env.PORT || 8000;
const URL_PYTHON = `http://localhost:${PUERTO_PYTHON}/api/baileys-webhook`;
const CARPETA_STATIC = path.join(__dirname, 'static');
const RUTA_QR = path.join(CARPETA_STATIC, 'qr_actual.png');

if (!fs.existsSync(CARPETA_STATIC)) fs.mkdirSync(CARPETA_STATIC, { recursive: true });

// Por teléfono, guarda los ids de las opciones que se mostraron la última
// vez, para poder traducir una respuesta numérica ("2") al id real que
// espera bot_logic (ej. "tam_grande") antes de reenviarla a Python.
const _ultimasOpciones = {};

function construirTexto(respuesta) {
    const opciones = respuesta.opciones || [];
    if (opciones.length === 0) {
        return respuesta.texto || '';
    }
    const lineas = [respuesta.texto, ''];
    opciones.forEach((o, i) => lineas.push(`*${i + 1}.* ${o.titulo}`));
    lineas.push(
        '',
        `👉 *Responde solo con el número* de tu opción (ejemplo: escribe *${1}* para elegir la primera).`
    );
    return lineas.join('\n');
}

async function enviarRespuesta(sock, jid, respuesta) {
    await sock.sendMessage(jid, { text: construirTexto(respuesta) });
    if (respuesta.opciones && respuesta.opciones.length > 0) {
        _ultimasOpciones[jid] = respuesta.opciones.map((o) => o.id);
    } else {
        delete _ultimasOpciones[jid];
    }
}

async function iniciarBot() {
    const { state, saveCreds } = await useMultiFileAuthState('sesion_whatsapp');
    const { version } = await fetchLatestBaileysVersion();
    console.log('Usando versión de WhatsApp Web:', version.join('.'));

    const sock = makeWASocket({
        auth: state,
        version,
        printQRInTerminal: false,
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
        if (msg.key.remoteJid?.endsWith('@g.us')) return;

        const jid = msg.key.remoteJid;
        const telefono = jid.replace('@s.whatsapp.net', '');
        const nombre = msg.pushName || 'Cliente';

        let lat = null, lon = null;
        let texto = '';

        if (msg.message.locationMessage) {
            lat = msg.message.locationMessage.degreesLatitude;
            lon = msg.message.locationMessage.degreesLongitude;
        } else {
            texto = msg.message.conversation || msg.message.extendedTextMessage?.text || '';

            const crudo = texto.trim();
            if (/^\d+$/.test(crudo) && _ultimasOpciones[jid]) {
                const indice = parseInt(crudo, 10) - 1;
                const opcionesPrevias = _ultimasOpciones[jid];
                if (indice >= 0 && indice < opcionesPrevias.length) {
                    texto = opcionesPrevias[indice];
                }
            }
        }

        try {
            const res = await axios.post(URL_PYTHON, {
                telefono, nombre, texto, lat, lon,
                tipo: lat !== null ? 'ubicacion' : 'texto',
            });

            if (res.data) {
                await enviarRespuesta(sock, jid, res.data);
            }
        } catch (err) {
            console.error('⚠️  Error al conectar con Python (¿está corriendo main.py?):', err.message);
        }
    });
}

iniciarBot();
