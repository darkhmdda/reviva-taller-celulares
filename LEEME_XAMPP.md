# Reviva con MySQL (XAMPP + phpMyAdmin)

La app puede guardar todo en MySQL/MariaDB de XAMPP en lugar de SQLite. Así ves los cambios en vivo en
http://localhost/phpmyadmin/ (base `taller_celulares`).

## Pasos (Windows, cmd)
1. Abre el Panel de XAMPP y pulsa **Start** en **Apache** y **MySQL**.
2. En la carpeta del proyecto:
   ```
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. (Solo si ya tienes datos en SQLite que quieres llevar a MySQL)
   ```
   set DB_ENGINE=mysql
   python migrar_a_mysql.py
   ```
4. Inicia la app (usa MySQL por defecto, con `python app.py` o con `iniciar_mysql.bat`):
   ```
   python app.py
   ```
   La primera vez crea la base `taller_celulares` con sus 14 tablas, 9 vistas y 13 triggers.
5. Abre http://127.0.0.1:5000/login y en otra pestaña http://localhost/phpmyadmin/ -> `taller_celulares`.
   Después de cada acción en la app, pulsa el nombre de la tabla (o F5) en phpMyAdmin para ver el cambio.

## Importar el esquema a mano desde phpMyAdmin (opcional)
Pestaña **Importar** -> elige `database/schema_mysql.sql` -> Continuar. (Trae `DELIMITER` para los triggers.)

## Volver a SQLite
`set DB_ENGINE=sqlite` y luego `python app.py`. Las dos bases son independientes.

## Probar triggers y procedimientos
Abre `pruebas_mysql.sql` y ejecuta bloque por bloque en phpMyAdmin (pestaña SQL).

## Variables
`DB_ENGINE=mysql`, `MYSQL_HOST` (127.0.0.1), `MYSQL_PORT` (3306), `MYSQL_USER` (root),
`MYSQL_PASSWORD` (vacía en XAMPP), `MYSQL_DB` (taller_celulares).
