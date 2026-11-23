"""Pruebas de la capa MySQL que no necesitan un servidor: traducción de SQL, filas y lectura del esquema.

Se omiten si PyMySQL no está instalado (pip install PyMySQL).
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import db_mysql
except ImportError:  # PyMySQL no instalado
    db_mysql = None

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipIf(db_mysql is None, "PyMySQL no instalado")
class CapaMySQL(unittest.TestCase):
    def test_marcadores_y_porcentajes(self):
        self.assertEqual(db_mysql.traducir("SELECT * FROM t WHERE a = ? AND b LIKE '%x'"),
                         "SELECT * FROM t WHERE a = %s AND b LIKE '%%x'")

    def test_busqueda_sin_acentos(self):
        sql = db_mysql.traducir("WHERE norm(c.nombre) LIKE ? ESCAPE '\\'")
        self.assertEqual(sql, "WHERE c.nombre LIKE %s")

    def test_fechas(self):
        self.assertIn("NOW() - INTERVAL 7 DAY", db_mysql.traducir("x < datetime('now','localtime','-7 days')"))
        self.assertEqual(db_mysql.traducir("date('now','localtime')"), "CURDATE()")

    def test_upsert(self):
        sql = db_mysql.traducir("INSERT INTO p (estado, texto) VALUES (?, ?) ON CONFLICT(estado) DO UPDATE SET texto = excluded.texto")
        self.assertIn("ON DUPLICATE KEY UPDATE texto = VALUES(texto)", sql)

    def test_fila_como_sqlite_row(self):
        f = db_mysql.Fila(["id", "nombre"], (7, "Ana"))
        a, b = f
        self.assertEqual((f["id"], f[1], a, b, tuple(f), dict(f)), (7, "Ana", 7, "Ana", (7, "Ana"), {"id": 7, "nombre": "Ana"}))
        with self.assertRaises(KeyError):
            f["no_existe"]

    def test_esquema_mysql_se_divide_bien(self):
        with open(os.path.join(BASE, "database", "schema_mysql.sql"), encoding="utf-8") as fh:
            sentencias = db_mysql.dividir_sql(fh.read())
        tipos = [re.match(r"(CREATE TABLE|CREATE OR REPLACE VIEW|CREATE TRIGGER|DROP TRIGGER)", s) for s in sentencias]
        cuenta = {k: sum(1 for t in tipos if t and t.group(1) == k)
                  for k in ("CREATE TABLE", "CREATE OR REPLACE VIEW", "CREATE TRIGGER", "DROP TRIGGER")}
        self.assertEqual(cuenta, {"CREATE TABLE": 14, "CREATE OR REPLACE VIEW": 9, "CREATE TRIGGER": 13, "DROP TRIGGER": 13})
        for s in sentencias:
            self.assertEqual(s.count("("), s.count(")"))


if __name__ == "__main__":
    unittest.main()
