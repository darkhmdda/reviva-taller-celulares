-- ===============================================================
-- Esquema MySQL / MariaDB (XAMPP): Reviva: Taller de Celulares (Taller de Reparación de Celulares)
-- Equivalente al esquema de SQLite (database/schema.sql).
-- Se puede importar desde phpMyAdmin (pestaña Importar) o lo crea solo la
-- aplicación al iniciar con DB_ENGINE=mysql.
-- Diferencias con SQLite: FK obligatoriamente después de su tabla padre,
-- fechas DATETIME, índices parciales no existen (son índices normales),
-- los triggers usan SIGNAL en lugar de RAISE y IF en lugar de WHEN.
-- ===============================================================

CREATE DATABASE IF NOT EXISTS taller_celulares
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE taller_celulares;

-- ---------------- Tablas ----------------
CREATE TABLE IF NOT EXISTS usuarios (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    nombre         VARCHAR(150) NOT NULL,
    email          VARCHAR(190) NOT NULL UNIQUE,
    password_hash  VARCHAR(255) NOT NULL,
    rol            VARCHAR(10)  NOT NULL,
    activo         TINYINT      NOT NULL DEFAULT 1,
    creado_en      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_usuarios_rol    CHECK (rol IN ('admin', 'tecnico')),
    CONSTRAINT chk_usuarios_activo CHECK (activo IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS clientes (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    nombre     VARCHAR(150) NOT NULL,
    telefono   VARCHAR(30)  NOT NULL,
    email      VARCHAR(190) NULL,
    creado_en  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_clientes_telefono (telefono),
    INDEX idx_clientes_nombre (nombre)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS equipos (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    imei              VARCHAR(16)  NOT NULL UNIQUE,
    marca             VARCHAR(80)  NOT NULL,
    modelo            VARCHAR(120) NOT NULL,
    color             VARCHAR(60)  NULL,
    cliente_id        INT          NOT NULL,
    patron_desbloqueo VARCHAR(40)  NULL,
    pin_desbloqueo    VARCHAR(40)  NULL,
    creado_en         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_equipos_cliente (cliente_id),
    CONSTRAINT chk_equipos_imei CHECK (CHAR_LENGTH(imei) BETWEEN 14 AND 16),
    CONSTRAINT fk_equipos_cliente FOREIGN KEY (cliente_id) REFERENCES clientes(id)
        ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS refacciones (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    nombre            VARCHAR(150) NOT NULL,
    categoria         VARCHAR(20)  NOT NULL DEFAULT 'Otro',
    marca_compatible  VARCHAR(80)  NULL,
    modelo_compatible VARCHAR(120) NULL,
    stock             INT          NOT NULL DEFAULT 0,
    stock_minimo      INT          NOT NULL DEFAULT 2,
    costo_proveedor   DOUBLE       NOT NULL DEFAULT 0,
    precio_venta      DOUBLE       NOT NULL DEFAULT 0,
    activo            TINYINT      NOT NULL DEFAULT 1,
    INDEX idx_refacciones_categoria (categoria),
    INDEX idx_refacciones_stock (stock),
    CONSTRAINT chk_refacciones_categoria CHECK (categoria IN ('Batería', 'Centro de carga', 'Pantalla', 'Otro')),
    CONSTRAINT chk_refacciones_stock     CHECK (stock >= 0),
    CONSTRAINT chk_refacciones_minimo    CHECK (stock_minimo >= 0),
    CONSTRAINT chk_refacciones_costo     CHECK (costo_proveedor >= 0),
    CONSTRAINT chk_refacciones_precio    CHECK (precio_venta >= 0),
    CONSTRAINT chk_refacciones_activo    CHECK (activo IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ordenes (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    folio              VARCHAR(30) NOT NULL UNIQUE,
    equipo_id          INT         NOT NULL,
    tecnico_id         INT         NULL,
    recibido_por       INT         NOT NULL,
    estado             VARCHAR(20) NOT NULL DEFAULT 'Recibido',
    falla_reportada    TEXT        NOT NULL,
    diagnostico        TEXT        NULL,
    chk_pantalla_estrellada TINYINT NOT NULL DEFAULT 0,
    chk_tapa_rota           TINYINT NOT NULL DEFAULT 0,
    chk_equipo_mojado       TINYINT NOT NULL DEFAULT 0,
    chk_sin_bandeja_sim     TINYINT NOT NULL DEFAULT 0,
    observaciones_fisicas   TEXT    NULL,
    refaccion_id       INT         NULL,
    costo_refaccion    DOUBLE      NOT NULL DEFAULT 0,
    costo_proveedor    DOUBLE      NOT NULL DEFAULT 0,
    mano_obra          DOUBLE      NOT NULL DEFAULT 0,
    presupuesto_estado VARCHAR(10) NOT NULL DEFAULT 'Pendiente',
    presupuesto_fecha  DATETIME    NULL,
    stock_descontado   TINYINT     NOT NULL DEFAULT 0,
    garantia_dias      INT         NOT NULL DEFAULT 30,
    fecha_ingreso      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_entrega      DATETIME    NULL,
    fecha_promesa      DATE        NULL,
    actualizado_en     DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_ordenes_estado (estado),
    INDEX idx_ordenes_equipo (equipo_id),
    INDEX idx_ordenes_tecnico (tecnico_id),
    INDEX idx_ordenes_fecha (fecha_ingreso),
    INDEX idx_ordenes_presupuesto (presupuesto_estado),
    INDEX idx_ordenes_activas (estado, actualizado_en),
    CONSTRAINT chk_ordenes_estado CHECK (estado IN ('Recibido','En Diagnóstico','En Reparación','Listo','Entregado')),
    CONSTRAINT chk_ordenes_pantalla CHECK (chk_pantalla_estrellada IN (0,1)),
    CONSTRAINT chk_ordenes_tapa     CHECK (chk_tapa_rota IN (0,1)),
    CONSTRAINT chk_ordenes_mojado   CHECK (chk_equipo_mojado IN (0,1)),
    CONSTRAINT chk_ordenes_sim      CHECK (chk_sin_bandeja_sim IN (0,1)),
    CONSTRAINT chk_ordenes_costo_ref  CHECK (costo_refaccion >= 0),
    CONSTRAINT chk_ordenes_costo_prov CHECK (costo_proveedor >= 0),
    CONSTRAINT chk_ordenes_mano_obra  CHECK (mano_obra >= 0),
    CONSTRAINT chk_ordenes_presupuesto CHECK (presupuesto_estado IN ('Pendiente','Aprobado','Rechazado')),
    CONSTRAINT chk_ordenes_descontado CHECK (stock_descontado IN (0,1)),
    CONSTRAINT chk_ordenes_garantia   CHECK (garantia_dias >= 0),
    CONSTRAINT fk_ordenes_equipo    FOREIGN KEY (equipo_id)    REFERENCES equipos(id)     ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_ordenes_tecnico   FOREIGN KEY (tecnico_id)   REFERENCES usuarios(id)    ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_ordenes_recibido  FOREIGN KEY (recibido_por) REFERENCES usuarios(id)    ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_ordenes_refaccion FOREIGN KEY (refaccion_id) REFERENCES refacciones(id) ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS historial_estados (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    orden_id    INT         NOT NULL,
    estado      VARCHAR(20) NOT NULL,
    usuario_id  INT         NULL,
    fecha       DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_historial_orden (orden_id),
    CONSTRAINT fk_historial_orden   FOREIGN KEY (orden_id)   REFERENCES ordenes(id)  ON DELETE CASCADE,
    CONSTRAINT fk_historial_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS resenas (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    orden_id     INT      NOT NULL UNIQUE,
    calificacion INT      NOT NULL,
    comentario   TEXT     NULL,
    fecha        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_resenas_calificacion CHECK (calificacion BETWEEN 1 AND 5),
    CONSTRAINT fk_resenas_orden FOREIGN KEY (orden_id) REFERENCES ordenes(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS bitacora (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    orden_id   INT          NOT NULL,
    usuario_id INT          NULL,
    actor      VARCHAR(150) NOT NULL,
    accion     TEXT         NOT NULL,
    fecha      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_bitacora_orden (orden_id),
    INDEX idx_bitacora_fecha (fecha),
    CONSTRAINT fk_bitacora_orden   FOREIGN KEY (orden_id)   REFERENCES ordenes(id)  ON DELETE CASCADE,
    CONSTRAINT fk_bitacora_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS pagos (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    orden_id   INT         NOT NULL,
    monto      DOUBLE      NOT NULL,
    tipo       VARCHAR(12) NOT NULL DEFAULT 'Abono',
    metodo     VARCHAR(15) NOT NULL DEFAULT 'Efectivo',
    usuario_id INT         NULL,
    fecha      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_pagos_orden (orden_id),
    INDEX idx_pagos_fecha (fecha),
    CONSTRAINT chk_pagos_monto  CHECK (monto > 0),
    CONSTRAINT chk_pagos_tipo   CHECK (tipo IN ('Anticipo','Abono','Pago final')),
    CONSTRAINT chk_pagos_metodo CHECK (metodo IN ('Efectivo','Tarjeta','Transferencia')),
    CONSTRAINT fk_pagos_orden   FOREIGN KEY (orden_id)   REFERENCES ordenes(id)  ON DELETE CASCADE,
    CONSTRAINT fk_pagos_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS notas (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    orden_id   INT          NOT NULL,
    usuario_id INT          NULL,
    autor      VARCHAR(150) NOT NULL,
    texto      TEXT         NOT NULL,
    fecha      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_notas_orden (orden_id),
    CONSTRAINT fk_notas_orden   FOREIGN KEY (orden_id)   REFERENCES ordenes(id)  ON DELETE CASCADE,
    CONSTRAINT fk_notas_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS plantillas (
    estado VARCHAR(30) PRIMARY KEY,
    texto  TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS fotos (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    orden_id   INT          NOT NULL,
    archivo    VARCHAR(190) NOT NULL UNIQUE,
    usuario_id INT          NULL,
    fecha      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_fotos_orden (orden_id),
    CONSTRAINT fk_fotos_orden   FOREIGN KEY (orden_id)   REFERENCES ordenes(id)  ON DELETE CASCADE,
    CONSTRAINT fk_fotos_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auditoria_refacciones (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    refaccion_id    INT      NOT NULL,
    stock_anterior  INT      NOT NULL,
    stock_nuevo     INT      NOT NULL,
    costo_anterior  DOUBLE   NOT NULL,
    costo_nuevo     DOUBLE   NOT NULL,
    precio_anterior DOUBLE   NOT NULL,
    precio_nuevo    DOUBLE   NOT NULL,
    fecha           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_auditoria_refaccion (refaccion_id),
    CONSTRAINT fk_auditoria_refaccion FOREIGN KEY (refaccion_id) REFERENCES refacciones(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS alertas_stock (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    refaccion_id INT      NOT NULL,
    stock        INT      NOT NULL,
    stock_minimo INT      NOT NULL,
    atendida     TINYINT  NOT NULL DEFAULT 0,
    fecha        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_alertas_pendientes (refaccion_id, atendida),
    CONSTRAINT chk_alertas_atendida CHECK (atendida IN (0, 1)),
    CONSTRAINT fk_alertas_refaccion FOREIGN KEY (refaccion_id) REFERENCES refacciones(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- Vistas ----------------
CREATE OR REPLACE VIEW v_stock_bajo AS
SELECT id, nombre, categoria, stock, stock_minimo
FROM refacciones
WHERE activo = 1 AND stock < stock_minimo;

CREATE OR REPLACE VIEW v_garantias AS
SELECT o.id AS orden_id, o.folio, e.imei, o.fecha_entrega, o.garantia_dias,
       DATE_ADD(DATE(o.fecha_entrega), INTERVAL o.garantia_dias DAY) AS vence,
       CASE WHEN CURDATE() <= DATE_ADD(DATE(o.fecha_entrega), INTERVAL o.garantia_dias DAY)
            THEN 1 ELSE 0 END AS vigente
FROM ordenes o
JOIN equipos e ON e.id = o.equipo_id
WHERE o.estado = 'Entregado' AND o.fecha_entrega IS NOT NULL;

CREATE OR REPLACE VIEW v_ordenes_resumen AS
SELECT o.id AS orden_id, o.folio, o.estado, o.fecha_ingreso, o.fecha_promesa,
       c.nombre AS cliente, c.telefono,
       e.marca, e.modelo, e.imei,
       t.nombre AS tecnico,
       o.presupuesto_estado,
       (o.costo_refaccion + o.mano_obra) AS total,
       COALESCE((SELECT SUM(p.monto) FROM pagos p WHERE p.orden_id = o.id), 0) AS pagado,
       (o.costo_refaccion + o.mano_obra)
         - COALESCE((SELECT SUM(p.monto) FROM pagos p WHERE p.orden_id = o.id), 0) AS saldo
FROM ordenes o
JOIN equipos  e ON e.id = o.equipo_id
JOIN clientes c ON c.id = e.cliente_id
LEFT JOIN usuarios t ON t.id = o.tecnico_id;

CREATE OR REPLACE VIEW v_saldos_pendientes AS
SELECT orden_id, folio, estado, cliente, telefono, total, pagado, saldo
FROM v_ordenes_resumen
WHERE saldo > 0.005 AND presupuesto_estado = 'Aprobado';

CREATE OR REPLACE VIEW v_carga_tecnicos AS
SELECT u.id AS tecnico_id, u.nombre AS tecnico,
       SUM(CASE WHEN o.estado <> 'Entregado' THEN 1 ELSE 0 END) AS ordenes_activas,
       SUM(CASE WHEN o.estado = 'Entregado'  THEN 1 ELSE 0 END) AS ordenes_entregadas,
       COUNT(o.id) AS ordenes_totales
FROM usuarios u
LEFT JOIN ordenes o ON o.tecnico_id = u.id
WHERE u.rol = 'tecnico' AND u.activo = 1
GROUP BY u.id, u.nombre;

CREATE OR REPLACE VIEW v_expediente_imei AS
SELECT e.imei, e.marca, e.modelo, c.nombre AS cliente,
       o.folio, o.fecha_ingreso, o.fecha_entrega, o.estado, o.falla_reportada, o.diagnostico
FROM equipos e
JOIN clientes c ON c.id = e.cliente_id
JOIN ordenes  o ON o.equipo_id = e.id;

CREATE OR REPLACE VIEW v_ingresos_mensuales AS
SELECT DATE_FORMAT(p.fecha, '%Y-%m') AS mes,
       COUNT(*)     AS num_pagos,
       SUM(p.monto) AS ingresos
FROM pagos p
GROUP BY DATE_FORMAT(p.fecha, '%Y-%m');

CREATE OR REPLACE VIEW v_refacciones_mas_usadas AS
SELECT r.id AS refaccion_id, r.nombre, r.categoria,
       COUNT(o.id) AS veces_usada,
       SUM(o.costo_refaccion - o.costo_proveedor) AS utilidad_refaccion
FROM refacciones r
JOIN ordenes o ON o.refaccion_id = r.id AND o.stock_descontado = 1
GROUP BY r.id, r.nombre, r.categoria;

CREATE OR REPLACE VIEW v_calificacion_promedio AS
SELECT COUNT(*) AS total_resenas,
       ROUND(AVG(calificacion), 2) AS promedio,
       SUM(CASE WHEN calificacion >= 4 THEN 1 ELSE 0 END) AS positivas
FROM resenas;

-- ---------------- Triggers ----------------
DELIMITER $$

DROP TRIGGER IF EXISTS trg_ordenes_touch$$
CREATE TRIGGER trg_ordenes_touch BEFORE UPDATE ON ordenes
FOR EACH ROW
BEGIN
    -- T1. Mantiene actualizado_en al modificar una orden
    IF NEW.actualizado_en = OLD.actualizado_en THEN
        SET NEW.actualizado_en = NOW();
    END IF;
END$$

DROP TRIGGER IF EXISTS trg_ordenes_transicion_estado$$
CREATE TRIGGER trg_ordenes_transicion_estado BEFORE UPDATE ON ordenes
FOR EACH ROW
BEGIN
    -- T2. Solo se avanza o retrocede un paso; Entregado es final
    DECLARE n_nuevo INT;
    DECLARE n_viejo INT;
    IF NEW.estado <> OLD.estado THEN
        SET n_nuevo = CASE NEW.estado WHEN 'Recibido' THEN 1 WHEN 'En Diagnóstico' THEN 2
                                      WHEN 'En Reparación' THEN 3 WHEN 'Listo' THEN 4 ELSE 5 END;
        SET n_viejo = CASE OLD.estado WHEN 'Recibido' THEN 1 WHEN 'En Diagnóstico' THEN 2
                                      WHEN 'En Reparación' THEN 3 WHEN 'Listo' THEN 4 ELSE 5 END;
        IF OLD.estado = 'Entregado'
           OR NOT (ABS(n_nuevo - n_viejo) = 1
                   OR (OLD.estado = 'En Diagnóstico' AND NEW.estado = 'Listo'
                       AND NEW.presupuesto_estado = 'Rechazado')) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Transición de estado no permitida';
        END IF;
    END IF;
END$$

DROP TRIGGER IF EXISTS trg_ordenes_requiere_aprobacion$$
CREATE TRIGGER trg_ordenes_requiere_aprobacion BEFORE UPDATE ON ordenes
FOR EACH ROW
BEGIN
    -- T3. No se repara sin presupuesto aprobado
    IF NEW.estado = 'En Reparación' AND OLD.estado <> 'En Reparación'
       AND NEW.presupuesto_estado <> 'Aprobado' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'El presupuesto debe estar aprobado antes de reparar';
    END IF;
END$$

DROP TRIGGER IF EXISTS trg_ordenes_fecha_entrega$$
CREATE TRIGGER trg_ordenes_fecha_entrega BEFORE UPDATE ON ordenes
FOR EACH ROW
BEGIN
    -- T4. Al entregar, asegura la fecha de entrega
    IF NEW.estado = 'Entregado' AND NEW.fecha_entrega IS NULL THEN
        SET NEW.fecha_entrega = NOW();
    END IF;
END$$

DROP TRIGGER IF EXISTS trg_ordenes_folio_inmutable$$
CREATE TRIGGER trg_ordenes_folio_inmutable BEFORE UPDATE ON ordenes
FOR EACH ROW
BEGIN
    -- T5. El folio y la fecha de ingreso nunca cambian
    IF NEW.folio <> OLD.folio OR NEW.fecha_ingreso <> OLD.fecha_ingreso THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'El folio y la fecha de ingreso no se pueden modificar';
    END IF;
END$$

DROP TRIGGER IF EXISTS trg_pagos_no_excede_total$$
CREATE TRIGGER trg_pagos_no_excede_total BEFORE INSERT ON pagos
FOR EACH ROW
BEGIN
    -- T6. Un pago no puede exceder el total de la orden
    DECLARE v_total DOUBLE;
    DECLARE v_pagado DOUBLE;
    SELECT costo_refaccion + mano_obra INTO v_total FROM ordenes WHERE id = NEW.orden_id;
    SELECT COALESCE(SUM(monto), 0) INTO v_pagado FROM pagos WHERE orden_id = NEW.orden_id;
    IF v_total > 0 AND v_pagado + NEW.monto > v_total + 0.005 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'El pago excede el total de la orden';
    END IF;
END$$

DROP TRIGGER IF EXISTS trg_pagos_touch_orden$$
CREATE TRIGGER trg_pagos_touch_orden AFTER INSERT ON pagos
FOR EACH ROW
BEGIN
    -- T7. Registrar un pago cuenta como actividad de la orden
    UPDATE ordenes SET actualizado_en = NOW() WHERE id = NEW.orden_id;
END$$

DROP TRIGGER IF EXISTS trg_resenas_solo_entregadas$$
CREATE TRIGGER trg_resenas_solo_entregadas BEFORE INSERT ON resenas
FOR EACH ROW
BEGIN
    -- T8. Solo se reseñan órdenes entregadas
    DECLARE v_estado VARCHAR(20);
    SELECT estado INTO v_estado FROM ordenes WHERE id = NEW.orden_id;
    IF v_estado <> 'Entregado' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Solo se puede reseñar una orden entregada';
    END IF;
END$$

DROP TRIGGER IF EXISTS trg_refacciones_auditoria$$
CREATE TRIGGER trg_refacciones_auditoria AFTER UPDATE ON refacciones
FOR EACH ROW
BEGIN
    -- T9. Auditoría de cambios de stock, costo y precio
    IF NEW.stock <> OLD.stock OR NEW.costo_proveedor <> OLD.costo_proveedor
       OR NEW.precio_venta <> OLD.precio_venta THEN
        INSERT INTO auditoria_refacciones
            (refaccion_id, stock_anterior, stock_nuevo, costo_anterior, costo_nuevo, precio_anterior, precio_nuevo)
        VALUES (NEW.id, OLD.stock, NEW.stock, OLD.costo_proveedor, NEW.costo_proveedor, OLD.precio_venta, NEW.precio_venta);
    END IF;
END$$

DROP TRIGGER IF EXISTS trg_refacciones_alerta_stock$$
CREATE TRIGGER trg_refacciones_alerta_stock AFTER UPDATE ON refacciones
FOR EACH ROW
BEGIN
    -- T10. Alerta cuando el stock baja del mínimo
    IF NEW.stock < NEW.stock_minimo AND NEW.stock < OLD.stock THEN
        INSERT INTO alertas_stock (refaccion_id, stock, stock_minimo)
        VALUES (NEW.id, NEW.stock, NEW.stock_minimo);
    END IF;
END$$

DROP TRIGGER IF EXISTS trg_usuarios_ultimo_admin$$
CREATE TRIGGER trg_usuarios_ultimo_admin BEFORE UPDATE ON usuarios
FOR EACH ROW
BEGIN
    -- T11. Siempre debe quedar al menos un administrador activo
    DECLARE v_otros INT;
    IF OLD.rol = 'admin' AND OLD.activo = 1 AND (NEW.activo = 0 OR NEW.rol <> 'admin') THEN
        SELECT COUNT(*) INTO v_otros FROM usuarios WHERE rol = 'admin' AND activo = 1 AND id <> OLD.id;
        IF v_otros = 0 THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Debe existir al menos un administrador activo';
        END IF;
    END IF;
END$$

DROP TRIGGER IF EXISTS trg_equipos_imei_numerico$$
CREATE TRIGGER trg_equipos_imei_numerico BEFORE INSERT ON equipos
FOR EACH ROW
BEGIN
    -- T12. El IMEI solo contiene dígitos
    IF NEW.imei REGEXP '[^0-9]' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'El IMEI solo debe contener dígitos';
    END IF;
END$$

DROP TRIGGER IF EXISTS trg_bitacora_no_editable$$
CREATE TRIGGER trg_bitacora_no_editable BEFORE UPDATE ON bitacora
FOR EACH ROW
BEGIN
    -- T13. La bitácora es de solo escritura
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La bitácora no se puede modificar';
END$$

-- ---------------- Funciones y procedimientos almacenados ----------------
DROP FUNCTION IF EXISTS fn_saldo_orden$$
CREATE FUNCTION fn_saldo_orden(p_orden INT) RETURNS DOUBLE
NOT DETERMINISTIC READS SQL DATA
BEGIN
    -- Saldo por cobrar de una orden: total (refacción + mano de obra) menos lo pagado
    DECLARE v_saldo DOUBLE;
    SELECT (costo_refaccion + mano_obra)
           - COALESCE((SELECT SUM(monto) FROM pagos WHERE orden_id = p_orden), 0)
      INTO v_saldo FROM ordenes WHERE id = p_orden;
    RETURN v_saldo;
END$$

DROP PROCEDURE IF EXISTS sp_registrar_pago$$
CREATE PROCEDURE sp_registrar_pago(IN p_folio VARCHAR(30), IN p_monto DOUBLE,
                                   IN p_tipo VARCHAR(12), IN p_metodo VARCHAR(15), IN p_usuario INT)
BEGIN
    -- Registra un pago y lo anota en la bitácora, todo en una transacción.
    DECLARE v_orden INT;
    DECLARE v_actor VARCHAR(150);
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;
    SELECT MAX(id) INTO v_orden FROM ordenes WHERE folio = p_folio;
    IF v_orden IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'No existe una orden con ese folio';
    END IF;
    SELECT COALESCE(MAX(nombre), 'Sistema') INTO v_actor FROM usuarios WHERE id = p_usuario;
    START TRANSACTION;
    INSERT INTO pagos (orden_id, monto, tipo, metodo, usuario_id)
    VALUES (v_orden, p_monto, p_tipo, p_metodo, p_usuario);
    INSERT INTO bitacora (orden_id, usuario_id, actor, accion)
    VALUES (v_orden, p_usuario, v_actor,
            CONCAT('Registró ', LOWER(p_tipo), ' de $', FORMAT(p_monto, 2), ' (', LOWER(p_metodo), ')'));
    COMMIT;
    SELECT CONCAT(p_tipo, ' de $', FORMAT(p_monto, 2), ' registrado. Saldo: $',
                  FORMAT(fn_saldo_orden(v_orden), 2)) AS resultado;
END$$

DROP PROCEDURE IF EXISTS sp_cambiar_estado$$
CREATE PROCEDURE sp_cambiar_estado(IN p_folio VARCHAR(30), IN p_nuevo VARCHAR(20), IN p_usuario INT)
BEGIN
    -- Cambia el estado de una orden y deja historial y bitácora. Los triggers validan el flujo.
    DECLARE v_orden INT;
    DECLARE v_estado VARCHAR(20);
    DECLARE v_presup VARCHAR(10);
    DECLARE v_actor VARCHAR(150);
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;
    SELECT MAX(id) INTO v_orden FROM ordenes WHERE folio = p_folio;
    IF v_orden IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'No existe una orden con ese folio';
    END IF;
    SELECT estado, presupuesto_estado INTO v_estado, v_presup FROM ordenes WHERE id = v_orden;
    IF p_nuevo = 'Entregado' AND v_presup = 'Aprobado' AND fn_saldo_orden(v_orden) > 0.005 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Hay un saldo pendiente: registra el pago antes de entregar';
    END IF;
    SELECT COALESCE(MAX(nombre), 'Sistema') INTO v_actor FROM usuarios WHERE id = p_usuario;
    START TRANSACTION;
    UPDATE ordenes
       SET estado = p_nuevo,
           garantia_dias = IF(p_nuevo = 'Entregado' AND presupuesto_estado <> 'Aprobado', 0, garantia_dias)
     WHERE id = v_orden;
    INSERT INTO historial_estados (orden_id, estado, usuario_id) VALUES (v_orden, p_nuevo, p_usuario);
    INSERT INTO bitacora (orden_id, usuario_id, actor, accion)
    VALUES (v_orden, p_usuario, v_actor, CONCAT('Cambió el estado de ', v_estado, ' a ', p_nuevo));
    COMMIT;
    SELECT CONCAT('Orden ', p_folio, ' movida a ', p_nuevo) AS resultado;
END$$

DROP PROCEDURE IF EXISTS sp_aprobar_presupuesto$$
CREATE PROCEDURE sp_aprobar_presupuesto(IN p_folio VARCHAR(30), IN p_aprobar TINYINT, IN p_usuario INT)
BEGIN
    -- Aprueba (1) o rechaza (0) el presupuesto; al aprobar descuenta 1 pieza una sola vez.
    DECLARE v_orden INT;
    DECLARE v_estado VARCHAR(20);
    DECLARE v_presup VARCHAR(10);
    DECLARE v_total DOUBLE;
    DECLARE v_ref INT;
    DECLARE v_desc TINYINT;
    DECLARE v_actor VARCHAR(150);
    DECLARE v_msg VARCHAR(200);
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;
    SELECT MAX(id) INTO v_orden FROM ordenes WHERE folio = p_folio;
    IF v_orden IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'No existe una orden con ese folio';
    END IF;
    SELECT estado, presupuesto_estado, costo_refaccion + mano_obra, refaccion_id, stock_descontado
      INTO v_estado, v_presup, v_total, v_ref, v_desc FROM ordenes WHERE id = v_orden;
    IF v_presup <> 'Pendiente' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'El presupuesto ya fue resuelto';
    END IF;
    IF v_estado <> 'En Diagnóstico' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'El presupuesto solo se resuelve en el estado En Diagnóstico';
    END IF;
    IF p_aprobar = 1 AND v_total <= 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Captura el presupuesto antes de aprobarlo';
    END IF;
    SELECT COALESCE(MAX(nombre), 'Sistema') INTO v_actor FROM usuarios WHERE id = p_usuario;
    START TRANSACTION;
    UPDATE ordenes
       SET presupuesto_estado = IF(p_aprobar = 1, 'Aprobado', 'Rechazado'), presupuesto_fecha = NOW()
     WHERE id = v_orden;
    INSERT INTO bitacora (orden_id, usuario_id, actor, accion)
    VALUES (v_orden, p_usuario, v_actor,
            IF(p_aprobar = 1, 'Presupuesto aprobado', 'Presupuesto rechazado'));
    SET v_msg = IF(p_aprobar = 1, 'Presupuesto aprobado.', 'Presupuesto rechazado. El equipo puede devolverse sin reparar.');
    IF p_aprobar = 1 AND v_ref IS NOT NULL AND v_desc = 0 THEN
        UPDATE refacciones SET stock = stock - 1 WHERE id = v_ref AND stock > 0;
        IF ROW_COUNT() = 1 THEN
            UPDATE ordenes SET stock_descontado = 1 WHERE id = v_orden;
            INSERT INTO bitacora (orden_id, usuario_id, actor, accion)
            VALUES (v_orden, NULL, 'Sistema', 'Se descontó 1 pieza del inventario');
            SET v_msg = 'Presupuesto aprobado. Se descontó 1 pieza del inventario.';
        ELSE
            SET v_msg = 'Presupuesto aprobado, pero no hay stock de la refacción; reabastece el inventario.';
        END IF;
    END IF;
    COMMIT;
    SELECT v_msg AS resultado;
END$$

DROP PROCEDURE IF EXISTS sp_reabastecer$$
CREATE PROCEDURE sp_reabastecer(IN p_refaccion INT, IN p_cantidad INT)
BEGIN
    -- Suma piezas al inventario y marca como atendidas las alertas ya resueltas.
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;
    IF p_cantidad IS NULL OR p_cantidad <= 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'La cantidad debe ser mayor a cero';
    END IF;
    START TRANSACTION;
    UPDATE refacciones SET stock = stock + p_cantidad WHERE id = p_refaccion;
    IF ROW_COUNT() = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'No existe esa refacción';
    END IF;
    UPDATE alertas_stock a JOIN refacciones r ON r.id = a.refaccion_id
       SET a.atendida = 1
     WHERE a.refaccion_id = p_refaccion AND a.atendida = 0 AND r.stock >= r.stock_minimo;
    COMMIT;
    SELECT id, nombre, stock, stock_minimo FROM refacciones WHERE id = p_refaccion;
END$$

DROP PROCEDURE IF EXISTS sp_resumen_orden$$
CREATE PROCEDURE sp_resumen_orden(IN p_folio VARCHAR(30))
BEGIN
    -- Ficha de la orden, su historial de estados y sus pagos (tres resultados).
    SELECT * FROM v_ordenes_resumen WHERE folio = p_folio;
    SELECT h.estado, h.fecha, u.nombre AS usuario
      FROM historial_estados h
      JOIN ordenes o ON o.id = h.orden_id
      LEFT JOIN usuarios u ON u.id = h.usuario_id
     WHERE o.folio = p_folio ORDER BY h.id;
    SELECT p.tipo, p.metodo, p.monto, p.fecha
      FROM pagos p JOIN ordenes o ON o.id = p.orden_id
     WHERE o.folio = p_folio ORDER BY p.id;
END$$

DROP PROCEDURE IF EXISTS sp_corte_ingresos$$
CREATE PROCEDURE sp_corte_ingresos(IN p_desde DATE, IN p_hasta DATE)
BEGIN
    -- Corte financiero del periodo: cobrado, órdenes entregadas y utilidad.
    SELECT COUNT(*) AS pagos, COALESCE(SUM(monto), 0) AS ingresos
      FROM pagos WHERE DATE(fecha) BETWEEN p_desde AND p_hasta;
    SELECT COUNT(*) AS entregadas,
           COALESCE(SUM(costo_refaccion + mano_obra), 0) AS facturado,
           COALESCE(SUM(costo_refaccion + mano_obra - costo_proveedor), 0) AS utilidad
      FROM ordenes WHERE estado = 'Entregado' AND DATE(fecha_entrega) BETWEEN p_desde AND p_hasta;
END$$

DELIMITER ;
