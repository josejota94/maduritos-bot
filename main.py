import os
from typing import Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import bot_logic as bl

load_dotenv()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "TOKEN_SECRETO_WEBHOOK")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")

app = FastAPI(title="Maduritos Asados - Bot de Pedidos")
_static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(_static_dir, exist_ok=True)  # evita que el servidor no arranque si faltó subir esta carpeta
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


# ---------------------------------------------------------------------------
# Canal alterno: Baileys (WhatsApp por código QR, no oficial). Útil para
# probar HOY con clientes reales mientras arreglas el registro en Meta.
#
# A diferencia de antes, aquí YA NO se arma ningún texto numerado ("1. ...",
# "2. ...") en Python. Este endpoint solo procesa el mensaje y devuelve la
# respuesta tal cual la arma bot_logic (tipo: texto/botones/lista + opciones)
# — es el lado de Node (whatsapp_qr.js) el que intenta mostrarlas como
# botones/lista REALES de WhatsApp (como en el simulador), y solo si eso
# falla arma un texto de respaldo, traduciendo la respuesta numérica él mismo
# antes de volver a llamar aquí. Así este archivo no necesita adivinar nada.
# ---------------------------------------------------------------------------
class BaileysMensaje(BaseModel):
    telefono: str
    nombre: str = ""
    tipo: str = "texto"
    texto: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None


@app.post("/api/baileys-webhook")
def baileys_webhook(msg: BaileysMensaje):
    respuesta = bl.procesar_mensaje(
        msg.telefono, msg.nombre, msg.tipo, texto=(msg.texto or "").strip(), lat=msg.lat, lon=msg.lon
    )
    return JSONResponse(respuesta)


# ---------------------------------------------------------------------------
# PWA: manifest, ícono y service worker (para "Agregar a pantalla de inicio"
# y para que las notificaciones push funcionen aunque el navegador esté cerrado)
# ---------------------------------------------------------------------------
@app.get("/manifest.json")
def manifest():
    return JSONResponse({
        "name": "Maduritos Asados - Repartidor",
        "short_name": "Maduritos",
        "start_url": "/repartidor",
        "display": "standalone",
        "background_color": "#f0f2f5",
        "theme_color": "#00A884",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    })


@app.get("/sw.js")
def service_worker():
    js = """
self.addEventListener('push', function (event) {
    let datos = {};
    try { datos = event.data.json(); } catch (e) { datos = {titulo: 'Maduritos Asados', cuerpo: event.data ? event.data.text() : ''}; }
    const titulo = datos.titulo || 'Maduritos Asados';
    const opciones = {
        body: datos.cuerpo || '',
        icon: '/static/icon-192.png',
        badge: '/static/icon-192.png',
        data: { url: datos.url || '/repartidor' },
        vibrate: [200, 100, 200],
    };
    event.waitUntil(self.registration.showNotification(titulo, opciones));
});

self.addEventListener('notificationclick', function (event) {
    event.notification.close();
    const url = (event.notification.data && event.notification.data.url) || '/repartidor';
    event.waitUntil(clients.openWindow(url));
});
"""
    return Response(content=js, media_type="application/javascript")


class SuscripcionPush(BaseModel):
    endpoint: str
    keys: dict


@app.get("/api/push/vapid-public-key")
def vapid_public_key():
    return {"publicKey": VAPID_PUBLIC_KEY}


@app.post("/api/push/subscribe")
def push_subscribe(sub: SuscripcionPush):
    bl.guardar_suscripcion_push(sub.endpoint, sub.keys.get("p256dh", ""), sub.keys.get("auth", ""))
    return {"status": "ok"}


@app.post("/api/push/unsubscribe")
def push_unsubscribe(sub: SuscripcionPush):
    bl.eliminar_suscripcion_push(sub.endpoint)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Envío de mensajes a WhatsApp (texto plano, botones o listas interactivas)
# ---------------------------------------------------------------------------
def enviar_mensaje_whatsapp(telefono, respuesta: dict):
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print(f"[AVISO] WhatsApp no configurado. Se habría enviado a {telefono}:\n{respuesta}\n")
        return

    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}

    tipo = respuesta.get("tipo", "texto")
    if tipo == "botones":
        payload = {
            "messaging_product": "whatsapp",
            "to": telefono,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": respuesta["texto"]},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": o["id"], "title": o["titulo"][:20]}}
                        for o in respuesta["opciones"][:3]
                    ]
                },
            },
        }
    elif tipo == "lista":
        payload = {
            "messaging_product": "whatsapp",
            "to": telefono,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": respuesta["texto"]},
                "action": {
                    "button": respuesta.get("boton_texto", "Elegir")[:20],
                    "sections": [
                        {
                            "title": "Opciones",
                            "rows": [
                                {"id": o["id"], "title": o["titulo"][:24]} for o in respuesta["opciones"][:10]
                            ],
                        }
                    ],
                },
            },
        }
    else:
        payload = {
            "messaging_product": "whatsapp",
            "to": telefono,
            "type": "text",
            "text": {"body": respuesta["texto"]},
        }

    try:
        requests.post(url, json=payload, headers=headers, timeout=10)
    except Exception as e:
        print("Error enviando mensaje a WhatsApp:", e)


# ---------------------------------------------------------------------------
# 1. Verificación del Webhook de WhatsApp (Meta la llama al configurar)
# ---------------------------------------------------------------------------
@app.get("/webhook")
def verificar_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(content="Error de verificación", status_code=403)


# ---------------------------------------------------------------------------
# 2. Recepción de mensajes reales de WhatsApp (texto, ubicación, botón, lista)
# ---------------------------------------------------------------------------
@app.post("/webhook")
async def recibir_mensaje(request: Request):
    data = await request.json()
    try:
        entry = data["entry"][0]["changes"][0]["value"]
        if "messages" not in entry:
            return {"status": "ok"}

        mensaje = entry["messages"][0]
        telefono = mensaje["from"]
        nombre = entry.get("contacts", [{}])[0].get("profile", {}).get("name", "")

        if mensaje["type"] == "location":
            lat = mensaje["location"]["latitude"]
            lon = mensaje["location"]["longitude"]
            respuesta = bl.procesar_mensaje(telefono, nombre, "ubicacion", lat=lat, lon=lon)
        elif mensaje["type"] == "text":
            texto = mensaje["text"]["body"]
            respuesta = bl.procesar_mensaje(telefono, nombre, "texto", texto=texto)
        elif mensaje["type"] == "interactive":
            interactive = mensaje["interactive"]
            if interactive.get("type") == "button_reply":
                valor = interactive["button_reply"]["id"]
            elif interactive.get("type") == "list_reply":
                valor = interactive["list_reply"]["id"]
            else:
                valor = ""
            respuesta = bl.procesar_mensaje(telefono, nombre, "texto", texto=valor)
        else:
            respuesta = {"tipo": "texto", "texto": "Por ahora solo entiendo texto, botones y ubicación. Escribe *hola* para empezar."}

        enviar_mensaje_whatsapp(telefono, respuesta)
    except Exception as e:
        print("Error procesando mensaje:", e)

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# 3. SIMULADOR DE WHATSAPP (para probar todo el flujo sin cuenta de Meta)
# ---------------------------------------------------------------------------
@app.get("/simulador", response_class=HTMLResponse)
def simulador():
    return """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Simulador WhatsApp - Maduritos Asados</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background:#e5ddd5; margin:0; }
            .telefono-bar { background:#111b21; color:#fff; padding:14px; display:flex; align-items:center; gap:10px;}
            .telefono-bar b { font-size:16px; }
            #chat { padding:12px; max-width:480px; margin:0 auto; min-height:55vh; }
            .msg { max-width:85%; padding:8px 12px; border-radius:8px; margin:6px 0; white-space:pre-wrap; font-size:14px; line-height:1.4; }
            .cliente { background:#d9fdd3; margin-left:auto; }
            .bot { background:#fff; margin-right:auto; }
            .opciones { display:flex; flex-direction:column; gap:6px; margin:6px 0 6px auto; max-width:85%; }
            .opcion-btn { background:#fff; border:1px solid #00a884; color:#00a884; padding:8px 12px; border-radius:8px; cursor:pointer; font-size:14px; text-align:center; }
            .opcion-btn:hover { background:#e7fbf5; }
            #barra { display:flex; gap:8px; max-width:480px; margin:12px auto; padding: 0 12px; }
            #texto { flex:1; padding:10px; border-radius:20px; border:1px solid #ccc; }
            button#enviar-btn, #ubicacion-btn { padding:10px 16px; border:none; border-radius:20px; background:#00a884; color:#fff; font-weight:bold; cursor:pointer;}
            #ubicacion-btn { background:#1a73e8; }
            .top-links { max-width:480px; margin: 10px auto; padding: 0 12px; font-size: 13px;}
            .top-links a { color:#0a5; margin-right: 12px; }
        </style>
    </head>
    <body>
        <div class="telefono-bar"><b>🍌 Simulador de WhatsApp - Maduritos Asados</b></div>
        <div class="top-links">
            <a href="/repartidor" target="_blank">Panel del repartidor →</a>
            <a href="/caja" target="_blank">Caja →</a>
            <a href="/historial" target="_blank">Historial de clientes →</a>
        </div>
        <div id="chat"></div>
        <div id="barra">
            <input id="texto" placeholder="Escribe un mensaje... (ej: hola)" onkeydown="if(event.key==='Enter') enviarTexto()">
            <button id="enviar-btn" onclick="enviarTexto()">Enviar</button>
            <button id="ubicacion-btn" onclick="enviarUbicacion()">📍</button>
        </div>
        <script>
            const telefono = "51999" + Math.floor(Math.random()*1000000);
            const chat = document.getElementById("chat");

            function agregarTexto(texto, tipo) {
                const div = document.createElement("div");
                div.className = "msg " + tipo;
                div.innerText = texto;
                chat.appendChild(div);
                window.scrollTo(0, document.body.scrollHeight);
            }

            function agregarOpciones(opciones) {
                const cont = document.createElement("div");
                cont.className = "opciones";
                opciones.forEach(o => {
                    const b = document.createElement("div");
                    b.className = "opcion-btn";
                    b.innerText = o.titulo;
                    b.onclick = () => enviarValor(o.titulo, o.id);
                    cont.appendChild(b);
                });
                chat.appendChild(cont);
                window.scrollTo(0, document.body.scrollHeight);
            }

            function mostrarRespuesta(data) {
                agregarTexto(data.texto, "bot");
                if (data.tipo === "botones" || data.tipo === "lista") {
                    agregarOpciones(data.opciones);
                }
            }

            async function enviarAlBot(payload) {
                const r = await fetch("/api/simular", {
                    method: "POST", headers: {"Content-Type": "application/json"},
                    body: JSON.stringify(payload)
                });
                return await r.json();
            }

            async function enviarValor(etiquetaVisible, valorId) {
                agregarTexto(etiquetaVisible, "cliente");
                const data = await enviarAlBot({telefono, nombre: "Cliente Demo", tipo: "texto", texto: valorId});
                mostrarRespuesta(data);
            }

            async function enviarTexto() {
                const input = document.getElementById("texto");
                const texto = input.value.trim();
                if (!texto) return;
                input.value = "";
                await enviarValor(texto, texto);
            }

            function enviarUbicacion() {
                if (!navigator.geolocation) {
                    alert("Tu navegador no soporta geolocalización.");
                    return;
                }
                navigator.geolocation.getCurrentPosition(async (pos) => {
                    const lat = pos.coords.latitude, lon = pos.coords.longitude;
                    agregarTexto("📍 Ubicación enviada (" + lat.toFixed(4) + ", " + lon.toFixed(4) + ")", "cliente");
                    const data = await enviarAlBot({telefono, nombre: "Cliente Demo", tipo: "ubicacion", lat, lon});
                    mostrarRespuesta(data);
                }, (err) => {
                    alert("No se pudo obtener tu ubicación (" + err.message + ").");
                });
            }

            (async () => {
                const data = await enviarAlBot({telefono, nombre: "Cliente Demo", tipo: "texto", texto: "hola"});
                mostrarRespuesta(data);
            })();
        </script>
    </body>
    </html>
    """


@app.post("/api/simular")
async def api_simular(request: Request):
    body = await request.json()
    respuesta = bl.procesar_mensaje(
        body.get("telefono"), body.get("nombre", ""), body.get("tipo"),
        texto=body.get("texto"), lat=body.get("lat"), lon=body.get("lon"),
    )
    return JSONResponse(respuesta)


# ---------------------------------------------------------------------------
# 4. Panel del repartidor — se actualiza solo y avisa con sonido/notificación
# ---------------------------------------------------------------------------
@app.get("/api/pedidos-pendientes")
def api_pedidos_pendientes():
    pendientes = bl.pedidos_pendientes()
    for p in pendientes:
        p["maps_url"] = f"https://www.google.com/maps/dir/?api=1&destination={p['latitud']},{p['longitud']}"
    return {"pedidos": pendientes}


@app.get("/repartidor", response_class=HTMLResponse)
def app_repartidor():
    return """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Repartidor - Despacho</title>
        <link rel="manifest" href="/manifest.json">
        <link rel="apple-touch-icon" href="/static/icon-192.png">
        <meta name="theme-color" content="#00A884">
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background:#f0f2f5; margin:0; padding:16px; }
            .tarjeta { background:#fff; border-radius:12px; padding:16px; margin-bottom:16px; box-shadow:0 2px 6px rgba(0,0,0,0.1); }
            .fila { display:flex; justify-content:space-between; align-items:center; }
            .monto { background:#e8f5e9; color:#2e7d32; padding:4px 8px; border-radius:6px; font-weight:bold; }
            .acciones { display:flex; gap:10px; margin-top:12px; }
            .maps { flex:1; text-align:center; background:#1a73e8; color:#fff; text-decoration:none; padding:10px; border-radius:6px; font-weight:bold; }
            .entregar { flex:1; background:#34a853; color:#fff; border:none; padding:10px; border-radius:6px; font-weight:bold; cursor:pointer; }
            #estado-sonido { font-size:13px; color:#666; margin-bottom:10px; }
        </style>
    </head>
    <body>
        <h2 style="color:#111;" id="titulo">📦 Pedidos por Entregar (...)</h2>
        <p id="estado-sonido">🔔 Activando avisos de sonido...</p>
        <button id="btn-push" style="display:none; background:#00a884; color:#fff; border:none; padding:10px 16px; border-radius:8px; font-weight:bold; margin-bottom:14px; cursor:pointer;">
            🔔 Activar notificaciones (aunque cierre el navegador)
        </button>
        <p id="estado-push" style="font-size:13px; color:#666;"></p>
        <div id="lista"></div>
        <script>
            let idsConocidos = new Set();
            let primeraCarga = true;
            let audioListo = false;

            function activarAudio() {
                audioListo = true;
                document.getElementById("estado-sonido").innerText = "🔔 Avisos de sonido activados.";
                document.removeEventListener("click", activarAudio);
            }
            document.addEventListener("click", activarAudio);

            function sonarAviso() {
                if (!audioListo) return;
                try {
                    const ctx = new (window.AudioContext || window.webkitAudioContext)();
                    [0, 0.15, 0.3].forEach((t) => {
                        const o = ctx.createOscillator();
                        const g = ctx.createGain();
                        o.type = "sine";
                        o.frequency.value = 880;
                        g.gain.value = 0.2;
                        o.connect(g); g.connect(ctx.destination);
                        o.start(ctx.currentTime + t);
                        o.stop(ctx.currentTime + t + 0.12);
                    });
                } catch (e) {}
                if (window.Notification && Notification.permission === "granted") {
                    new Notification("🍌 Nuevo pedido de Maduritos Asados");
                }
            }

            if (window.Notification && Notification.permission === "default") {
                Notification.requestPermission();
            }

            function tarjetaHTML(p) {
                return `
                <div class="tarjeta">
                    <div class="fila">
                        <h3 style="margin:0; color:#333;">Orden #${p.id}</h3>
                        <span class="monto">S/ ${p.monto_total.toFixed(2)}</span>
                    </div>
                    <p style="margin:8px 0; color:#555;"><strong>Cliente:</strong> ${p.cliente_nombre} (${p.telefono})</p>
                    <p style="margin:8px 0; color:#555;"><strong>Pedido:</strong> ${p.detalle}</p>
                    <p style="margin:8px 0; color:#777; font-size:14px;">Distancia: ${p.distancia_km} km · ${p.fecha}</p>
                    <div class="acciones">
                        <a class="maps" href="${p.maps_url}" target="_blank">Abrir Maps</a>
                        <button class="entregar" onclick="entregar(${p.id})">Entregado</button>
                    </div>
                </div>`;
            }

            async function actualizar() {
                const r = await fetch("/api/pedidos-pendientes");
                const data = await r.json();
                const pedidos = data.pedidos;

                document.getElementById("titulo").innerText = `📦 Pedidos por Entregar (${pedidos.length})`;
                document.getElementById("lista").innerHTML = pedidos.length
                    ? pedidos.map(tarjetaHTML).join("")
                    : '<p style="color:#666;">No hay pedidos pendientes en la cola.</p>';

                const idsActuales = new Set(pedidos.map(p => p.id));
                if (!primeraCarga) {
                    for (const id of idsActuales) {
                        if (!idsConocidos.has(id)) { sonarAviso(); break; }
                    }
                }
                idsConocidos = idsActuales;
                primeraCarga = false;
            }

            async function entregar(id) {
                await fetch('/api/entregar/' + id, { method: 'POST' });
                actualizar();
            }

            function urlBase64ToUint8Array(base64String) {
                const padding = '='.repeat((4 - base64String.length % 4) % 4);
                const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
                const rawData = window.atob(base64);
                return Uint8Array.from([...rawData].map(c => c.charCodeAt(0)));
            }

            async function configurarPush() {
                const estadoPush = document.getElementById("estado-push");
                if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
                    estadoPush.innerText = "Tu navegador no soporta notificaciones push (usa Chrome/Edge/Firefox reciente).";
                    return;
                }
                const registro = await navigator.serviceWorker.register('/sw.js');
                const suscripcionExistente = await registro.pushManager.getSubscription();
                if (suscripcionExistente) {
                    estadoPush.innerText = "🔔 Notificaciones push activadas en este dispositivo.";
                    return;
                }
                const btn = document.getElementById("btn-push");
                btn.style.display = "inline-block";
                btn.onclick = async () => {
                    try {
                        const permiso = await Notification.requestPermission();
                        if (permiso !== "granted") {
                            estadoPush.innerText = "No diste permiso de notificaciones. Actívalo en los ajustes del navegador.";
                            return;
                        }
                        const { publicKey } = await (await fetch('/api/push/vapid-public-key')).json();
                        if (!publicKey) {
                            estadoPush.innerText = "El servidor aún no tiene configuradas las llaves VAPID (revisa tu .env).";
                            return;
                        }
                        const suscripcion = await registro.pushManager.subscribe({
                            userVisibleOnly: true,
                            applicationServerKey: urlBase64ToUint8Array(publicKey),
                        });
                        await fetch('/api/push/subscribe', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(suscripcion),
                        });
                        btn.style.display = "none";
                        estadoPush.innerText = "🔔 Notificaciones push activadas en este dispositivo.";
                    } catch (e) {
                        estadoPush.innerText = "No se pudo activar la notificación push: " + e.message;
                    }
                };
            }
            configurarPush();

            actualizar();
            setInterval(actualizar, 5000);
        </script>
    </body>
    </html>
    """


@app.post("/api/entregar/{pedido_id}")
def marcar_entregado(pedido_id: int):
    with bl._lock:
        bl.cursor.execute("UPDATE pedidos SET estado = 'ENTREGADO' WHERE id = ?", (pedido_id,))
        bl.conn.commit()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# 5. Caja / conteo de ventas — por día, semana o mes
# ---------------------------------------------------------------------------
@app.get("/reporte-caja")
def reporte_caja(periodo: str = Query("dia", description="dia, semana o mes")):
    return bl.reporte_por_periodo(periodo)


@app.get("/caja/exportar.xlsx")
def exportar_caja_excel(periodo: str = Query("dia")):
    contenido = bl.generar_excel_reporte(periodo)
    return StreamingResponse(
        iter([contenido]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="caja_{periodo}.xlsx"'},
    )


@app.get("/caja/exportar.pdf")
def exportar_caja_pdf(periodo: str = Query("dia")):
    contenido = bl.generar_pdf_reporte(periodo)
    return StreamingResponse(
        iter([contenido]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="caja_{periodo}.pdf"'},
    )


@app.get("/caja", response_class=HTMLResponse)
def caja_html(periodo: str = Query("dia")):
    data = bl.reporte_por_periodo(periodo)
    etiquetas = {"dia": "Hoy", "semana": "Últimos 7 días", "mes": "Este mes"}

    def boton(p):
        activo = "background:#00a884;color:#fff;" if p == periodo else "background:#eee;color:#333;"
        return f'<a href="/caja?periodo={p}" style="{activo}text-decoration:none;padding:8px 14px;border-radius:20px;margin-right:8px;font-size:13px;">{etiquetas[p]}</a>'

    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Cierre de Caja</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background:#f0f2f5; margin:0; padding:24px; }}
            .card {{ background:#fff; border-radius:14px; padding:24px; max-width:380px; margin:0 auto; box-shadow:0 2px 8px rgba(0,0,0,0.1); }}
            .num {{ font-size:32px; font-weight:bold; color:#2e7d32; }}
            .label {{ color:#666; font-size:14px; margin-bottom:18px; }}
            .botones {{ max-width:380px; margin:0 auto 16px auto; }}
            .exportar {{ max-width:380px; margin:16px auto 0 auto; display:flex; gap:10px; }}
            .exportar a {{ flex:1; text-align:center; text-decoration:none; padding:12px; border-radius:10px; font-size:14px; font-weight:bold; }}
            .btn-excel {{ background:#1d6f42; color:#fff; }}
            .btn-pdf {{ background:#c0392b; color:#fff; }}
        </style>
    </head>
    <body>
        <div class="botones">{boton('dia')}{boton('semana')}{boton('mes')}</div>
        <div class="card">
            <h2>💰 Cierre de Caja</h2>
            <p style="color:#999; font-size:13px;">{etiquetas[periodo]}</p>
            <div class="num">S/ {data['total_recaudado_soles']:.2f}</div>
            <div class="label">Total recaudado</div>
            <div class="num">{data['maduritos_vendidos']}</div>
            <div class="label">Maduritos vendidos</div>
            <div class="num">{data['pedidos_entregados']}</div>
            <div class="label">Pedidos entregados</div>
            <div class="exportar">
                <a class="btn-excel" href="/caja/exportar.xlsx?periodo={periodo}">⬇️ Excel</a>
                <a class="btn-pdf" href="/caja/exportar.pdf?periodo={periodo}">⬇️ PDF</a>
            </div>
        </div>
    </body>
    </html>
    """


# ---------------------------------------------------------------------------
# 6. Historial de pedidos por cliente
# ---------------------------------------------------------------------------
@app.get("/api/historial")
def api_historial(telefono: str):
    return bl.historial_cliente(telefono)


@app.get("/historial", response_class=HTMLResponse)
def historial_html(telefono: str = Query(None)):
    filas = ""
    resumen = ""
    if telefono:
        data = bl.historial_cliente(telefono)
        resumen = f"<p><strong>Total gastado (pedidos entregados):</strong> S/ {data['total_gastado_soles']:.2f}</p>"
        for p in data["pedidos"]:
            color = "#2e7d32" if p["estado"] == "ENTREGADO" else "#e65100"
            filas += f"""
            <tr>
                <td>#{p['id']}</td><td>{p['fecha']}</td><td>{p['detalle']}</td>
                <td>S/ {p['monto_total']:.2f}</td>
                <td style="color:{color}; font-weight:bold;">{p['estado']}</td>
            </tr>"""
        if not filas:
            filas = '<tr><td colspan="5" style="color:#666;">Este cliente no tiene pedidos registrados.</td></tr>'

    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Historial de Clientes</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background:#f0f2f5; margin:0; padding:20px; }}
            input {{ padding:10px; border-radius:6px; border:1px solid #ccc; width:220px; }}
            button {{ padding:10px 16px; border:none; border-radius:6px; background:#00a884; color:#fff; font-weight:bold; cursor:pointer; }}
            table {{ width:100%; border-collapse:collapse; background:#fff; border-radius:8px; overflow:hidden; margin-top:16px; }}
            th, td {{ padding:10px; text-align:left; border-bottom:1px solid #eee; font-size:14px; }}
            th {{ background:#fafafa; }}
        </style>
    </head>
    <body>
        <h2>📜 Historial de pedidos por cliente</h2>
        <form method="get">
            <input type="text" name="telefono" placeholder="Número de teléfono del cliente" value="{telefono or ''}">
            <button type="submit">Buscar</button>
        </form>
        {resumen}
        {'<table><tr><th>Orden</th><th>Fecha</th><th>Detalle</th><th>Monto</th><th>Estado</th></tr>' + filas + '</table>' if telefono else ''}
    </body>
    </html>
    """


@app.get("/qr", response_class=HTMLResponse)
def ver_qr():
    ruta_qr = os.path.join(_static_dir, "qr_actual.png")
    if os.path.exists(ruta_qr):
        cuerpo = """
        <h2>📱 Escanea este QR con WhatsApp</h2>
        <p>Configuración → Dispositivos vinculados → Vincular un dispositivo</p>
        <img src="/static/qr_actual.png" style="width:320px; border:8px solid #fff; border-radius:12px;">
        <p style="color:#888; font-size:13px;">Esta página se actualiza sola cada 5 segundos.</p>
        """
    else:
        cuerpo = """
        <h2>✅ Ya está conectado (o aún generando el QR)</h2>
        <p>Si acabas de reiniciar el servicio, espera unos segundos y recarga.
        Si no aparece nunca un QR aquí y tampoco responde el bot, revisa los
        Logs de Render por algún error.</p>
        """
    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta http-equiv="refresh" content="5">
        <title>Vincular WhatsApp - Maduritos Asados</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background:#111b21; color:#fff; margin:0; padding:24px; text-align:center; }}
            img {{ margin: 16px 0; }}
        </style>
    </head>
    <body>
        {cuerpo}
    </body>
    </html>
    """


@app.get("/privacidad", response_class=HTMLResponse)
def politica_privacidad():
    return """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Política de Privacidad - Maduritos Asados</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background:#f0f2f5; margin:0; padding:24px; color:#222; }
            .card { background:#fff; border-radius:14px; padding:28px; max-width:640px; margin:0 auto; box-shadow:0 2px 8px rgba(0,0,0,0.1); line-height:1.6; }
            h1 { color:#00A884; }
            h2 { font-size:18px; margin-top:24px; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🍌 Política de Privacidad</h1>
            <p>Maduritos Asados</p>

            <h2>Qué datos recopilamos</h2>
            <p>Cuando nos escribes por WhatsApp para hacer un pedido, guardamos: tu número de
            teléfono, tu nombre (el que muestra WhatsApp), el detalle de tu pedido, el monto
            total, y tu ubicación GPS únicamente para calcular si estás dentro de nuestra zona
            de reparto.</p>

            <h2>Para qué usamos tus datos</h2>
            <p>Solo para procesar y entregar tu pedido, calcular tu total, verificar la zona
            de reparto, y llevar un historial de tus pedidos anteriores por si vuelves a
            escribirnos.</p>

            <h2>Con quién compartimos tus datos</h2>
            <p>No vendemos ni compartimos tus datos con nadie fuera de nuestro negocio. Solo
            usamos la plataforma de WhatsApp Business (Meta) para poder enviarte y recibir
            mensajes, según los términos de esa plataforma.</p>

            <h2>Cuánto tiempo guardamos tus datos</h2>
            <p>Guardamos el historial de tus pedidos mientras seas cliente activo. Puedes
            pedirnos en cualquier momento, por WhatsApp, que eliminemos tu información.</p>

            <h2>Contacto</h2>
            <p>Si tienes preguntas sobre tus datos, escríbenos directamente por WhatsApp al
            número de este negocio.</p>
        </div>
    </body>
    </html>
    """


@app.get("/")
def raiz():
    return {
        "app": "Maduritos Asados - Bot de Pedidos",
        "prueba_aqui": "/simulador",
        "panel_repartidor": "/repartidor",
        "caja": "/caja",
        "historial": "/historial",
        "politica_privacidad": "/privacidad",
    }
