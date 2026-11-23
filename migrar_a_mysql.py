"""Copia los datos de la base SQLite (database/taller.db) a MySQL/MariaDB de XAMPP.

Uso (con XAMPP encendido: Apache y MySQL):
    python migrar_a_mysql.py                     # usa database/taller.db
    python migrar_a_mysql.py ruta\\otra_base.db

Crea la base y las tablas si no existen, y copia todos los registros.
Si la base MySQL ya tiene datos, se detiene para no duplicarlos (usa --forzar para vaciarla primero).
"""
import os
import sqlite3
import sys

import db_mysql

BASE = os.path.dirname(os.path.abspath(__file__))
ORDEN = ["usuarios", "clientes", "equipos", "refacciones", "ordenes", "historial_estados", "resenas",
         "bitacora", "notas", "plantillas", "fotos", "pagos", "auditoria_refacciones", "alertas_stock"]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    forzar = "--forzar" in sys.argv
    origen_ruta = args[0] if args else os.path.join(BASE, "database", "taller.db")
    if not os.path.exists(origen_ruta):
        sys.exit(f"No encuentro la base SQLite: {origen_ruta}")

    db_mysql.inicializar(os.path.join(BASE, "database", "schema_mysql.sql"))
    destino = db_mysql.conectar()
    origen = sqlite3.connect(origen_ruta)
    origen.row_factory = sqlite3.Row
    existentes = {r[0] for r in origen.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    if destino.execute("SELECT COUNT(*) FROM ordenes").fetchone()[0] or \
            destino.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]:
        if not forzar:
            sys.exit("La base MySQL ya tiene datos. Si quieres reemplazarlos, ejecuta con --forzar.")
        destino.execute("SET FOREIGN_KEY_CHECKS = 0")
        for t in reversed(ORDEN):
            destino.execute(f"DELETE FROM {t}")
        destino.execute("SET FOREIGN_KEY_CHECKS = 1")
        destino.commit()

    actualizado = {}
    for tabla in ORDEN:
        if tabla not in existentes:
            continue
        filas = origen.execute(f"SELECT * FROM {tabla}").fetchall()
        if not filas:
            print(f"{tabla:24s} 0")
            continue
        cols = filas[0].keys()
        if tabla == "ordenes":
            actualizado = {f["id"]: f["actualizado_en"] for f in filas}
        sql = f"INSERT INTO {tabla} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        for f in filas:
            destino.execute(sql, tuple(f[c] for c in cols))
        destino.commit()
        print(f"{tabla:24s} {len(filas)}")

    # Los triggers de MySQL tocan actualizado_en al insertar pagos: se restaura el valor original.
    for oid, valor in actualizado.items():
        destino.execute("UPDATE ordenes SET actualizado_en = ? WHERE id = ?", (valor, oid))
    destino.commit()
    destino.close()
    origen.close()
    print("Listo: los datos ya están en MySQL (phpMyAdmin, base taller_celulares).")


if __name__ == "__main__":
    main()
