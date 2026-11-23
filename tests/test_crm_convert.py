"""Conversor del volcado de SuiteCRM a los archivos del importador (app/crm/importer/convert.py): puro, sin base de datos. Datos 100 % inventados."""
import io
import json

from app.crm.importer import convert, formats

DUMP = '''"id","name","date_entered","deleted","account_type","billing_address_city","sic_code","phone_office","website","description","industry","assigned_user_id"
"a1","EMPRESA UNO","2020-01-01 10:00:00","0","Agencias","Bogota","900123456-1","6011111","uno.example","nota","Eventos","u1"
"a2","Empresa Uno","2020-01-02 10:00:00","0","Customer","Cali",NULL,NULL,NULL,NULL,NULL,NULL
"a3","BORRADA","2020-01-02 10:00:00","1",NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL
"a4","SIN CODIGO","2020-01-02 10:00:00","0",NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL
"id_c","codigo_c","estado_c","categoria_c","plazo_pago_c"
"a1","101","NoGestionar","ClienteVIP","30"
"a2","101","Raro","ClienteA","15"
"a4","","","",""
"id","contact_id","account_id","date_modified","deleted"
"r1","c1","a1","2020-01-01 00:00:00","0"
"r2","c2","a3","2020-01-01 00:00:00","0"
"id","first_name","last_name","title","phone_work","phone_mobile","reports_to_id","lead_source","deleted","description"
"c1","Ana","Prueba","Gerente","601","300","","Web","0","hola"
"c2","Luis","Sin cuenta viva","X","","","","","0",""
"c3","Zoe","Huerfano","X","","","","","0",""
"id","email_address","email_address_caps","invalid_email","opt_out","deleted"
"e1","ana@example.com","ANA@EXAMPLE.COM","0","0","0"
"e2","malo@example.com","MALO@EXAMPLE.COM","1","0","0"
"id","email_address_id","bean_id","bean_module","primary_address","reply_to_address","date_created","date_modified","deleted"
"m1","e1","c1","Contacts","1","0","2020-01-01","2020-01-01","0"
"m2","e2","a1","Accounts","1","0","2020-01-01","2020-01-01","0"
"id","name","sales_stage","amount","date_closed","currency_id","opportunity_type","deleted"
"o1","Evento uno","Closed Won","1500000.00000000","2021-05-10","-99","Existing Business","0"
"o2","Sin cuenta","Prospecting","10","2021-05-10","-99",NULL,"0"
"id_c","codbase_c","codigo_c"
"o1","B1","555"
"id","opportunity_id","account_id","date_modified","deleted"
"q1","o1","a1","2020-01-01 00:00:00","0"
"id","name","description","deleted","duration_hours","duration_minutes","date_start","date_end","parent_type","status","direction","parent_id"
"k1","Llamada uno","charla","0","0","15","2021-06-01 10:00:00","2021-06-01 10:15:00","Opportunities","Held","Outbound","o1"
"k2","Llamada de cuenta","","0","0","15","2021-06-02 10:00:00","2021-06-02 10:15:00","Accounts","Planned","Outbound","a1"
"k3","Llamada de lead","","0","0","15","2021-06-02 10:00:00","2021-06-02 10:15:00","Leads","Planned","Outbound","l1"
"id","name","description","deleted","billing_account_id","expiration","number","opportunity_id","total_amount","currency_id","stage","term","approval_status","invoice_status","billing_contact_id","subtotal_amount","discount_amount","tax_amount","assigned_user_id","date_entered","total_amt","billing_address_street"
"z1","Cotizacion uno","","0","a1","2021-07-01","1001","o1","119.00000000","-99","Tarifarios","Net 30","Approved","Not Invoiced","","100","0","19","","2021-06-01","100","x"
"z2","Sin cuenta","","0","","2021-07-01","1002","","5","-99","Draft","","","","","","","","","","",""
"id","name","description","deleted","product_qty","product_list_price","product_unit_price","product_discount","discount","vat","parent_id","item_description","group_id","parent_type","product_total_price","number"
"p1","Camiseta","","0","2.0000","50.00000000","45.00000000","10.00000000","Percentage","19.0","z1","bonita","g","AOS_Quotes","90","1"
"p2","Gorra","","0","1.0000","20.00000000","15.00000000","5.00000000","Amount","5.0","z1","","g","AOS_Quotes","15","2"
"id","name","description","deleted","maincode","part_number","price","cost","category","currency_id","type","product_image","url","contact_id","aos_product_category_id","cost_usdollar","price_usdollar"
"pr1","Camiseta","","0","M1","P-1","50","20","Ropa","-99","Good","","","","","",""
'''


def _convert():
    return convert.convert(convert.load_tables(io.StringIO(DUMP)))


def test_accounts_status_code_and_duplicates():
    files, report = _convert()
    header, rows = files["accounts"]
    by = {r[0]: dict(zip(header, r)) for r in rows}
    assert set(by) == {"a1", "a2", "a4"}                                   # la borrada no pasa
    assert by["a1"]["estado"] == "no_gestionar" and by["a1"]["categoria"] == "ClienteVIP" and by["a1"]["tipo"] == "Agencias" and by["a1"]["industria"] == "Eventos"
    assert by["a1"]["nit"] == "900123456-1" and by["a1"]["numero de cuenta"] == "101"
    assert by["a2"]["numero de cuenta"] == ""                              # código repetido: el siguiente del contador; el original queda en legacy_json
    assert json.loads(by["a2"]["legacy_json"])["codigo_original_repetido"] == "101"
    assert by["a2"]["estado"] == "" and json.loads(by["a2"]["legacy_json"])["estado_original"] == "Raro"
    assert by["a2"]["nombre"] != "Empresa Uno" and by["a2"]["nombre"].startswith("Empresa Uno (cuenta ")      # mismo nombre normalizado: la segunda se distingue
    assert json.loads(by["a2"]["legacy_json"])["nombre_original"] == "Empresa Uno"
    assert json.loads(by["a1"]["legacy_json"])["plazo_pago_c"] == "30"
    assert by["a1"]["correo electronico"] == ""                            # el correo inválido no entra
    assert report["accounts"]["deleted"] == 1 and report["accounts"]["duplicate_name"] == 2 and report["accounts"]["code_repeated"] == 1


def test_contacts_need_a_live_account_and_take_primary_email():
    files, report = _convert()
    header, rows = files["contacts"]
    assert len(rows) == 1
    c = dict(zip(header, rows[0]))
    assert c["nombre"] == "Ana" and c["apellidos"] == "Prueba" and c["correo electronico"] == "ana@example.com" and c["nombre de la cuenta"] == "EMPRESA UNO"
    assert c["telefono"] == "601" and c["telefono movil"] == "300" and json.loads(c["legacy_json"])["lead_source"] == "Web"
    assert report["contacts"]["no_account"] == 2


def test_opportunities_amount_and_code():
    files, report = _convert()
    header, rows = files["opportunities"]
    assert len(rows) == 1
    o = dict(zip(header, rows[0]))
    assert o["importe"] == "1500000.00" and o["moneda"] == "" and o["codigo"] == "555" and o["etapa"] == "Closed Won"
    assert json.loads(o["legacy_json"])["codbase_c"] == "B1"
    assert report["opportunities"]["no_account"] == 1


def test_output_is_readable_by_the_importer_formats():
    files, _ = _convert()
    for kind, (header, rows) in files.items():
        raw = convert.to_csv(header, rows)
        read = list(formats.read_rows(kind, raw))
        assert len(read) == len(rows)
    acc = {r["legacy_id"]: r for _n, r in formats.read_rows("accounts", convert.to_csv(*files["accounts"]))}
    assert acc["a1"]["status"] == "no_gestionar" and acc["a1"]["category"] == "ClienteVIP" and acc["a1"]["account_type"] == "Agencias" and acc["a1"]["website"] == "uno.example"
    assert acc["a1"]["legacy_json"].startswith("{")


def test_activities_quotes_lines_products():
    files, report = _convert()
    h, rows = files["activities"]
    a = {r[0]: dict(zip(h, r)) for r in rows}
    assert set(a) == {"k1", "k2"} and a["k1"]["id oportunidad"] == "o1" and a["k2"]["nombre de la cuenta"] == "EMPRESA UNO" and a["k1"]["tipo"] == "call"
    assert report["activities"]["unlinked_leads"] == 1
    h, rows = files["quotes"]
    assert len(rows) == 1
    q = dict(zip(h, rows[0]))
    assert q["numero"] == "1001" and q["total"] == "119.00" and q["id oportunidad"] == "o1" and q["moneda"] == "" and json.loads(q["legacy_json"])["stage"] == "Tarifarios"
    h, rows = files["quote_lines"]
    lines = [dict(zip(h, r)) for r in rows]
    assert len(lines) == 2 and lines[0]["precio unitario"] == "50.00" and lines[0]["descuento"] == "10.00" and lines[0]["impuesto"] == "19.00"
    assert lines[1]["descuento"] == "25.00"                                # 5 en pesos sobre 20 = 25 %
    h, rows = files["products"]
    assert len(rows) == 1 and dict(zip(h, rows[0]))["codigo"] == "P-1"
    for kind in ("activities", "quotes", "quote_lines", "products"):
        assert len(list(formats.read_rows(kind, convert.to_csv(*files[kind])))) == len(files[kind][1])
