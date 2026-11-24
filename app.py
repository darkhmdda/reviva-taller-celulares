"""Reviva: Taller de Celulares - Sistema de Control de Recepción, Diagnóstico y Seguimiento.

Estructura inicial (Fase 1). Ejecutar:  python app.py
"""
import csv
import hashlib
import hmac
import io
import math
import os
import re
import secrets
import sqlite3
import tempfile
import time
import unicodedata
import urllib.parse
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta
from functools import wraps

import qrcode
from flask import (Flask, Response, abort, flash, g, redirect, render_template, request,
                   send_file, send_from_directory, session, url_for)
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen import canvas as pdf_canvas
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Motor de base de datos: "mysql" (por defecto: XAMPP, MySQL/MariaDB + phpMyAdmin) o "sqlite" (DB_ENGINE=sqlite).
MOTOR = os.environ.get("DB_ENGINE", "mysql").strip().lower()
if MOTOR == "mysql":
    import db_mysql
    ERRORES_INTEGRIDAD = (sqlite3.IntegrityError, db_mysql.IntegrityError)
else:
    db_mysql = None
    ERRORES_INTEGRIDAD = (sqlite3.IntegrityError,)
DB_PATH = os.path.join(BASE_DIR, "database", "taller.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "database", "schema_mysql.sql" if MOTOR == "mysql" else "schema.sql")
RESPALDOS_DIR = os.path.join(BASE_DIR, "database", "respaldos")

ESTADOS = ["Recibido", "En Diagnóstico", "En Reparación", "Listo", "Entregado"]

def cargar_secret_key():
    """Clave secreta desde la variable SECRET_KEY o, si no existe, un archivo local generado una vez."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    ruta = os.path.join(BASE_DIR, "database", ".secret_key")
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    if not os.path.exists(ruta):
        with open(ruta, "w") as f:
            f.write(secrets.token_hex(32))
        try:
            os.chmod(ruta, 0o600)
        except OSError:
            pass
    with open(ruta) as f:
        return f.read().strip()


app = Flask(__name__)
app.config["SECRET_KEY"] = cargar_secret_key()
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=int(os.environ.get("SESSION_MINUTOS", "30")))
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["CSRF_ACTIVADO"] = True

# Rutas del portal público que ya se protegen con su propio código firmado (HMAC) o límite de intentos.
EXENTAS_CSRF = {"seguimiento_verificar", "seguimiento_presupuesto", "seguimiento_resena"}


def csrf_token():
    """Token por sesión que viaja en un campo oculto de cada formulario POST."""
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def proteger_csrf():
    if request.method != "POST" or not app.config["CSRF_ACTIVADO"] or request.endpoint in EXENTAS_CSRF:
        return None
    enviado = request.form.get("csrf_token", "")
    if enviado and hmac.compare_digest(enviado, session.get("csrf", "")):
        return None
    if "usuario_id" not in session or request.endpoint == "login":
        flash("La página expiró. Inicia sesión de nuevo e inténtalo otra vez.")
        return redirect(url_for("login"))
    abort(400)


@app.after_request
def cabeceras_seguridad(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if resp.mimetype == "text/html":
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; form-action 'self'")
        if "usuario_id" in session:
            resp.headers["Cache-Control"] = "no-store"  # tras cerrar sesión, «atrás» no muestra datos
    return resp


@app.template_filter("slug")
def slug(texto):
    """'En Diagnóstico' -> 'en-diagnostico' (para clases CSS)."""
    sin_acentos = unicodedata.normalize("NFD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sin_acentos.lower()).strip("-")


@app.context_processor
def inyectar_navegacion():
    """Variables para la plantilla base: sección activa y destino del botón «Volver»."""
    destino = url_for("kanban")
    ref = request.referrer
    if ref:
        p = urllib.parse.urlparse(ref)
        if p.netloc == request.host and p.path != request.path and p.path not in ("/recepcion", "/login", "/logout"):
            destino = p.path + (f"?{p.query}" if p.query else "")
    return {"volver_url": destino, "ruta_actual": request.endpoint}


# ---------------- Base de datos ----------------
def normalizar(texto):
    """Minúsculas y sin acentos: 'Pérez' -> 'perez' (búsquedas tolerantes)."""
    if texto is None:
        return ""
    return unicodedata.normalize("NFD", str(texto)).encode("ascii", "ignore").decode().lower()


def get_db():
    if "db" not in g:
        if MOTOR == "mysql":
            g.db = db_mysql.conectar()
        else:
            g.db = sqlite3.connect(DB_PATH)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
            g.db.create_function("norm", 1, normalizar, deterministic=True)
    return g.db


def registrar(db, orden_id, accion, usuario_id=None, actor=None):
    """Anota en la bitácora de la orden quién hizo qué (se llama dentro de un `with db:`)."""
    if actor is None:
        fila = db.execute("SELECT nombre FROM usuarios WHERE id = ?", (usuario_id,)).fetchone() if usuario_id else None
        actor = fila["nombre"] if fila else "Sistema"
    db.execute("INSERT INTO bitacora (orden_id, usuario_id, actor, accion) VALUES (?, ?, ?, ?)",
               (orden_id, usuario_id, actor, accion))


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def migrar(db):
    """Agrega columnas nuevas a bases SQLite creadas con versiones anteriores."""
    if MOTOR == "mysql":
        return
    cols = {r[1] for r in db.execute("PRAGMA table_info(ordenes)")}
    if "fecha_promesa" not in cols:
        db.execute("ALTER TABLE ordenes ADD COLUMN fecha_promesa TEXT")


def init_db():
    """Crea las tablas y un usuario admin inicial si no existe."""
    if MOTOR == "mysql":
        db_mysql.inicializar(SCHEMA_PATH)
        db = db_mysql.conectar()
    else:
        db = sqlite3.connect(DB_PATH)
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            db.executescript(f.read())
    migrar(db)
    existe = db.execute("SELECT 1 FROM usuarios WHERE rol = 'admin' LIMIT 1").fetchone()
    if not existe:
        db.execute(
            "INSERT INTO usuarios (nombre, email, password_hash, rol) VALUES (?, ?, ?, 'admin')",
            ("Administrador", "admin@taller.local", generate_password_hash("admin123")),
        )
    db.commit()
    db.close()


# ---------------- Autenticación y roles ----------------
def login_required(rol=None):
    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            if "usuario_id" not in session:
                return redirect(url_for("login"))
            activo = get_db().execute(
                "SELECT activo FROM usuarios WHERE id = ?", (session["usuario_id"],)
            ).fetchone()
            if not activo or not activo["activo"]:
                session.clear()
                flash("Tu usuario está desactivado.")
                return redirect(url_for("login"))
            if rol and session.get("rol") != rol:
                flash("No tienes permiso para acceder a esta sección.")
                return redirect(url_for("kanban"))
            return vista(*args, **kwargs)
        return envoltura
    return decorador


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        ip = request.remote_addr
        if bloqueado(("login", email)) or bloqueado(("login-ip", ip), maximo=20):
            flash("Demasiados intentos fallidos. Espera 10 minutos e inténtalo de nuevo.")
            return render_template("login.html"), 429
        user = get_db().execute("SELECT * FROM usuarios WHERE email = ? AND activo = 1", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            _fallos.pop(("login", email), None)
            session.clear()
            session.permanent = True  # expira tras SESSION_MINUTOS de inactividad
            session.update(usuario_id=user["id"], nombre=user["nombre"], rol=user["rol"],
                           pass_default=(password == "admin123"))
            return redirect(url_for("kanban"))
        registrar_fallo(("login", email))
        registrar_fallo(("login-ip", ip))
        flash("Credenciales incorrectas.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))



# ---------------- Fase 2: Recepción ----------------
CHECKLIST = [
    ("chk_pantalla_estrellada", "Pantalla estrellada"),
    ("chk_tapa_rota", "Tapa rota"),
    ("chk_equipo_mojado", "Equipo mojado"),
    ("chk_sin_bandeja_sim", "Sin bandeja SIM"),
]


def generar_folio(db):
    prefijo = f"TC-{datetime.now():%Y%m%d}-"
    n = db.execute("SELECT COUNT(*) FROM ordenes WHERE folio LIKE ?", (prefijo + "%",)).fetchone()[0]
    return f"{prefijo}{n + 1:04d}"


@app.route("/recepcion", methods=["GET", "POST"])
@login_required()
def recepcion():
    if request.method == "GET":
        return render_template("recepcion.html", datos={}, checklist=CHECKLIST)

    f = request.form
    nombre = f.get("nombre", "").strip()
    telefono = re.sub(r"\D", "", f.get("telefono", ""))
    imei = re.sub(r"\D", "", f.get("imei", ""))
    marca, modelo = f.get("marca", "").strip(), f.get("modelo", "").strip()
    color = f.get("color", "").strip() or None
    falla = f.get("falla", "").strip()
    patron = f.get("patron", "").strip()
    pin = f.get("pin", "").strip()

    errores = []
    if not nombre:
        errores.append("El nombre del cliente es obligatorio.")
    if len(telefono) < 10:
        errores.append("El teléfono debe tener al menos 10 dígitos.")
    if not 14 <= len(imei) <= 16:
        errores.append("El IMEI es obligatorio y debe tener entre 14 y 16 dígitos.")
    if not marca or not modelo:
        errores.append("Marca y modelo son obligatorios.")
    if not falla:
        errores.append("Describe la falla reportada.")
    if patron and not re.fullmatch(r"[1-9](-[1-9]){3,8}", patron):
        errores.append("El patrón de desbloqueo debe tener entre 4 y 9 puntos.")
    if errores:
        for e in errores:
            flash(e)
        return render_template("recepcion.html", datos=f, checklist=CHECKLIST), 400

    db = get_db()
    with db:
        cli = db.execute("SELECT id FROM clientes WHERE telefono = ?", (telefono,)).fetchone()
        if cli:
            cliente_id = cli["id"]
        else:
            cliente_id = db.execute(
                "INSERT INTO clientes (nombre, telefono) VALUES (?, ?)", (nombre, telefono)
            ).lastrowid

        eq = db.execute("SELECT id FROM equipos WHERE imei = ?", (imei,)).fetchone()
        if eq:
            equipo_id = eq["id"]
            db.execute(
                "UPDATE equipos SET cliente_id=?, color=?, patron_desbloqueo=?, pin_desbloqueo=? WHERE id=?",
                (cliente_id, color, patron or None, pin or None, equipo_id),
            )
        else:
            equipo_id = db.execute(
                "INSERT INTO equipos (imei, marca, modelo, color, cliente_id, patron_desbloqueo, pin_desbloqueo)"
                " VALUES (?,?,?,?,?,?,?)",
                (imei, marca, modelo, color, cliente_id, patron or None, pin or None),
            ).lastrowid

        avisos = garantias_vigentes(db, equipo_id)
        folio = generar_folio(db)
        chk = {campo: 1 if f.get(campo) else 0 for campo, _ in CHECKLIST}
        orden_id = db.execute(
            """INSERT INTO ordenes (folio, equipo_id, recibido_por, falla_reportada,
                   chk_pantalla_estrellada, chk_tapa_rota, chk_equipo_mojado, chk_sin_bandeja_sim,
                   observaciones_fisicas)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (folio, equipo_id, session["usuario_id"], falla,
             chk["chk_pantalla_estrellada"], chk["chk_tapa_rota"],
             chk["chk_equipo_mojado"], chk["chk_sin_bandeja_sim"],
             f.get("observaciones", "").strip() or None),
        ).lastrowid
        db.execute(
            "INSERT INTO historial_estados (orden_id, estado, usuario_id) VALUES (?, 'Recibido', ?)",
            (orden_id, session["usuario_id"]),
        )
        registrar(db, orden_id, "Orden creada en recepción", session["usuario_id"])
        _, avisos_fotos = guardar_fotos(db, orden_id, request.files.getlist("fotos"), session["usuario_id"])
    for a in avisos_fotos:
        flash(a)
    for folio_previo, vence in avisos:
        flash(f"⚠️ Este equipo tiene garantía vigente por la orden {folio_previo} "
              f"(vence el {vence:%d/%m/%Y}). Verifica si la falla está cubierta.")
    return redirect(url_for("orden_creada", folio=folio))


@app.route("/orden/<folio>")
@login_required()
def orden_creada(folio):
    orden = obtener_orden(folio)
    return render_template("orden_creada.html", o=orden)


def obtener_orden(folio):
    fila = get_db().execute(
        """SELECT o.*, e.imei, e.marca, e.modelo, e.patron_desbloqueo, e.pin_desbloqueo,
                  c.nombre AS cliente, c.telefono, u.nombre AS tecnico,
                  (SELECT COALESCE(SUM(monto), 0) FROM pagos WHERE orden_id = o.id) AS pagado
           FROM ordenes o
           JOIN equipos e ON e.id = o.equipo_id
           JOIN clientes c ON c.id = e.cliente_id
           LEFT JOIN usuarios u ON u.id = o.tecnico_id
           WHERE o.folio = ?""",
        (folio,),
    ).fetchone()
    if fila is None:
        abort(404)
    return fila


def url_seguimiento(folio):
    base = os.environ.get("BASE_URL") or request.host_url
    return f"{base.rstrip('/')}{url_for('seguimiento', folio=folio)}?t={token_folio(folio)}"


LOGO_TICKET = os.path.join(BASE_DIR, "static", "img", "isotipo_ticket.png")


def dibujar_logo(c, ancho, y, tam=40):
    """Dibuja el isotipo de Reviva centrado en la parte superior del ticket o recibo."""
    try:
        c.drawImage(ImageReader(LOGO_TICKET), (ancho - tam) / 2, y - tam, tam, tam * 0.96, mask="auto")
    except Exception:  # si falta el archivo, el comprobante se genera igual
        pass


@app.route("/ticket/<folio>/pdf")
@login_required()
def ticket_pdf(folio):
    o = obtener_orden(folio)
    url = url_seguimiento(folio)

    qr = qrcode.QRCode(box_size=8, border=1)
    qr.add_data(url)
    qr.make(fit=True)
    qr_buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(qr_buf, format="PNG")
    qr_buf.seek(0)

    ancho, alto = 226, 515  # ~80 mm de ancho (impresora térmica)
    margen = 12
    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=(ancho, alto))
    y = alto - 14
    dibujar_logo(c, ancho, y)
    y -= 52

    def centrado(texto, fuente="Helvetica", tam=9):
        nonlocal y
        c.setFont(fuente, tam)
        c.drawCentredString(ancho / 2, y, texto)
        y -= tam + 4

    def linea(texto, fuente="Helvetica", tam=8):
        nonlocal y
        c.setFont(fuente, tam)
        for parte in simpleSplit(texto, fuente, tam, ancho - 2 * margen):
            c.drawString(margen, y, parte)
            y -= tam + 3

    centrado("REVIVA: TALLER DE CELULARES", "Helvetica-Bold", 12)
    centrado("Comprobante de recepción", "Helvetica", 8)
    y -= 4
    centrado(o["folio"], "Helvetica-Bold", 13)
    centrado(datetime.strptime(o["fecha_ingreso"], "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M"), "Helvetica", 8)
    y -= 4
    linea(f"Cliente: {o['cliente']}", "Helvetica-Bold")
    linea(f"Tel: {o['telefono']}")
    linea(f"Equipo: {o['marca']} {o['modelo']}")
    linea(f"IMEI: {o['imei']}")
    linea(f"Falla: {o['falla_reportada']}")
    marcados = [txt for campo, txt in CHECKLIST if o[campo]]
    linea("Estado físico: " + (", ".join(marcados) if marcados else "Sin daños reportados"))
    if o["observaciones_fisicas"]:
        linea(f"Obs: {o['observaciones_fisicas']}")
    y -= 6
    tam_qr = 110
    c.drawImage(ImageReader(qr_buf), (ancho - tam_qr) / 2, y - tam_qr, tam_qr, tam_qr)
    y -= tam_qr + 10
    centrado("Escanea para consultar tu equipo", "Helvetica", 7)
    for parte in simpleSplit(url, "Helvetica", 6, ancho - 2 * margen):
        centrado(parte, "Helvetica", 6)
    centrado("Sin QR: consulta con tu folio y tu teléfono.", "Helvetica", 6)
    y -= 4
    centrado("Conserva este comprobante para recoger tu equipo.", "Helvetica", 6)
    c.showPage()
    c.save()
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf", download_name=f"{folio}.pdf")


# ---------------- Fase 3: flujo técnico, inventario y WhatsApp ----------------
CATEGORIAS = ["Batería", "Centro de carga", "Pantalla", "Otro"]


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def leer_numero(valor, tipo=float):
    """Convierte texto a número >= 0; devuelve None si es inválido."""
    try:
        n = tipo((valor or "0").strip().replace(",", "") or 0)
    except ValueError:
        return None
    return n if n >= 0 else None


def destino_seguro(valor):
    if valor and valor.startswith("/") and not valor.startswith("//"):
        return valor
    return url_for("kanban")


def verificar_acceso(o):
    """Admin ve todo; técnico solo órdenes asignadas a él o sin asignar."""
    if session["rol"] != "admin" and o["tecnico_id"] not in (None, session["usuario_id"]):
        abort(403)


def telefono_whatsapp(tel):
    d = re.sub(r"\D", "", tel)
    return "52" + d if len(d) == 10 else d


PLANTILLAS_BASE = {
    "Recibido": "Hola {nombre}, en Reviva recibimos tu {equipo}. Tu folio es {folio}.{promesa}\nSeguimiento: {enlace}",
    "En Diagnóstico": "Hola {nombre}, tu {equipo} (folio {folio}) está en diagnóstico.{presupuesto}{promesa}\nSeguimiento: {enlace}",
    "En Reparación": "Hola {nombre}, tu {equipo} (folio {folio}) ya está en reparación.{promesa}\nSeguimiento: {enlace}",
    "Listo": "Hola {nombre}, ¡tu {equipo} (folio {folio}) ya está listo para recoger!{saldo}\nSeguimiento: {enlace}",
    "Entregado": "Hola {nombre}, gracias por confiar en Reviva. Entregamos tu {equipo} (folio {folio}).\nSeguimiento: {enlace}",
}
VARIABLES_PLANTILLA = [
    ("{nombre}", "Primer nombre del cliente"),
    ("{equipo}", "Marca y modelo"),
    ("{folio}", "Folio de la orden"),
    ("{enlace}", "Enlace de seguimiento del portal"),
    ("{total}", "Total del presupuesto (ej. $850.00)"),
    ("{presupuesto}", "Frase automática con el presupuesto, solo si está pendiente"),
    ("{promesa}", "Frase con la fecha prometida de entrega, si existe"),
    ("{saldo}", "Frase con el saldo pendiente, si lo hay"),
]


def plantillas_actuales():
    if "plantillas" not in g:
        textos = dict(PLANTILLAS_BASE)
        for fila in get_db().execute("SELECT estado, texto FROM plantillas"):
            if fila["estado"] in textos and fila["texto"].strip():
                textos[fila["estado"]] = fila["texto"]
        g.plantillas = textos
    return g.plantillas


def campo(o, nombre, defecto=None):
    try:
        v = o[nombre]
    except (KeyError, IndexError):
        return defecto
    return defecto if v is None else v


def total_orden(o):
    return (campo(o, "costo_refaccion", 0) or 0) + (campo(o, "mano_obra", 0) or 0)


def saldo_de(o):
    """Saldo por cobrar: solo existe cuando el presupuesto fue aprobado."""
    if campo(o, "presupuesto_estado") != "Aprobado":
        return 0.0
    return max(round(total_orden(o) - (campo(o, "pagado", 0) or 0), 2), 0.0)


def fecha_larga(texto):
    try:
        return datetime.strptime(texto, "%Y-%m-%d").strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return ""


def url_whatsapp(o):
    """Enlace wa.me con el mensaje de la plantilla editable de la etapa actual."""
    total = total_orden(o)
    presupuesto = ""
    if o["estado"] == "En Diagnóstico" and o["presupuesto_estado"] == "Pendiente" and total > 0:
        presupuesto = f" El presupuesto es de ${total:,.2f}. Puedes autorizarlo o rechazarlo en el enlace."
    promesa = ""
    if campo(o, "fecha_promesa") and o["estado"] not in ("Listo", "Entregado"):
        promesa = f" Fecha estimada de entrega: {fecha_larga(o['fecha_promesa'])}."
    saldo = saldo_de(o)
    valores = {
        "nombre": (o["cliente"].split() or ["cliente"])[0],
        "equipo": f"{o['marca']} {o['modelo']}",
        "folio": o["folio"],
        "enlace": url_seguimiento(o["folio"]),
        "total": f"${total:,.2f}",
        "presupuesto": presupuesto,
        "promesa": promesa,
        "saldo": f" Saldo por pagar: ${saldo:,.2f}." if saldo > 0 else "",
    }
    msg = re.sub(r"\{(\w+)\}", lambda m: valores.get(m.group(1), m.group(0)), plantillas_actuales()[o["estado"]])
    return f"https://wa.me/{telefono_whatsapp(o['telefono'])}?text={urllib.parse.quote(msg)}"


def semaforo(o):
    """Devuelve (clase, texto) según la fecha prometida, o (None, '') si no aplica."""
    if o["estado"] in ("Listo", "Entregado") or not campo(o, "fecha_promesa"):
        return None, ""
    try:
        dias = (datetime.strptime(o["fecha_promesa"], "%Y-%m-%d").date() - datetime.now().date()).days
    except ValueError:
        return None, ""
    if dias < 0:
        return "vencida", f"Vencida hace {-dias} d"
    if dias == 0:
        return "hoy", "Se promete hoy"
    if dias == 1:
        return "proxima", "Mañana"
    return "enplazo", f"En {dias} d"


DIAS_ESTANCADA = 3


def estancada(o):
    if o["estado"] in ("Listo", "Entregado"):
        return False
    try:
        ult = datetime.strptime(o["actualizado_en"], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, KeyError):
        return False
    return (datetime.now() - ult).days >= DIAS_ESTANCADA


def transicion_valida(o, nuevo):
    actual = o["estado"]
    if actual == "Entregado" or nuevo not in ESTADOS or nuevo == actual:
        return False
    if abs(ESTADOS.index(actual) - ESTADOS.index(nuevo)) == 1:
        return True
    # Presupuesto rechazado: el equipo se devuelve sin reparar
    return actual == "En Diagnóstico" and nuevo == "Listo" and o["presupuesto_estado"] == "Rechazado"


def descontar_stock(db, o):
    """Descuenta 1 pieza una sola vez por orden. Devuelve (ok, mensaje)."""
    if not o["refaccion_id"] or o["stock_descontado"]:
        return True, ""
    cur = db.execute(
        "UPDATE refacciones SET stock = stock - 1 WHERE id = ? AND stock > 0", (o["refaccion_id"],)
    )
    if cur.rowcount == 0:
        return False, "no hay stock de la refacción seleccionada; reabastece el inventario."
    db.execute("UPDATE ordenes SET stock_descontado = 1 WHERE id = ?", (o["id"],))
    registrar(db, o["id"], "Se descontó 1 pieza del inventario", actor="Sistema")
    return True, ""


def cambiar_estado(db, o, nuevo, usuario_id, forzar=False):
    """Aplica un cambio de estado validando reglas. Devuelve (ok, mensaje)."""
    if not transicion_valida(o, nuevo):
        return False, f"No se puede pasar de «{o['estado']}» a «{nuevo}»."
    if nuevo == "En Reparación":
        if o["presupuesto_estado"] != "Aprobado":
            return False, "El cliente debe aprobar el presupuesto antes de iniciar la reparación."
        ok, msg = descontar_stock(db, o)
        if not ok:
            return False, f"No se puede iniciar: {msg}"
    if nuevo == "Entregado" and saldo_de(o) > 0:
        if not forzar:
            return False, f"Hay un saldo pendiente de ${saldo_de(o):,.2f}. Registra el pago antes de entregar."
        registrar(db, o["id"], f"Entregó con saldo pendiente de ${saldo_de(o):,.2f} (autorizado por administrador)", usuario_id)
    sets, params = "estado = ?, actualizado_en = ?", [nuevo, ahora()]
    if nuevo == "Entregado":
        sets += ", fecha_entrega = ?"
        params.append(ahora())
        if o["presupuesto_estado"] != "Aprobado":
            sets += ", garantia_dias = 0"  # no hubo reparación, no hay garantía
    db.execute(f"UPDATE ordenes SET {sets} WHERE id = ?", params + [o["id"]])
    db.execute(
        "INSERT INTO historial_estados (orden_id, estado, usuario_id) VALUES (?, ?, ?)",
        (o["id"], nuevo, usuario_id),
    )
    return True, f"Orden {o['folio']} movida a «{nuevo}»."


def resolver_presupuesto(db, o, aprobar, usuario_id=None):
    """Aprueba o rechaza el presupuesto. Reutilizable por el portal del cliente (Fase 4)."""
    if o["presupuesto_estado"] != "Pendiente":
        return False, "El presupuesto ya fue resuelto."
    if o["estado"] != "En Diagnóstico":
        return False, "El presupuesto solo se resuelve cuando el equipo está en «En Diagnóstico»."
    if aprobar and (o["costo_refaccion"] + o["mano_obra"]) <= 0:
        return False, "Captura el presupuesto antes de aprobarlo."
    nuevo = "Aprobado" if aprobar else "Rechazado"
    db.execute(
        "UPDATE ordenes SET presupuesto_estado = ?, presupuesto_fecha = ?, actualizado_en = ? WHERE id = ?",
        (nuevo, ahora(), ahora(), o["id"]),
    )
    if usuario_id is None:
        registrar(db, o["id"], f"Presupuesto {nuevo.lower()} por el cliente desde el portal", actor="Cliente (portal)")
    else:
        registrar(db, o["id"], f"Registró el presupuesto como {nuevo.lower()} (respuesta del cliente en mostrador)", usuario_id)
    if not aprobar:
        return True, "Presupuesto rechazado. El equipo puede devolverse sin reparar."
    if not o["refaccion_id"]:
        return True, "Presupuesto aprobado."
    ok, msg = descontar_stock(db, o)
    if ok:
        return True, "Presupuesto aprobado. Se descontó 1 pieza del inventario."
    return True, f"Presupuesto aprobado, pero {msg}"


@app.route("/")
@login_required()
def kanban():
    db = get_db()
    condiciones = ["NOT (o.estado = 'Entregado' AND o.fecha_entrega < datetime('now','localtime','-7 days'))"]
    params = []
    if session["rol"] != "admin":
        condiciones.append("(o.tecnico_id IS NULL OR o.tecnico_id = ?)")
        params.append(session["usuario_id"])
    filas = db.execute(
        f"""SELECT o.id, o.folio, o.estado, o.falla_reportada, o.presupuesto_estado,
                   o.costo_refaccion, o.mano_obra, o.fecha_promesa, o.actualizado_en,
                   (SELECT COALESCE(SUM(monto), 0) FROM pagos WHERE orden_id = o.id) AS pagado,
                   c.nombre AS cliente, c.telefono,
                   e.marca, e.modelo, e.imei, u.nombre AS tecnico
            FROM ordenes o
            JOIN equipos e ON e.id = o.equipo_id
            JOIN clientes c ON c.id = e.cliente_id
            LEFT JOIN usuarios u ON u.id = o.tecnico_id
            WHERE {' AND '.join(condiciones)}
            ORDER BY o.fecha_ingreso DESC""",
        params,
    ).fetchall()
    columnas = {e: [] for e in ESTADOS}
    for fila in filas:
        d = dict(fila)
        d["wa"] = url_whatsapp(d)
        d["semaforo"], d["semaforo_texto"] = semaforo(d)
        d["estancada"] = estancada(d)
        d["saldo"] = saldo_de(d)
        i = ESTADOS.index(d["estado"])
        d["siguiente"] = ESTADOS[i + 1] if i < len(ESTADOS) - 1 else None
        columnas[d["estado"]].append(d)
    stock_bajo = db.execute("SELECT COUNT(*) FROM v_stock_bajo").fetchone()[0]
    return render_template("kanban.html", columnas=columnas, stock_bajo=stock_bajo)


@app.route("/orden/<folio>/detalle")
@login_required()
def orden_detalle(folio):
    o = obtener_orden(folio)
    verificar_acceso(o)
    db = get_db()
    es_admin = session["rol"] == "admin"
    refacciones = db.execute(
        "SELECT id, nombre, categoria, stock, precio_venta FROM refacciones WHERE activo = 1 ORDER BY categoria, nombre"
    ).fetchall()
    historial = []
    for b in db.execute("SELECT id, accion, fecha, actor FROM bitacora WHERE orden_id = ?", (o["id"],)):
        historial.append({"fecha": b["fecha"], "prio": 0, "id": b["id"], "texto": b["accion"], "quien": b["actor"]})
    for h in db.execute(
        """SELECT h.id, h.estado, h.fecha, u.nombre AS usuario FROM historial_estados h
           LEFT JOIN usuarios u ON u.id = h.usuario_id WHERE h.orden_id = ?""", (o["id"],)
    ):
        historial.append({"fecha": h["fecha"], "prio": 1, "id": h["id"], "texto": f"Cambió el estado a «{h['estado']}»",
                          "quien": h["usuario"] or "Sistema"})
    historial.sort(key=lambda e: (e["fecha"], e["prio"], e["id"]))
    pagos = db.execute(
        """SELECT p.*, u.nombre AS quien FROM pagos p LEFT JOIN usuarios u ON u.id = p.usuario_id
           WHERE p.orden_id = ? ORDER BY p.fecha, p.id""", (o["id"],)).fetchall()
    notas = db.execute("SELECT * FROM notas WHERE orden_id = ? ORDER BY fecha DESC, id DESC", (o["id"],)).fetchall()
    fotos = db.execute("SELECT id, fecha FROM fotos WHERE orden_id = ? ORDER BY id", (o["id"],)).fetchall()
    sem, sem_texto = semaforo(o)
    tecnicos = db.execute(
        "SELECT id, nombre FROM usuarios WHERE rol = 'tecnico' AND activo = 1 ORDER BY nombre"
    ).fetchall() if es_admin else []
    total = o["costo_refaccion"] + o["mano_obra"]
    return render_template(
        "orden_detalle.html", o=o, refacciones=refacciones, historial=historial, tecnicos=tecnicos,
        marcados=[txt for campo, txt in CHECKLIST if o[campo]],
        destinos=[e for e in ESTADOS if transicion_valida(o, e)],
        editable=o["presupuesto_estado"] != "Aprobado" and o["estado"] in ("Recibido", "En Diagnóstico"),
        total=total, margen=total - o["costo_proveedor"], wa=url_whatsapp(o), portal=url_seguimiento(folio),
        pagos=pagos, notas=notas, fotos=fotos, max_fotos=MAX_FOTOS_ORDEN, saldo=saldo_de(o), semaforo=sem, semaforo_texto=sem_texto,
        estancada=estancada(o), hoy=datetime.now().strftime("%Y-%m-%d"),
    )


@app.route("/orden/<folio>/estado", methods=["POST"])
@login_required()
def cambiar_estado_vista(folio):
    o = obtener_orden(folio)
    verificar_acceso(o)
    db = get_db()
    with db:
        ok, msg = cambiar_estado(db, o, request.form.get("estado", ""), session["usuario_id"],
                                 forzar=session["rol"] == "admin" and bool(request.form.get("forzar")))
        if ok and session["rol"] == "tecnico" and o["tecnico_id"] is None:
            db.execute("UPDATE ordenes SET tecnico_id = ? WHERE id = ?", (session["usuario_id"], o["id"]))
    flash(msg)
    return redirect(destino_seguro(request.form.get("volver")))


# ---------------- Tanda 3: fotos del equipo ----------------
MAX_FOTOS_ORDEN = 8
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024


def carpeta_fotos():
    d = os.path.join(os.path.dirname(DB_PATH), "fotos")
    os.makedirs(d, exist_ok=True)
    return d


def guardar_fotos(db, orden_id, archivos, usuario_id):
    """Valida, reduce y guarda las fotos (siempre como JPEG nuevo). Devuelve (guardadas, avisos)."""
    from PIL import Image, ImageOps
    existentes = db.execute("SELECT COUNT(*) FROM fotos WHERE orden_id = ?", (orden_id,)).fetchone()[0]
    guardadas, avisos = 0, []
    for archivo in archivos:
        if not archivo or not archivo.filename:
            continue
        if existentes + guardadas >= MAX_FOTOS_ORDEN:
            avisos.append(f"Máximo {MAX_FOTOS_ORDEN} fotos por orden.")
            break
        try:
            img = Image.open(archivo.stream)
            img.load()
            img = ImageOps.exif_transpose(img).convert("RGB")
        except Exception:
            avisos.append(f"«{archivo.filename}» no es una imagen válida.")
            continue
        img.thumbnail((1400, 1400))
        nombre = secrets.token_hex(12) + ".jpg"
        img.save(os.path.join(carpeta_fotos(), nombre), "JPEG", quality=82, optimize=True)
        db.execute("INSERT INTO fotos (orden_id, archivo, usuario_id) VALUES (?,?,?)", (orden_id, nombre, usuario_id))
        guardadas += 1
    if guardadas:
        registrar(db, orden_id, f"Agregó {guardadas} foto(s) del equipo", usuario_id)
    return guardadas, avisos


@app.route("/orden/<folio>/fotos", methods=["POST"])
@login_required()
def subir_fotos(folio):
    o = obtener_orden(folio)
    verificar_acceso(o)
    db = get_db()
    with db:
        n, avisos = guardar_fotos(db, o["id"], request.files.getlist("fotos"), session["usuario_id"])
    for a in avisos:
        flash(a)
    if n:
        flash(f"{n} foto(s) guardada(s).")
    elif not avisos:
        flash("Elige al menos una foto.")
    return redirect(url_for("orden_detalle", folio=folio) + "#fotos")


@app.route("/foto/<int:fid>")
@login_required()
def ver_foto(fid):
    fila = get_db().execute(
        "SELECT f.archivo, o.folio FROM fotos f JOIN ordenes o ON o.id = f.orden_id WHERE f.id = ?", (fid,)).fetchone()
    if not fila:
        abort(404)
    verificar_acceso(obtener_orden(fila["folio"]))
    resp = send_from_directory(carpeta_fotos(), fila["archivo"], mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@app.route("/foto/<int:fid>/eliminar", methods=["POST"])
@login_required("admin")
def eliminar_foto(fid):
    db = get_db()
    fila = db.execute(
        "SELECT f.id, f.archivo, f.orden_id, o.folio FROM fotos f JOIN ordenes o ON o.id = f.orden_id WHERE f.id = ?",
        (fid,)).fetchone()
    if not fila:
        abort(404)
    with db:
        db.execute("DELETE FROM fotos WHERE id = ?", (fid,))
        registrar(db, fila["orden_id"], "Eliminó una foto del equipo", session["usuario_id"])
    try:
        os.remove(os.path.join(carpeta_fotos(), fila["archivo"]))
    except OSError:
        pass
    flash("Foto eliminada.")
    return redirect(url_for("orden_detalle", folio=fila["folio"]) + "#fotos")


@app.route("/respaldo/fotos")
@login_required("admin")
def respaldo_fotos():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for f in get_db().execute("SELECT f.archivo, o.folio FROM fotos f JOIN ordenes o ON o.id = f.orden_id ORDER BY f.id"):
            ruta = os.path.join(carpeta_fotos(), f["archivo"])
            if os.path.exists(ruta):
                z.write(ruta, f"{f['folio']}/{f['archivo']}")
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"fotos_{datetime.now():%Y%m%d}.zip")


@app.route("/orden/<folio>/pago", methods=["POST"])
@login_required()
def registrar_pago(folio):
    o = obtener_orden(folio)
    verificar_acceso(o)
    f = request.form
    monto = leer_numero(f.get("monto"))
    tipo = f.get("tipo", "Abono")
    metodo = f.get("metodo", "Efectivo")
    destino = redirect(url_for("orden_detalle", folio=folio))
    if not monto or monto <= 0:
        flash("Captura un monto válido mayor a cero.")
        return destino
    if tipo not in ("Anticipo", "Abono", "Pago final") or metodo not in ("Efectivo", "Tarjeta", "Transferencia"):
        flash("Tipo o método de pago no válido.")
        return destino
    total = total_orden(o)
    if total > 0 and o["pagado"] + monto > total + 0.005:
        flash(f"El pago excede el total de la orden (${total:,.2f}). Ya se han cobrado ${o['pagado']:,.2f}.")
        return destino
    db = get_db()
    with db:
        db.execute("INSERT INTO pagos (orden_id, monto, tipo, metodo, usuario_id) VALUES (?,?,?,?,?)",
                   (o["id"], monto, tipo, metodo, session["usuario_id"]))
        registrar(db, o["id"], f"Registró {tipo.lower()} de ${monto:,.2f} ({metodo.lower()})", session["usuario_id"])
    flash(f"{tipo} de ${monto:,.2f} registrado.")
    return destino


@app.route("/orden/<folio>/pago/<int:pid>/eliminar", methods=["POST"])
@login_required("admin")
def eliminar_pago(folio, pid):
    o = obtener_orden(folio)
    db = get_db()
    p = db.execute("SELECT * FROM pagos WHERE id = ? AND orden_id = ?", (pid, o["id"])).fetchone()
    if p:
        with db:
            db.execute("DELETE FROM pagos WHERE id = ?", (pid,))
            registrar(db, o["id"], f"Eliminó un pago de ${p['monto']:,.2f} ({p['tipo'].lower()})", session["usuario_id"])
        flash("Pago eliminado.")
    return redirect(url_for("orden_detalle", folio=folio))


@app.route("/orden/<folio>/promesa", methods=["POST"])
@login_required()
def fijar_promesa(folio):
    o = obtener_orden(folio)
    verificar_acceso(o)
    valor = request.form.get("fecha_promesa", "").strip()
    if valor:
        try:
            datetime.strptime(valor, "%Y-%m-%d")
        except ValueError:
            flash("Fecha no válida.")
            return redirect(url_for("orden_detalle", folio=folio))
    db = get_db()
    with db:
        db.execute("UPDATE ordenes SET fecha_promesa = ? WHERE id = ?", (valor or None, o["id"]))
        registrar(db, o["id"], f"Fecha de entrega prometida: {fecha_larga(valor)}" if valor
                  else "Quitó la fecha de entrega prometida", session["usuario_id"])
    flash("Fecha prometida guardada." if valor else "Fecha prometida eliminada.")
    return redirect(url_for("orden_detalle", folio=folio))


@app.route("/orden/<folio>/nota", methods=["POST"])
@login_required()
def agregar_nota(folio):
    o = obtener_orden(folio)
    verificar_acceso(o)
    texto = request.form.get("texto", "").strip()[:1000]
    if not texto:
        flash("Escribe la nota.")
    else:
        db = get_db()
        with db:
            db.execute("INSERT INTO notas (orden_id, usuario_id, autor, texto) VALUES (?,?,?,?)",
                       (o["id"], session["usuario_id"], session["nombre"], texto))
            registrar(db, o["id"], "Agregó una nota interna", session["usuario_id"])
        flash("Nota guardada.")
    return redirect(url_for("orden_detalle", folio=folio) + "#notas")


@app.route("/plantillas", methods=["GET", "POST"])
@login_required("admin")
def plantillas():
    db = get_db()
    if request.method == "POST":
        with db:
            for estado in ESTADOS:
                texto = request.form.get(f"t_{estado}", "").strip()
                if request.form.get(f"r_{estado}") or not texto or texto == PLANTILLAS_BASE[estado]:
                    db.execute("DELETE FROM plantillas WHERE estado = ?", (estado,))
                else:
                    db.execute("INSERT INTO plantillas (estado, texto) VALUES (?, ?) "
                               "ON CONFLICT(estado) DO UPDATE SET texto = excluded.texto", (estado, texto[:600]))
        flash("Mensajes guardados.")
        return redirect(url_for("plantillas"))
    return render_template("plantillas.html", textos=plantillas_actuales(), base=PLANTILLAS_BASE,
                           variables=VARIABLES_PLANTILLA, estados=ESTADOS)


@app.route("/orden/<folio>/recibo/pdf")
@login_required()
def recibo_pdf(folio):
    o = obtener_orden(folio)
    verificar_acceso(o)
    pagos = get_db().execute("SELECT * FROM pagos WHERE orden_id = ? ORDER BY fecha, id", (o["id"],)).fetchall()
    ancho, margen = 226, 12
    alto = 345 + 14 * len(pagos)
    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=(ancho, alto))
    y = alto - 14
    dibujar_logo(c, ancho, y)
    y -= 52

    def centrado(texto, fuente="Helvetica", tam=9):
        nonlocal y
        c.setFont(fuente, tam)
        c.drawCentredString(ancho / 2, y, texto)
        y -= tam + 4

    def par(izq, der, fuente="Helvetica", tam=8):
        nonlocal y
        c.setFont(fuente, tam)
        c.drawString(margen, y, izq)
        c.drawRightString(ancho - margen, y, der)
        y -= tam + 4

    centrado("REVIVA: TALLER DE CELULARES", "Helvetica-Bold", 12)
    centrado("Recibo de pagos", "Helvetica", 8)
    y -= 4
    centrado(o["folio"], "Helvetica-Bold", 12)
    centrado(f"{o['cliente']} · {o['marca']} {o['modelo']}", "Helvetica", 7)
    y -= 6
    par("Total de la orden", f"${total_orden(o):,.2f}", "Helvetica-Bold")
    y -= 2
    for p in pagos:
        par(f"{p['fecha'][:10]} {p['tipo']} ({p['metodo']})", f"${p['monto']:,.2f}", tam=7)
    if not pagos:
        centrado("Sin pagos registrados", "Helvetica", 7)
    y -= 4
    par("Pagado", f"${o['pagado']:,.2f}", "Helvetica-Bold")
    par("Saldo pendiente", f"${saldo_de(o):,.2f}", "Helvetica-Bold", 9)
    y -= 10
    centrado(f"Emitido {datetime.now():%d/%m/%Y %H:%M}", "Helvetica", 6)
    centrado("Gracias por tu preferencia.", "Helvetica", 7)
    c.showPage()
    c.save()
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf", download_name=f"recibo-{folio}.pdf")


@app.route("/orden/<folio>/etiqueta/pdf")
@login_required()
def etiqueta_pdf(folio):
    """Etiqueta pequeña (50 x 30 mm) para pegar en el equipo o en su bolsa."""
    o = obtener_orden(folio)
    verificar_acceso(o)
    qr = qrcode.QRCode(box_size=6, border=0)
    qr.add_data(url_seguimiento(folio))
    qr.make(fit=True)
    qr_buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(qr_buf, format="PNG")
    qr_buf.seek(0)
    ancho, alto = 142, 85
    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=(ancho, alto))
    c.drawImage(ImageReader(qr_buf), ancho - 62, 12, 56, 56)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(6, alto - 14, o["folio"])
    y = alto - 26
    for texto, fuente, tam in ((o["cliente"], "Helvetica-Bold", 8), (f"{o['marca']} {o['modelo']}", "Helvetica", 7),
                               (f"IMEI ...{o['imei'][-6:]}", "Helvetica", 6.5),
                               (f"Promesa: {fecha_larga(o['fecha_promesa'])}" if campo(o, "fecha_promesa") else "", "Helvetica", 6.5)):
        for parte in simpleSplit(texto, fuente, tam, ancho - 74)[:2]:
            c.setFont(fuente, tam)
            c.drawString(6, y, parte)
            y -= tam + 3
    c.showPage()
    c.save()
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf", download_name=f"etiqueta-{folio}.pdf")


@app.route("/orden/<folio>/asignar", methods=["POST"])
@login_required()
def asignar_tecnico(folio):
    o = obtener_orden(folio)
    verificar_acceso(o)
    db = get_db()
    if session["rol"] == "admin":
        tid = request.form.get("tecnico_id", type=int)
        if tid and not db.execute(
            "SELECT 1 FROM usuarios WHERE id = ? AND rol = 'tecnico' AND activo = 1", (tid,)
        ).fetchone():
            abort(400)
    else:
        if o["tecnico_id"] is not None:
            abort(403)
        tid = session["usuario_id"]
    with db:
        db.execute("UPDATE ordenes SET tecnico_id = ?, actualizado_en = ? WHERE id = ?", (tid, ahora(), o["id"]))
        if session["rol"] != "admin":
            texto = "Tomó la orden"
        elif tid:
            texto = f"Asignó la orden a {db.execute('SELECT nombre FROM usuarios WHERE id = ?', (tid,)).fetchone()['nombre']}"
        else:
            texto = "Quitó la asignación de técnico"
        registrar(db, o["id"], texto, session["usuario_id"])
    flash("Asignación actualizada.")
    return redirect(url_for("orden_detalle", folio=folio))


@app.route("/orden/<folio>/diagnostico", methods=["POST"])
@login_required()
def guardar_diagnostico(folio):
    o = obtener_orden(folio)
    verificar_acceso(o)
    if o["estado"] == "Entregado":
        abort(400)
    f = request.form
    db = get_db()
    diag = f.get("diagnostico", "").strip() or None
    editable = o["presupuesto_estado"] != "Aprobado" and o["estado"] in ("Recibido", "En Diagnóstico")
    if not editable:
        with db:
            db.execute("UPDATE ordenes SET diagnostico = ?, actualizado_en = ? WHERE id = ?", (diag, ahora(), o["id"]))
            registrar(db, o["id"], "Actualizó el diagnóstico técnico", session["usuario_id"])
        flash("Diagnóstico guardado. El presupuesto ya no se puede modificar.")
        return redirect(url_for("orden_detalle", folio=folio))

    rid = f.get("refaccion_id", type=int)
    ref = db.execute("SELECT * FROM refacciones WHERE id = ? AND activo = 1", (rid,)).fetchone() if rid else None
    if rid and not ref:
        flash("La refacción seleccionada no existe.")
        return redirect(url_for("orden_detalle", folio=folio))
    precio_txt = f.get("costo_refaccion", "").strip()
    precio = (ref["precio_venta"] if ref else 0.0) if precio_txt == "" else leer_numero(precio_txt)
    mano = leer_numero(f.get("mano_obra"))
    garantia = leer_numero(f.get("garantia_dias", "30"), int)
    if precio is None or mano is None or garantia is None:
        flash("Revisa los montos y los días de garantía: deben ser números mayores o iguales a 0.")
        return redirect(url_for("orden_detalle", folio=folio))
    with db:
        db.execute(
            """UPDATE ordenes SET diagnostico = ?, refaccion_id = ?, costo_refaccion = ?, costo_proveedor = ?,
                   mano_obra = ?, garantia_dias = ?, presupuesto_estado = 'Pendiente', actualizado_en = ?
               WHERE id = ?""",
            (diag, ref["id"] if ref else None, precio, ref["costo_proveedor"] if ref else 0.0,
             mano, garantia, ahora(), o["id"]),
        )
        registrar(db, o["id"], f"Guardó diagnóstico y presupuesto (total ${precio + mano:,.2f}, garantía {garantia} días)",
                  session["usuario_id"])
    flash("Diagnóstico y presupuesto guardados.")
    return redirect(url_for("orden_detalle", folio=folio))


@app.route("/orden/<folio>/presupuesto/<accion>", methods=["POST"])
@login_required()
def presupuesto_accion(folio, accion):
    if accion not in ("aprobar", "rechazar"):
        abort(404)
    o = obtener_orden(folio)
    verificar_acceso(o)
    db = get_db()
    with db:
        ok, msg = resolver_presupuesto(db, o, accion == "aprobar", session["usuario_id"])
    flash(msg)
    return redirect(url_for("orden_detalle", folio=folio))


# ---- Búsqueda y filtros de órdenes ----
POR_PAGINA = 25
COLUMNAS_BUSQUEDA = ["o.folio", "c.nombre", "c.telefono", "e.imei", "e.marca", "e.modelo", "e.color",
                     "o.falla_reportada", "o.diagnostico"]
FROM_ORDENES = """FROM ordenes o JOIN equipos e ON e.id = o.equipo_id JOIN clientes c ON c.id = e.cliente_id
                  LEFT JOIN usuarios u ON u.id = o.tecnico_id """


def condiciones_busqueda():
    """WHERE y parámetros según los filtros de la URL (y el rol: el técnico solo ve lo suyo)."""
    a = request.args
    cond, params = [], []
    for palabra in normalizar(a.get("q", "")).split():  # todas las palabras deben aparecer (en cualquier campo)
        like = "%" + palabra.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        cond.append("(" + " OR ".join(f"norm({c}) LIKE ? ESCAPE '\\'" for c in COLUMNAS_BUSQUEDA) + ")")
        params += [like] * len(COLUMNAS_BUSQUEDA)
    if a.get("estado") in ESTADOS:
        cond.append("o.estado = ?"); params.append(a["estado"])
    if a.get("presupuesto") in ("Pendiente", "Aprobado", "Rechazado"):
        cond.append("o.presupuesto_estado = ?"); params.append(a["presupuesto"])
    tecnico = a.get("tecnico", "")
    if session["rol"] == "admin":
        if tecnico == "sin":
            cond.append("o.tecnico_id IS NULL")
        elif tecnico.isdigit():
            cond.append("o.tecnico_id = ?"); params.append(int(tecnico))
    else:  # el técnico solo ve sus órdenes y las que no tienen técnico
        cond.append("(o.tecnico_id IS NULL OR o.tecnico_id = ?)"); params.append(session["usuario_id"])
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.get("desde", "")):
        cond.append("date(o.fecha_ingreso) >= ?"); params.append(a["desde"])
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.get("hasta", "")):
        cond.append("date(o.fecha_ingreso) <= ?"); params.append(a["hasta"])
    return (("WHERE " + " AND ".join(cond)) if cond else ""), params


@app.route("/buscar")
@login_required()
def buscar():
    db = get_db()
    a = request.args
    pagina = max(a.get("pagina", 1, type=int), 1)
    donde, params = condiciones_busqueda()
    total = db.execute("SELECT COUNT(*) " + FROM_ORDENES + donde, params).fetchone()[0]
    filas = db.execute(
        """SELECT o.folio, o.estado, o.presupuesto_estado, o.falla_reportada, o.fecha_ingreso,
                  c.nombre AS cliente, c.telefono, e.imei, e.marca, e.modelo, u.nombre AS tecnico """
        + FROM_ORDENES + donde + " ORDER BY o.fecha_ingreso DESC, o.id DESC LIMIT ? OFFSET ?",
        params + [POR_PAGINA, (pagina - 1) * POR_PAGINA],
    ).fetchall()
    tecnicos = db.execute("SELECT id, nombre FROM usuarios WHERE rol = 'tecnico' ORDER BY nombre").fetchall() \
        if session["rol"] == "admin" else []
    args = {k: v for k, v in a.items() if k != "pagina" and v}
    return render_template(
        "buscar.html", filas=filas, total=total, pagina=pagina, paginas=max(1, -(-total // POR_PAGINA)),
        args=args, q=a.get("q", "").strip(), estado=a.get("estado", ""), tecnico=a.get("tecnico", ""),
        presupuesto=a.get("presupuesto", ""), desde=a.get("desde", ""), hasta=a.get("hasta", ""),
        estados=ESTADOS, tecnicos=tecnicos, hay_filtros=bool(args),
    )


@app.route("/buscar/exportar")
@login_required()
def buscar_exportar():
    donde, params = condiciones_busqueda()
    filas = get_db().execute(
        """SELECT o.folio, o.fecha_ingreso, o.estado, c.nombre, c.telefono, e.imei, e.marca, e.modelo,
                  o.falla_reportada, o.diagnostico, u.nombre, o.presupuesto_estado, o.costo_refaccion + o.mano_obra """
        + FROM_ORDENES + donde + " ORDER BY o.fecha_ingreso DESC, o.id DESC", params).fetchall()
    return respuesta_csv(f"ordenes_{datetime.now():%Y%m%d_%H%M}.csv",
                         ["Folio", "Ingreso", "Estado", "Cliente", "Teléfono", "IMEI", "Marca", "Modelo", "Falla",
                          "Diagnóstico", "Técnico", "Presupuesto", "Total al cliente"], [tuple(f) for f in filas])


# ---- Inventario ----
@app.route("/inventario")
@login_required()
def inventario():
    items = get_db().execute(
        "SELECT * FROM refacciones WHERE activo = 1 ORDER BY (stock < stock_minimo) DESC, categoria, nombre"
    ).fetchall()
    return render_template("inventario.html", items=items, categorias=CATEGORIAS)


@app.route("/inventario/nueva", methods=["POST"])
@login_required("admin")
def refaccion_nueva():
    f = request.form
    nombre = f.get("nombre", "").strip()
    categoria = f.get("categoria")
    stock = leer_numero(f.get("stock"), int)
    minimo = leer_numero(f.get("stock_minimo", "2"), int)
    costo = leer_numero(f.get("costo_proveedor"))
    precio = leer_numero(f.get("precio_venta"))
    if not nombre or categoria not in CATEGORIAS or None in (stock, minimo, costo, precio):
        flash("Revisa los datos de la refacción.")
    else:
        db = get_db()
        with db:
            db.execute(
                """INSERT INTO refacciones (nombre, categoria, marca_compatible, modelo_compatible,
                       stock, stock_minimo, costo_proveedor, precio_venta) VALUES (?,?,?,?,?,?,?,?)""",
                (nombre, categoria, f.get("marca_compatible", "").strip() or None,
                 f.get("modelo_compatible", "").strip() or None, stock, minimo, costo, precio),
            )
        flash("Refacción agregada.")
    return redirect(url_for("inventario"))


@app.route("/inventario/<int:rid>/editar", methods=["POST"])
@login_required("admin")
def refaccion_editar(rid):
    f = request.form
    stock = leer_numero(f.get("stock"), int)
    costo = leer_numero(f.get("costo_proveedor"))
    precio = leer_numero(f.get("precio_venta"))
    if None in (stock, costo, precio):
        flash("Valores inválidos.")
    else:
        db = get_db()
        with db:
            db.execute(
                "UPDATE refacciones SET stock = ?, costo_proveedor = ?, precio_venta = ? WHERE id = ?",
                (stock, costo, precio, rid),
            )
        flash("Refacción actualizada.")
    return redirect(url_for("inventario"))


@app.route("/inventario/<int:rid>/baja", methods=["POST"])
@login_required("admin")
def refaccion_baja(rid):
    db = get_db()
    with db:
        db.execute("UPDATE refacciones SET activo = 0 WHERE id = ?", (rid,))
    flash("Refacción dada de baja.")
    return redirect(url_for("inventario"))


# ---- Usuarios y cuenta ----
@app.route("/usuarios", methods=["GET", "POST"])
@login_required("admin")
def usuarios():
    db = get_db()
    if request.method == "POST":
        f = request.form
        nombre, email = f.get("nombre", "").strip(), f.get("email", "").strip().lower()
        password, rol = f.get("password", ""), f.get("rol")
        if not nombre or not email or rol not in ("admin", "tecnico") or len(password) < 8:
            flash("Completa nombre, correo, rol y una contraseña de al menos 8 caracteres.")
        else:
            try:
                with db:
                    db.execute(
                        "INSERT INTO usuarios (nombre, email, password_hash, rol) VALUES (?,?,?,?)",
                        (nombre, email, generate_password_hash(password), rol),
                    )
                flash("Usuario creado.")
            except ERRORES_INTEGRIDAD:
                flash("Ya existe un usuario con ese correo.")
        return redirect(url_for("usuarios"))
    lista = db.execute("SELECT id, nombre, email, rol, activo FROM usuarios ORDER BY activo DESC, rol, nombre").fetchall()
    return render_template("usuarios.html", lista=lista)


@app.route("/usuarios/<int:uid>/activo", methods=["POST"])
@login_required("admin")
def usuario_activo(uid):
    if uid == session["usuario_id"]:
        flash("No puedes desactivar tu propio usuario.")
    else:
        db = get_db()
        with db:
            db.execute("UPDATE usuarios SET activo = 1 - activo WHERE id = ?", (uid,))
        flash("Usuario actualizado.")
    return redirect(url_for("usuarios"))


@app.route("/cuenta", methods=["GET", "POST"])
@login_required()
def cuenta():
    if request.method == "POST":
        db = get_db()
        user = db.execute("SELECT * FROM usuarios WHERE id = ?", (session["usuario_id"],)).fetchone()
        actual, nueva = request.form.get("actual", ""), request.form.get("nueva", "")
        if not check_password_hash(user["password_hash"], actual):
            flash("La contraseña actual no es correcta.")
        elif len(nueva) < 8 or nueva != request.form.get("confirmar", ""):
            flash("La nueva contraseña debe tener 8 caracteres o más y coincidir con la confirmación.")
        else:
            with db:
                db.execute("UPDATE usuarios SET password_hash = ? WHERE id = ?",
                           (generate_password_hash(nueva), user["id"]))
            session.pop("pass_default", None)
            flash("Contraseña actualizada.")
            return redirect(url_for("kanban"))
    return render_template("cuenta.html")


# ---------------- Fase 4: portal del cliente, reseñas y garantías ----------------
# Acceso del cliente: el enlace del QR / WhatsApp lleva un token firmado (HMAC) del folio.
# Sin token, el folio solo muestra el avance; para ver el presupuesto el cliente confirma
# los últimos 4 dígitos de su teléfono. Así nadie puede adivinar folios para aprobar ajenos.
def token_folio(folio):
    return hmac.new(app.config["SECRET_KEY"].encode(), folio.encode(), hashlib.sha256).hexdigest()[:12]


def token_valido(folio, token):
    return bool(token) and hmac.compare_digest(token.encode(), token_folio(folio).encode())


_fallos = {}


def bloqueado(clave, maximo=5, ventana=600):
    recientes = [t for t in _fallos.get(clave, []) if time.time() - t < ventana]
    _fallos[clave] = recientes
    return len(recientes) >= maximo


def registrar_fallo(clave):
    _fallos.setdefault(clave, []).append(time.time())


def garantia_de(o):
    """Garantía de una orden entregada y reparada, o None si no aplica."""
    if o["estado"] != "Entregado" or o["presupuesto_estado"] != "Aprobado" \
            or not o["garantia_dias"] or not o["fecha_entrega"]:
        return None
    entrega = datetime.strptime(o["fecha_entrega"], "%Y-%m-%d %H:%M:%S").date()
    vence = entrega + timedelta(days=o["garantia_dias"])
    return {"vence": vence, "vigente": date.today() <= vence, "dias_restantes": (vence - date.today()).days}


def garantias_vigentes(db, equipo_id):
    resultado = []
    for fila in db.execute("SELECT * FROM ordenes WHERE equipo_id = ? AND estado = 'Entregado'", (equipo_id,)):
        g = garantia_de(fila)
        if g and g["vigente"]:
            resultado.append((fila["folio"], g["vence"]))
    return resultado


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(413)
def error_amigable(e):
    mensajes = {400: "No pudimos procesar la solicitud. Recarga la página e inténtalo de nuevo.",
                403: "No tienes permiso para ver esta página.", 404: "No encontramos lo que buscas.",
                413: "Las fotos pesan demasiado. Sube menos fotos a la vez (máximo 40 MB en total)."}
    return render_template("error.html", codigo=e.code, mensaje=mensajes[e.code]), e.code


@app.route("/consulta")
def consulta():
    folio = request.args.get("folio", "").strip().upper()
    if folio:
        if get_db().execute("SELECT 1 FROM ordenes WHERE folio = ?", (folio,)).fetchone():
            return redirect(url_for("seguimiento", folio=folio))
        flash("No encontramos ese folio. Revísalo en tu ticket.")
    return render_template("consulta.html")


@app.route("/seguimiento/<folio>")
def seguimiento(folio):
    o = obtener_orden(folio)
    token = request.args.get("t", "")
    completo = token_valido(folio, token)
    db = get_db()
    resena = db.execute("SELECT * FROM resenas WHERE orden_id = ?", (o["id"],)).fetchone() if completo else None
    ref = db.execute("SELECT nombre FROM refacciones WHERE id = ?", (o["refaccion_id"],)).fetchone() \
        if completo and o["refaccion_id"] else None
    return render_template(
        "seguimiento.html", o=o, estados=ESTADOS, completo=completo, token=token if completo else "",
        total=o["costo_refaccion"] + o["mano_obra"], resena=resena, saldo=saldo_de(o), pagado=o["pagado"],
        refaccion=ref["nombre"] if ref else None, garantia=garantia_de(o) if completo else None,
    )


@app.route("/seguimiento/<folio>/verificar", methods=["POST"])
def seguimiento_verificar(folio):
    o = obtener_orden(folio)
    clave = (request.remote_addr, folio)
    if bloqueado(clave):
        flash("Demasiados intentos. Inténtalo de nuevo en unos minutos o usa el QR de tu ticket.")
        return redirect(url_for("seguimiento", folio=folio))
    # Acepta el teléfono completo (con o sin lada de país) o solo sus últimos 4+ dígitos.
    digitos = re.sub(r"\D", "", request.form.get("telefono", ""))
    telefono = re.sub(r"\D", "", o["telefono"])
    n = min(len(digitos), len(telefono))
    if n >= 4 and hmac.compare_digest(digitos[-n:].encode(), telefono[-n:].encode()):
        return redirect(url_for("seguimiento", folio=folio, t=token_folio(folio)))
    registrar_fallo(clave)
    flash("El teléfono no coincide con el que se registró al dejar el equipo.")
    return redirect(url_for("seguimiento", folio=folio))


@app.route("/seguimiento/<folio>/presupuesto/<accion>", methods=["POST"])
def seguimiento_presupuesto(folio, accion):
    if accion not in ("aprobar", "rechazar"):
        abort(404)
    o = obtener_orden(folio)
    token = request.form.get("t", "")
    if not token_valido(folio, token):
        abort(403)
    db = get_db()
    with db:
        ok, msg = resolver_presupuesto(db, o, accion == "aprobar")
    if ok:
        msg = ("¡Gracias! Autorizaste la reparación; comenzaremos en cuanto sea posible."
               if accion == "aprobar"
               else "Registramos que no autorizaste la reparación. Te avisaremos para que recojas tu equipo.")
    flash(msg)
    return redirect(url_for("seguimiento", folio=folio, t=token))


@app.route("/seguimiento/<folio>/resena", methods=["POST"])
def seguimiento_resena(folio):
    o = obtener_orden(folio)
    token = request.form.get("t", "")
    if not token_valido(folio, token):
        abort(403)
    destino = redirect(url_for("seguimiento", folio=folio, t=token))
    if o["estado"] != "Entregado":
        flash("Podrás calificar el servicio cuando recojas tu equipo.")
        return destino
    calificacion = request.form.get("calificacion", type=int)
    if calificacion not in (1, 2, 3, 4, 5):
        flash("Elige de 1 a 5 estrellas.")
        return destino
    comentario = request.form.get("comentario", "").strip()[:500] or None
    db = get_db()
    try:
        with db:
            db.execute("INSERT INTO resenas (orden_id, calificacion, comentario) VALUES (?, ?, ?)",
                       (o["id"], calificacion, comentario))
            registrar(db, o["id"], f"Dejó una reseña de {calificacion} estrella(s)", actor="Cliente (portal)")
        flash("¡Gracias por tu opinión!")
    except ERRORES_INTEGRIDAD:
        flash("Ya registramos tu calificación para esta orden.")
    return destino


@app.route("/resenas")
@login_required()
def resenas():
    db = get_db()
    filas = db.execute(
        """SELECT r.calificacion, r.comentario, r.fecha, o.folio, c.nombre AS cliente, e.marca, e.modelo
           FROM resenas r JOIN ordenes o ON o.id = r.orden_id
           JOIN equipos e ON e.id = o.equipo_id JOIN clientes c ON c.id = e.cliente_id
           ORDER BY r.fecha DESC"""
    ).fetchall()
    promedio = sum(r["calificacion"] for r in filas) / len(filas) if filas else None
    conteo = {n: sum(1 for r in filas if r["calificacion"] == n) for n in (5, 4, 3, 2, 1)}
    return render_template("resenas.html", filas=filas, promedio=promedio, conteo=conteo)


@app.route("/garantias")
@login_required()
def garantias():
    imei = re.sub(r"\D", "", request.args.get("imei", ""))
    equipo, historial = None, []
    if imei:
        db = get_db()
        equipo = db.execute(
            """SELECT e.*, c.nombre AS cliente, c.telefono FROM equipos e
               JOIN clientes c ON c.id = e.cliente_id WHERE e.imei = ?""", (imei,)
        ).fetchone()
        if equipo:
            for o in db.execute("SELECT * FROM ordenes WHERE equipo_id = ? ORDER BY fecha_ingreso DESC", (equipo["id"],)):
                historial.append((o, garantia_de(o)))
    return render_template("garantias.html", imei=imei, equipo=equipo, historial=historial,
                           vigentes=[h for h in historial if h[1] and h[1]["vigente"]])


# ---------------- Exportación CSV ----------------
def celda_segura(valor):
    """Evita inyección de fórmulas al abrir el CSV en Excel: =, +, -, @ al inicio de un texto."""
    if isinstance(valor, str) and valor and valor[0] in "=+-@\t\r":
        return "'" + valor
    return "" if valor is None else valor


def csv_bytes(encabezados, filas):
    buf = io.StringIO()
    escritor = csv.writer(buf)
    escritor.writerow(encabezados)
    for fila in filas:
        escritor.writerow([celda_segura(c) for c in fila])
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM: Excel abre bien los acentos


def respuesta_csv(nombre, encabezados, filas):
    return Response(csv_bytes(encabezados, filas), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


# ---------------- Cortes financieros (solo administrador) ----------------
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


@app.template_filter("dinero")
def dinero(valor):
    return f"${(valor or 0):,.2f}"


def fecha_arg(nombre, defecto):
    try:
        return datetime.strptime(request.args.get(nombre, ""), "%Y-%m-%d").date()
    except ValueError:
        return defecto


def techo_bonito(valor):
    if valor <= 0:
        return 1
    exp = 10 ** math.floor(math.log10(valor))
    for m in (1, 2, 2.5, 5, 10):
        if valor <= m * exp:
            return m * exp
    return 10 * exp


def construir_grafica(detalle, desde, hasta):
    """Barras de ingresos y ganancia por día, semana o mes (SVG generado en el servidor, sin librerías)."""
    dias = (hasta - desde).days + 1
    if dias <= 45:
        paso, inicio = "día", desde
        siguiente = lambda f: f + timedelta(days=1)
        clave = lambda f: f
        etiqueta = lambda f: f"{f.day}/{f.month}"
    elif dias <= 200:
        paso, inicio = "semana", desde - timedelta(days=desde.weekday())
        siguiente = lambda f: f + timedelta(days=7)
        clave = lambda f: f - timedelta(days=f.weekday())
        etiqueta = lambda f: f"{f.day}/{f.month}"
    else:
        paso, inicio = "mes", desde.replace(day=1)
        siguiente = lambda f: (f.replace(day=28) + timedelta(days=4)).replace(day=1)
        clave = lambda f: f.replace(day=1)
        etiqueta = lambda f: f"{MESES[f.month - 1]} {f.year % 100}"
    cubetas, f = {}, inicio
    while f <= hasta:
        cubetas[f] = {"ingreso": 0.0, "ganancia": 0.0}
        f = siguiente(f)
    for o in detalle:
        k = clave(datetime.strptime(o["fecha_entrega"][:10], "%Y-%m-%d").date())
        if k in cubetas:
            cubetas[k]["ingreso"] += o["ingreso"]
            cubetas[k]["ganancia"] += o["ganancia"]
    W, H, ml, mr, mt, mb = 900, 280, 70, 12, 14, 34
    techo = techo_bonito(max([c["ingreso"] for c in cubetas.values()] + [0]))
    area_h, banda = H - mt - mb, (W - ml - mr) / max(len(cubetas), 1)
    cada = max(1, math.ceil(len(cubetas) / 14))
    barras = []
    for i, (k, c) in enumerate(cubetas.items()):
        x, bw = ml + i * banda + banda * 0.12, banda * 0.76
        hi, hg = area_h * c["ingreso"] / techo, area_h * max(c["ganancia"], 0) / techo
        barras.append({"x": round(x, 1), "w": round(bw / 2 - 1, 1), "xg": round(x + bw / 2, 1),
                       "y": round(mt + area_h - hi, 1), "h": round(hi, 1),
                       "yg": round(mt + area_h - hg, 1), "hg": round(hg, 1),
                       "cx": round(x + bw / 2, 1), "etiqueta": etiqueta(k), "mostrar": i % cada == 0,
                       "titulo": f"{etiqueta(k)}: ingresos {dinero(c['ingreso'])} · ganancia {dinero(c['ganancia'])}"})
    ticks = [{"y": round(mt + area_h - area_h * n / 4, 1), "texto": f"${techo * n / 4:,.0f}"} for n in range(5)]
    return {"W": W, "H": H, "ml": ml, "mr": mr, "barras": barras, "ticks": ticks, "paso": paso, "base": mt + area_h}


def calcular_corte(db, desde, hasta):
    """Ingresos = órdenes con presupuesto aprobado entregadas en el periodo (refacción + mano de obra)."""
    d, h = desde.isoformat(), hasta.isoformat()
    detalle = []
    for o in db.execute(
        """SELECT o.folio, o.fecha_entrega, o.costo_refaccion, o.mano_obra, o.costo_proveedor,
                  e.marca, e.modelo, c.nombre AS cliente, u.nombre AS tecnico, r.nombre AS refaccion
           FROM ordenes o JOIN equipos e ON e.id = o.equipo_id JOIN clientes c ON c.id = e.cliente_id
           LEFT JOIN usuarios u ON u.id = o.tecnico_id LEFT JOIN refacciones r ON r.id = o.refaccion_id
           WHERE o.estado = 'Entregado' AND o.presupuesto_estado = 'Aprobado'
                 AND date(o.fecha_entrega) BETWEEN ? AND ? ORDER BY o.fecha_entrega""", (d, h)):
        ingreso = o["costo_refaccion"] + o["mano_obra"]
        detalle.append({**dict(o), "ingreso": ingreso, "costo": o["costo_proveedor"],
                        "ganancia": ingreso - o["costo_proveedor"]})
    ingresos = sum(x["ingreso"] for x in detalle)
    costos = sum(x["costo"] for x in detalle)

    refs, tecs = {}, {}
    for x in detalle:
        if x["refaccion"]:
            r = refs.setdefault(x["refaccion"], {"nombre": x["refaccion"], "usos": 0, "ingreso": 0.0, "costo": 0.0})
            r["usos"] += 1; r["ingreso"] += x["costo_refaccion"]; r["costo"] += x["costo"]
        t = tecs.setdefault(x["tecnico"] or "Sin asignar", {"nombre": x["tecnico"] or "Sin asignar", "n": 0, "ingreso": 0.0, "ganancia": 0.0})
        t["n"] += 1; t["ingreso"] += x["ingreso"]; t["ganancia"] += x["ganancia"]

    equipos = db.execute(
        """SELECT e.marca || ' ' || e.modelo AS nombre, COUNT(*) AS n FROM ordenes o JOIN equipos e ON e.id = o.equipo_id
           WHERE date(o.fecha_ingreso) BETWEEN ? AND ? GROUP BY lower(e.marca), lower(e.modelo)
           ORDER BY n DESC, nombre LIMIT 8""", (d, h)).fetchall()
    fallas = Counter(); original = {}
    for (texto,) in db.execute("SELECT falla_reportada FROM ordenes WHERE date(fecha_ingreso) BETWEEN ? AND ?", (d, h)):
        k = " ".join(normalizar(texto).split())
        fallas[k] += 1; original.setdefault(k, texto.strip())
    pend = db.execute("""SELECT COUNT(*), COALESCE(SUM(costo_refaccion + mano_obra), 0) FROM ordenes
                         WHERE presupuesto_estado = 'Aprobado' AND estado != 'Entregado'""").fetchone()
    resenas = db.execute("SELECT COUNT(*), AVG(calificacion) FROM resenas WHERE date(fecha) BETWEEN ? AND ?", (d, h)).fetchone()
    return {
        "detalle": detalle, "ingresos": ingresos, "costos": costos, "ganancia": ingresos - costos,
        "margen": (ingresos - costos) / ingresos * 100 if ingresos else 0.0,
        "n_entregadas": len(detalle), "ticket": ingresos / len(detalle) if detalle else 0.0,
        "recibidas": db.execute("SELECT COUNT(*) FROM ordenes WHERE date(fecha_ingreso) BETWEEN ? AND ?", (d, h)).fetchone()[0],
        "rechazadas": db.execute("SELECT COUNT(*) FROM ordenes WHERE presupuesto_estado = 'Rechazado' AND date(presupuesto_fecha) BETWEEN ? AND ?", (d, h)).fetchone()[0],
        "por_entregar_n": pend[0], "por_entregar_monto": pend[1],
        "n_resenas": resenas[0], "calificacion": resenas[1],
        "refacciones": sorted(refs.values(), key=lambda r: (-r["usos"], r["nombre"]))[:8],
        "tecnicos": sorted(tecs.values(), key=lambda t: -t["ingreso"]),
        "equipos": equipos, "fallas": [(original[k], n) for k, n in fallas.most_common(8)],
        "grafica": construir_grafica(detalle, desde, hasta),
    }


@app.route("/finanzas")
@login_required("admin")
def finanzas():
    hoy = date.today()
    desde, hasta = fecha_arg("desde", hoy.replace(day=1)), fecha_arg("hasta", hoy)
    if desde > hasta:
        desde, hasta = hasta, desde
    fin_mes_ant = hoy.replace(day=1) - timedelta(days=1)
    atajos = {"Hoy": (hoy, hoy), "Últimos 7 días": (hoy - timedelta(days=6), hoy),
              "Este mes": (hoy.replace(day=1), hoy), "Mes anterior": (fin_mes_ant.replace(day=1), fin_mes_ant),
              "Este año": (hoy.replace(month=1, day=1), hoy)}
    return render_template("finanzas.html", c=calcular_corte(get_db(), desde, hasta), desde=desde, hasta=hasta,
                           atajos=atajos)


@app.route("/finanzas/exportar")
@login_required("admin")
def finanzas_exportar():
    hoy = date.today()
    desde, hasta = fecha_arg("desde", hoy.replace(day=1)), fecha_arg("hasta", hoy)
    corte = calcular_corte(get_db(), min(desde, hasta), max(desde, hasta))
    filas = [(x["folio"], x["fecha_entrega"], x["cliente"], f"{x['marca']} {x['modelo']}", x["tecnico"] or "",
              x["refaccion"] or "", x["costo_refaccion"], x["mano_obra"], x["ingreso"], x["costo"], x["ganancia"])
             for x in corte["detalle"]]
    filas.append(("TOTAL", "", "", "", "", "", "", "", corte["ingresos"], corte["costos"], corte["ganancia"]))
    return respuesta_csv(f"corte_{desde}_{hasta}.csv",
                         ["Folio", "Entrega", "Cliente", "Equipo", "Técnico", "Refacción", "Precio refacción",
                          "Mano de obra", "Ingreso", "Costo proveedor", "Ganancia"], filas)


# ---------------- Respaldo y exportación (solo administrador) ----------------
def copiar_base(destino):
    """Copia consistente de la base (API de respaldo de SQLite, segura aunque la app esté en uso)."""
    if MOTOR == "mysql":
        raise RuntimeError("Con MySQL el respaldo se hace desde phpMyAdmin (Exportar).")
    origen = sqlite3.connect(DB_PATH)
    copia = sqlite3.connect(destino)
    try:
        origen.backup(copia)
    finally:
        copia.close()
        origen.close()


def respaldo_automatico(directorio=None, conservar=14):
    """Un respaldo por día al arrancar la app; conserva los últimos `conservar`."""
    directorio = directorio or RESPALDOS_DIR
    if MOTOR == "mysql" or not os.path.exists(DB_PATH):
        return None
    os.makedirs(directorio, exist_ok=True)
    destino = os.path.join(directorio, f"taller_{date.today():%Y%m%d}.db")
    creado = None
    if not os.path.exists(destino):
        copiar_base(destino)
        creado = destino
    for viejo in sorted(f for f in os.listdir(directorio) if re.fullmatch(r"taller_\d{8}\.db", f))[:-conservar]:
        os.remove(os.path.join(directorio, viejo))
    return creado


def datasets_exportacion(db):
    return {
        "ordenes": (
            ["Folio", "Ingreso", "Entrega", "Estado", "Cliente", "Teléfono", "IMEI", "Marca", "Modelo", "Falla",
             "Diagnóstico", "Técnico", "Presupuesto", "Precio refacción", "Mano de obra", "Total", "Costo proveedor",
             "Ganancia", "Garantía (días)"],
            [tuple(r) for r in db.execute(
                """SELECT o.folio, o.fecha_ingreso, o.fecha_entrega, o.estado, c.nombre, c.telefono, e.imei, e.marca,
                          e.modelo, o.falla_reportada, o.diagnostico, u.nombre, o.presupuesto_estado,
                          o.costo_refaccion, o.mano_obra, o.costo_refaccion + o.mano_obra, o.costo_proveedor,
                          o.costo_refaccion + o.mano_obra - o.costo_proveedor, o.garantia_dias
                   """ + FROM_ORDENES + " ORDER BY o.id")]),
        "clientes": (["Nombre", "Teléfono", "Email", "Alta"],
                     [tuple(r) for r in db.execute("SELECT nombre, telefono, email, creado_en FROM clientes ORDER BY id")]),
        "inventario": (["Refacción", "Categoría", "Marca", "Modelo", "Stock", "Stock mínimo", "Costo proveedor",
                        "Precio venta", "Activa"],
                       [tuple(r) for r in db.execute(
                           """SELECT nombre, categoria, marca_compatible, modelo_compatible, stock, stock_minimo,
                                     costo_proveedor, precio_venta, activo FROM refacciones ORDER BY categoria, nombre""")]),
        "resenas": (["Folio", "Cliente", "Calificación", "Comentario", "Fecha"],
                    [tuple(r) for r in db.execute(
                        """SELECT o.folio, c.nombre, r.calificacion, r.comentario, r.fecha FROM resenas r
                           JOIN ordenes o ON o.id = r.orden_id JOIN equipos e ON e.id = o.equipo_id
                           JOIN clientes c ON c.id = e.cliente_id ORDER BY r.id""")]),
        "bitacora": (["Fecha", "Folio", "Quién", "Acción"],
                     [tuple(r) for r in db.execute(
                         """SELECT b.fecha, o.folio, b.actor, b.accion FROM bitacora b JOIN ordenes o ON o.id = b.orden_id
                            ORDER BY b.id""")]),
    }


@app.route("/respaldo")
@login_required("admin")
def respaldo():
    archivos = []
    if os.path.isdir(RESPALDOS_DIR):
        for nombre in sorted((f for f in os.listdir(RESPALDOS_DIR) if re.fullmatch(r"taller_\d{8}\.db", f)), reverse=True):
            archivos.append({"nombre": nombre, "kb": round(os.path.getsize(os.path.join(RESPALDOS_DIR, nombre)) / 1024)})
    kb = round(os.path.getsize(DB_PATH) / 1024) if os.path.exists(DB_PATH) else 0
    return render_template("respaldo.html", archivos=archivos, kb=kb, motor=MOTOR,
                           conjuntos=list(datasets_exportacion(get_db()).keys()))


@app.route("/respaldo/descargar")
@login_required("admin")
def respaldo_descargar():
    if MOTOR == "mysql":
        flash("Tu base está en MySQL: respáldala desde phpMyAdmin (pestaña Exportar).")
        return redirect(url_for("respaldo"))
    with tempfile.TemporaryDirectory() as tmp:
        destino = os.path.join(tmp, "copia.db")
        copiar_base(destino)
        with open(destino, "rb") as f:
            contenido = io.BytesIO(f.read())
    return send_file(contenido, mimetype="application/octet-stream", as_attachment=True,
                     download_name=f"taller_respaldo_{datetime.now():%Y%m%d_%H%M}.db")


@app.route("/respaldo/archivo/<nombre>")
@login_required("admin")
def respaldo_archivo(nombre):
    if not re.fullmatch(r"taller_\d{8}\.db", nombre):
        abort(404)
    return send_from_directory(RESPALDOS_DIR, nombre, as_attachment=True)


@app.route("/respaldo/exportar/<nombre>")
@login_required("admin")
def respaldo_exportar(nombre):
    datos = datasets_exportacion(get_db())
    sello = f"{datetime.now():%Y%m%d}"
    if nombre == "todo.zip":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for clave, (encabezados, filas) in datos.items():
                z.writestr(f"{clave}.csv", csv_bytes(encabezados, filas))
        buf.seek(0)
        return send_file(buf, mimetype="application/zip", as_attachment=True, download_name=f"taller_exportacion_{sello}.zip")
    clave = nombre[:-4] if nombre.endswith(".csv") else None
    if clave not in datos:
        abort(404)
    return respuesta_csv(f"{clave}_{sello}.csv", *datos[clave])


if __name__ == "__main__":
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    try:
        init_db()
    except Exception as error:  # MySQL apagado, contraseña incorrecta, etc.
        if MOTOR != "mysql":
            raise
        raise SystemExit(
            "\nNo se pudo preparar la base de datos MySQL.\n"
            "1) Abre el Panel de XAMPP y pulsa Start en MySQL.\n"
            "2) Si tu MySQL tiene contraseña, define MYSQL_PASSWORD.\n"
            f"Detalle: {error}\n")
    respaldo_automatico()
    host = os.environ.get("HOST", "127.0.0.1")
    # El modo debug (recarga automática) solo se activa en local: expone una consola si la app es accesible por red.
    debug = os.environ.get("FLASK_DEBUG", "1" if host in ("127.0.0.1", "localhost") else "0") == "1"
    app.run(host=host, debug=debug)
