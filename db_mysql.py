"""Conector MySQL / MariaDB (XAMPP) con la misma interfaz que usa app.py con sqlite3.

La aplicación escribe su SQL pensando en SQLite (marcadores `?`, funciones de fecha, etc.).
Este módulo lo traduce al vuelo y devuelve filas que se leen igual que sqlite3.Row
(por nombre o por posición). Se activa con la variable de entorno DB_ENGINE=mysql.

Variables de entorno (valores por defecto de XAMPP):
    MYSQL_HOST=127.0.0.1  MYSQL_PORT=3306  MYSQL_USER=root  MYSQL_PASSWORD=  MYSQL_DB=taller_celulares
"""
import os
import re

import pymysql
from pymysql.constants import CLIENT, FIELD_TYPE
from pymysql.converters import conversions

IntegrityError = pymysql.err.IntegrityError


def configuracion():
    return {
        "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.environ.get("MYSQL_PORT", "3306")),
        "user": os.environ.get("MYSQL_USER", "root"),
        "password": os.environ.get("MYSQL_PASSWORD", ""),
        "database": os.environ.get("MYSQL_DB", "taller_celulares"),
    }


# ---------------- Traducción de SQL (SQLite -> MySQL) ----------------
def traducir(sql):
    """Convierte el SQL de la aplicación (estilo SQLite) a SQL de MySQL."""
    s = sql
    # norm(col): en SQLite quitaba acentos y mayúsculas. En MySQL lo hace la colación utf8mb4_unicode_ci.
    s = re.sub(r"\bnorm\(([^()]*)\)", r"\1", s)
    s = re.sub(r"\s+ESCAPE\s+'\\'", "", s)  # el carácter de escape por defecto de MySQL ya es la barra invertida
    # Fechas
    s = re.sub(r"datetime\('now',\s*'localtime',\s*'([+-]?)(\d+) days'\)",
               lambda m: f"(NOW() {'+' if m.group(1) == '+' else '-'} INTERVAL {m.group(2)} DAY)", s)
    s = s.replace("datetime('now','localtime')", "NOW()").replace("datetime('now', 'localtime')", "NOW()")
    s = s.replace("date('now','localtime')", "CURDATE()").replace("date('now', 'localtime')", "CURDATE()")
    # UPSERT
    s = re.sub(r"ON CONFLICT\(\w+\) DO UPDATE SET (\w+) = excluded\.(\w+)",
               r"ON DUPLICATE KEY UPDATE \1 = VALUES(\2)", s)
    # Marcadores: los % literales se duplican y cada ? pasa a %s
    s = s.replace("%", "%%").replace("?", "%s")
    return s


# ---------------- Filas y cursores ----------------
class Fila:
    """Fila de resultado: se lee por nombre (fila["id"]) o por posición (fila[0]), como sqlite3.Row."""
    __slots__ = ("_nombres", "_valores")

    def __init__(self, nombres, valores):
        self._nombres = nombres
        self._valores = tuple(valores)

    def __getitem__(self, clave):
        if isinstance(clave, (int, slice)):
            return self._valores[clave]
        try:
            return self._valores[self._nombres.index(clave)]
        except ValueError:
            raise KeyError(clave) from None

    def keys(self):
        return list(self._nombres)

    def __iter__(self):
        return iter(self._valores)

    def __len__(self):
        return len(self._valores)


class Cursor:
    def __init__(self, cur):
        self._cur = cur
        self.lastrowid = cur.lastrowid
        self.rowcount = cur.rowcount
        self._nombres = [d[0] for d in cur.description] if cur.description else []

    def fetchone(self):
        v = self._cur.fetchone()
        return None if v is None else Fila(self._nombres, v)

    def fetchall(self):
        return [Fila(self._nombres, v) for v in self._cur.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


def _numero(texto):
    """DECIMAL de MySQL (SUM, AVG) -> int o float de Python."""
    return float(texto) if ("." in texto or "e" in texto.lower()) else int(texto)


def _convertidores():
    c = conversions.copy()
    for tipo in (FIELD_TYPE.DATETIME, FIELD_TYPE.TIMESTAMP, FIELD_TYPE.DATE):
        c[tipo] = lambda s: s  # la app maneja las fechas como texto 'AAAA-MM-DD HH:MM:SS'
    c[FIELD_TYPE.NEWDECIMAL] = _numero
    c[FIELD_TYPE.DECIMAL] = _numero
    return c


class Conexion:
    """Envuelve una conexión de PyMySQL con execute/commit/rollback/with como sqlite3."""

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=()):
        cur = self._raw.cursor()
        cur.execute(traducir(sql), tuple(params))
        return Cursor(cur)

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()

    def __enter__(self):
        return self

    def __exit__(self, tipo, valor, tb):
        if tipo is None:
            self._raw.commit()
        else:
            self._raw.rollback()
        return False


def _conectar_raw(con_base=True):
    cfg = configuracion()
    args = dict(host=cfg["host"], port=cfg["port"], user=cfg["user"], password=cfg["password"],
                charset="utf8mb4", autocommit=False, conv=_convertidores(),
                client_flag=CLIENT.FOUND_ROWS)  # rowcount = filas encontradas, como en SQLite
    if con_base:
        args["database"] = cfg["database"]
    raw = pymysql.connect(**args)
    with raw.cursor() as cur:
        # PIPES_AS_CONCAT: la app usa || para concatenar texto, igual que SQLite.
        cur.execute("SET SESSION sql_mode = 'PIPES_AS_CONCAT,STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION'")
        cur.execute("SET SESSION time_zone = SYSTEM")
    return raw


def conectar():
    return Conexion(_conectar_raw())


# ---------------- Creación de la base ----------------
def dividir_sql(texto):
    """Separa un script SQL en sentencias respetando las líneas `DELIMITER` (para los triggers)."""
    delimitador, actual, sentencias = ";", [], []
    for linea in texto.splitlines():
        limpia = linea.strip()
        if limpia.upper().startswith("DELIMITER "):
            delimitador = limpia.split(None, 1)[1].strip()
            continue
        if not limpia or limpia.startswith("--"):
            continue
        actual.append(linea)
        if limpia.endswith(delimitador):
            sentencia = "\n".join(actual).rstrip()
            sentencia = sentencia[: -len(delimitador)].rstrip()
            if sentencia:
                sentencias.append(sentencia)
            actual = []
    resto = "\n".join(actual).strip()
    if resto:
        sentencias.append(resto)
    return sentencias


def inicializar(ruta_schema):
    """Crea la base y todas sus tablas, vistas y triggers (se puede ejecutar varias veces)."""
    cfg = configuracion()
    raw = _conectar_raw(con_base=False)
    try:
        with raw.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{cfg['database']}` "
                        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            cur.execute(f"USE `{cfg['database']}`")
            with open(ruta_schema, encoding="utf-8") as f:
                for sentencia in dividir_sql(f.read()):
                    if re.match(r"(CREATE DATABASE|USE)\b", sentencia, re.IGNORECASE):
                        continue  # la base ya se creó y seleccionó arriba con el nombre configurado
                    cur.execute(sentencia)
        raw.commit()
    finally:
        raw.close()
