-- ===================================================================
-- PRUEBAS DE TRIGGERS Y PROCEDIMIENTOS (phpMyAdmin -> base taller_celulares -> pestaña SQL)
--
-- IMPORTANTE: phpMyAdmin se DETIENE en el primer error. Por eso:
--   * Los bloques marcados [JUNTO] no fallan: puedes pegarlos completos y ejecutarlos de una vez.
--   * Los comandos marcados [SOLO] DEBEN FALLAR: pega y ejecuta UNO a la vez.
--     Que salga un error en rojo con el mensaje indicado = el trigger funcionó.
-- Se asume que el administrador tiene id = 1.
-- Orden sugerido: 99 (limpiar, por si quedaron datos) -> 0 -> A -> B -> C -> D -> 99.
-- ===================================================================

-- ------------------------------------------------------------------
-- BLOQUE 99. LIMPIAR DATOS DE PRUEBA  [JUNTO]  (ejecútalo primero y al terminar)
-- ------------------------------------------------------------------
DELETE FROM ordenes WHERE folio IN ('TC-PRUEBA-0001', 'TC-PRUEBA-0002');
DELETE FROM equipos WHERE imei = '999999999999999';
DELETE FROM clientes WHERE nombre = 'Cliente Prueba SQL';
DELETE FROM refacciones WHERE nombre = 'Pantalla PRUEBA';

-- ------------------------------------------------------------------
-- BLOQUE 0. PREPARAR DATOS DE PRUEBA  [JUNTO]
-- ------------------------------------------------------------------
INSERT INTO clientes (nombre, telefono) VALUES ('Cliente Prueba SQL', '4420000000');
INSERT INTO equipos (imei, marca, modelo, cliente_id)
VALUES ('999999999999999', 'Prueba', 'Modelo X', (SELECT MAX(id) FROM clientes));
INSERT INTO refacciones (nombre, categoria, stock, stock_minimo, costo_proveedor, precio_venta)
VALUES ('Pantalla PRUEBA', 'Pantalla', 3, 2, 400, 750);
INSERT INTO ordenes (folio, equipo_id, recibido_por, falla_reportada, refaccion_id,
                     costo_refaccion, costo_proveedor, mano_obra)
VALUES ('TC-PRUEBA-0001', (SELECT MAX(id) FROM equipos), 1, 'Pantalla rota',
        (SELECT MAX(id) FROM refacciones), 750, 400, 200);
SELECT folio, estado, presupuesto_estado, costo_refaccion + mano_obra AS total
  FROM ordenes WHERE folio = 'TC-PRUEBA-0001';

-- ==================================================================
-- PARTE A. TRIGGERS Y RESTRICCIONES QUE RECHAZAN  [SOLO]  (uno por uno; todos DEBEN FALLAR)
-- La orden TC-PRUEBA-0001 está en estado Recibido.
-- ==================================================================

-- A1 (T2) DEBE FALLAR: "Transición de estado no permitida" (Recibido -> Entregado salta pasos)
UPDATE ordenes SET estado = 'Entregado' WHERE folio = 'TC-PRUEBA-0001';

-- A2 (T2) DEBE FALLAR: "Transición de estado no permitida" (Recibido -> En Reparación salta un paso)
UPDATE ordenes SET estado = 'En Reparación' WHERE folio = 'TC-PRUEBA-0001';

-- A3 (T5) DEBE FALLAR: "El folio y la fecha de ingreso no se pueden modificar"
UPDATE ordenes SET folio = 'OTRO-FOLIO' WHERE folio = 'TC-PRUEBA-0001';

-- A4 (T6) DEBE FALLAR: "El pago excede el total de la orden" (la orden vale 950)
INSERT INTO pagos (orden_id, monto, tipo, metodo)
VALUES ((SELECT id FROM ordenes WHERE folio = 'TC-PRUEBA-0001'), 5000, 'Abono', 'Efectivo');

-- A5 (T8) DEBE FALLAR: "Solo se puede reseñar una orden entregada"
INSERT INTO resenas (orden_id, calificacion)
VALUES ((SELECT id FROM ordenes WHERE folio = 'TC-PRUEBA-0001'), 5);

-- A6 (T12) DEBE FALLAR: "El IMEI solo debe contener dígitos"
INSERT INTO equipos (imei, marca, modelo, cliente_id)
VALUES ('35693803AB43809', 'X', 'Y', (SELECT MAX(id) FROM clientes));

-- A7 (T11) DEBE FALLAR: "Debe existir al menos un administrador activo"
-- (si tienes varios administradores, la sentencia completa se deshace y no cambia nada)
UPDATE usuarios SET activo = 0 WHERE rol = 'admin';

-- A8 (CHECK) DEBE FALLAR: Constraint chk_pagos_monto failed (monto debe ser > 0)
INSERT INTO pagos (orden_id, monto) VALUES ((SELECT id FROM ordenes WHERE folio = 'TC-PRUEBA-0001'), 0);

-- A9 (UNIQUE) DEBE FALLAR: #1062 Duplicate entry '999999999999999' (IMEI repetido)
INSERT INTO equipos (imei, marca, modelo, cliente_id) VALUES ('999999999999999', 'X', 'Y', (SELECT MAX(id) FROM clientes));

-- A10 (FOREIGN KEY) DEBE FALLAR: #1452 a foreign key constraint fails (equipo inexistente)
INSERT INTO ordenes (folio, equipo_id, recibido_por, falla_reportada) VALUES ('TC-FK', 999999, 1, 'x');

-- ==================================================================
-- PARTE B. TRIGGERS AUTOMÁTICOS  [JUNTO]  (no fallan; mira los resultados de cada SELECT)
-- (ya la ejecutaste sin errores; repítela si quieres capturas)
-- ==================================================================
SELECT folio, actualizado_en FROM ordenes WHERE folio = 'TC-PRUEBA-0001';
UPDATE ordenes SET diagnostico = 'Pantalla dañada, requiere cambio' WHERE folio = 'TC-PRUEBA-0001';
SELECT folio, diagnostico, actualizado_en FROM ordenes WHERE folio = 'TC-PRUEBA-0001';   -- B1 (T1): actualizado_en cambió solo

UPDATE refacciones SET stock = 1 WHERE nombre = 'Pantalla PRUEBA';
SELECT refaccion_id, stock_anterior, stock_nuevo, precio_anterior, precio_nuevo FROM auditoria_refacciones
 WHERE refaccion_id = (SELECT id FROM refacciones WHERE nombre = 'Pantalla PRUEBA');       -- B2 (T9): fila de auditoría 3 -> 1
SELECT refaccion_id, stock, stock_minimo, atendida FROM alertas_stock
 WHERE refaccion_id = (SELECT id FROM refacciones WHERE nombre = 'Pantalla PRUEBA');       -- B2 (T10): alerta con stock 1, mínimo 2
SELECT * FROM v_stock_bajo;                                                                 -- la vista la muestra

UPDATE refacciones SET precio_venta = 800 WHERE nombre = 'Pantalla PRUEBA';
SELECT stock_anterior, stock_nuevo, precio_anterior, precio_nuevo FROM auditoria_refacciones
 WHERE refaccion_id = (SELECT id FROM refacciones WHERE nombre = 'Pantalla PRUEBA') ORDER BY id;  -- B3: otra fila, 750 -> 800

-- Deja el precio y el stock como estaban para la parte C
UPDATE refacciones SET precio_venta = 750, stock = 3 WHERE nombre = 'Pantalla PRUEBA';

-- ==================================================================
-- PARTE C. FLUJO COMPLETO CON PROCEDIMIENTOS  [JUNTO]  (ninguno falla)
-- Requiere el BLOQUE 0 (orden en Recibido). Si ya moviste esa orden, ejecuta 99 y 0 de nuevo.
-- ==================================================================
CALL sp_cambiar_estado('TC-PRUEBA-0001', 'En Diagnóstico', 1);
CALL sp_aprobar_presupuesto('TC-PRUEBA-0001', 1, 1);                       -- aprueba y descuenta 1 pieza
SELECT nombre, stock FROM refacciones WHERE nombre = 'Pantalla PRUEBA';    -- stock 3 -> 2
SELECT stock_descontado FROM ordenes WHERE folio = 'TC-PRUEBA-0001';       -- 1
CALL sp_registrar_pago('TC-PRUEBA-0001', 300, 'Anticipo', 'Efectivo', 1);
SELECT fn_saldo_orden((SELECT id FROM ordenes WHERE folio = 'TC-PRUEBA-0001')) AS saldo;   -- 650
CALL sp_cambiar_estado('TC-PRUEBA-0001', 'En Reparación', 1);
CALL sp_cambiar_estado('TC-PRUEBA-0001', 'Listo', 1);
CALL sp_registrar_pago('TC-PRUEBA-0001', 650, 'Pago final', 'Tarjeta', 1);
CALL sp_cambiar_estado('TC-PRUEBA-0001', 'Entregado', 1);                  -- T4 pone fecha_entrega
SELECT folio, estado, fecha_entrega, garantia_dias FROM ordenes WHERE folio = 'TC-PRUEBA-0001';
INSERT INTO resenas (orden_id, calificacion, comentario)                   -- T8 ahora sí lo permite
VALUES ((SELECT id FROM ordenes WHERE folio = 'TC-PRUEBA-0001'), 5, 'Excelente servicio');
CALL sp_resumen_orden('TC-PRUEBA-0001');                                   -- 3 resultados: ficha, historial, pagos
CALL sp_corte_ingresos(DATE_FORMAT(NOW(), '%Y-%m-01'), CURDATE());         -- 2 resultados: ingresos y utilidad

-- Reabastecer: baja el stock a 0 (alerta pendiente) y súbelo con el procedimiento (alerta atendida)
UPDATE refacciones SET stock = 0 WHERE nombre = 'Pantalla PRUEBA';
SELECT refaccion_id, stock, atendida FROM alertas_stock
 WHERE refaccion_id = (SELECT id FROM refacciones WHERE nombre = 'Pantalla PRUEBA') ORDER BY id;   -- atendida = 0
CALL sp_reabastecer((SELECT id FROM refacciones WHERE nombre = 'Pantalla PRUEBA'), 5);
SELECT refaccion_id, stock, atendida FROM alertas_stock
 WHERE refaccion_id = (SELECT id FROM refacciones WHERE nombre = 'Pantalla PRUEBA') ORDER BY id;   -- atendida = 1

-- ==================================================================
-- PARTE D. PROCEDIMIENTOS Y TRIGGERS QUE RECHAZAN  (alternando [JUNTO] y [SOLO])
-- Requiere haber ejecutado el BLOQUE 0 y la PARTE C.
-- ==================================================================

-- D0 [JUNTO] Segunda orden de prueba, en En Diagnóstico con presupuesto pendiente
INSERT INTO ordenes (folio, equipo_id, recibido_por, falla_reportada, refaccion_id,
                     costo_refaccion, costo_proveedor, mano_obra)
VALUES ('TC-PRUEBA-0002', (SELECT MAX(id) FROM equipos), 1, 'Otra falla',
        (SELECT MAX(id) FROM refacciones), 750, 400, 200);
CALL sp_cambiar_estado('TC-PRUEBA-0002', 'En Diagnóstico', 1);

-- D1 [SOLO] DEBE FALLAR: "El presupuesto debe estar aprobado antes de reparar" (trigger T3 vía procedimiento)
CALL sp_cambiar_estado('TC-PRUEBA-0002', 'En Reparación', 1);

-- D1b [JUNTO] Aprueba y deja la orden 0002 en Listo con saldo pendiente
CALL sp_aprobar_presupuesto('TC-PRUEBA-0002', 1, 1);
CALL sp_cambiar_estado('TC-PRUEBA-0002', 'En Reparación', 1);
CALL sp_cambiar_estado('TC-PRUEBA-0002', 'Listo', 1);

-- D2 [SOLO] DEBE FALLAR: "Hay un saldo pendiente: registra el pago antes de entregar"
CALL sp_cambiar_estado('TC-PRUEBA-0002', 'Entregado', 1);

-- D3 [SOLO] DEBE FALLAR: "La bitácora no se puede modificar" (trigger T13)
UPDATE bitacora SET accion = 'alterada'
 WHERE orden_id = (SELECT id FROM ordenes WHERE folio = 'TC-PRUEBA-0001');

-- D4 [SOLO] DEBE FALLAR: "La cantidad debe ser mayor a cero"
CALL sp_reabastecer((SELECT id FROM refacciones WHERE nombre = 'Pantalla PRUEBA'), 0);

-- D5 [SOLO] DEBE FALLAR: "No existe una orden con ese folio"
CALL sp_registrar_pago('NO-EXISTE', 100, 'Abono', 'Efectivo', 1);

-- Al terminar: ejecuta el BLOQUE 99 para borrar los datos de prueba.
