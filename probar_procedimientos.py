"""Prueba los procedimientos que devuelven varias tablas (phpMyAdmin no los muestra bien).
Uso (con XAMPP/MySQL encendido y el venv activo):  python probar_procedimientos.py [FOLIO]
"""
import sys
import db_mysql

folio = sys.argv[1] if len(sys.argv) > 1 else "TC-PRUEBA-0001"
llamadas = [
    ("sp_resumen_orden", "CALL sp_resumen_orden(%s)", (folio,)),
    ("sp_corte_ingresos", "CALL sp_corte_ingresos(DATE_FORMAT(NOW(), '%%Y-%%m-01'), CURDATE())", ()),
]
raw = db_mysql._conectar_raw()
try:
    for nombre, sql, params in llamadas:
        print("=" * 70)
        print(nombre, params)
        with raw.cursor() as cur:
            cur.execute(sql, params)
            n = 1
            while True:
                if cur.description:
                    cols = [d[0] for d in cur.description]
                    print(f"\n  -- Resultado {n}: {cols}")
                    for fila in cur.fetchall():
                        print("    ", fila)
                    n += 1
                if not cur.nextset():
                    break
        raw.commit()
finally:
    raw.close()
print("\nListo.")
