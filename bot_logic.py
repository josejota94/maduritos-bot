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
DIRECCION_LOCAL = os.getenv("DIRECCION_LOCAL", "Jr. Lima cuadra 4, frente al Banco BCP")

PRECIOS = {"mediano": 3.00, "grande": 4.00, "relleno_extra": 5.00}
TAMANOS_TITULOS = {"mediano": "Mediano", "grande": "Grande", "relleno_extra": "Relleno Extra"}

# Sabores base y TODAS las combinaciones posibles entre ellos (dobles + la triple).
# El precio es el mismo de siempre (según tamaño), combinar sabores no tiene costo extra.
_SABORES_BASE = ["queso", "mani", "chicharron"]
RELLENOS = [
    "queso", "mani", "chicharron",
    "queso_mani", "queso_chicharron", "mani_chicharron",
    "combinado",
]
RELLENOS_TITULOS = {
    "queso": "Queso",
    "mani": "Maní",
    "chicharron": "Chicharrón",
    "queso_mani": "Queso + Maní",
    "queso_chicharron": "Queso + Chicharrón",
    "mani_chicharron": "Maní + Chicharrón",
    "combinado": "Combinado (Queso + Maní + Chicharrón)",
}

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


def _detectar_tamano(texto_o_id: str):
    """
    Reconoce el tamaño elegido, ya sea un id de botón (ej. 'tam_relleno_extra')
    o texto libre escrito a mano (ej. 'Relleno Extra', con espacio en vez de
    guion bajo). Devuelve la key de PRECIOS o None si no se reconoce nada.
    """
    v = _valor_opcion(texto_o_id or "", "tam_")
    if v in PRECIOS:
        return v
    v_guion = v.replace(" ", "_")
    if v_guion in PRECIOS:
        return v_guion
    return None


_CONFIRMAR_PALABRAS = {"confirmar_pedido", "confirmar", "confirmo", "si", "sí", "s", "ok", "okay", "dale", "claro", "yes", "correcto", "va"}
_CANCELAR_PALABRAS = {"cancelar_pedido", "cancelar", "cancelo", "no", "n", "cancela"}


def _resolver_por_posicion(texto_o_id: str, opciones):
    """
    Si el cliente responde con un número suelto (ej. '2') que coincide con
    la POSICIÓN de una de las opciones que se le mostraron (ej. la 2da de la
    lista), lo traduce al id real de esa opción (ej. 'tam_grande').
    Necesario porque, por WhatsApp-QR, las opciones a veces solo se pueden
    mostrar como texto numerado ("1. Mediano / 2. Grande / ..."), y sin esto
    el cliente escribe "2" y el bot no lo reconoce — repite la pregunta en
    bucle en vez de avanzar.
    """
    crudo = (texto_o_id or "").strip()
    if crudo.isdigit():
        idx = int(crudo) - 1
        if 0 <= idx < len(opciones):
            return opciones[idx][0]
    return texto_o_id


def _detectar_confirmacion(texto_o_id: str):
    """Devuelve 'confirmar', 'cancelar' o None. Acepta el id del botón o
    sinónimos comunes escritos a mano ('si', 'sí', 'ok', 'no', ...)."""
    v = _normalizar(texto_o_id or "")
    if v in _CANCELAR_PALABRAS:
        return "cancelar"
    if v in _CONFIRMAR_PALABRAS:
        return "confirmar"
    return None


def _detectar_relleno(texto_o_id: str):
    """
    Reconoce el relleno elegido, ya sea:
    - un id de la lista de WhatsApp (ej. 'rel_queso_mani' -> 'queso_mani'), o
    - texto libre escrito a mano (ej. 'queso y mani', 'los 3', 'combinado', 'todo').
    Devuelve el valor canónico (una key de RELLENOS) o None si no se reconoce nada.
    """
    v = _valor_opcion(texto_o_id or "", "rel_")
    if v in RELLENOS:
        return v

    if v in ("combinado", "todo", "todos", "los3", "los 3", "de todo"):
        return "combinado"

    presentes = [s for s in _SABORES_BASE if s in v or (s == "mani" and "man" in v)]
    if len(presentes) >= 3:
        return "combinado"
    if len(presentes) == 2:
        # Orden fijo para que coincida con las keys de RELLENOS_TITULOS
        presentes.sort(key=_SABORES_BASE.index)
        return "_".join(presentes)
    if len(presentes) == 1:
        return presentes[0]
    return None


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
    return [
        ("tam_mediano", "Mediano (S/ 3.00)"),
        ("tam_grande", "Grande (S/ 4.00)"),
        ("tam_relleno_extra", "Relleno Extra (S/ 5.00)"),
    ]


def _opciones_relleno():
    return [(f"rel_{r}", RELLENOS_TITULOS[r]) for r in RELLENOS]


def _pedir_tamano(unidad_actual, cantidad_total):
    return _botones(
        f"Maduro *{unidad_actual}/{cantidad_total}* — elige el tamaño:",
        _opciones_tamano(),
    )


def _pedir_relleno(unidad_actual, cantidad_total, tamano):
    nombre_tam = TAMANOS_TITULOS.get(tamano, tamano)
    return _lista(
        f"Maduro {unidad_actual}/{cantidad_total} ({nombre_tam}) — elige el relleno:",
        _opciones_relleno(),
        boton_texto="Elegir relleno",
    )


def _resumen_carrito(carrito):
    return "\n".join(
        f"- {TAMANOS_TITULOS.get(c['tamano'], c['tamano'])} {RELLENOS_TITULOS[c['relleno']]} (S/ {c['precio']:.2f})"
        for c in carrito
    )


def _detalle_agrupado(carrito, con_precios=True):
    """
    Junta los maduritos iguales (mismo tamaño + relleno) y devuelve un texto
    de varias líneas, tipo lista de cocina/despacho, ej.:
        2x Grande - Queso + Chicharrón — S/ 8.00
        1x Relleno Extra - Combinado (Queso + Maní + Chicharrón) — S/ 5.00
    Mucho más claro para el repartidor y para pedirle a la cocinera que
    "grande queso_chicharron, grande queso_chicharron, relleno_extra combinado".
    Con `con_precios=True` (para el repartidor) cada línea trae su subtotal,
    así sabe cuánto cobrar por cada grupo aunque el cliente pague por partes.
    """
    conteo = {}
    orden = []
    for c in carrito:
        clave = (c["tamano"], c["relleno"])
        if clave not in conteo:
            conteo[clave] = {"cantidad": 0, "precio_unit": c["precio"]}
            orden.append(clave)
        conteo[clave]["cantidad"] += 1
    lineas = []
    for tamano, relleno in orden:
        info = conteo[(tamano, relleno)]
        cantidad = info["cantidad"]
        nombre_tam = TAMANOS_TITULOS.get(tamano, tamano)
        nombre_rel = RELLENOS_TITULOS.get(relleno, relleno)
        linea = f"{cantidad}x {nombre_tam} - {nombre_rel}"
        if con_precios:
            subtotal = cantidad * info["precio_unit"]
            linea += f" — S/ {subtotal:.2f}"
        lineas.append(linea)
    return "\n".join(lineas)


_AGRADECIMIENTO_PALABRAS = {
    "gracias", "muchas gracias", "grac", "gracias!", "muchisimas gracias",
    "ok gracias", "genial", "perfecto", "excelente", "buenisimo", "de nada",
}


def _es_agradecimiento(texto: str) -> bool:
    v = _normalizar(texto or "")
    if v in _AGRADECIMIENTO_PALABRAS:
        return True
    return "gracias" in v and len(v) <= 40


MENU_INTRO = (
    "¡Hola{saludo}! Bienvenido a *Maduritos Asados* 🍌🔥\n\n"
    "*Carta:*\n"
    "- Mediano: S/ 3.00\n"
    "- Grande: S/ 4.00\n"
    "- Relleno Extra: S/ 5.00 🔥\n"
    "_Sabores: Queso, Maní, Chicharrón — o cualquier combinación entre ellos "
    "(2 sabores, o los 3 juntos), sin costo extra._\n\n"
    f"*Condición:* pedido mínimo de {PEDIDO_MINIMO_UNIDADES} unidades para delivery.\n\n"
    "_Escribe *cancelar* en cualquier momento para reiniciar tu pedido._"
)


def _opciones_cantidad():
    return [("cant_3", "3 unidades"), ("cant_5", "5 unidades"), ("cant_otra", "Otra cantidad")]


def _pedir_cantidad(nombre):
    msg = MENU_INTRO.format(saludo=f" {nombre}" if nombre else "") + "\n\n¿Cuántos maduritos en total deseas pedir?"
    return _botones(msg, _opciones_cantidad())


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

    # --- Sin sesión activa ---
    if sesion is None:
        # Si el cliente solo está agradeciendo/despidiéndose después de un
        # pedido ya confirmado, no lo metemos de nuevo al flujo de "cuántos
        # maduritos quieres" — respondemos amable y quedamos ahí.
        if texto and _es_agradecimiento(texto):
            return _texto(
                "¡Con gusto! 🍌 Tu pedido ya fue tomado y está en camino. "
                "Cualquier consulta, escríbenos por aquí."
            )
        _guardar_sesion(telefono, nombre, "esperando_cantidad")
        return _pedir_cantidad(nombre)

    paso = sesion["paso"]

    # --- Paso 1: cantidad total ---
    if paso == "esperando_cantidad":
        crudo = (texto or "").strip()
        valor = _valor_opcion(crudo, "cant_")
        opciones = _opciones_cantidad()

        if valor == "otra":
            return _texto("Escribe el número total de maduritos que deseas pedir.")

        cantidad = None
        if valor.isdigit():
            cantidad = int(valor)
        elif crudo.isdigit():
            cantidad = int(crudo)
        else:
            return _pedir_cantidad(nombre)

        # Corrección de ambigüedad: si un canal le muestra al cliente las
        # opciones numeradas en texto plano ("1. 3 unidades / 2. 5 unidades /
        # 3. Otra cantidad") y el cliente responde solo "1" pensando "elijo la
        # opción 1", eso llega aquí como el número 1 suelto. Como una cantidad
        # así de chica (menor al mínimo) de todas formas sería inválida por sí
        # sola, y coincide con la posición de una opción ofrecida, asumimos que
        # quiso decir "esa opción" en vez de rechazarlo como pedido inválido.
        if cantidad < PEDIDO_MINIMO_UNIDADES and 1 <= cantidad <= len(opciones):
            id_opcion = opciones[cantidad - 1][0]
            if id_opcion == "cant_otra":
                return _texto("Escribe el número total de maduritos que deseas pedir.")
            valor_opcion = _valor_opcion(id_opcion, "cant_")
            if valor_opcion.isdigit():
                cantidad = int(valor_opcion)

        if cantidad < PEDIDO_MINIMO_UNIDADES:
            resp = _pedir_cantidad(nombre)
            resp["texto"] = (
                f"El pedido mínimo para delivery es de {PEDIDO_MINIMO_UNIDADES} unidades. "
                f"¿Cuántos maduritos deseas pedir?"
            )
            return resp

        # Antes de armar el pedido, confirmamos el nombre del cliente (para que
        # el repartidor sepa a quién llamar y a quién entregarle) — usamos el
        # número de WhatsApp de siempre como número de contacto, no hace falta
        # pedirlo aparte.
        _guardar_sesion(telefono, nombre, "esperando_nombre", cantidad_total=cantidad, unidad_actual=1, carrito=[])
        return _texto("¿A nombre de quién anotamos el pedido? (para que el repartidor te llame al llegar)")

    # --- Paso 1b: nombre del cliente (para el repartidor) ---
    if paso == "esperando_nombre":
        nombre_cliente = (texto or "").strip()
        if not nombre_cliente:
            return _texto("¿A nombre de quién anotamos el pedido?")
        _guardar_sesion(
            telefono, nombre_cliente, "esperando_tamano",
            cantidad_total=sesion["cantidad_total"], unidad_actual=1, carrito=[],
        )
        return _pedir_tamano(1, sesion["cantidad_total"])

    # --- Paso 2a: tamaño del maduro actual ---
    if paso == "esperando_tamano":
        valor = _detectar_tamano(_resolver_por_posicion(texto, _opciones_tamano()))
        if not valor:
            resp = _pedir_tamano(sesion["unidad_actual"], sesion["cantidad_total"])
            resp["texto"] = "No entendí esa opción. " + resp["texto"]
            return resp
        _guardar_sesion(
            telefono, sesion["nombre"], "esperando_relleno",
            cantidad_total=sesion["cantidad_total"], unidad_actual=sesion["unidad_actual"],
            tamano_pendiente=valor, carrito=sesion["carrito"],
        )
        return _pedir_relleno(sesion["unidad_actual"], sesion["cantidad_total"], valor)

    # --- Paso 2b: relleno del maduro actual ---
    if paso == "esperando_relleno":
        valor = _detectar_relleno(_resolver_por_posicion(texto, _opciones_relleno()))
        if not valor:
            resp = _pedir_relleno(sesion["unidad_actual"], sesion["cantidad_total"], sesion["tamano_pendiente"])
            resp["texto"] = "No entendí ese relleno. " + resp["texto"]
            return resp

        tamano = sesion["tamano_pendiente"]
        carrito = sesion["carrito"] + [{"tamano": tamano, "relleno": valor, "precio": PRECIOS[tamano]}]
        siguiente_unidad = sesion["unidad_actual"] + 1
        cantidad_total = sesion["cantidad_total"]

        if siguiente_unidad <= cantidad_total:
            _guardar_sesion(
                telefono, sesion["nombre"], "esperando_tamano",
                cantidad_total=cantidad_total, unidad_actual=siguiente_unidad,
                carrito=carrito,
            )
            return _pedir_tamano(siguiente_unidad, cantidad_total)

        total = sum(c["precio"] for c in carrito)
        _guardar_sesion(
            telefono, sesion["nombre"], "esperando_confirmacion",
            cantidad_total=cantidad_total, unidad_actual=siguiente_unidad, carrito=carrito,
        )
        resumen = _resumen_carrito(carrito)
        return _botones(
            f"Tu pedido:\n{resumen}\n\n*Total: S/ {total:.2f}*\n\n¿Confirmas este pedido?",
            [("confirmar_pedido", "✅ Confirmar"), ("cancelar_pedido", "❌ Cancelar")],
        )

    # --- Paso 3: confirmación antes de pedir ubicación ---
    if paso == "esperando_confirmacion":
        opciones_confirmacion = [("confirmar_pedido", "✅ Confirmar"), ("cancelar_pedido", "❌ Cancelar")]
        decision = _detectar_confirmacion(_resolver_por_posicion(texto, opciones_confirmacion))
        if decision == "cancelar":
            _borrar_sesion(telefono)
            return _texto("Tu pedido fue cancelado. Escribe cualquier mensaje para empezar de nuevo. 🙂")
        if decision == "confirmar":
            _guardar_sesion(
                telefono, sesion["nombre"], "esperando_ubicacion",
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
                f"es de {RADIO_MAXIMO_KM} km. 😔\n\n"
                f"Mientras tanto puedes recogerlo tú mismo en nuestro local: {DIRECCION_LOCAL}. "
                f"¡Pronto llegaremos más lejos! Escribe cualquier mensaje si deseas intentar con otra dirección."
            )

        carrito = sesion["carrito"]
        cliente_nombre = sesion["nombre"] or nombre
        total_unidades = sesion["cantidad_total"]
        monto_total = sum(c["precio"] for c in carrito)
        detalle = _detalle_agrupado(carrito)

        with _lock:
            cursor.execute(
                """
                INSERT INTO pedidos
                    (telefono, cliente_nombre, detalle, total_unidades, monto_total, latitud, longitud, distancia_km)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (telefono, cliente_nombre, detalle, total_unidades, monto_total, lat, lon, round(distancia, 2)),
            )
            conn.commit()

        _borrar_sesion(telefono)
        return _texto(
            f"¡Pedido confirmado! ✅\n"
            f"{detalle}\n"
            f"Total: S/ {monto_total:.2f}\n"
            f"Distancia: {distancia:.1f} km\n\n"
            f"Gracias, {cliente_nombre}. Tu pedido está en camino. 🍌\n\n"
            f"_Si quieres agregar algo más, escríbelo y con gusto te ayudamos con un pedido nuevo._"
        )

    # Estado desconocido: reiniciar
    _borrar_sesion(telefono)
    return _pedir_cantidad(nombre)


def obtener_pedido(pedido_id: int):
    cursor.execute(
        "SELECT id, telefono, cliente_nombre, detalle, monto_total, estado FROM pedidos WHERE id = ?",
        (pedido_id,),
    )
    f = cursor.fetchone()
    if not f:
        return None
    return {
        "id": f[0], "telefono": f[1], "cliente_nombre": f[2],
        "detalle": f[3], "monto_total": f[4], "estado": f[5],
    }


def mensaje_entregado(cliente_nombre: str) -> str:
    """Mensaje de agradecimiento que se envía al cliente cuando el
    repartidor marca su pedido como 'Entregado'."""
    saludo = f"¡Gracias, {cliente_nombre}, " if cliente_nombre else "¡Gracias "
    return (
        f"{saludo}por disfrutar los ricos sabores de Maduritos Asados! 🍌🔥\n\n"
        f"No olvides que estamos todos los días en {DIRECCION_LOCAL}.\n\n"
        f"¡Pronto llegaremos más lejos y te esperamos de nuevo! 😊"
    )


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


def pedidos_detallados_periodo(periodo: str = "dia"):
    """Detalle fila por fila de los pedidos ENTREGADOS de un periodo (para exportar)."""
    condiciones = {
        "dia": "date(fecha) = date('now')",
        "semana": "date(fecha) >= date('now', '-6 days')",
        "mes": "strftime('%Y-%m', fecha) = strftime('%Y-%m', 'now')",
    }
    condicion = condiciones.get(periodo, condiciones["dia"])
    cursor.execute(
        f"""
        SELECT id, cliente_nombre, telefono, detalle, total_unidades, monto_total, fecha
        FROM pedidos WHERE estado = 'ENTREGADO' AND {condicion}
        ORDER BY fecha ASC
        """
    )
    filas = cursor.fetchall()
    return [
        {
            "id": f[0], "cliente_nombre": f[1] or "Sin nombre", "telefono": f[2],
            "detalle": f[3], "total_unidades": f[4], "monto_total": f[5], "fecha": f[6],
        }
        for f in filas
    ]


def generar_excel_reporte(periodo: str = "dia") -> bytes:
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    pedidos = pedidos_detallados_periodo(periodo)
    resumen = reporte_por_periodo(periodo)
    etiquetas = {"dia": "Hoy", "semana": "Últimos 7 días", "mes": "Este mes"}

    wb = Workbook()
    ws = wb.active
    ws.title = "Reporte de Caja"

    titulo_font = Font(name="Arial", size=14, bold=True, color="FFFFFF")
    titulo_fill = PatternFill("solid", fgColor="00A884")
    encabezado_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    encabezado_fill = PatternFill("solid", fgColor="2E7D32")

    ws.merge_cells("A1:F1")
    ws["A1"] = f"Maduritos Asados — Cierre de Caja ({etiquetas.get(periodo, periodo)})"
    ws["A1"].font = titulo_font
    ws["A1"].fill = titulo_fill
    ws["A1"].alignment = Alignment(horizontal="center")

    ws["A3"] = "Total recaudado (S/)"
    ws["B3"] = resumen["total_recaudado_soles"]
    ws["A4"] = "Maduritos vendidos"
    ws["B4"] = resumen["maduritos_vendidos"]
    ws["A5"] = "Pedidos entregados"
    ws["B5"] = resumen["pedidos_entregados"]
    for fila in (3, 4, 5):
        ws[f"A{fila}"].font = Font(name="Arial", bold=True)

    encabezados = ["ID", "Cliente", "Teléfono", "Detalle", "Maduritos", "Monto (S/)", "Fecha"]
    fila_encabezado = 7
    for col, titulo in enumerate(encabezados, start=1):
        celda = ws.cell(row=fila_encabezado, column=col, value=titulo)
        celda.font = encabezado_font
        celda.fill = encabezado_fill

    for i, p in enumerate(pedidos, start=fila_encabezado + 1):
        ws.cell(row=i, column=1, value=p["id"])
        ws.cell(row=i, column=2, value=p["cliente_nombre"])
        ws.cell(row=i, column=3, value=p["telefono"])
        ws.cell(row=i, column=4, value=p["detalle"])
        ws.cell(row=i, column=5, value=p["total_unidades"])
        ws.cell(row=i, column=6, value=p["monto_total"])
        ws.cell(row=i, column=7, value=p["fecha"])

    anchos = [6, 18, 16, 40, 11, 12, 20]
    for col, ancho in enumerate(anchos, start=1):
        ws.column_dimensions[chr(64 + col)].width = ancho

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.read()


def generar_pdf_reporte(periodo: str = "dia") -> bytes:
    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    pedidos = pedidos_detallados_periodo(periodo)
    resumen = reporte_por_periodo(periodo)
    etiquetas = {"dia": "Hoy", "semana": "Últimos 7 días", "mes": "Este mes"}

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    estilos = getSampleStyleSheet()
    elementos = []

    elementos.append(Paragraph(
        f"<b>Maduritos Asados</b> — Cierre de Caja ({etiquetas.get(periodo, periodo)})",
        estilos["Title"],
    ))
    elementos.append(Spacer(1, 12))
    elementos.append(Paragraph(
        f"Total recaudado: <b>S/ {resumen['total_recaudado_soles']:.2f}</b> &nbsp;&nbsp; "
        f"Maduritos vendidos: <b>{resumen['maduritos_vendidos']}</b> &nbsp;&nbsp; "
        f"Pedidos entregados: <b>{resumen['pedidos_entregados']}</b>",
        estilos["Normal"],
    ))
    elementos.append(Spacer(1, 16))

    datos = [["ID", "Cliente", "Teléfono", "Detalle", "Uds", "Monto", "Fecha"]]
    for p in pedidos:
        datos.append([
            str(p["id"]), p["cliente_nombre"], p["telefono"],
            Paragraph(p["detalle"], estilos["Normal"]),
            str(p["total_unidades"]), f"S/ {p['monto_total']:.2f}", p["fecha"],
        ])

    tabla = Table(datos, colWidths=[1.3 * cm, 3 * cm, 2.8 * cm, 6.5 * cm, 1.3 * cm, 2.2 * cm, 3 * cm], repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E7D32")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
    ]))
    elementos.append(tabla)

    doc.build(elementos)
    buffer.seek(0)
    return buffer.read()


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
