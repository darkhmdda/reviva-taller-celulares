-- Esquema SQLite: Sistema de Control de Recepción, Diagnóstico y Seguimiento
-- Reviva: Taller de Celulares (Taller de Reparación de Celulares)

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------
-- Usuarios (roles: admin / tecnico)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usuarios (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre         TEXT    NOT NULL,
    email          TEXT    NOT NULL UNIQUE,
    password_hash  TEXT    NOT NULL,
    rol            TEXT    NOT NULL CHECK (rol IN ('admin', 'tecnico')),
    activo         INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    creado_en      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ---------------------------------------------------------------
-- Clientes
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clientes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre     TEXT NOT NULL,
    telefono   TEXT NOT NULL,           -- usado para WhatsApp (con lada)
    email      TEXT,
    creado_en  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_clientes_telefono ON clientes(telefono);
CREATE INDEX IF NOT EXISTS idx_clientes_nombre   ON clientes(nombre);

-- ---------------------------------------------------------------
-- Equipos (identificados por IMEI; base del expediente histórico)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS equipos (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    imei              TEXT    NOT NULL UNIQUE CHECK (length(imei) BETWEEN 14 AND 16),
    marca             TEXT    NOT NULL,
    modelo            TEXT    NOT NULL,
    color             TEXT,
    cliente_id        INTEGER NOT NULL,
    patron_desbloqueo TEXT,             -- secuencia numérica, ej. '1-2-3-6-9'
    pin_desbloqueo    TEXT,             -- alternativa al patrón
    creado_en         TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON UPDATE CASCADE ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_equipos_cliente ON equipos(cliente_id);

-- ---------------------------------------------------------------
-- Órdenes de reparación
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ordenes (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    folio              TEXT    NOT NULL UNIQUE,        -- ej. 'TC-20261113-0001'
    equipo_id          INTEGER NOT NULL,
    tecnico_id         INTEGER,
    recibido_por       INTEGER NOT NULL,
    estado             TEXT    NOT NULL DEFAULT 'Recibido'
                       CHECK (estado IN ('Recibido','En Diagnóstico','En Reparación','Listo','Entregado')),
    falla_reportada    TEXT    NOT NULL,
    diagnostico        TEXT,
    -- Checklist visual de estado físico
    chk_pantalla_estrellada INTEGER NOT NULL DEFAULT 0 CHECK (chk_pantalla_estrellada IN (0,1)),
    chk_tapa_rota           INTEGER NOT NULL DEFAULT 0 CHECK (chk_tapa_rota IN (0,1)),
    chk_equipo_mojado       INTEGER NOT NULL DEFAULT 0 CHECK (chk_equipo_mojado IN (0,1)),
    chk_sin_bandeja_sim     INTEGER NOT NULL DEFAULT 0 CHECK (chk_sin_bandeja_sim IN (0,1)),
    observaciones_fisicas   TEXT,
    -- Presupuesto
    refaccion_id       INTEGER,
    costo_refaccion    REAL    NOT NULL DEFAULT 0 CHECK (costo_refaccion >= 0),   -- precio al cliente
    costo_proveedor    REAL    NOT NULL DEFAULT 0 CHECK (costo_proveedor >= 0),   -- solo admin
    mano_obra          REAL    NOT NULL DEFAULT 0 CHECK (mano_obra >= 0),
    presupuesto_estado TEXT    NOT NULL DEFAULT 'Pendiente'
                       CHECK (presupuesto_estado IN ('Pendiente','Aprobado','Rechazado')),
    presupuesto_fecha  TEXT,
    stock_descontado   INTEGER NOT NULL DEFAULT 0 CHECK (stock_descontado IN (0,1)),
    -- Garantía
    garantia_dias      INTEGER NOT NULL DEFAULT 30 CHECK (garantia_dias >= 0),
    fecha_ingreso      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    fecha_entrega      TEXT,
    fecha_promesa      TEXT,                           -- fecha prometida al cliente
    actualizado_en     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (equipo_id)    REFERENCES equipos(id)     ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (tecnico_id)   REFERENCES usuarios(id)    ON UPDATE CASCADE ON DELETE SET NULL,
    FOREIGN KEY (recibido_por) REFERENCES usuarios(id)    ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (refaccion_id) REFERENCES refacciones(id) ON UPDATE CASCADE ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_ordenes_estado  ON ordenes(estado);
CREATE INDEX IF NOT EXISTS idx_ordenes_equipo  ON ordenes(equipo_id);
CREATE INDEX IF NOT EXISTS idx_ordenes_tecnico ON ordenes(tecnico_id);
CREATE INDEX IF NOT EXISTS idx_ordenes_fecha   ON ordenes(fecha_ingreso);

-- ---------------------------------------------------------------
-- Historial de cambios de estado (trazabilidad)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS historial_estados (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_id    INTEGER NOT NULL,
    estado      TEXT    NOT NULL,
    usuario_id  INTEGER,
    fecha       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (orden_id)   REFERENCES ordenes(id)  ON DELETE CASCADE,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_historial_orden ON historial_estados(orden_id);

-- ---------------------------------------------------------------
-- Inventario de refacciones
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS refacciones (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre           TEXT    NOT NULL,
    categoria        TEXT    NOT NULL DEFAULT 'Otro'
                     CHECK (categoria IN ('Batería','Centro de carga','Pantalla','Otro')),
    marca_compatible TEXT,
    modelo_compatible TEXT,
    stock            INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    stock_minimo     INTEGER NOT NULL DEFAULT 2 CHECK (stock_minimo >= 0),  -- alerta si stock < 2
    costo_proveedor  REAL    NOT NULL DEFAULT 0 CHECK (costo_proveedor >= 0),
    precio_venta     REAL    NOT NULL DEFAULT 0 CHECK (precio_venta >= 0),
    activo           INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
);
CREATE INDEX IF NOT EXISTS idx_refacciones_categoria ON refacciones(categoria);
CREATE INDEX IF NOT EXISTS idx_refacciones_stock     ON refacciones(stock);

-- ---------------------------------------------------------------
-- Reseñas post-entrega (una por orden)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS resenas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_id    INTEGER NOT NULL UNIQUE,
    calificacion INTEGER NOT NULL CHECK (calificacion BETWEEN 1 AND 5),
    comentario  TEXT,
    fecha       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (orden_id) REFERENCES ordenes(id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------
-- Vista: alertas de stock bajo
-- ---------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_stock_bajo AS
SELECT id, nombre, categoria, stock, stock_minimo
FROM refacciones
WHERE activo = 1 AND stock < stock_minimo;

-- ---------------------------------------------------------------
-- Vista: garantía vigente por orden entregada
-- ---------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_garantias AS
SELECT o.id AS orden_id,
       o.folio,
       e.imei,
       o.fecha_entrega,
       o.garantia_dias,
       date(o.fecha_entrega, '+' || o.garantia_dias || ' days') AS vence,
       CASE WHEN date('now','localtime') <= date(o.fecha_entrega, '+' || o.garantia_dias || ' days')
            THEN 1 ELSE 0 END AS vigente
FROM ordenes o
JOIN equipos e ON e.id = o.equipo_id
WHERE o.estado = 'Entregado' AND o.fecha_entrega IS NOT NULL;

-- ---------------------------------------------------------------
-- Bitácora de acciones por orden (quién hizo qué)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bitacora (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_id   INTEGER NOT NULL,
    usuario_id INTEGER,
    actor      TEXT    NOT NULL,          -- nombre del usuario, 'Cliente (portal)' o 'Sistema'
    accion     TEXT    NOT NULL,
    fecha      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (orden_id)   REFERENCES ordenes(id)  ON DELETE CASCADE,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_bitacora_orden ON bitacora(orden_id);

-- ---------------------------------------------------------------
-- Tanda 2: pagos y anticipos, notas internas, plantillas de WhatsApp
-- (ordenes.fecha_promesa también se agrega con migrar() a bases antiguas)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pagos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_id   INTEGER NOT NULL,
    monto      REAL    NOT NULL CHECK (monto > 0),
    tipo       TEXT    NOT NULL DEFAULT 'Abono' CHECK (tipo IN ('Anticipo','Abono','Pago final')),
    metodo     TEXT    NOT NULL DEFAULT 'Efectivo' CHECK (metodo IN ('Efectivo','Tarjeta','Transferencia')),
    usuario_id INTEGER,
    fecha      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (orden_id)   REFERENCES ordenes(id)  ON DELETE CASCADE,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_pagos_orden ON pagos(orden_id);

CREATE TABLE IF NOT EXISTS notas (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_id   INTEGER NOT NULL,
    usuario_id INTEGER,
    autor      TEXT    NOT NULL,
    texto      TEXT    NOT NULL,
    fecha      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (orden_id)   REFERENCES ordenes(id)  ON DELETE CASCADE,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_notas_orden ON notas(orden_id);

CREATE TABLE IF NOT EXISTS plantillas (
    estado TEXT PRIMARY KEY,
    texto  TEXT NOT NULL
);

-- ---------------------------------------------------------------
-- Tanda 3: fotos del equipo (los archivos viven en database/fotos/)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fotos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_id   INTEGER NOT NULL,
    archivo    TEXT    NOT NULL UNIQUE,
    usuario_id INTEGER,
    fecha      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (orden_id)   REFERENCES ordenes(id)  ON DELETE CASCADE,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_fotos_orden ON fotos(orden_id);

-- ===============================================================
-- Tanda 5 (examen de Base de Datos): tablas de apoyo, vistas,
-- índices adicionales y triggers
-- ===============================================================

-- Auditoría de cambios en inventario (la llena un trigger)
CREATE TABLE IF NOT EXISTS auditoria_refacciones (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    refaccion_id    INTEGER NOT NULL,
    stock_anterior  INTEGER NOT NULL,
    stock_nuevo     INTEGER NOT NULL,
    costo_anterior  REAL    NOT NULL,
    costo_nuevo     REAL    NOT NULL,
    precio_anterior REAL    NOT NULL,
    precio_nuevo    REAL    NOT NULL,
    fecha           TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (refaccion_id) REFERENCES refacciones(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_auditoria_refaccion ON auditoria_refacciones(refaccion_id);

-- Alertas de reabastecimiento (la llena un trigger)
CREATE TABLE IF NOT EXISTS alertas_stock (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    refaccion_id INTEGER NOT NULL,
    stock        INTEGER NOT NULL,
    stock_minimo INTEGER NOT NULL,
    atendida     INTEGER NOT NULL DEFAULT 0 CHECK (atendida IN (0, 1)),
    fecha        TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (refaccion_id) REFERENCES refacciones(id) ON DELETE CASCADE
);

-- Índices adicionales
CREATE INDEX IF NOT EXISTS idx_pagos_fecha         ON pagos(fecha);
CREATE INDEX IF NOT EXISTS idx_bitacora_fecha      ON bitacora(fecha);
CREATE INDEX IF NOT EXISTS idx_ordenes_presupuesto ON ordenes(presupuesto_estado);
CREATE INDEX IF NOT EXISTS idx_ordenes_activas     ON ordenes(estado, actualizado_en) WHERE estado <> 'Entregado';
CREATE INDEX IF NOT EXISTS idx_alertas_pendientes  ON alertas_stock(refaccion_id) WHERE atendida = 0;

-- ---------------- Vistas ----------------
-- Orden completa con cliente, equipo, técnico, total, pagado y saldo
CREATE VIEW IF NOT EXISTS v_ordenes_resumen AS
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

-- Órdenes con saldo por cobrar
CREATE VIEW IF NOT EXISTS v_saldos_pendientes AS
SELECT orden_id, folio, estado, cliente, telefono, total, pagado, saldo
FROM v_ordenes_resumen
WHERE saldo > 0.005 AND presupuesto_estado = 'Aprobado';

-- Carga de trabajo por técnico
CREATE VIEW IF NOT EXISTS v_carga_tecnicos AS
SELECT u.id AS tecnico_id, u.nombre AS tecnico,
       SUM(CASE WHEN o.estado <> 'Entregado' THEN 1 ELSE 0 END) AS ordenes_activas,
       SUM(CASE WHEN o.estado = 'Entregado'  THEN 1 ELSE 0 END) AS ordenes_entregadas,
       COUNT(o.id) AS ordenes_totales
FROM usuarios u
LEFT JOIN ordenes o ON o.tecnico_id = u.id
WHERE u.rol = 'tecnico' AND u.activo = 1
GROUP BY u.id, u.nombre;

-- Expediente histórico por IMEI
CREATE VIEW IF NOT EXISTS v_expediente_imei AS
SELECT e.imei, e.marca, e.modelo, c.nombre AS cliente,
       o.folio, o.fecha_ingreso, o.fecha_entrega, o.estado, o.falla_reportada, o.diagnostico
FROM equipos e
JOIN clientes c ON c.id = e.cliente_id
JOIN ordenes  o ON o.equipo_id = e.id;

-- Ingresos y utilidad estimada por mes (pagos cobrados)
CREATE VIEW IF NOT EXISTS v_ingresos_mensuales AS
SELECT strftime('%Y-%m', p.fecha) AS mes,
       COUNT(*)      AS num_pagos,
       SUM(p.monto)  AS ingresos
FROM pagos p
GROUP BY strftime('%Y-%m', p.fecha);

-- Refacciones más utilizadas en reparaciones aprobadas
CREATE VIEW IF NOT EXISTS v_refacciones_mas_usadas AS
SELECT r.id AS refaccion_id, r.nombre, r.categoria,
       COUNT(o.id) AS veces_usada,
       SUM(o.costo_refaccion - o.costo_proveedor) AS utilidad_refaccion
FROM refacciones r
JOIN ordenes o ON o.refaccion_id = r.id AND o.stock_descontado = 1
GROUP BY r.id, r.nombre, r.categoria;

-- Satisfacción promedio
CREATE VIEW IF NOT EXISTS v_calificacion_promedio AS
SELECT COUNT(*) AS total_resenas,
       ROUND(AVG(calificacion), 2) AS promedio,
       SUM(CASE WHEN calificacion >= 4 THEN 1 ELSE 0 END) AS positivas
FROM resenas;

-- ---------------- Triggers ----------------
-- T1. Mantiene actualizado_en al modificar una orden
CREATE TRIGGER IF NOT EXISTS trg_ordenes_touch
AFTER UPDATE ON ordenes
WHEN NEW.actualizado_en = OLD.actualizado_en
 AND NEW.actualizado_en <> datetime('now', 'localtime')
BEGIN
    UPDATE ordenes SET actualizado_en = datetime('now', 'localtime') WHERE id = NEW.id;
END;

-- T2. Valida el flujo de estados (adyacentes o rechazo de presupuesto; Entregado es final)
CREATE TRIGGER IF NOT EXISTS trg_ordenes_transicion_estado
BEFORE UPDATE OF estado ON ordenes
WHEN NEW.estado <> OLD.estado
BEGIN
    SELECT RAISE(ABORT, 'Transición de estado no permitida')
    WHERE OLD.estado = 'Entregado'
       OR NOT (
            abs(CASE NEW.estado WHEN 'Recibido' THEN 1 WHEN 'En Diagnóstico' THEN 2
                                WHEN 'En Reparación' THEN 3 WHEN 'Listo' THEN 4 ELSE 5 END
              - CASE OLD.estado WHEN 'Recibido' THEN 1 WHEN 'En Diagnóstico' THEN 2
                                WHEN 'En Reparación' THEN 3 WHEN 'Listo' THEN 4 ELSE 5 END) = 1
            OR (OLD.estado = 'En Diagnóstico' AND NEW.estado = 'Listo'
                AND NEW.presupuesto_estado = 'Rechazado')
       );
END;

-- T3. No se repara sin presupuesto aprobado
CREATE TRIGGER IF NOT EXISTS trg_ordenes_requiere_aprobacion
BEFORE UPDATE OF estado ON ordenes
WHEN NEW.estado = 'En Reparación' AND NEW.presupuesto_estado <> 'Aprobado'
BEGIN
    SELECT RAISE(ABORT, 'El presupuesto debe estar aprobado antes de reparar');
END;

-- T4. Al entregar, asegura la fecha de entrega
CREATE TRIGGER IF NOT EXISTS trg_ordenes_fecha_entrega
AFTER UPDATE OF estado ON ordenes
WHEN NEW.estado = 'Entregado' AND NEW.fecha_entrega IS NULL
BEGIN
    UPDATE ordenes SET fecha_entrega = datetime('now', 'localtime') WHERE id = NEW.id;
END;

-- T5. El folio y la fecha de ingreso nunca cambian
CREATE TRIGGER IF NOT EXISTS trg_ordenes_folio_inmutable
BEFORE UPDATE OF folio, fecha_ingreso ON ordenes
WHEN NEW.folio <> OLD.folio OR NEW.fecha_ingreso <> OLD.fecha_ingreso
BEGIN
    SELECT RAISE(ABORT, 'El folio y la fecha de ingreso no se pueden modificar');
END;

-- T6. Un pago no puede exceder el total de la orden
CREATE TRIGGER IF NOT EXISTS trg_pagos_no_excede_total
BEFORE INSERT ON pagos
BEGIN
    SELECT RAISE(ABORT, 'El pago excede el total de la orden')
    WHERE (SELECT costo_refaccion + mano_obra FROM ordenes WHERE id = NEW.orden_id) > 0
      AND COALESCE((SELECT SUM(monto) FROM pagos WHERE orden_id = NEW.orden_id), 0) + NEW.monto
          > (SELECT costo_refaccion + mano_obra FROM ordenes WHERE id = NEW.orden_id) + 0.005;
END;

-- T7. Registrar un pago cuenta como actividad de la orden
CREATE TRIGGER IF NOT EXISTS trg_pagos_touch_orden
AFTER INSERT ON pagos
BEGIN
    UPDATE ordenes SET actualizado_en = datetime('now', 'localtime') WHERE id = NEW.orden_id;
END;

-- T8. Solo se reseñan órdenes entregadas
CREATE TRIGGER IF NOT EXISTS trg_resenas_solo_entregadas
BEFORE INSERT ON resenas
BEGIN
    SELECT RAISE(ABORT, 'Solo se puede reseñar una orden entregada')
    WHERE (SELECT estado FROM ordenes WHERE id = NEW.orden_id) <> 'Entregado';
END;

-- T9. Auditoría de cambios de stock, costo y precio
CREATE TRIGGER IF NOT EXISTS trg_refacciones_auditoria
AFTER UPDATE OF stock, costo_proveedor, precio_venta ON refacciones
WHEN NEW.stock <> OLD.stock OR NEW.costo_proveedor <> OLD.costo_proveedor
  OR NEW.precio_venta <> OLD.precio_venta
BEGIN
    INSERT INTO auditoria_refacciones
        (refaccion_id, stock_anterior, stock_nuevo, costo_anterior, costo_nuevo, precio_anterior, precio_nuevo)
    VALUES (NEW.id, OLD.stock, NEW.stock, OLD.costo_proveedor, NEW.costo_proveedor, OLD.precio_venta, NEW.precio_venta);
END;

-- T10. Alerta cuando el stock baja del mínimo
CREATE TRIGGER IF NOT EXISTS trg_refacciones_alerta_stock
AFTER UPDATE OF stock ON refacciones
WHEN NEW.stock < NEW.stock_minimo AND NEW.stock < OLD.stock
BEGIN
    INSERT INTO alertas_stock (refaccion_id, stock, stock_minimo)
    VALUES (NEW.id, NEW.stock, NEW.stock_minimo);
END;

-- T11. Siempre debe quedar al menos un administrador activo
CREATE TRIGGER IF NOT EXISTS trg_usuarios_ultimo_admin
BEFORE UPDATE OF activo, rol ON usuarios
WHEN OLD.rol = 'admin' AND OLD.activo = 1 AND (NEW.activo = 0 OR NEW.rol <> 'admin')
BEGIN
    SELECT RAISE(ABORT, 'Debe existir al menos un administrador activo')
    WHERE (SELECT COUNT(*) FROM usuarios WHERE rol = 'admin' AND activo = 1 AND id <> OLD.id) = 0;
END;

-- T12. El IMEI solo contiene dígitos
CREATE TRIGGER IF NOT EXISTS trg_equipos_imei_numerico
BEFORE INSERT ON equipos
WHEN NEW.imei GLOB '*[^0-9]*'
BEGIN
    SELECT RAISE(ABORT, 'El IMEI solo debe contener dígitos');
END;

-- T13. La bitácora es de solo escritura (no se edita)
CREATE TRIGGER IF NOT EXISTS trg_bitacora_no_editable
BEFORE UPDATE ON bitacora
BEGIN
    SELECT RAISE(ABORT, 'La bitácora no se puede modificar');
END;
