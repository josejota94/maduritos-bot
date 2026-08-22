// Conecta WhatsApp por código QR (Baileys) con tu servidor Python.
// Correr con: node whatsapp_qr.js
// Necesita que tu servidor Python (main.py) ya esté corriendo.
//
// Envía las preguntas de cantidad/tamaño/relleno como BOTONES o LISTAS reales
// de WhatsApp (igual que se ven en el /simulador), no como texto numerado.
// Si el teléfono del cliente no logra mostrarlos como botones (pasa en
// algunos WhatsApp viejos), se manda un texto de respaldo numerado, y este
// mismo archivo se encarga de traducir una respuesta como "2" al id real
// (ej. "tam_grande") antes de pasarla a Python — así nunca llega un número
// suelto ambiguo al motor de conversación.

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

// Por teléfono, guarda los ids de las opciones mostradas la ÚLTIMA VEZ que
// tuvimos que recurrir al texto de respaldo numerado (no cuando los botones
// reales funcionan, porque ahí la respuesta del cliente ya trae el id real).
const _ultimasOpcionesRespaldo = {};

async function enviarRespuesta(sock, jid, respuesta) {
    const tipo = respuesta.tipo || 'texto';

    if (tipo === 'texto' || !respuesta.opciones || respuesta.opciones.length === 0) {
        await sock.sendMessage(jid, { text: respuesta.texto || '' });
        return;
    }

    try {
        if (tipo === 'botones') {
            await sock.sendMessage(jid, {
                text: respuesta.texto,
                footer: 'Maduritos Asados 🍌',
                buttons: respuesta.opciones.slice(0, 3).map((o) => ({
                    buttonId: o.id,
                    buttonText: { displayText: o.titulo },
                    type: 1,
                })),
                headerType: 1,
            });
        } else if (tipo === 'lista') {
            await sock.sendMessage(jid, {
                text: respuesta.texto,
                footer: 'Maduritos Asados 🍌',
                title: 'Maduritos Asados',
                buttonText: respuesta.boton_texto || 'Elegir',
                sections: [
                    {
                        title: 'Opciones',
                        rows: respuesta.opciones.slice(0, 10).map((o) => ({
                            title: o.titulo,
                            rowId: o.id,
                        })),
                    },
                ],
            });
        }
        // Si el envío con botones/lista funcionó, este teléfono ya no necesita
        // el respaldo numerado — limpiamos cualquier rastro anterior.
        delete _ultimasOpcionesRespaldo[jid];
    } catch (err) {
        console.error('⚠️  No se pudieron enviar botones/lista reales, uso texto de respaldo:', err.message);
        const lineas = [respuesta.texto, ''];
        respuesta.opciones.forEach((o, i) => lineas.push(`${i + 1}. ${o.titulo}`));
        lineas.push('', 'Responde con el número de la opción.');
        await sock.sendMessage(jid, { text: lineas.join('\n') });
        _ultimasOpcionesRespaldo[jid] = respuesta.opciones.map((o) => o.id);
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
        } else if (msg.message.buttonsResponseMessage) {
            texto = msg.message.buttonsResponseMessage.selectedButtonId || '';
        } else if (msg.message.listResponseMessage) {
            texto = msg.message.listResponseMessage.singleSelectReply?.selectedRowId || '';
        } else {
            texto = msg.message.conversation || msg.message.extendedTextMessage?.text || '';

            const crudo = texto.trim();
            if (/^\d+$/.test(crudo) && _ultimasOpcionesRespaldo[jid]) {
                const indice = parseInt(crudo, 10) - 1;
                const opcionesPrevias = _ultimasOpcionesRespaldo[jid];
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
