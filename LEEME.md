# Maduritos Asados — Bot de Pedidos por WhatsApp

Esta aplicación:
- Recibe pedidos (por ahora simulados, más adelante por WhatsApp real).
- Exige un mínimo de 3 maduritos.
- Calcula el precio automáticamente (Estándar S/ 3.00 / Grande S/ 4.00).
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
- Los pedidos guardados pueden perderse si Render reinicia el servidor. Para un
  negocio real que no puede permitirse perder pedidos, lo ideal es pasar al plan
  pagado más básico de Render (desde ~USD 7/mes) con un "disco persistente" — puedo
  ayudarte a configurar eso cuando quieras dar ese paso.

Una vez que tengas esta URL pública, también es el paso previo para conectar el
WhatsApp real (Meta necesita una URL de internet, no puede apuntar a tu laptop).

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
- **Historial de pedidos por cliente** (`/historial`): busca por número de teléfono y
  ve todos sus pedidos anteriores y cuánto ha gastado en total.
- **Reportes por periodo**: la Caja (`/caja`) ahora tiene pestañas de Hoy / Últimos 7
  días / Este mes (`/reporte-caja?periodo=dia|semana|mes` en formato JSON).
- Simulador de WhatsApp para probar sin necesitar cuenta de Meta.
- Configuración por archivo `.env` en vez de datos escritos directamente en el código.

## 7. Ideas para más adelante (dime si quieres que las agregue)

- Notificaciones push al celular del repartidor incluso con la pantalla apagada
  (requiere convertir el panel en una PWA instalable).
- Reportes descargables en Excel/PDF.
- Publicar la app en internet 24/7 con almacenamiento persistente (plan pagado de Render).
