@echo off
cd /d "%~dp0"
echo === Reviva con MySQL (XAMPP) ===
echo Carpeta: %CD%

if not exist venv\Scripts\activate.bat (
    echo Creando entorno virtual...
    python -m venv venv
    if errorlevel 1 (
        echo.
        echo ERROR: no se pudo crear el entorno. Prueba con: py -m venv venv
        goto fin
    )
)
call venv\Scripts\activate.bat

echo Instalando dependencias (solo tarda la primera vez)...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR instalando dependencias. Revisa tu conexion a internet.
    goto fin
)

set DB_ENGINE=mysql
set MYSQL_HOST=127.0.0.1
set MYSQL_PORT=3306
set MYSQL_USER=root
set MYSQL_PASSWORD=
set MYSQL_DB=taller_celulares

echo.
echo Iniciando (MySQL debe estar en Start en el panel de XAMPP)...
python app.py

:fin
echo.
echo La aplicacion se detuvo. Copia los mensajes de arriba si hubo un error.
pause
