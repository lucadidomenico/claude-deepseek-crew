import csv, io
import pytest
from conftest import uniq

def sheet(api):
    r = api.post("/api/sheets", {"name": uniq("S")}); assert r.status_code == 201, r.text; return r.json()["id"]

def put(api, sid, ref, inp):
    r = api.put(f"/api/sheets/{sid}/cells/{ref}", {"input": inp}); assert r.status_code == 200, r.text; return r.json()

def get(api, sid, ref):
    r = api.get(f"/api/sheets/{sid}/cells/{ref}"); assert r.status_code == 200, r.text; return r.json()

def val(api, sid, ref): return get(api, sid, ref)["value"]
def inp(api, sid, ref): return get(api, sid, ref)["input"]

def batch(api, sid, cells):
    r = api.post(f"/api/sheets/{sid}/cells", {"cells": cells}); assert r.status_code == 200, r.text; return r.json()["cells"]

def ev(api, formula, setup=None):
    sid = sheet(api)
    if setup: batch(api, sid, setup)
    return put(api, sid, "Z900", formula)

def test_index_html(api):
    r = api.get("/"); assert r.status_code == 200 and "text/html" in r.headers.get("content-type", "")

def test_sheet_crud(api):
    sid = sheet(api); assert api.get(f"/api/sheets/{sid}").json()["cells"] == {}
    assert sid in [s["id"] for s in api.get("/api/sheets").json()]
    assert api.post("/api/sheets", {"name": "  "}).status_code == 400
    assert api.get("/api/sheets/999999").status_code == 404
    assert api.get("/api/sheets/999999/cells/A1").status_code == 404
    assert api.delete(f"/api/sheets/{sid}").status_code == 204
    assert api.get(f"/api/sheets/{sid}").status_code == 404

@pytest.mark.parametrize("text,value,typ", [
    ("42", 42, "number"), ("-3.5", -3.5, "number"), ("1e3", 1000, "number"), (".5", 0.5, "number"), ("+7", 7, "number"),
    ("TRUE", True, "boolean"), ("false", False, "boolean"), ("'123", "123", "string"), ("hello", "hello", "string"),
    ("12abc", "12abc", "string"), ("", None, "empty"),
])
def test_input_interpretation(api, text, value, typ):
    sid = sheet(api); r = put(api, sid, "A1", text)
    assert r["type"] == typ and r["value"] == value and r["input"] == text and r["ref"] == "A1"

def test_cells_listing_and_case(api):
    sid = sheet(api); r = put(api, sid, "b7", "5"); assert r["ref"] == "B7"
    put(api, sid, "C3", "x"); put(api, sid, "C3", "")
    cells = api.get(f"/api/sheets/{sid}").json()["cells"]
    assert cells == {"B7": {"input": "5", "value": 5, "type": "number"}}
    assert get(api, sid, "D4") == {"ref": "D4", "input": "", "value": None, "type": "empty"}

@pytest.mark.parametrize("ref,body", [("AA1", {"input": "1"}), ("A1001", {"input": "1"}), ("A0", {"input": "1"}),
                                      ("A1", {"input": 5}), ("A1", {"input": "x" * 1001}), ("A1", {})])
def test_put_validation(api, ref, body):
    sid = sheet(api); assert api.put(f"/api/sheets/{sid}/cells/{ref}", body).status_code == 400

@pytest.mark.parametrize("f,expected", [
    ("=1+2*3", 7), ("=(1+2)*3", 9), ("=2^3^2", 64), ("=-2^2", 4), ("=2^-1", 0.5), ("=10/4", 2.5), ("=7-2-1", 4),
    ("= 1 +   2 ", 3), ("=--3", 3), ("=TRUE+TRUE", 2), ("=Z999+5", 5), ("=1+1=2", True), ("=2<>2", False),
    ("=1<2", True), ('="abc"="ABC"', True), ('="a"<"B"', True), ("=TRUE>FALSE", True), ("=A99=0", True), ('=A99=""', True),
])
def test_arithmetic_and_comparison(api, f, expected):
    r = ev(api, f)
    if isinstance(expected, bool): assert r["type"] == "boolean" and r["value"] is expected, r
    elif isinstance(expected, float): assert r["value"] == pytest.approx(expected), r
    else: assert r["type"] == "number" and r["value"] == expected, r

@pytest.mark.parametrize("f,expected", [
    ('="a""b"', 'a"b'), ('="x"&1&TRUE', "x1TRUE"), ("=1&2", "12"), ('=0.5&""', "0.5"), ('="n"&A50', "n"),
])
def test_strings(api, f, expected):
    r = ev(api, f); assert r["type"] == "string" and r["value"] == expected

@pytest.mark.parametrize("f,err", [
    ("=1/0", "#DIV/0!"), ("=10^400", "#NUM!"), ("=1+", "#ERROR!"), ("=(1", "#ERROR!"), ('="abc"+1', "#VALUE!"),
    ('=1="1"', "#VALUE!"), ("=AA1", "#REF!"), ("=A1001+1", "#REF!"), ("=FOO(1)", "#NAME?"), ("=ABS(1,2)", "#NAME?"),
    ("=A1:A2", "#VALUE!"), ("=(1/0)+AA1", "#DIV/0!"), ("=AA1+(1/0)", "#REF!"),
])
def test_errors(api, f, err):
    r = ev(api, f); assert r["type"] == "error" and r["value"] == err and r["input"] == f

def test_dependencies_update(api):
    sid = sheet(api)
    batch(api, sid, {"A1": "1", "B1": "=A1+1", "C1": "=b1*10", "D1": "=$A$1"})
    assert val(api, sid, "C1") == 20
    put(api, sid, "A1", "5"); assert val(api, sid, "C1") == 60 and val(api, sid, "D1") == 5
    put(api, sid, "A1", "x"); assert val(api, sid, "C1") == "#VALUE!"
    put(api, sid, "A1", ""); assert val(api, sid, "C1") == 10

def test_error_propagation(api):
    sid = sheet(api); batch(api, sid, {"A1": "=1/0", "B1": "=A1+1", "C1": "=SUM(A1,1)", "D1": "=IF(TRUE,1,A1)"})
    assert val(api, sid, "B1") == "#DIV/0!" and val(api, sid, "C1") == "#DIV/0!" and val(api, sid, "D1") == 1

def test_cycles(api):
    sid = sheet(api)
    batch(api, sid, {"A1": "=B1", "B1": "=A1", "C1": "=A1+1", "D1": "=D1+1"})
    for ref in ("A1", "B1", "C1", "D1"): assert val(api, sid, ref) == "#CYCLE!", ref
    put(api, sid, "B1", "5")
    assert val(api, sid, "A1") == 5 and val(api, sid, "C1") == 6 and val(api, sid, "D1") == "#CYCLE!"

def test_aggregate_functions(api):
    sid = sheet(api); batch(api, sid, {"A1": "1", "A2": "x", "A3": "TRUE", "A5": "4"})
    cases = {"=SUM(A1:A5)": 5, "=COUNT(A1:A5)": 2, "=AVERAGE(A1:A5)": 2.5, "=MIN(A1:A5)": 1, "=MAX(A1:A5)": 4,
             "=SUM(A1:A5,TRUE)": 6, "=sum(a5:a1)": 5, '=COUNT(1,"x",TRUE,A1:A5)': 3, "=MIN(B1:B3)": 0, "=MAX(B1:B3)": 0,
             "=SUM(A1:A5)*2": 10}
    for f, exp in cases.items():
        r = put(api, sid, "C1", f); assert r["value"] == exp, (f, r)
    assert put(api, sid, "C1", "=AVERAGE(B1:B3)")["value"] == "#DIV/0!"
    assert put(api, sid, "C1", '=SUM("x")')["value"] == "#VALUE!"
    put(api, sid, "A4", "=1/0"); assert put(api, sid, "C1", "=SUM(A1:A5)")["value"] == "#DIV/0!"

@pytest.mark.parametrize("f,expected", [
    ('=IF(1>0,"y","n")', "y"), ("=IF(0,1)", False), ("=IF(TRUE,1,1/0)", 1), ('=IF("x",1,2)', "#VALUE!"), ("=IF(A77,1,2)", 2),
    ("=ROUND(2.5,0)", 3), ("=ROUND(-2.5,0)", -3), ("=ROUND(1234,-2)", 1200), ("=ROUND(3.14159,2)", 3.14), ("=ABS(-3)", 3),
    ('=LEN("hello")', 5), ("=LEN(12.5)", 4), ('=CONCAT("a",1,TRUE)', "a1TRUE"), ('=if(true,"low","x")', "low"),
])
def test_other_functions(api, f, expected):
    r = ev(api, f)
    if isinstance(expected, bool): assert r["type"] == "boolean" and r["value"] is expected, r
    elif isinstance(expected, float): assert r["value"] == pytest.approx(expected)
    else: assert r["value"] == expected and type(r["value"]) is type(expected), r

def test_concat_range_row_major(api):
    sid = sheet(api); batch(api, sid, {"C1": "a", "D1": "1", "C2": "TRUE", "E3": "z"})
    assert put(api, sid, "A1", "=CONCAT(C1:D2)")["value"] == "a1TRUE"

def test_batch_order_independent_and_atomic(api):
    sid = sheet(api); res = batch(api, sid, {"A1": "=B1*2", "B1": "21"})
    assert res["A1"]["value"] == 42 and res["B1"]["value"] == 21
    r = api.post(f"/api/sheets/{sid}/cells", {"cells": {"B1": "1", "ZZ9": "2"}}); assert r.status_code == 400
    assert val(api, sid, "B1") == 21

def test_long_chain(api):
    sid = sheet(api); cells = {"A1": "1"}
    for i in range(2, 301): cells[f"A{i}"] = f"=A{i-1}+1"
    batch(api, sid, cells); assert val(api, sid, "A300") == 300
    put(api, sid, "A1", "101"); assert val(api, sid, "A300") == 400

def test_insert_rows(api):
    sid = sheet(api)
    batch(api, sid, {"A1": "1", "A2": "2", "A3": "3", "B2": "10", "A5": "=SUM(A1:A3)*$B$2", "C1": "=A3", "D1": "=sum(A1:A3) + 0",
                     "E1": "=A1"})
    r = api.post(f"/api/sheets/{sid}/rows/insert", {"at": 2, "count": 1}); assert r.status_code == 200
    assert val(api, sid, "A2") is None and val(api, sid, "A3") == 2 and val(api, sid, "A4") == 3 and val(api, sid, "B3") == 10
    assert inp(api, sid, "A6") == "=SUM(A1:A4)*$B$3" and val(api, sid, "A6") == 60
    assert inp(api, sid, "C1") == "=A4" and val(api, sid, "C1") == 3
    assert inp(api, sid, "D1") == "=sum(A1:A4) + 0"
    assert inp(api, sid, "E1") == "=A1"
    assert get(api, sid, "A5")["type"] == "empty"

def test_insert_rows_bottom_overflow(api):
    sid = sheet(api); batch(api, sid, {"A999": "9", "B1": "=A999", "A1000": "x"})
    api.post(f"/api/sheets/{sid}/rows/insert", {"at": 500, "count": 2})
    assert inp(api, sid, "B1") == "=#REF!" and val(api, sid, "B1") == "#REF!"
    assert get(api, sid, "A1000")["type"] == "empty"

def test_delete_rows(api):
    sid = sheet(api)
    batch(api, sid, {"A1": "1", "A2": "2", "A3": "3", "A4": "4", "A5": "5", "B1": "=A2+A5", "C1": "=SUM(A2:A4)",
                     "C10": "=A3", "C12": "=SUM(A2:A3)", "C13": "=SUM(A1:A5)"})
    r = api.post(f"/api/sheets/{sid}/rows/delete", {"at": 2, "count": 2}); assert r.status_code == 200
    assert [val(api, sid, f"A{i}") for i in (1, 2, 3, 4)] == [1, 4, 5, None]
    assert inp(api, sid, "B1") == "=#REF!+A3" and val(api, sid, "B1") == "#REF!"
    assert inp(api, sid, "C1") == "=SUM(A2:A2)" and val(api, sid, "C1") == 4
    assert inp(api, sid, "C8") == "=#REF!" and val(api, sid, "C8") == "#REF!"
    assert inp(api, sid, "C10") == "=SUM(#REF!)" and val(api, sid, "C10") == "#REF!"
    assert inp(api, sid, "C11") == "=SUM(A1:A3)" and val(api, sid, "C11") == 10
    assert get(api, sid, "C12")["type"] == "empty" and get(api, sid, "C13")["type"] == "empty"

def test_copy_relative_absolute(api):
    sid = sheet(api); batch(api, sid, {"A1": "1", "A2": "2", "B1": "=A1*2", "B2": "=$A$1+A2", "C1": "x"})
    assert api.post(f"/api/sheets/{sid}/copy", {"from": "B1:C2", "to": "D5"}).status_code == 200
    assert inp(api, sid, "D5") == "=C5*2" and val(api, sid, "D5") == 0
    assert inp(api, sid, "D6") == "=$A$1+C6" and val(api, sid, "D6") == 1
    assert inp(api, sid, "E5") == "x" and get(api, sid, "E6")["type"] == "empty"
    batch(api, sid, {"E10": "=$A1+B$1", "D10": "=A1"})
    api.post(f"/api/sheets/{sid}/copy", {"from": "E10", "to": "E20"}); assert inp(api, sid, "E20") == "=$A11+B$1"
    api.post(f"/api/sheets/{sid}/copy", {"from": "D10", "to": "A10"}); assert inp(api, sid, "A10") == "=#REF!" and val(api, sid, "A10") == "#REF!"

def test_copy_overlap_and_clear(api):
    sid = sheet(api); batch(api, sid, {"A1": "1", "A2": "2", "A3": "=A1+A2", "B2": "keep"})
    api.post(f"/api/sheets/{sid}/copy", {"from": "A1:A3", "to": "A2"})
    assert [inp(api, sid, f"A{i}") for i in (1, 2, 3, 4)] == ["1", "1", "2", "=A2+A3"] and val(api, sid, "A4") == 3
    batch(api, sid, {"F1": "v"}); api.post(f"/api/sheets/{sid}/copy", {"from": "G1", "to": "F1"})
    assert get(api, sid, "F1")["type"] == "empty"

@pytest.mark.parametrize("path,body", [("rows/insert", {"at": 0, "count": 1}), ("rows/insert", {"at": 1, "count": 0}),
                                       ("rows/delete", {"at": "x", "count": 1}), ("copy", {"from": "A1:ZZ2", "to": "B1"}),
                                       ("copy", {"from": "A1", "to": "nope"})])
def test_structural_validation(api, path, body):
    sid = sheet(api); assert api.post(f"/api/sheets/{sid}/{path}", body).status_code == 400

def test_export_csv(api):
    sid = sheet(api); batch(api, sid, {"A1": "1", "B1": "x,y", "A2": "TRUE", "C2": "=1/0", "B3": "=0.5*1"})
    r = api.get(f"/api/sheets/{sid}/export.csv"); assert r.status_code == 200 and "text/csv" in r.headers.get("content-type", "")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert [x for x in rows if x] == [["1", "x,y", ""], ["TRUE", "", "#DIV/0!"], ["", "0.5", ""]]
    assert '"x,y"' in r.text

def test_persistence(server, api):
    sid = sheet(api); batch(api, sid, {"A1": "2", "B1": "=A1*3"})
    server.restart()
    assert val(api, sid, "B1") == 6
    put(api, sid, "A1", "5"); assert val(api, sid, "B1") == 15
