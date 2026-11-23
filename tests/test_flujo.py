"""Pruebas de flujo completo (Fase 4): recepción -> diagnóstico -> aprobación del cliente -> entrega -> reseña.

Ejecutar desde la carpeta del proyecto:  python -m unittest discover -s tests -v
Usan una base de datos temporal; no tocan database/taller.db.
"""
import io
import os
import re
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_ENGINE"] = "sqlite"  # las pruebas usan una base SQLite temporal
import app as taller  # noqa: E402

IMEI = "356938035643809"


class BaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        taller.DB_PATH = os.path.join(self.tmp.name, "test.db")
        taller.init_db()
        taller.app.config["TESTING"] = True
        taller.app.config["CSRF_ACTIVADO"] = False  # las pruebas de seguridad lo activan por su cuenta
        taller._fallos.clear()
        self.admin = taller.app.test_client()
        self.admin.post("/login", data={"email": "admin@taller.local", "password": "admin123"})
        self.admin.post("/inventario/nueva", data={
            "nombre": "Pantalla A15", "categoria": "Pantalla", "stock": "3", "stock_minimo": "2",
            "costo_proveedor": "400", "precio_venta": "750"})

    def tearDown(self):
        taller.app.config["CSRF_ACTIVADO"] = True
        self.tmp.cleanup()

    def sql(self, consulta, params=()):
        con = sqlite3.connect(taller.DB_PATH)
        try:
            return con.execute(consulta, params).fetchall()
        finally:
            con.close()

    def recibir(self, imei=IMEI, telefono="4421234567", seguir=False):
        r = self.admin.post("/recepcion", follow_redirects=seguir, data={
            "nombre": "Ana Pérez", "telefono": telefono, "imei": imei,
            "marca": "Samsung", "modelo": "A15", "falla": "Pantalla rota"})
        return r if seguir else r.headers["Location"].rsplit("/", 1)[1]

    def mover(self, folio, estado):
        if estado == "Entregado":  # liquida el saldo para poder entregar
            self.pagar_saldo(folio)
        self.admin.post(f"/orden/{folio}/estado", data={"estado": estado})

    def pagar_saldo(self, folio):
        o = self.sql("SELECT presupuesto_estado, costo_refaccion + mano_obra FROM ordenes WHERE folio = ?", (folio,))[0]
        pagado = self.sql("SELECT COALESCE(SUM(monto),0) FROM pagos WHERE orden_id = (SELECT id FROM ordenes WHERE folio = ?)", (folio,))[0][0]
        if o[0] == "Aprobado" and o[1] - pagado > 0:
            self.admin.post(f"/orden/{folio}/pago", data={"monto": str(o[1] - pagado), "tipo": "Pago final"})

    def diagnosticar(self, folio, refaccion="1"):
        self.mover(folio, "En Diagnóstico")
        self.admin.post(f"/orden/{folio}/diagnostico", data={
            "diagnostico": "Display dañado", "refaccion_id": refaccion,
            "costo_refaccion": "", "mano_obra": "200", "garantia_dias": "30"})

    def estado(self, folio):
        return self.sql("SELECT estado FROM ordenes WHERE folio = ?", (folio,))[0][0]

    def stock(self):
        return self.sql("SELECT stock FROM refacciones WHERE id = 1")[0][0]


class FlujoCompleto(BaseTest):
    def test_recepcion_hasta_resena(self):
        folio = self.recibir()
        self.assertRegex(folio, r"^TC-\d{8}-0001$")
        self.diagnosticar(folio)
        cliente = taller.app.test_client()
        t = taller.token_folio(folio)

        pagina = cliente.get(f"/seguimiento/{folio}?t={t}").get_data(as_text=True)
        self.assertIn("Autorizar reparación", pagina)
        self.assertIn("950.00", pagina)  # 750 refacción + 200 mano de obra
        self.assertEqual(self.stock(), 3)  # aún no se descuenta

        cliente.post(f"/seguimiento/{folio}/presupuesto/aprobar", data={"t": t})
        self.assertEqual(self.stock(), 2)  # se descuenta al aprobar
        cliente.post(f"/seguimiento/{folio}/presupuesto/aprobar", data={"t": t})
        self.assertEqual(self.stock(), 2)  # nunca dos veces

        for e in ("En Reparación", "Listo", "Entregado"):
            self.mover(folio, e)
        self.assertEqual(self.estado(folio), "Entregado")

        pagina = cliente.get(f"/seguimiento/{folio}?t={t}").get_data(as_text=True)
        self.assertIn("Garantía", pagina)
        cliente.post(f"/seguimiento/{folio}/resena", data={"t": t, "calificacion": "5", "comentario": "Excelente"})
        cliente.post(f"/seguimiento/{folio}/resena", data={"t": t, "calificacion": "1"})
        self.assertEqual(self.sql("SELECT calificacion, comentario FROM resenas"), [(5, "Excelente")])
        self.assertIn("Excelente", self.admin.get("/resenas").get_data(as_text=True))

    def test_rechazo_devuelve_sin_reparar_y_sin_garantia(self):
        folio = self.recibir()
        self.diagnosticar(folio)
        t = taller.token_folio(folio)
        taller.app.test_client().post(f"/seguimiento/{folio}/presupuesto/rechazar", data={"t": t})
        self.mover(folio, "En Reparación")
        self.assertEqual(self.estado(folio), "En Diagnóstico")  # no se puede reparar
        self.mover(folio, "Listo")
        self.mover(folio, "Entregado")
        self.assertEqual(self.stock(), 3)
        self.assertEqual(self.sql("SELECT garantia_dias FROM ordenes")[0][0], 0)

    def test_resena_solo_despues_de_entregar(self):
        folio = self.recibir()
        t = taller.token_folio(folio)
        taller.app.test_client().post(f"/seguimiento/{folio}/resena", data={"t": t, "calificacion": "5"})
        self.assertEqual(self.sql("SELECT COUNT(*) FROM resenas")[0][0], 0)


class SeguridadPortal(BaseTest):
    def test_sin_token_no_hay_acciones(self):
        folio = self.recibir()
        self.diagnosticar(folio)
        c = taller.app.test_client()
        pagina = c.get(f"/seguimiento/{folio}").get_data(as_text=True)
        self.assertNotIn("Autorizar reparación", pagina)
        self.assertNotIn("Ana", pagina)
        self.assertEqual(c.post(f"/seguimiento/{folio}/presupuesto/aprobar", data={}).status_code, 403)
        self.assertEqual(c.post(f"/seguimiento/{folio}/presupuesto/aprobar", data={"t": "falso"}).status_code, 403)

    def test_verificacion_por_ultimos_4_digitos_y_limite_de_intentos(self):
        folio = self.recibir(telefono="4421234567")
        c = taller.app.test_client()
        r = c.post(f"/seguimiento/{folio}/verificar", data={"telefono": "4567"})
        self.assertIn("t=" + taller.token_folio(folio), r.headers["Location"])
        for _ in range(5):
            r = c.post(f"/seguimiento/{folio}/verificar", data={"telefono": "0000"})
            self.assertNotIn("t=", r.headers["Location"])
        r = c.post(f"/seguimiento/{folio}/verificar", data={"telefono": "4567"})  # ya bloqueado
        self.assertNotIn("t=", r.headers["Location"])

    def test_verificacion_acepta_telefono_completo_o_con_lada(self):
        folio = self.recibir(telefono="4421234567")
        for valor in ("4421234567", "442 123 4567", "+52 442 123 4567"):
            c = taller.app.test_client()
            r = c.post(f"/seguimiento/{folio}/verificar", data={"telefono": valor})
            self.assertIn("t=", r.headers["Location"], valor)
        c = taller.app.test_client()
        r = c.post(f"/seguimiento/{folio}/verificar", data={"telefono": "442123999"})
        self.assertNotIn("t=", r.headers["Location"])
        r = c.post(f"/seguimiento/{folio}/verificar", data={"telefono": "123"})  # muy corto
        self.assertNotIn("t=", r.headers["Location"])

    def test_folio_inexistente(self):
        c = taller.app.test_client()
        self.assertEqual(c.get("/seguimiento/TC-NO-EXISTE").status_code, 404)
        self.assertIn("No encontramos", c.get("/consulta?folio=XX", follow_redirects=True).get_data(as_text=True))


class GarantiasYRoles(BaseTest):
    def test_garantia_vigente_avisa_en_nueva_recepcion(self):
        folio = self.recibir()
        self.diagnosticar(folio)
        self.admin.post(f"/orden/{folio}/presupuesto/aprobar")
        for e in ("En Reparación", "Listo", "Entregado"):
            self.mover(folio, e)
        pagina = self.recibir(seguir=True).get_data(as_text=True)
        self.assertIn("garantía vigente", pagina)
        historial = self.admin.get(f"/garantias?imei={IMEI}").get_data(as_text=True)
        self.assertIn(folio, historial)
        self.assertIn("Garantía vigente", historial)

    def test_tecnico_solo_ve_sus_ordenes_y_no_ve_costos(self):
        for n in ("1", "2"):
            self.admin.post("/usuarios", data={"nombre": f"Tec {n}", "email": f"t{n}@x.mx",
                                               "password": "tecnico123", "rol": "tecnico"})
        folio = self.recibir()
        id_t2 = self.sql("SELECT id FROM usuarios WHERE email = 't2@x.mx'")[0][0]
        self.admin.post(f"/orden/{folio}/asignar", data={"tecnico_id": str(id_t2)})
        t1, t2 = taller.app.test_client(), taller.app.test_client()
        t1.post("/login", data={"email": "t1@x.mx", "password": "tecnico123"})
        t2.post("/login", data={"email": "t2@x.mx", "password": "tecnico123"})
        self.assertEqual(t1.get(f"/orden/{folio}/detalle").status_code, 403)
        self.assertEqual(t2.get(f"/orden/{folio}/detalle").status_code, 200)
        self.assertNotIn("Finanzas", t2.get(f"/orden/{folio}/detalle").get_data(as_text=True))
        self.assertEqual(t2.get("/usuarios").status_code, 302)


class BusquedaYBitacora(BaseTest):
    def setUp(self):
        super().setUp()
        self.f1 = self.recibir(imei="356938035643809", telefono="4421234567")           # Ana Pérez
        self.admin.post("/recepcion", data={"nombre": "Luis Mora", "telefono": "4429876543", "imei": "490154203237518",
                                            "marca": "Motorola", "modelo": "G32", "falla": "No carga"})
        self.f2 = self.sql("SELECT folio FROM ordenes ORDER BY id DESC LIMIT 1")[0][0]

    def buscar(self, cliente=None, **params):
        return (cliente or self.admin).get("/buscar", query_string=params).get_data(as_text=True)

    def test_busca_sin_acentos_ni_mayusculas_y_por_varios_campos(self):
        for q in ("perez", "PÉREZ", "ana a15", "4421234567", "442 1234", "3569380", self.f1, "pantalla rota"):
            html = self.buscar(q=q)
            self.assertIn(self.f1, html, q)
            self.assertNotIn(self.f2, html, q)
        self.assertIn(self.f2, self.buscar(q="mora g32"))

    def test_sin_resultados_y_comodines_literales(self):
        self.assertIn("No encontramos", self.buscar(q="zzzz"))
        html = self.buscar(q="%")  # el % no debe comportarse como comodín
        self.assertNotIn(self.f1, html)
        self.assertNotIn(self.f2, html)

    def test_filtros_por_estado_y_tecnico(self):
        self.mover(self.f2, "En Diagnóstico")
        self.assertIn(self.f2, self.buscar(estado="En Diagnóstico"))
        self.assertNotIn(self.f1, self.buscar(estado="En Diagnóstico"))
        self.assertIn(self.f1, self.buscar(tecnico="sin"))
        self.assertIn(self.f1, self.buscar(desde="2000-01-01", hasta="2999-12-31"))
        self.assertNotIn(self.f1, self.buscar(desde="2999-01-01"))

    def test_tecnico_solo_encuentra_sus_ordenes(self):
        for n in ("1", "2"):
            self.admin.post("/usuarios", data={"nombre": f"Tec {n}", "email": f"t{n}@x.mx", "password": "tecnico123", "rol": "tecnico"})
        id_t2 = self.sql("SELECT id FROM usuarios WHERE email = 't2@x.mx'")[0][0]
        self.admin.post(f"/orden/{self.f1}/asignar", data={"tecnico_id": str(id_t2)})
        t1 = taller.app.test_client(); t1.post("/login", data={"email": "t1@x.mx", "password": "tecnico123"})
        self.assertNotIn(self.f1, self.buscar(cliente=t1))   # asignada a otro técnico
        self.assertIn(self.f2, self.buscar(cliente=t1))      # sin asignar
        self.assertIn(self.f1, self.buscar(self.admin))

    def test_bitacora_registra_quien_hizo_que(self):
        self.diagnosticar(self.f1)
        t = taller.token_folio(self.f1)
        taller.app.test_client().post(f"/seguimiento/{self.f1}/presupuesto/aprobar", data={"t": t})
        html = self.admin.get(f"/orden/{self.f1}/detalle").get_data(as_text=True)
        for texto in ("Orden creada en recepción", "Guardó diagnóstico y presupuesto", "Cliente (portal)",
                      "aprobado por el cliente desde el portal", "Se descontó 1 pieza", "Cambió el estado a «En Diagnóstico»"):
            self.assertIn(texto, html)


class FinanzasYRespaldo(BaseTest):
    def entregar(self, imei, telefono, mano, refaccion=""):
        folio = self.recibir(imei=imei, telefono=telefono)
        self.mover(folio, "En Diagnóstico")
        self.admin.post(f"/orden/{folio}/diagnostico", data={"diagnostico": "x", "refaccion_id": refaccion,
                        "costo_refaccion": "", "mano_obra": str(mano), "garantia_dias": "30"})
        self.admin.post(f"/orden/{folio}/presupuesto/aprobar")
        for e in ("En Reparación", "Listo", "Entregado"):
            self.mover(folio, e)
        return folio

    def test_corte_financiero(self):
        a = self.entregar("356938035643809", "4421234567", 200, "1")   # 750 + 200 = 950, costo 400
        b = self.entregar("490154203237518", "4429876543", 500)         # 500, sin refacción
        r = self.recibir(imei="353879234252633", telefono="4425551234")
        self.mover(r, "En Diagnóstico")
        self.admin.post(f"/orden/{r}/diagnostico", data={"diagnostico": "x", "refaccion_id": "", "costo_refaccion": "0",
                                                         "mano_obra": "300", "garantia_dias": "30"})
        self.admin.post(f"/orden/{r}/presupuesto/rechazar")
        html = self.admin.get("/finanzas").get_data(as_text=True)
        for esperado in ("$1,450.00", "$400.00", "$1,050.00", "72.4%", "$725.00", a, b):
            self.assertIn(esperado, html)
        self.assertNotIn(f">{r}<", html)  # la rechazada no genera ingreso
        vacio = self.admin.get("/finanzas?desde=2000-01-01&hasta=2000-01-31").get_data(as_text=True)
        self.assertIn("Aún no hay órdenes entregadas", vacio)
        self.assertNotIn(a, vacio)
        csv_ = self.admin.get("/finanzas/exportar").data
        self.assertTrue(csv_.startswith(b"\xef\xbb\xbf"))
        self.assertIn(a.encode(), csv_)
        self.assertIn(b"TOTAL", csv_)

    def test_solo_el_administrador_ve_finanzas_y_respaldo(self):
        self.admin.post("/usuarios", data={"nombre": "Tec", "email": "t@x.mx", "password": "tecnico123", "rol": "tecnico"})
        t = taller.app.test_client(); t.post("/login", data={"email": "t@x.mx", "password": "tecnico123"})
        for ruta in ("/finanzas", "/finanzas/exportar", "/respaldo", "/respaldo/descargar", "/respaldo/exportar/ordenes.csv"):
            self.assertEqual(t.get(ruta).status_code, 302, ruta)

    def test_respaldo_y_exportacion(self):
        self.admin.post("/recepcion", data={"nombre": "=cmd|calc", "telefono": "4421112222", "imei": "111111111111111",
                                            "marca": "M", "modelo": "X", "falla": "f", "patron": "1-2-3-6", "pin": "9876"})
        r = self.admin.get("/respaldo/descargar")
        self.assertTrue(r.data.startswith(b"SQLite format 3\x00"))
        csv_ = self.admin.get("/respaldo/exportar/ordenes.csv").data
        self.assertTrue(csv_.startswith(b"\xef\xbb\xbf"))
        self.assertIn("'=cmd|calc".encode(), csv_)  # sin inyección de fórmulas
        z = zipfile.ZipFile(io.BytesIO(self.admin.get("/respaldo/exportar/todo.zip").data))
        self.assertEqual(sorted(z.namelist()), ["bitacora.csv", "clientes.csv", "inventario.csv", "ordenes.csv", "resenas.csv"])
        for nombre in z.namelist():
            self.assertNotIn(b"9876", z.read(nombre))  # el PIN nunca se exporta
        self.assertEqual(self.admin.get("/respaldo/exportar/otra.csv").status_code, 404)
        self.assertEqual(self.admin.get("/respaldo/archivo/secreto.db").status_code, 404)
        self.assertEqual(self.admin.get("/respaldo").status_code, 200)

    def test_respaldo_automatico_diario_y_limpieza(self):
        d = os.path.join(self.tmp.name, "resp")
        os.makedirs(d)
        for n in ("taller_20200101.db", "taller_20200102.db", "taller_20200103.db"):
            with open(os.path.join(d, n), "w") as f:
                f.write("x")
        creado = taller.respaldo_automatico(directorio=d, conservar=2)
        self.assertTrue(os.path.exists(creado))
        self.assertIsNone(taller.respaldo_automatico(directorio=d, conservar=2))  # solo uno por día
        self.assertEqual(len(os.listdir(d)), 2)

    def test_exportar_resultados_de_busqueda(self):
        ana = self.recibir()
        self.admin.post("/recepcion", data={"nombre": "Luis Mora", "telefono": "4429876543", "imei": "490154203237518",
                                            "marca": "Motorola", "modelo": "G32", "falla": "No carga"})
        luis = self.sql("SELECT folio FROM ordenes ORDER BY id DESC LIMIT 1")[0][0]
        csv_ = self.admin.get("/buscar/exportar", query_string={"q": "luis"}).data.decode("utf-8-sig")
        self.assertIn(luis, csv_)
        self.assertNotIn(ana, csv_)


class Seguridad(BaseTest):
    def test_csrf_bloquea_formularios_sin_token(self):
        folio = self.recibir()
        taller.app.config["CSRF_ACTIVADO"] = True
        c = taller.app.test_client()
        r = c.post("/login", data={"email": "admin@taller.local", "password": "admin123"})  # sin token
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])
        token = re.search(r'name="csrf_token" value="([^"]+)"', c.get("/login").get_data(as_text=True)).group(1)
        r = c.post("/login", data={"email": "admin@taller.local", "password": "admin123", "csrf_token": token})
        self.assertNotIn("/login", r.headers["Location"])
        nuevo = {"nombre": "Tec", "email": "t@x.mx", "password": "tecnico123", "rol": "tecnico"}
        self.assertEqual(c.post("/usuarios", data=nuevo).status_code, 400)  # sesión iniciada, sin token
        self.assertEqual(self.sql("SELECT COUNT(*) FROM usuarios WHERE email = 't@x.mx'")[0][0], 0)
        token = re.search(r'name="csrf_token" value="([^"]+)"', c.get("/usuarios").get_data(as_text=True)).group(1)
        self.assertEqual(c.post("/usuarios", data={**nuevo, "csrf_token": token}).status_code, 302)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM usuarios WHERE email = 't@x.mx'")[0][0], 1)
        # el portal del cliente usa su propio código firmado y no exige el token CSRF
        r = taller.app.test_client().post(f"/seguimiento/{folio}/verificar", data={"telefono": "4567"})
        self.assertIn("t=", r.headers["Location"])

    def test_bloqueo_tras_intentos_fallidos(self):
        c = taller.app.test_client()
        for _ in range(5):
            self.assertEqual(c.post("/login", data={"email": "admin@taller.local", "password": "mala"}).status_code, 200)
        r = c.post("/login", data={"email": "admin@taller.local", "password": "admin123"})
        self.assertEqual(r.status_code, 429)

    def test_cabeceras_sesion_y_aviso_de_contrasena_inicial(self):
        r = self.admin.get("/")
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        self.assertIn("contraseña inicial", r.get_data(as_text=True))
        self.admin.post("/cuenta", data={"actual": "admin123", "nueva": "nuevaclave1", "confirmar": "nuevaclave1"})
        self.assertNotIn("contraseña inicial", self.admin.get("/").get_data(as_text=True))
        self.assertEqual(taller.app.config["PERMANENT_SESSION_LIFETIME"], timedelta(minutes=30))
        r = taller.app.test_client().post("/login", data={"email": "admin@taller.local", "password": "nuevaclave1"})
        self.assertIn("Expires", r.headers["Set-Cookie"])  # la sesión caduca por inactividad


if __name__ == "__main__":
    unittest.main()


class Tanda2(BaseTest):
    def listo_aprobado(self, folio):
        self.diagnosticar(folio)
        self.admin.post(f"/orden/{folio}/presupuesto/aprobar")
        self.mover(folio, "En Reparación")
        self.mover(folio, "Listo")

    def test_saldo_bloquea_entrega_y_admin_puede_forzar(self):
        folio = self.recibir()
        self.listo_aprobado(folio)
        self.admin.post(f"/orden/{folio}/pago", data={"monto": "300", "tipo": "Anticipo", "metodo": "Tarjeta"})
        self.admin.post(f"/orden/{folio}/estado", data={"estado": "Entregado"})
        self.assertEqual(self.estado(folio), "Listo")
        # no se acepta un pago mayor al total
        self.admin.post(f"/orden/{folio}/pago", data={"monto": "5000"})
        self.assertEqual(self.sql("SELECT COUNT(*) FROM pagos")[0][0], 1)
        self.admin.post(f"/orden/{folio}/estado", data={"estado": "Entregado", "forzar": "1"})
        self.assertEqual(self.estado(folio), "Entregado")
        self.assertTrue(self.sql("SELECT 1 FROM bitacora WHERE accion LIKE '%saldo pendiente%'"))

    def test_tecnico_no_puede_forzar_ni_borrar_pagos(self):
        self.admin.post("/usuarios", data={"nombre": "Tec", "email": "t@x.com", "rol": "tecnico", "password": "tecnico123"})
        folio = self.recibir()
        self.listo_aprobado(folio)
        tec = taller.app.test_client()
        tec.post("/login", data={"email": "t@x.com", "password": "tecnico123"})
        tec.post(f"/orden/{folio}/estado", data={"estado": "Entregado", "forzar": "1"})
        self.assertEqual(self.estado(folio), "Listo")
        self.admin.post(f"/orden/{folio}/pago", data={"monto": "100"})
        tec.post(f"/orden/{folio}/pago/1/eliminar")
        self.assertEqual(self.sql("SELECT COUNT(*) FROM pagos")[0][0], 1)
        self.admin.post(f"/orden/{folio}/pago/1/eliminar")
        self.assertEqual(self.sql("SELECT COUNT(*) FROM pagos")[0][0], 0)

    def test_semaforo_y_estancada(self):
        from datetime import datetime, timedelta
        hoy = datetime.now().date()
        base = {"estado": "Recibido", "actualizado_en": ahora_txt()}
        for dias, clase in ((-2, "vencida"), (0, "hoy"), (1, "proxima"), (5, "enplazo")):
            o = dict(base, fecha_promesa=(hoy + timedelta(days=dias)).isoformat())
            self.assertEqual(taller.semaforo(o)[0], clase)
        self.assertEqual(taller.semaforo(dict(base, fecha_promesa=None))[0], None)
        self.assertEqual(taller.semaforo({"estado": "Listo", "fecha_promesa": "2020-01-01"})[0], None)
        viejo = (datetime.now() - timedelta(days=4)).strftime("%Y-%m-%d %H:%M:%S")
        self.assertTrue(taller.estancada({"estado": "En Reparación", "actualizado_en": viejo}))
        self.assertFalse(taller.estancada({"estado": "Listo", "actualizado_en": viejo}))

    def test_promesa_notas_pdfs(self):
        folio = self.recibir()
        self.admin.post(f"/orden/{folio}/promesa", data={"fecha_promesa": "2030-01-15"})
        self.assertEqual(self.sql("SELECT fecha_promesa FROM ordenes")[0][0], "2030-01-15")
        self.admin.post(f"/orden/{folio}/promesa", data={"fecha_promesa": "basura"})
        self.assertEqual(self.sql("SELECT fecha_promesa FROM ordenes")[0][0], "2030-01-15")
        self.admin.post(f"/orden/{folio}/nota", data={"texto": "Cliente pide discreción"})
        pag = self.admin.get(f"/orden/{folio}/detalle").get_data(as_text=True)
        self.assertIn("Cliente pide discreción", pag)
        portal = taller.app.test_client().get(f"/seguimiento/{folio}?t={taller.token_folio(folio)}").get_data(as_text=True)
        self.assertNotIn("discreción", portal)
        for ruta in ("etiqueta", "recibo"):
            r = self.admin.get(f"/orden/{folio}/{ruta}/pdf")
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.data.startswith(b"%PDF"))

    def test_plantillas_editables(self):
        folio = self.recibir()
        self.admin.post("/plantillas", data={"t_Recibido": "Hey {nombre}! {equipo} listo {folio} {raro}",
                                             "t_En Diagnóstico": "", "t_En Reparación": "", "t_Listo": "", "t_Entregado": ""})
        pag = self.admin.get(f"/orden/{folio}/detalle").get_data(as_text=True)
        import urllib.parse
        self.assertIn(urllib.parse.quote("Hey Ana! Samsung A15 listo " + folio + " {raro}"), pag)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM plantillas")[0][0], 1)
        self.admin.post("/plantillas", data={"t_Recibido": "x", "r_Recibido": "1"})
        self.assertEqual(self.sql("SELECT COUNT(*) FROM plantillas")[0][0], 0)

    def test_migracion_agrega_fecha_promesa(self):
        con = sqlite3.connect(taller.DB_PATH)
        try:
            con.execute("ALTER TABLE ordenes DROP COLUMN fecha_promesa")
        except sqlite3.OperationalError:
            con.close()
            self.skipTest("SQLite sin DROP COLUMN")
        con.commit(); con.close()
        taller.init_db()
        cols = [r[1] for r in self.sql("PRAGMA table_info(ordenes)")]
        self.assertIn("fecha_promesa", cols)


def ahora_txt():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Tanda3Fotos(BaseTest):
    def imagen(self, formato="PNG", lado=2000):
        from PIL import Image
        b = io.BytesIO()
        Image.new("RGB", (lado, lado // 2), (200, 80, 30)).save(b, formato)
        b.seek(0)
        return b

    def test_fotos_en_recepcion_y_detalle(self):
        r = self.admin.post("/recepcion", content_type="multipart/form-data", data={
            "nombre": "Ana", "telefono": "4421234567", "imei": IMEI, "marca": "S", "modelo": "A", "falla": "x",
            "fotos": [(self.imagen(), "a.png"), (io.BytesIO(b"no soy imagen"), "b.jpg")]})
        folio = r.headers["Location"].rsplit("/", 1)[1]
        self.assertEqual(self.sql("SELECT COUNT(*) FROM fotos")[0][0], 1)  # la inválida se descarta
        archivo = self.sql("SELECT archivo FROM fotos")[0][0]
        from PIL import Image
        with Image.open(os.path.join(os.path.dirname(taller.DB_PATH), "fotos", archivo)) as im:
            self.assertEqual(im.format, "JPEG")
            self.assertLessEqual(max(im.size), 1400)
        pag = self.admin.get(f"/orden/{folio}/detalle").get_data(as_text=True)
        self.assertIn("/foto/1", pag)
        with self.admin.get("/foto/1") as resp:
            self.assertEqual(resp.status_code, 200)
        self.assertEqual(taller.app.test_client().get("/foto/1").status_code, 302)  # sin sesión no se ve

    def test_limite_y_eliminacion(self):
        folio = self.recibir()
        for _ in range(3):
            self.admin.post(f"/orden/{folio}/fotos", content_type="multipart/form-data",
                            data={"fotos": [(self.imagen("JPEG", 300), f"{i}.jpg") for i in range(3)]})
        self.assertEqual(self.sql("SELECT COUNT(*) FROM fotos")[0][0], 8)
        archivo = self.sql("SELECT archivo FROM fotos WHERE id = 1")[0][0]
        self.admin.post("/foto/1/eliminar")
        self.assertEqual(self.sql("SELECT COUNT(*) FROM fotos")[0][0], 7)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(taller.DB_PATH), "fotos", archivo)))
        z = self.admin.get("/respaldo/fotos")
        self.assertEqual(len(zipfile.ZipFile(io.BytesIO(z.data)).namelist()), 7)
