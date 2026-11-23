# Arquitectura de Reviva: Taller de Celulares

El navegador solo habla con Flask, y solo Flask habla con la base de datos.

```
Navegador  <-- HTTP, puerto 5000 -->  Flask (app.py)  <-- SQL -->  db_mysql.py  <-- SQL, puerto 3306 -->  MySQL / MariaDB (XAMPP)
                                          |
                                          +-- (alternativa) SQLite con DB_ENGINE=sqlite
phpMyAdmin se usa solo para ver y probar la base en vivo.
```

## Tecnologías
Python 3 y Flask, PyMySQL, MySQL/MariaDB de XAMPP, plantillas Jinja2 con HTML, CSS y JavaScript,
`qrcode` y Pillow (QR e imágenes) y ReportLab (PDF).

## Estructura
| Ruta | Contenido |
| --- | --- |
| `app.py` | Rutas, reglas de negocio, PDFs, WhatsApp y respaldos |
| `db_mysql.py` | Conexión a MySQL y traducción del SQL de SQLite |
| `database/schema_mysql.sql` | Tablas, vistas, triggers y procedimientos (MySQL) |
| `database/schema.sql` | El mismo esquema para SQLite |
| `templates/`, `static/` | Pantallas HTML, estilos y JavaScript |
| `tests/` | Pruebas automáticas |
| `pruebas_mysql.sql` | Pruebas de triggers y procedimientos para phpMyAdmin |

## Base de datos
14 tablas, 9 vistas, 13 triggers, 6 procedimientos almacenados y 1 función.
Las reglas más importantes las hace cumplir la propia base: los estados avanzan en orden,
no se repara sin presupuesto aprobado, un pago no puede exceder el total y la bitácora no se edita.

## Flujo de una reparación
Recibido -> En Diagnóstico -> En Reparación -> Listo -> Entregado
