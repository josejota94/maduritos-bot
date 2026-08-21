import json
import math
import os
import sqlite3
import threading
import unicodedata

# ---------------------------------------------------------------------------
# CONFIGURACIÓN DEL NEGOCIO (edita estos valores a tu gusto, o mejor en .env)
# ---------------------------------------------------------------------------
LAT_LOCAL = float(os.getenv("LAT_LOCAL", "-6.0350"))
LON_LOCAL = float(os.getenv("LON_LOCAL", "-76.9700"))
RADIO_MAXIMO_KM = float(os.getenv("RADIO_MAXIMO_KM", "4.0"))
PEDIDO_MINIMO_UNIDADES = int(os.getenv("PEDIDO_MINIMO_UNIDADES", "3"))

PRECIOS = {"estandar": 3.00, "grande": 4.00}
RELLENOS = ["queso", "mani", "chicharron", "combinado"]
RELLENOS_TITULOS = {"queso": "Queso", "mani": "Maní", "chicharron": "Chicharrón", "combinado": "Combinado"}

DB_PATH = os.path.join(os.path.dirname(__file__), "pedidos_maduritos.db")

_lock = threading.Lock()
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS pedidos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telefono TEXT,
        cliente_nombre TEXT,
        detalle TEXT,
        total_unidades INTEGER,
        monto_total REAL,
        latitud REAL,
        longitud REAL,
        distancia_km REAL,
        estado TEXT DEFAULT 'PENDIENTE',
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """
)
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS sesiones (
        telefono TEXT PRIMARY KEY,
        nombre TEXT,
        paso TEXT,
        cantidad_total INTEGER,
        unidad_actual INTEGER DEFAULT 0,
        tamano_pendiente TEXT,
        carrito TEXT
    )
    """
)
conn.commit()

# Migración suave por si existía una base de datos de una versión anterior
_columnas_sesiones = {c[1] for c in cursor.execute("PRAGMA table_info(sesiones)").fetchall()}
if "unidad_actual" not in _columnas_sesiones:
    cursor.execute("ALTER TABLE sesiones ADD COLUMN unidad_actual INTEGER DEFAULT 0")
if "tamano_pendiente" not in _columnas_sesiones:
    cursor.execute("ALTER TABLE sesiones ADD COLUMN tamano_pendiente TEXT")
conn.commit()


# ---------------------------------------------------------------------------
# UTILIDADES
# ---------------------------------------------------------------------------
def _normalizar(texto: str) -> str:
    texto = (texto or "").strip().lower()
    texto = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return texto


def calcular_distancia(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def _texto(msg):
    return {"tipo": "texto", "texto": msg}


def _botones(msg, opciones):
    """opciones: lista de (id, titulo) — máximo 3, límite real de WhatsApp."""
    return {"tipo": "botones", "texto": msg, "opciones": [{"id": i, "titulo": t} for i, t in opciones]}


def _lista(msg, opciones, boton_texto="Elegir"):
    """opciones: lista de (id, titulo) — hasta 10, usa el formato de lista de WhatsApp."""
    return {"tipo": "lista", "texto": msg, "boton_texto": boton_texto, "opciones": [{"id": i, "titulo": t} for i, t in opciones]}


def _valor_opcion(texto_o_id: str, prefijo: str) -> str:
    """
    Normaliza tanto un id de botón/lista (ej. 'tam_grande') como texto libre
    escrito a mano (ej. 'Grande') a un mismo valor comparable ('grande').
    """
    v = _normalizar(texto_o_id)
    if v.startswith(prefijo):
        v = v[len(prefijo):]
    return v


def _get_sesion(telefono):
    cursor.execute(
        "SELECT telefono, nombre, paso, cantidad_total, unidad_actual, tamano_pendiente, carrito "
        "FROM sesiones WHERE telefono=?",
        (telefono,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "telefono": row[0],
        "nombre": row[1],
        "paso": row[2],
        "cantidad_total": row[3],
        "unidad_actual": row[4] or 0,
        "tamano_pendiente": row[5],
        "carrito": json.loads(row[6]) if row[6] else [],
    }


def _guardar_sesion(telefono, nombre, paso, cantidad_total=None, unidad_actual=0, tamano_pendiente=None, carrito=None):
    with _lock:
        cursor.execute(
            """
            INSERT INTO sesiones (telefono, nombre, paso, cantidad_total, unidad_actual, tamano_pendiente, carrito)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telefono) DO UPDATE SET
                nombre=excluded.nombre,
                paso=excluded.paso,
                cantidad_total=excluded.cantidad_total,
                unidad_actual=excluded.unidad_actual,
                tamano_pendiente=excluded.tamano_pendiente,
                carrito=excluded.carrito
            """,
            (telefono, nombre, paso, cantidad_total, unidad_actual, tamano_pendiente, json.dumps(carrito or [])),
        )
        conn.commit()


def _borrar_sesion(telefono):
    with _lock:
        cursor.execute("DELETE FROM sesiones WHERE telefono=?", (telefono,))
        conn.commit()


def _opciones_tamano():
    return [("tam_estandar", "Estándar (S/ 3.00)"), ("tam_grande", "Grande (S/ 4.00)")]


def _opciones_relleno():
    return [(f"rel_{r}", RELLENOS_TITULOS[r]) for r in RELLENOS]


def _pedir_tamano(unidad_actual, cantidad_total):
    return _botones(
        f"Maduro *{unidad_actual}/{cantidad_total}* — elige el tamaño:",
        _opciones_tamano(),
    )


def _pedir_relleno(unidad_actual, cantidad_total, tamano):
    nombre_tam = "Estándar" if tamano == "estandar" else "Grande"
    return _lista(
        f"Maduro {unidad_actual}/{cantidad_total} ({nombre_tam}) — elige el relleno:",
        _opciones_relleno(),
        boton_texto="Elegir relleno",
    )


def _resumen_carrito(carrito):
    return "\n".join(
        f"- {('Estándar' if c['tamano']=='estandar' else 'Grande')} {RELLENOS_TITULOS[c['relleno']]} (S/ {c['precio']:.2f})"
        for c in carrito
    )


MENU_INTRO = (
    "¡Hola{saludo}! Bienvenido a *Maduritos Asados* 🍌🔥\n\n"
    "*Carta:*\n"
    "- Estándar (Queso, Maní, Chicharrón, Combinado): S/ 3.00\n"
    "- Grande (Queso, Maní, Chicharrón, Combinado): S/ 4.00\n\n"
    f"*Condición:* pedido mínimo de {PEDIDO_MINIMO_UNIDADES} unidades para delivery.\n\n"
    "_Escribe *cancelar* en cualquier momento para reiniciar tu pedido._"
)


def _pedir_cantidad(nombre):
    msg = MENU_INTRO.format(saludo=f" {nombre}" if nombre else "") + "\n\n¿Cuántos maduritos en total deseas pedir?"
    opciones_rapidas = [("cant_3", "3 unidades"), ("cant_5", "5 unidades"), ("cant_otra", "Otra cantidad")]
    return _botones(msg, opciones_rapidas)


def procesar_mensaje(telefono: str, nombre: str, tipo: str, texto: str = None, lat: float = None, lon: float = None):
    """
    Motor del flujo conversacional. Usado tanto por el webhook real de WhatsApp
    como por el simulador de pruebas (/simulador).

    Devuelve un diccionario describiendo la respuesta:
      {"tipo": "texto", "texto": "..."}
      {"tipo": "botones", "texto": "...", "opciones": [{"id":..,"titulo":..}, ...]}   (máx. 3)
      {"tipo": "lista",   "texto": "...", "boton_texto": "...", "opciones": [...]}     (hasta 10)

    Tanto un botón/lista real de WhatsApp como texto escrito a mano llegan aquí
    como tipo="texto" con `texto` = id de la opción (ej. "tam_grande") o palabra libre
    (ej. "grande") — ambos se aceptan.
    """
    sesion = _get_sesion(telefono)

    if texto and _normalizar(texto) in ("cancelar", "reiniciar"):
        _borrar_sesion(telefono)
        return _texto("Tu pedido fue cancelado. Escribe cualquier mensaje para empezar de nuevo. 🙂")

    # --- Sin sesión activa: mostrar menú y pedir cantidad ---
    if sesion is None:
        _guardar_sesion(telefono, nombre, "esperando_cantidad")
        return _pedir_cantidad(nombre)

    paso = sesion["paso"]

    # --- Paso 1: cantidad total ---
    if paso == "esperando_cantidad":
        valor = _valor_opcion(texto or "", "cant_")
        if valor == "otra":
            return _texto("Escribe el número total de maduritos que deseas pedir.")
        if valor.isdigit():
            cantidad = int(valor)
        elif texto and texto.strip().isdigit():
            cantidad = int(texto.strip())
        else:
            return _pedir_cantidad(nombre)

        if cantidad < PEDIDO_MINIMO_UNIDADES:
            resp = _pedir_cantidad(nombre)
            resp["texto"] = (
                f"El pedido mínimo para delivery es de {PEDIDO_MINIMO_UNIDADES} unidades. "
                f"¿Cuántos maduritos deseas pedir?"
            )
            return resp

        _guardar_sesion(telefono, nombre, "esperando_tamano", cantidad_total=cantidad, unidad_actual=1, carrito=[])
        return _pedir_tamano(1, cantidad)

    # --- Paso 2a: tamaño del maduro actual ---
    if paso == "esperando_tamano":
        valor = _valor_opcion(texto or "", "tam_")
        if valor not in PRECIOS:
            resp = _pedir_tamano(sesion["unidad_actual"], sesion["cantidad_total"])
            resp["texto"] = "No entendí esa opción. " + resp["texto"]
            return resp
        _guardar_sesion(
            telefono, nombre, "esperando_relleno",
            cantidad_total=sesion["cantidad_total"], unidad_actual=sesion["unidad_actual"],
            tamano_pendiente=valor, carrito=sesion["carrito"],
        )
        return _pedir_relleno(sesion["unidad_actual"], sesion["cantidad_total"], valor)

    # --- Paso 2b: relleno del maduro actual ---
    if paso == "esperando_relleno":
        valor = _valor_opcion(texto or "", "rel_")
        if valor not in RELLENOS:
            resp = _pedir_relleno(sesion["unidad_actual"], sesion["cantidad_total"], sesion["tamano_pendiente"])
            resp["texto"] = "No entendí ese relleno. " + resp["texto"]
            return resp

        tamano = sesion["tamano_pendiente"]
        carrito = sesion["carrito"] + [{"tamano": tamano, "relleno": valor, "precio": PRECIOS[tamano]}]
        siguiente_unidad = sesion["unidad_actual"] + 1
        cantidad_total = sesion["cantidad_total"]

        if siguiente_unidad <= cantidad_total:
            _guardar_sesion(
                telefono, nombre, "esperando_tamano",
                cantidad_total=cantidad_total, unidad_actual=siguiente_unidad,
                carrito=carrito,
            )
            return _pedir_tamano(siguiente_unidad, cantidad_total)

        total = sum(c["precio"] for c in carrito)
        _guardar_sesion(
            telefono, nombre, "esperando_confirmacion",
            cantidad_total=cantidad_total, unidad_actual=siguiente_unidad, carrito=carrito,
        )
        resumen = _resumen_carrito(carrito)
        return _botones(
            f"Tu pedido:\n{resumen}\n\n*Total: S/ {total:.2f}*\n\n¿Confirmas este pedido?",
            [("confirmar_pedido", "✅ Confirmar"), ("cancelar_pedido", "❌ Cancelar")],
        )

    # --- Paso 3: confirmación antes de pedir ubicación ---
    if paso == "esperando_confirmacion":
        valor = _valor_opcion(texto or "", "")
        if "cancelar" in valor:
            _borrar_sesion(telefono)
            return _texto("Tu pedido fue cancelado. Escribe cualquier mensaje para empezar de nuevo. 🙂")
        if "confirmar" in valor:
            _guardar_sesion(
                telefono, nombre, "esperando_ubicacion",
                cantidad_total=sesion["cantidad_total"], carrito=sesion["carrito"],
            )
            return _texto(
                f"Ahora comparte tu *ubicación* (GPS) para verificar si estás dentro de nuestra zona "
                f"de reparto ({RADIO_MAXIMO_KM} km)."
            )
        resumen = _resumen_carrito(sesion["carrito"])
        total = sum(c["precio"] for c in sesion["carrito"])
        return _botones(
            f"Tu pedido:\n{resumen}\n\n*Total: S/ {total:.2f}*\n\n¿Confirmas este pedido?",
            [("confirmar_pedido", "✅ Confirmar"), ("cancelar_pedido", "❌ Cancelar")],
        )

    # --- Paso 4: ubicación ---
    if paso == "esperando_ubicacion":
        if tipo != "ubicacion" or lat is None or lon is None:
            return _texto("Por favor comparte tu ubicación (GPS) usando el botón/función de ubicación de WhatsApp.")

        distancia = calcular_distancia(LAT_LOCAL, LON_LOCAL, lat, lon)
        if distancia > RADIO_MAXIMO_KM:
            _borrar_sesion(telefono)
            return _texto(
                f"Lo sentimos, tu ubicación está a {distancia:.1f} km y nuestro rango máximo de delivery "
                f"es de {RADIO_MAXIMO_KM} km. Escribe cualquier mensaje si deseas intentar con otra dirección."
            )

        carrito = sesion["carrito"]
        total_unidades = sesion["cantidad_total"]
        monto_total = sum(c["precio"] for c in carrito)
        detalle = ", ".join(f"{c['tamano']} {c['relleno']}" for c in carrito)

        with _lock:
            cursor.execute(
                """
                INSERT INTO pedidos
                    (telefono, cliente_nombre, detalle, total_unidades, monto_total, latitud, longitud, distancia_km)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (telefono, nombre, detalle, total_unidades, monto_total, lat, lon, round(distancia, 2)),
            )
            conn.commit()

        _borrar_sesion(telefono)
        return _texto(
            f"¡Pedido confirmado! ✅\n"
            f"{detalle}\n"
            f"Total: S/ {monto_total:.2f}\n"
            f"Distancia: {distancia:.1f} km\n\n"
            f"Tu pedido está en camino. ¡Gracias por tu compra! 🍌"
        )

    # Estado desconocido: reiniciar
    _borrar_sesion(telefono)
    return _pedir_cantidad(nombre)


# ---------------------------------------------------------------------------
# HISTORIAL Y REPORTES (idea: historial por cliente + reportes por periodo)
# ---------------------------------------------------------------------------
def historial_cliente(telefono: str):
    cursor.execute(
        """
        SELECT id, detalle, total_unidades, monto_total, distancia_km, estado, fecha
        FROM pedidos WHERE telefono = ? ORDER BY fecha DESC
        """,
        (telefono,),
    )
    filas = cursor.fetchall()
    pedidos = [
        {
            "id": f[0], "detalle": f[1], "total_unidades": f[2], "monto_total": f[3],
            "distancia_km": f[4], "estado": f[5], "fecha": f[6],
        }
        for f in filas
    ]
    total_gastado = sum(p["monto_total"] for p in pedidos if p["estado"] == "ENTREGADO")
    return {"telefono": telefono, "pedidos": pedidos, "total_gastado_soles": round(total_gastado, 2)}


def reporte_por_periodo(periodo: str = "dia"):
    condiciones = {
        "dia": "date(fecha) = date('now')",
        "semana": "date(fecha) >= date('now', '-6 days')",
        "mes": "strftime('%Y-%m', fecha) = strftime('%Y-%m', 'now')",
    }
    condicion = condiciones.get(periodo, condiciones["dia"])
    cursor.execute(
        f"""
        SELECT COUNT(id), SUM(total_unidades), SUM(monto_total)
        FROM pedidos WHERE estado = 'ENTREGADO' AND {condicion}
        """
    )
    total_pedidos, total_maduros, total_dinero = cursor.fetchone()
    return {
        "periodo": periodo,
        "pedidos_entregados": total_pedidos or 0,
        "maduritos_vendidos": total_maduros or 0,
        "total_recaudado_soles": round(total_dinero or 0.0, 2),
    }


def pedidos_pendientes():
    cursor.execute(
        """
        SELECT id, cliente_nombre, telefono, detalle, monto_total, latitud, longitud, distancia_km, fecha
        FROM pedidos WHERE estado = 'PENDIENTE' ORDER BY id ASC
        """
    )
    filas = cursor.fetchall()
    return [
        {
            "id": f[0], "cliente_nombre": f[1] or "Sin nombre", "telefono": f[2], "detalle": f[3],
            "monto_total": f[4], "latitud": f[5], "longitud": f[6], "distancia_km": f[7], "fecha": f[8],
        }
        for f in filas
    ]
