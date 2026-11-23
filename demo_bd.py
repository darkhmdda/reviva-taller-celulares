import sqlite3, os, json
import pathlib; BASE=pathlib.Path(__file__).resolve().parent
SCHEMA=str(BASE/"database"/"schema.sql")
DB=str(BASE/"taller_demo.db")
if os.path.exists(DB): os.remove(DB)
db=sqlite3.connect(DB); db.execute("PRAGMA foreign_keys=ON")
db.executescript(open(SCHEMA,encoding="utf-8").read())
out=[]
def rows(sql,p=()):
    cur=db.execute(sql,p); cols=[d[0] for d in cur.description]; return cols,cur.fetchall()
def show(titulo,sql,p=()):
    cols,r=rows(sql,p); out.append({"t":titulo,"sql":sql.strip(),"cols":cols,"rows":r})
def attempt(titulo,sql,p=()):
    try:
        db.execute(sql,p); db.commit(); res="OK (permitido)"
    except sqlite3.Error as e: res=f"{type(e).__name__}: {e}"
    out.append({"t":titulo,"sql":sql.strip(),"res":res})
# datos
db.executescript("""
INSERT INTO usuarios(nombre,email,password_hash,rol) VALUES
 ('Administrador','admin@taller.local','x','admin'),
 ('Luis Hernández','luis@taller.local','x','tecnico'),
 ('María Torres','maria@taller.local','x','tecnico');
INSERT INTO clientes(nombre,telefono,email) VALUES
 ('Ana Pérez','4421234567','ana@mail.com'),('Carlos Ruiz','4429876543',NULL),('Sofía Díaz','4425551212',NULL);
INSERT INTO equipos(imei,marca,modelo,color,cliente_id) VALUES
 ('356938035643809','Samsung','Galaxy A15','Negro',1),
 ('490154203237518','Apple','iPhone 11','Blanco',2),
 ('352099001761481','Motorola','Moto G23','Azul',3);
INSERT INTO refacciones(nombre,categoria,marca_compatible,modelo_compatible,stock,stock_minimo,costo_proveedor,precio_venta) VALUES
 ('Pantalla A15','Pantalla','Samsung','A15',3,2,400,750),
 ('Batería iPhone 11','Batería','Apple','iPhone 11',2,2,180,400),
 ('Centro de carga G23','Centro de carga','Motorola','G23',1,2,60,180);
INSERT INTO ordenes(folio,equipo_id,tecnico_id,recibido_por,estado,falla_reportada,refaccion_id,costo_refaccion,costo_proveedor,mano_obra,presupuesto_estado,stock_descontado,garantia_dias,fecha_ingreso,fecha_entrega,actualizado_en) VALUES
 ('TC-20261101-0001',1,2,1,'Entregado','Pantalla rota',1,750,400,200,'Aprobado',1,30,'2026-11-01 10:00:00','2026-11-04 17:00:00','2026-11-04 17:00:00'),
 ('TC-20261110-0002',2,3,1,'En Reparación','No carga la batería',2,400,180,150,'Aprobado',1,30,'2026-11-10 09:30:00',NULL,'2026-11-12 12:00:00'),
 ('TC-20261113-0003',3,2,1,'En Diagnóstico','No carga',3,180,60,100,'Pendiente',0,30,'2026-11-13 11:00:00',NULL,'2026-11-13 11:00:00');
INSERT INTO pagos(orden_id,monto,tipo,metodo,usuario_id) VALUES (1,950,'Pago final','Efectivo',1),(2,300,'Anticipo','Tarjeta',1);
INSERT INTO resenas(orden_id,calificacion,comentario) VALUES (1,5,'Excelente servicio');
INSERT INTO bitacora(orden_id,usuario_id,actor,accion) VALUES (1,1,'Administrador','Registró pago final de $950.00');
INSERT INTO historial_estados(orden_id,estado,usuario_id) VALUES (1,'Recibido',1),(1,'En Diagnóstico',2),(1,'En Reparación',2),(1,'Listo',2),(1,'Entregado',1);
""")
db.execute("UPDATE pagos SET fecha='2026-11-04 17:00:00' WHERE id=1"); db.execute("UPDATE pagos SET fecha='2026-11-12 12:00:00' WHERE id=2"); db.commit()
# datos básicos
for t in ["usuarios","clientes","equipos","ordenes","refacciones","pagos"]:
    show(f"Contenido de {t}",f"SELECT * FROM {t}")
# vistas
for v in ["v_stock_bajo","v_garantias","v_ordenes_resumen","v_saldos_pendientes","v_carga_tecnicos","v_expediente_imei","v_ingresos_mensuales","v_refacciones_mas_usadas","v_calificacion_promedio"]:
    show(f"Vista {v}",f"SELECT * FROM {v}")
# triggers
attempt("T2 Saltar de En Diagnóstico a Entregado","UPDATE ordenes SET estado='Entregado' WHERE folio='TC-20261113-0003'")
attempt("T2 Cambiar una orden ya entregada","UPDATE ordenes SET estado='Listo' WHERE folio='TC-20261101-0001'")
attempt("T3 Reparar sin presupuesto aprobado","UPDATE ordenes SET estado='En Reparación' WHERE folio='TC-20261113-0003'")
attempt("T5 Cambiar el folio","UPDATE ordenes SET folio='TC-X' WHERE id=1")
attempt("T6 Pago mayor al total (orden 2 total 550, pagado 300, +400)","INSERT INTO pagos(orden_id,monto,tipo,metodo) VALUES (2,400,'Abono','Efectivo')")
attempt("T8 Reseña de una orden no entregada","INSERT INTO resenas(orden_id,calificacion) VALUES (2,4)")
attempt("T11 Desactivar al único administrador","UPDATE usuarios SET activo=0 WHERE id=1")
attempt("T12 IMEI con letras","INSERT INTO equipos(imei,marca,modelo,cliente_id) VALUES ('35693803AB43809','X','Y',1)")
attempt("T13 Modificar la bitácora","UPDATE bitacora SET accion='alterada' WHERE id=1")
attempt("CHECK: pago con monto 0","INSERT INTO pagos(orden_id,monto) VALUES (2,0)")
attempt("FK: orden con equipo inexistente","INSERT INTO ordenes(folio,equipo_id,recibido_por,falla_reportada) VALUES ('TC-F',99,1,'x')")
attempt("UNIQUE: IMEI duplicado","INSERT INTO equipos(imei,marca,modelo,cliente_id) VALUES ('356938035643809','X','Y',1)")
attempt("CHECK: stock negativo","UPDATE refacciones SET stock=-1 WHERE id=1")
# triggers que sí actúan
show("T1 antes: actualizado_en de orden 3","SELECT folio,actualizado_en FROM ordenes WHERE id=3")
db.execute("UPDATE ordenes SET diagnostico='Falla en centro de carga' WHERE id=3"); db.commit()
show("T1 después de cambiar el diagnóstico","SELECT folio,diagnostico,actualizado_en FROM ordenes WHERE id=3")
db.execute("UPDATE ordenes SET estado='En Reparación', presupuesto_estado='Aprobado' WHERE id=3"); db.commit()
db.execute("UPDATE ordenes SET estado='Listo' WHERE id=3"); db.execute("UPDATE ordenes SET estado='Entregado' WHERE id=3"); db.commit()
show("T4 fecha_entrega asignada automáticamente","SELECT folio,estado,fecha_entrega IS NOT NULL AS tiene_fecha FROM ordenes WHERE id=3")
db.execute("UPDATE refacciones SET stock=stock-1 WHERE id=3"); db.commit()
show("T9 auditoría tras descontar stock","SELECT refaccion_id,stock_anterior,stock_nuevo,costo_anterior,costo_nuevo,precio_anterior,precio_nuevo FROM auditoria_refacciones")
show("T10 alertas de stock generadas","SELECT refaccion_id,stock,stock_minimo,atendida FROM alertas_stock")
db.execute("UPDATE refacciones SET precio_venta=800 WHERE id=1"); db.commit()
show("T9 auditoría tras cambiar precio","SELECT refaccion_id,precio_anterior,precio_nuevo FROM auditoria_refacciones WHERE id=2")
db.execute("INSERT INTO usuarios(nombre,email,password_hash,rol) VALUES ('Admin 2','a2@t.local','x','admin')"); db.execute("UPDATE usuarios SET activo=0 WHERE id=1"); db.commit()
show("T11 con un segundo admin sí se permite desactivar","SELECT id,nombre,rol,activo FROM usuarios WHERE rol='admin'")
# metadatos
show("Objetos de la base de datos","SELECT type,name,tbl_name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")
show("Claves foráneas de ordenes","SELECT * FROM pragma_foreign_key_list('ordenes')")
show("Integridad","PRAGMA integrity_check")
# consultas adicionales
Q={
"Q1 Órdenes con cliente, equipo y técnico (JOIN)":"SELECT o.folio,c.nombre AS cliente,e.marca||' '||e.modelo AS equipo,u.nombre AS tecnico,o.estado FROM ordenes o JOIN equipos e ON e.id=o.equipo_id JOIN clientes c ON c.id=e.cliente_id LEFT JOIN usuarios u ON u.id=o.tecnico_id ORDER BY o.id",
"Q2 Órdenes por estado (GROUP BY)":"SELECT estado,COUNT(*) AS total FROM ordenes GROUP BY estado ORDER BY total DESC",
"Q3 Clientes con compras mayores a $500 (HAVING)":"SELECT c.nombre,COUNT(o.id) AS ordenes,SUM(o.costo_refaccion+o.mano_obra) AS facturado FROM clientes c JOIN equipos e ON e.cliente_id=c.id JOIN ordenes o ON o.equipo_id=e.id GROUP BY c.id HAVING SUM(o.costo_refaccion+o.mano_obra)>500 ORDER BY facturado DESC",
"Q4 Utilidad por orden (aritmética)":"SELECT folio,(costo_refaccion-costo_proveedor)+mano_obra AS utilidad FROM ordenes WHERE presupuesto_estado='Aprobado'",
"Q5 Subconsulta: órdenes sin pagos":"SELECT folio FROM ordenes WHERE id NOT IN (SELECT orden_id FROM pagos)",
"Q6 CTE: tiempo de entrega en días":"WITH e AS (SELECT folio,julianday(fecha_entrega)-julianday(fecha_ingreso) AS dias FROM ordenes WHERE fecha_entrega IS NOT NULL) SELECT folio,ROUND(dias,1) AS dias FROM e",
"Q7 Función de ventana: acumulado de ingresos":"SELECT fecha,monto,SUM(monto) OVER (ORDER BY fecha) AS acumulado FROM pagos",
}
for k,v in Q.items(): show(k,v)
json.dump(out,open("resultados_demo.json","w"),ensure_ascii=False,default=str,indent=1)
for o in out:
    print("##",o["t"])
    if "res" in o: print("  ->",o["res"])
    else:
        print("  ",o["cols"])
        for r in o["rows"][:8]: print("  ",r)
