# Reviva: Taller de Celulares

Sistema web para recepción, diagnóstico, seguimiento y entrega de reparaciones de celulares.
Python + Flask, base de datos MySQL/MariaDB (XAMPP), con SQLite como alternativa.

## Qué incluye
- Roles Administrador y Técnico, tablero Kanban, recepción con checklist, patrón de 9 puntos y fotos.
- Ticket PDF con QR, etiqueta del equipo y recibo; portal público de seguimiento por folio.
- Presupuesto con aprobación del cliente, pagos y anticipos, garantías por IMEI y reseñas.
- Inventario con alerta de stock bajo, cortes financieros y exportación CSV.
- Base de datos: 14 tablas, 9 vistas, 13 triggers, 6 procedimientos almacenados y 1 función.

## Cómo ejecutarlo (Windows)
1. Abre XAMPP y pulsa Start en MySQL.
2. En la carpeta del proyecto: `iniciar_mysql.bat` (crea el entorno, instala y arranca).
3. Abre http://127.0.0.1:5000 y entra como administrador (cambia la contraseña inicial).

Más detalle en `LEEME_XAMPP.md`. Para abrirlo a otros equipos de la misma red: `set HOST=0.0.0.0`
y luego `python app.py`; los demás entran con `http://TU_IP:5000`.

## Estructura
- `app.py`: aplicación Flask (rutas, reglas de negocio, PDFs).
- `db_mysql.py`: conector MySQL con la misma interfaz que sqlite3.
- `database/schema_mysql.sql` y `database/schema.sql`: esquema completo (MySQL y SQLite).
- `templates/`, `static/`: interfaz.
- `tests/`: pruebas automáticas. `pruebas_mysql.sql`: pruebas de triggers y procedimientos.
Repositorio del examen final: Base de Datos II, Ingeniería de Software I y Teleprocesos y Redes.
