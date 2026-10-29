import csv, io
import pytest
from conftest import uniq, Api

PW = "s3cret-pass-XYZ"

def user(server, name=None):
    a = Api(server); email = f"{uniq()}@example.com"; name = name or uniq("n")
    r = a.post("/api/auth/register", {"email": email, "password": PW, "name": name}); assert r.status_code == 201, r.text
    r2 = a.post("/api/auth/login", {"email": email, "password": PW}); assert r2.status_code == 200, r2.text
    a.token = r2.json()["token"]; a.id = r.json()["id"]; a.email = email; a.name = name; return a

def group(owner, *members, name="G"):
    r = owner.post("/api/groups", {"name": name}); assert r.status_code == 201, r.text; g = r.json()
    for m in members:
        r = owner.post(f"/api/groups/{g['id']}/members", {"email": m.email}); assert r.status_code == 201, r.text
    return g

def exp(a, gid, amount, paid_by, typ, parts, date="2026-10-01", desc="e", code=201):
    body = {"description": desc, "amountCents": amount, "paidBy": paid_by, "date": date,
            "split": {"type": typ, "participants": parts}}
    r = a.post(f"/api/groups/{gid}/expenses", body); assert r.status_code == code, r.text
    return r.json()

def shares(e): return [(s["userId"], s["amountCents"]) for s in e["shares"]]
def bal(a, gid):
    r = a.get(f"/api/groups/{gid}/balances"); assert r.status_code == 200; return {x["userId"]: x["balanceCents"] for x in r.json()}
def sett(a, gid):
    r = a.get(f"/api/groups/{gid}/settlements"); assert r.status_code == 200
    return [(x["fromUserId"], x["toUserId"], x["amountCents"]) for x in r.json()]

@pytest.fixture
def four(server):
    us = [user(server) for _ in range(4)]; g = group(us[0], *us[1:]); return us, g

def test_index_html(api):
    r = api.get("/"); assert r.status_code == 200 and "text/html" in r.headers.get("content-type", "")

def test_register_login(server, api):
    e = f"{uniq()}@EX.com"
    r = api.post("/api/auth/register", {"email": e, "password": PW, "name": "  Ann  "}); assert r.status_code == 201
    j = r.json(); assert j["email"] == e.lower() and j["name"] == "Ann" and PW not in r.text
    assert api.post("/api/auth/register", {"email": e, "password": PW, "name": "B"}).status_code == 409
    assert api.post("/api/auth/register", {"email": "x" + e, "password": "short", "name": "B"}).status_code == 400
    assert api.post("/api/auth/register", {"email": "y" + e, "password": PW, "name": ""}).status_code == 400
    assert api.post("/api/auth/login", {"email": e, "password": "wrongwrong"}).status_code == 401
    assert api.get("/api/groups").status_code == 401

def test_groups_and_membership(server):
    a, b, c = user(server), user(server), user(server)
    g = group(a, b)
    gg = a.get(f"/api/groups/{g['id']}").json(); assert [m["id"] for m in gg["members"]] == sorted([a.id, b.id])
    assert {"id", "email", "name"} <= set(gg["members"][0])
    assert b.post(f"/api/groups/{g['id']}/members", {"email": c.email}).status_code == 201
    assert b.post(f"/api/groups/{g['id']}/members", {"email": c.email}).status_code == 409
    assert b.post(f"/api/groups/{g['id']}/members", {"email": "ghost@x.com"}).status_code == 404
    assert g["id"] in [x["id"] for x in c.get("/api/groups").json()]
    assert a.post("/api/groups", {"name": ""}).status_code == 400

def test_access_rules(server, four):
    (a, b, c, d), g = four; x = user(server)
    for path in ["", "/expenses", "/balances", "/settlements", "/payments", "/export.csv"]:
        assert x.get(f"/api/groups/{g['id']}{path}").status_code == 403, path
    assert x.get("/api/groups/999999").status_code == 404
    assert x.post(f"/api/groups/{g['id']}/members", {"email": x.email}).status_code == 403

def test_equal_remainder_in_listed_order(four):
    (a, b, c, d), g = four
    e = exp(a, g["id"], 1000, a.id, "equal", [{"userId": c.id}, {"userId": a.id}, {"userId": b.id}])
    assert shares(e) == [(c.id, 334), (a.id, 333), (b.id, 333)]
    assert e["amountCents"] == 1000 and e["paidBy"] == a.id and e["groupId"] == g["id"] and e["createdBy"] == a.id

def test_exact(four):
    (a, b, c, d), g = four
    e = exp(a, g["id"], 3000, b.id, "exact", [{"userId": c.id, "value": 1000}, {"userId": d.id, "value": 2000}])
    assert shares(e) == [(c.id, 1000), (d.id, 2000)]
    exp(a, g["id"], 3000, b.id, "exact", [{"userId": c.id, "value": 1000}, {"userId": d.id, "value": 1999}], code=400)

def test_percent_largest_remainder(four):
    (a, b, c, d), g = four
    e = exp(a, g["id"], 1001, a.id, "percent",
            [{"userId": a.id, "value": 33.33}, {"userId": b.id, "value": 33.33}, {"userId": c.id, "value": 33.34}])
    assert shares(e) == [(a.id, 334), (b.id, 333), (c.id, 334)]
    exp(a, g["id"], 1000, a.id, "percent", [{"userId": a.id, "value": 50}, {"userId": b.id, "value": 49}], code=400)

def test_shares_largest_remainder(four):
    (a, b, c, d), g = four
    e = exp(a, g["id"], 1000, a.id, "shares", [{"userId": b.id, "value": 1}, {"userId": c.id, "value": 1}, {"userId": a.id, "value": 1}])
    assert shares(e) == [(b.id, 334), (c.id, 333), (a.id, 333)]
    e2 = exp(a, g["id"], 101, a.id, "shares", [{"userId": b.id, "value": 2}, {"userId": c.id, "value": 1}])
    assert shares(e2) == [(b.id, 67), (c.id, 34)]
    exp(a, g["id"], 100, a.id, "shares", [{"userId": b.id, "value": 0}], code=400)

@pytest.mark.parametrize("mut", ["desc", "amount0", "amountfloat", "paidby", "date", "date2", "empty", "dup", "nonmember", "type", "novalue"])
def test_expense_validation(server, four, mut):
    (a, b, c, d), g = four; x = user(server)
    body = {"description": "ok", "amountCents": 500, "paidBy": a.id, "date": "2026-10-01",
            "split": {"type": "equal", "participants": [{"userId": a.id}, {"userId": b.id}]}}
    if mut == "desc": body["description"] = "  "
    if mut == "amount0": body["amountCents"] = 0
    if mut == "amountfloat": body["amountCents"] = 10.5
    if mut == "paidby": body["paidBy"] = x.id
    if mut == "date": body["date"] = "2026-02-30"
    if mut == "date2": body["date"] = "01/10/2026"
    if mut == "empty": body["split"]["participants"] = []
    if mut == "dup": body["split"]["participants"] = [{"userId": a.id}, {"userId": a.id}]
    if mut == "nonmember": body["split"]["participants"] = [{"userId": x.id}]
    if mut == "type": body["split"]["type"] = "weird"
    if mut == "novalue": body["split"] = {"type": "exact", "participants": [{"userId": a.id}, {"userId": b.id}]}
    assert a.post(f"/api/groups/{g['id']}/expenses", body).status_code == 400

def test_expense_list_order_and_delete(four):
    (a, b, c, d), g = four; P = [{"userId": a.id}, {"userId": b.id}]
    e1 = exp(a, g["id"], 100, a.id, "equal", P, date="2026-09-01")
    e2 = exp(a, g["id"], 100, a.id, "equal", P, date="2026-10-05")
    e3 = exp(a, g["id"], 100, a.id, "equal", P, date="2026-09-01")
    assert [e["id"] for e in a.get(f"/api/groups/{g['id']}/expenses").json()] == [e2["id"], e3["id"], e1["id"]]
    assert b.delete(f"/api/groups/{g['id']}/expenses/{e2['id']}").status_code == 204
    assert b.delete(f"/api/groups/{g['id']}/expenses/{e2['id']}").status_code == 404
    assert [e["id"] for e in a.get(f"/api/groups/{g['id']}/expenses").json()] == [e3["id"], e1["id"]]

def test_balances_payments_settlements(four):
    (a, b, c, d), g = four; gid = g["id"]
    exp(a, gid, 9000, a.id, "equal", [{"userId": a.id}, {"userId": b.id}, {"userId": c.id}])
    exp(b, gid, 3000, b.id, "exact", [{"userId": c.id, "value": 1000}, {"userId": d.id, "value": 2000}])
    exp(d, gid, 1200, d.id, "shares", [{"userId": a.id, "value": 1}, {"userId": d.id, "value": 2}])
    assert bal(a, gid) == {a.id: 5600, b.id: 0, c.id: -4000, d.id: -1600}
    r = a.get(f"/api/groups/{gid}/balances").json(); assert [x["userId"] for x in r] == sorted([a.id, b.id, c.id, d.id])
    assert {x["userId"]: x["name"] for x in r}[c.id] == c.name
    assert sett(a, gid) == [(c.id, a.id, 4000), (d.id, a.id, 1600)]
    p = c.post(f"/api/groups/{gid}/payments", {"fromUserId": c.id, "toUserId": b.id, "amountCents": 500})
    assert p.status_code == 201 and p.json()["amountCents"] == 500
    assert bal(a, gid) == {a.id: 5600, b.id: -500, c.id: -3500, d.id: -1600}
    assert sett(a, gid) == [(c.id, a.id, 3500), (d.id, a.id, 1600), (b.id, a.id, 500)]
    assert [x["id"] for x in a.get(f"/api/groups/{gid}/payments").json()] == [p.json()["id"]]

def test_settlement_ties(four):
    (p, q, r, s), g = four; gid = g["id"]
    exp(p, gid, 1000, p.id, "equal", [{"userId": r.id}, {"userId": s.id}])
    exp(q, gid, 1000, q.id, "equal", [{"userId": r.id}, {"userId": s.id}])
    assert sett(p, gid) == [(r.id, p.id, 1000), (s.id, q.id, 1000)]

def test_settlements_zero_after_paying(four):
    (a, b, c, d), g = four; gid = g["id"]
    exp(a, gid, 777, b.id, "equal", [{"userId": a.id}, {"userId": b.id}, {"userId": c.id}, {"userId": d.id}])
    for f, t, amt in sett(a, gid):
        assert a.post(f"/api/groups/{gid}/payments", {"fromUserId": f, "toUserId": t, "amountCents": amt}).status_code == 201
    assert set(bal(a, gid).values()) == {0} and sett(a, gid) == []

@pytest.mark.parametrize("body_fn", [lambda a, b, x: {"fromUserId": a, "toUserId": a, "amountCents": 5},
                                     lambda a, b, x: {"fromUserId": a, "toUserId": x, "amountCents": 5},
                                     lambda a, b, x: {"fromUserId": a, "toUserId": b, "amountCents": 0}])
def test_payment_validation(server, four, body_fn):
    (a, b, c, d), g = four; x = user(server)
    assert a.post(f"/api/groups/{g['id']}/payments", body_fn(a.id, b.id, x.id)).status_code == 400

def test_balance_includes_all_members(four):
    (a, b, c, d), g = four
    assert bal(a, g["id"]) == {a.id: 0, b.id: 0, c.id: 0, d.id: 0} and sett(a, g["id"]) == []

def test_export_csv(server):
    a = user(server, name="Ann, the payer"); b = user(server, name="Bob"); g = group(a, b); gid = g["id"]
    P = [{"userId": a.id}, {"userId": b.id}]
    exp(a, gid, 500, b.id, "equal", P, date="2026-10-02", desc='Pizza "Napoli"')
    exp(a, gid, 300, a.id, "equal", P, date="2026-09-30", desc="Taxi")
    r = a.get(f"/api/groups/{gid}/export.csv"); assert r.status_code == 200 and "text/csv" in r.headers.get("content-type", "")
    rows = [x for x in csv.reader(io.StringIO(r.text)) if x]
    assert rows == [["date", "description", "paidBy", "amountCents"], ["2026-09-30", "Taxi", "Ann, the payer", "300"],
                    ["2026-10-02", 'Pizza "Napoli"', "Bob", "500"]]
    assert '"Ann, the payer"' in r.text and '"Pizza ""Napoli"""' in r.text

def test_persistence(server):
    a = user(server); b = user(server); g = group(a, b)
    exp(a, g["id"], 1000, a.id, "equal", [{"userId": a.id}, {"userId": b.id}])
    server.restart()
    r = a.post("/api/auth/login", {"email": a.email, "password": PW}); a.token = r.json()["token"]
    assert bal(a, g["id"]) == {a.id: 500, b.id: -500}
