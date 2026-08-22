# Maduritos Asados — Bot de Pedidos por WhatsApp

Esta aplicación:
- Recibe pedidos (por ahora simulados, más adelante por WhatsApp real).
- Exige un mínimo de 3 maduritos.
- Calcula el precio automáticamente (Mediano S/ 3.00 / Grande S/ 4.00 / Relleno Extra S/ 5.00).
- Permite combinar sabores en un mismo maduro (Queso, Maní, Chicharrón, o cualquier
  combinación entre ellos), sin costo extra.
- Verifica que la dirección del cliente esté dentro de tu zona de reparto (por GPS).
- Guarda todo en una base de datos (`pedidos_maduritos.db`).
- Tiene un panel para tu repartidor (ver pedidos, abrir Google Maps, marcar "Entregado").
- Tiene una pantalla de "Caja" con el total vendido y cuántos maduritos se despacharon.
- Incluye un **simulador de WhatsApp** para que puedas probar TODO ahora mismo, sin
  necesitar todavía una cuenta de WhatsApp Business.

No necesitas saber programar para usarla. Sigue los pasos tal cual.

---

## 1. Instalar lo necesario (una sola vez)

1. Instala Python desde https://www.python.org/downloads/ (marca la casilla
   "Add Python to PATH" durante la instalación, en Windows).
2. Descarga y descomprime la carpeta de esta aplicación en tu computadora.
3. Abre una terminal (en Windows: busca "cmd" o "PowerShell"; en Mac: "Terminal")
   dentro de esa carpeta.
4. Instala las dependencias con:
   ```
   pip install -r requirements.txt
   ```

## 2. Probar la app HOY MISMO (sin WhatsApp todavía)

1. En la terminal, dentro de la carpeta, ejecuta:
   ```
   python main.py
   ```
   o si eso no funciona:
   ```
   python -m uvicorn main:app --reload
   ```
2. Abre tu navegador en: **http://localhost:8000/simulador**
3. Escribe "hola" y sigue la conversación como si fueras un cliente:
   - Te preguntará cuántos maduritos quieres (mínimo 3).
   - Luego, maduro por maduro, toca el tamaño (botón) y el relleno (lista) de cada uno.
   - Verás el resumen y el total — toca "✅ Confirmar".
   - Luego te pedirá tu ubicación (botón "📍" — tu navegador pedirá permiso).
4. Si estás dentro del rango de reparto, el pedido se confirma y queda guardado.
5. Abre **http://localhost:8000/repartidor** para ver el pedido y marcarlo como "Entregado".
6. Abre **http://localhost:8000/caja** para ver el total vendido del día.

Puedes repetir esto tantas veces quieras para probar distintos escenarios
(pedidos menores a 3, direcciones fuera de rango, etc.) — no borra tus pedidos
reales una vez que conectes WhatsApp de verdad.

## 3. Ajustar los datos de tu negocio

Copia el archivo `.env.example` y renómbralo a `.env`. Ahí puedes cambiar:
- `LAT_LOCAL` / `LON_LOCAL`: la ubicación exacta de tu local (búscala en Google Maps,
  clic derecho sobre tu local → aparecen las coordenadas).
- `RADIO_MAXIMO_KM`: qué tan lejos entregas.
- `PEDIDO_MINIMO_UNIDADES`: el mínimo de maduritos por pedido.
- `DIRECCION_LOCAL`: la dirección de tu local en texto (ej. "Jr. Lima cuadra 4,
  frente al Banco BCP"). Se usa en dos mensajes automáticos: cuando alguien
  pide fuera de tu rango de reparto (para invitarlo a recoger su pedido en
  el local) y cuando el repartidor marca un pedido como "Entregado" (mensaje
  de agradecimiento con tu dirección, para que no se olvide de ti).

## 4. Conectar WhatsApp real (cuando estés listo)

Esto requiere una cuenta en Meta for Developers (gratis) y tu propio número de WhatsApp Business:

1. Crea una cuenta en https://developers.facebook.com/ y crea una "App" de tipo Business.
2. Dentro de la app, agrega el producto "WhatsApp".
3. Meta te dará un **Token temporal** y un **Phone Number ID** — cópialos al archivo `.env`
   (`WHATSAPP_TOKEN` y `PHONE_NUMBER_ID`).
4. Como tu computadora no es visible desde internet, necesitas exponerla temporalmente con
   una herramienta como **ngrok** (https://ngrok.com/download):
   ```
   ngrok http 8000
   ```
   Esto te da una URL pública tipo `https://algo.ngrok-free.app`.
5. En el panel de Meta, en "Configuration" del producto WhatsApp, coloca como
   **Callback URL**: `https://algo.ngrok-free.app/webhook` y como **Verify Token**
   el mismo valor que pusiste en `VERIFY_TOKEN` dentro de tu `.env`.
6. Escribe desde tu celular al número de prueba de WhatsApp que te dio Meta — debería
   responderte el bot igual que en el simulador.

Cuando quieras que esto funcione todo el tiempo (24/7) sin tener tu computadora
prendida, se puede subir a un servicio como Render o Railway — puedo ayudarte con
eso cuando llegues a ese punto.

## 5. Que el REPARTIDOR lo use desde su celular, sin depender de tu laptop

Para esto necesitas "subir" la app a un servicio en internet (hosting), que la deja
prendida todo el día aunque tu laptop esté apagada. Usaremos **Render** (tiene un
plan gratuito, suficiente para empezar).

1. **Sube el código a GitHub** (una sola vez):
   - Crea una cuenta gratis en https://github.com
   - Crea un repositorio nuevo (botón "New repository"), dale un nombre como
     `maduritos-bot`, y déjalo en "Public" o "Private", como prefieras.
   - En la página del repositorio, usa "Add file" → "Upload files" y arrastra
     TODOS los archivos de esta carpeta (`main.py`, `bot_logic.py`,
     `requirements.txt`, `render.yaml`, `.env.example`, `LEEME.md`). Dale "Commit".

2. **Crea una cuenta gratis en Render**: https://render.com

3. En Render, haz clic en **"New" → "Blueprint"**, y conecta tu cuenta de GitHub.
   Selecciona el repositorio `maduritos-bot` que subiste. Render detectará
   automáticamente el archivo `render.yaml` y configurará todo solo.

4. Espera unos minutos a que termine el "Deploy". Cuando termine, Render te da una
   URL pública parecida a: `https://maduritos-bot.onrender.com`

5. Esa es tu app en internet. Desde el celular del repartidor, abre en el navegador:
   `https://maduritos-bot.onrender.com/repartidor`
   y luego, en el menú del navegador, elige **"Agregar a pantalla de inicio"** —
   así le queda como un ícono de "app" en su celular, sin necesitar tu laptop.

   La caja queda igual en: `https://maduritos-bot.onrender.com/caja`
   Y el simulador de pruebas en: `https://maduritos-bot.onrender.com/simulador`

**Dos cosas a tener en cuenta con el plan gratuito de Render:**
- Si la app no recibe visitas por un rato, "se duerme" y tarda ~30 segundos en
  despertar la próxima vez que alguien entra (normal, no es un error).
- **Sobre perder pedidos si Render reinicia:** el plan gratis de Render borra los
  archivos del servidor en cada reinicio — eso incluye la base de datos si no
  haces nada más. La sección 8 de abajo explica cómo evitar esto **gratis**
  (sin pasar a un plan pagado de Render), conectando una base de datos externa
  gratuita que sí es permanente.

Una vez que tengas esta URL pública, también es el paso previo para conectar el
WhatsApp real (Meta necesita una URL de internet, no puede apuntar a tu laptop).

## 6b. Mejoras de esta última actualización

- **Pedido más ordenado para el repartidor y la cocina**: antes el detalle
  se guardaba como texto crudo ("grande queso_chicharron, grande queso..."),
  ahora se agrupa y se muestra legible, ej.:
  ```
  2x Grande - Queso + Chicharrón
  1x Mediano - Chicharrón
  ```
- **El bot ahora pide el nombre del cliente** justo después de la cantidad
  ("¿A nombre de quién anotamos el pedido?"), para que el repartidor sepa a
  quién llamar. El número de contacto sigue siendo el mismo WhatsApp del
  cliente — en el panel `/repartidor` ahora es un enlace para llamar directo.
- **Ya no se reinicia el pedido si el cliente solo agradece** ("gracias",
  "genial", etc.) después de que su pedido quedó confirmado — el bot
  responde que ya está en camino, en vez de volver a preguntar cuántos
  maduritos quiere.
- **Si la dirección está fuera de tu rango de reparto**, el mensaje ahora
  también invita al cliente a recoger su pedido en tu local (usando
  `DIRECCION_LOCAL`), para no perder esa venta.
- **Mensaje automático al marcar "Entregado"**: el cliente recibe un
  WhatsApp de agradecimiento con la dirección de tu local, tanto si usas
  la API oficial de Meta como si usas WhatsApp por código QR (Baileys) —
  para esto último, `whatsapp_qr.js` ahora también levanta un pequeño
  servidor interno (puerto `BAILEYS_PUERTO`, por defecto 8088) que Python
  usa para pedirle ese envío.

## 6. Mejoras que ya incluye esta versión (sobre la idea original)

- El flujo de conversación real está implementado (antes solo se guardaba un pedido
  de ejemplo fijo al recibir la ubicación). Ahora es paso a paso, maduro por maduro.
- **Botones y listas interactivas reales de WhatsApp**: el cliente elige la cantidad,
  el tamaño (botones) y el relleno (lista desplegable) tocando opciones, no escribiendo
  texto — igual que los bots de WhatsApp de negocios grandes. Si el cliente prefiere
  escribir a mano ("grande", "queso"), también funciona como respaldo.
- Paso de confirmación ("✅ Confirmar" / "❌ Cancelar") antes de pedir la ubicación,
  con el resumen y el total del pedido.
- Validación de cantidad mínima, de tamaños y de rellenos válidos, con mensajes de
  error claros para el cliente.
- Comando "cancelar" para que el cliente reinicie su pedido en cualquier momento.
- Cálculo automático del total según lo que realmente pidió cada cliente.
- **Panel del repartidor con aviso automático**: ya no hace falta recargar la página
  a mano — se actualiza sola cada 5 segundos y suena un aviso (y muestra una
  notificación del navegador) apenas entra un pedido nuevo. La primera vez que abras
  el panel, haz un clic en cualquier parte de la pantalla para "activar" el sonido
  (los navegadores lo exigen por seguridad).
- **Notificaciones push reales**, aunque el repartidor tenga la pantalla apagada o
  el navegador cerrado (ver sección 9). El panel también se puede "Agregar a
  pantalla de inicio" como una app.
- **Historial de pedidos por cliente** (`/historial`): busca por número de teléfono y
  ve todos sus pedidos anteriores y cuánto ha gastado en total.
- **Reportes por periodo**: la Caja (`/caja`) ahora tiene pestañas de Hoy / Últimos 7
  días / Este mes, y botones para descargar el reporte en **Excel** o **PDF**.
- Simulador de WhatsApp para probar sin necesitar cuenta de Meta.
- Configuración por archivo `.env` en vez de datos escritos directamente en el código.
- **Base de datos persistente gratis** (sección 8): tus pedidos no se pierden aunque
  Render reinicie el servidor, sin pagar nada.

## 8. Que tus pedidos NUNCA se pierdan (gratis, con Supabase)

Por defecto, la app guarda los pedidos en un archivo (`pedidos_maduritos.db`) dentro
del propio servidor de Render. El problema: en el plan gratis, Render borra ese
archivo cada vez que reinicia tu servicio (y lo reinicia seguido: cada vez que se
"duerme" por falta de visitas, en cada actualización de código, etc.).

La solución gratis es guardar los pedidos en una base de datos aparte, que vive
fuera de Render y no se borra nunca. Usaremos **Supabase** (tiene un plan gratis
para siempre, sin tarjeta de crédito).

1. Crea una cuenta gratis en https://supabase.com y crea un nuevo proyecto
   (ponle un nombre, por ejemplo `maduritos-bot`, y una contraseña — **guárdala**,
   la necesitas en el paso 3).
2. Espera 1-2 minutos a que Supabase termine de crear tu base de datos.
3. En el menú lateral ve a **Project Settings → Database → Connection string**,
   elige la pestaña **"URI"**, y copia el link (empieza con `postgresql://...`).
   Reemplaza donde dice `[YOUR-PASSWORD]` por la contraseña que pusiste en el
   paso 1.
4. Pega ese link completo en la variable `DATABASE_URL` de tu `.env` (para probar
   en tu compu) y también en Render: **Dashboard de tu servicio → Environment →
   Add Environment Variable** → `DATABASE_URL` con ese mismo valor.
5. Vuelve a desplegar en Render (o simplemente reinicia el servicio). La próxima
   vez que arranque, la app va a crear las tablas automáticamente en Supabase y
   usarlas en vez del archivo local. A partir de ahí, tus pedidos quedan guardados
   ahí para siempre, sin importar cuántas veces Render reinicie.

**Nota:** si dejas `DATABASE_URL` vacío, la app sigue funcionando exactamente
igual que antes con el archivo local — perfecto para seguir probando en tu compu
sin depender de internet. Solo necesitas Supabase en tu servidor de producción
(Render).

**Nota 2:** el plan gratis de Supabase "pausa" el proyecto si pasan 7 días
*sin ninguna consulta* a la base de datos — algo poco probable si tu negocio
recibe pedidos regularmente. Si llegara a pasar, entras un momento a tu panel
de Supabase y le das "Restore/Reanudar" (tus datos no se pierden, solo hay que
despertarlo).

## 9. Notificaciones push al repartidor (aunque tenga la pantalla apagada)

1. Corre una sola vez en tu compu: `python generar_vapid_keys.py` — te va a dar
   dos llaves (`VAPID_PUBLIC_KEY` y `VAPID_PRIVATE_KEY`).
2. Pégalas en tu `.env` (y en Render, en Environment Variables), junto con
   `VAPID_CLAIM_EMAIL` (cualquier correo tuyo).
3. Sube también la carpeta `static/` (con los íconos) junto al resto de archivos.
4. Esto necesita HTTPS para funcionar (con `ngrok` o ya en Render funciona bien;
   en `http://localhost` sin HTTPS el navegador puede bloquearlo).
5. El repartidor abre `/repartidor` en su celular, toca el botón
   "🔔 Activar notificaciones" una vez, acepta el permiso — y desde ahí le
   suena y vibra el celular con cada pedido nuevo, incluso con la pantalla
   apagada o el navegador cerrado.

## 11. WhatsApp por código QR corriendo 24/7 (sin dejar tu compu prendida)

Si aún no lograste registrar tu número en la API oficial de Meta (o mientras lo
resuelves), puedes recibir pedidos reales YA usando WhatsApp por código QR
(Baileys) — y hacer que corra en Render, no en tu computadora.

1. Sube también estos 3 archivos nuevos a GitHub (junto a los demás):
   `whatsapp_qr.js`, `package.json`, `start.sh`.
2. En Render no necesitas cambiar nada manualmente — el `render.yaml` ya quedó
   actualizado para instalar Node.js (via `nodejs-bin`, un paquete de Python que
   trae Node incluido) y arrancar los dos programas juntos.
3. Espera a que el deploy diga "Live". Luego ve a la pestaña **Logs** de tu
   servicio en Render — ahí, entre el texto, va a aparecer el código QR (hecho
   de caracteres, como en tu terminal local). Escanéalo con el WhatsApp de tu
   celular: **Configuración → Dispositivos vinculados → Vincular un
   dispositivo**.
4. Listo — desde ahí corre solo, sin tu computadora, aunque cierres el
   navegador.

**Sobre que Render "se duerma":** el plan gratis apaga tu servicio si no recibe
visitas por 15 minutos, lo que cortaría la conexión de WhatsApp. Para evitarlo,
gratis, usa un "pinger": entra a https://uptimerobot.com, crea una cuenta
gratis, "Add New Monitor" → tipo HTTP(s) → pega tu URL de Render
(`https://maduritos-bot.onrender.com`) → intervalo de 5 minutos → Crear. Eso le
manda una visita cada 5 minutos y Render nunca lo deja dormir.

**Limitación a saber:** cada vez que subas una actualización de código (un
nuevo deploy), la sesión de WhatsApp se desconecta y hay que volver a escanear
el QR desde los Logs — Render no guarda esa sesión de forma permanente en el
plan gratis. Para el día a día (sin subir cambios de código) debería quedarse
conectado de forma continua gracias al pinger.

## 12. Ideas para más adelante (dime si quieres que las agregue)

- App nativa de verdad (en vez de PWA) para el repartidor.
- Integración con pasarela de pagos (Yape/Plin/tarjeta) para cobrar por adelantado.
- Panel de administrador para editar precios y sabores sin tocar código.

