import os
import pytest
from conftest import uniq, Api

PW = "s3cret-pass-XYZ"

def user(server, email=None):
    a = Api(server); email = email or f"{uniq()}@example.com"
    r = a.post("/api/auth/register", {"email": email, "password": PW}); assert r.status_code == 201, r.text
    r2 = a.post("/api/auth/login", {"email": email, "password": PW}); assert r2.status_code == 200, r2.text
    a.token = r2.json()["token"]; a.id = r.json()["id"]; a.email = email.lower(); return a

def board(a, **kw):
    r = a.post("/api/boards", {"name": kw.pop("name", "B"), **kw}); assert r.status_code == 201, r.text; return r.json()

def card(a, bid, title="c", column=None, code=201):
    body = {"title": title}
    if column: body["column"] = column
    r = a.post(f"/api/boards/{bid}/cards", body); assert r.status_code == code, r.text; return r.json()

def cols(a, bid):
    r = a.get(f"/api/boards/{bid}/cards"); assert r.status_code == 200; return r.json()

def titles(a, bid, col): return [c["title"] for c in cols(a, bid)[col]]

def test_index_html(api):
    r = api.get("/"); assert r.status_code == 200 and "text/html" in r.headers.get("content-type", "")

def test_register_ok_no_secret(api):
    e = f"{uniq()}@Example.COM"; r = api.post("/api/auth/register", {"email": e, "password": PW})
    assert r.status_code == 201; j = r.json(); assert j["email"] == e.lower() and isinstance(j["id"], int)
    assert PW not in r.text and "password" not in {k.lower() for k in j} and "hash" not in r.text.lower()

@pytest.mark.parametrize("body", [{"email": "bad", "password": PW}, {"email": "a@b", "password": PW},
                                  {"email": "x@y.com", "password": "short"}, {"password": PW}, {"email": "z@y.com"}])
def test_register_validation(api, body):
    assert api.post("/api/auth/register", body).status_code == 400

def test_register_duplicate_case_insensitive(server, api):
    u = user(server); assert api.post("/api/auth/register", {"email": u.email.upper(), "password": PW}).status_code == 409

def test_login(server, api):
    u = user(server)
    r = api.post("/api/auth/login", {"email": u.email.upper(), "password": PW}); assert r.status_code == 200
    assert r.json()["user"] == {"id": u.id, "email": u.email}
    assert api.post("/api/auth/login", {"email": u.email, "password": PW + "x"}).status_code == 401
    assert api.post("/api/auth/login", {"email": "nobody@x.com", "password": PW}).status_code == 401

def test_auth_required(api):
    assert api.get("/api/boards").status_code == 401
    assert api.get("/api/me").status_code == 401
    assert api.get("/api/boards", token="garbage").status_code == 401

def test_me(server):
    u = user(server); assert u.get("/api/me").json() == {"id": u.id, "email": u.email}

def test_logout_invalidates(server):
    u = user(server); assert u.post("/api/auth/logout").status_code == 204
    assert u.get("/api/me").status_code == 401

def test_password_not_on_disk(server):
    secret = "Unique-Plain-" + uniq()
    a = Api(server); e = f"{uniq()}@example.com"
    assert a.post("/api/auth/register", {"email": e, "password": secret}).status_code == 201
    server.restart()
    found = False
    for root, _, files in os.walk(server.data_dir):
        for f in files:
            with open(os.path.join(root, f), "rb") as fh:
                if secret.encode() in fh.read(): found = True
    assert not found
    assert a.post("/api/auth/login", {"email": e, "password": secret}).status_code == 200

def test_board_crud(server):
    u = user(server); b = board(u, name="  Proj  ")
    assert b["name"] == "Proj" and b["ownerId"] == u.id and b["wipLimit"] is None
    assert u.post("/api/boards", {"name": " "}).status_code == 400
    assert u.post("/api/boards", {"name": "x" * 101}).status_code == 400
    g = u.get(f"/api/boards/{b['id']}").json(); assert g["members"] == [{"id": u.id, "email": u.email}]
    r = u.patch(f"/api/boards/{b['id']}", {"name": "P2", "wipLimit": 2}); assert r.status_code == 200
    assert r.json()["name"] == "P2" and r.json()["wipLimit"] == 2
    assert u.delete(f"/api/boards/{b['id']}").status_code == 204
    assert u.get(f"/api/boards/{b['id']}").status_code == 404

def test_list_boards_owned_and_member(server):
    a = user(server); b = user(server); c = user(server)
    b1 = board(a); b2 = board(b); board(c)
    assert b.post(f"/api/boards/{b2['id']}/members", {"email": a.email}).status_code == 201
    assert [x["id"] for x in a.get("/api/boards").json()] == sorted([b1["id"], b2["id"]])

def test_access_rules(server):
    o = user(server); m = user(server); x = user(server); b = board(o)
    assert x.get(f"/api/boards/{b['id']}").status_code == 403
    assert x.get(f"/api/boards/{b['id']}/cards").status_code == 403
    assert x.get("/api/boards/999999").status_code == 404
    r = o.post(f"/api/boards/{b['id']}/members", {"email": m.email}); assert r.status_code == 201
    assert [u["id"] for u in r.json()] == sorted([o.id, m.id])
    assert m.get(f"/api/boards/{b['id']}").status_code == 200
    assert m.patch(f"/api/boards/{b['id']}", {"name": "hack"}).status_code == 403
    assert m.delete(f"/api/boards/{b['id']}").status_code == 403
    assert m.post(f"/api/boards/{b['id']}/members", {"email": x.email}).status_code == 403
    c = card(o, b["id"]); assert x.patch(f"/api/cards/{c['id']}", {"title": "z"}).status_code == 403
    assert x.delete(f"/api/cards/{c['id']}").status_code == 403
    assert o.patch("/api/cards/999999", {"title": "z"}).status_code == 404

def test_members_errors(server):
    o = user(server); m = user(server); b = board(o)
    assert o.post(f"/api/boards/{b['id']}/members", {"email": "ghost@x.com"}).status_code == 404
    assert o.post(f"/api/boards/{b['id']}/members", {"email": m.email}).status_code == 201
    assert o.post(f"/api/boards/{b['id']}/members", {"email": m.email}).status_code == 409
    assert o.post(f"/api/boards/{b['id']}/members", {"email": o.email}).status_code == 409
    assert o.delete(f"/api/boards/{b['id']}/members/{o.id}").status_code == 400
    assert o.delete(f"/api/boards/{b['id']}/members/{m.id}").status_code == 204
    assert m.get(f"/api/boards/{b['id']}").status_code == 403

def test_card_create_defaults(server):
    u = user(server); b = board(u)
    c = card(u, b["id"], "first"); assert c["column"] == "todo" and c["position"] == 0 and c["description"] == ""
    assert c["createdBy"] == u.id and c["boardId"] == b["id"]
    c2 = card(u, b["id"], "second"); assert c2["position"] == 1
    card(u, b["id"], "bad", column="later", code=400)
    card(u, b["id"], "", code=400)
    assert titles(u, b["id"], "todo") == ["first", "second"]
    assert cols(u, b["id"]) .keys() >= {"todo", "doing", "done"}

def test_member_can_edit_cards(server):
    o = user(server); m = user(server); b = board(o)
    o.post(f"/api/boards/{b['id']}/members", {"email": m.email})
    c = card(o, b["id"]); r = m.patch(f"/api/cards/{c['id']}", {"title": "by member", "description": "d"})
    assert r.status_code == 200 and r.json()["title"] == "by member" and r.json()["description"] == "d"

def test_move_to_end_of_other_column(server):
    u = user(server); b = board(u)
    a, bb, c = [card(u, b["id"], t) for t in "abc"]; d = card(u, b["id"], "d", column="done")
    r = u.patch(f"/api/cards/{bb['id']}", {"column": "done"}); assert r.status_code == 200
    assert r.json()["column"] == "done" and r.json()["position"] == 1
    assert titles(u, b["id"], "todo") == ["a", "c"] and titles(u, b["id"], "done") == ["d", "b"]
    k = cols(u, b["id"]); assert [x["position"] for x in k["todo"]] == [0, 1] and [x["position"] for x in k["done"]] == [0, 1]

def test_move_with_position_and_clamp(server):
    u = user(server); b = board(u)
    cs = {t: card(u, b["id"], t) for t in "abcd"}
    u.patch(f"/api/cards/{cs['d']['id']}", {"position": 0}); assert titles(u, b["id"], "todo") == ["d", "a", "b", "c"]
    u.patch(f"/api/cards/{cs['d']['id']}", {"position": 99}); assert titles(u, b["id"], "todo") == ["a", "b", "c", "d"]
    u.patch(f"/api/cards/{cs['a']['id']}", {"position": 2}); assert titles(u, b["id"], "todo") == ["b", "c", "a", "d"]
    u.patch(f"/api/cards/{cs['c']['id']}", {"column": "doing", "position": -5}); assert titles(u, b["id"], "doing") == ["c"]
    u.patch(f"/api/cards/{cs['b']['id']}", {"column": "doing", "position": 0}); assert titles(u, b["id"], "doing") == ["b", "c"]
    k = cols(u, b["id"]); assert [x["position"] for x in k["todo"]] == [0, 1] and [x["position"] for x in k["doing"]] == [0, 1]

def test_delete_card_compacts(server):
    u = user(server); b = board(u); cs = [card(u, b["id"], t) for t in "abc"]
    assert u.delete(f"/api/cards/{cs[0]['id']}").status_code == 204
    k = cols(u, b["id"]); assert [x["title"] for x in k["todo"]] == ["b", "c"] and [x["position"] for x in k["todo"]] == [0, 1]
    assert u.delete(f"/api/cards/{cs[0]['id']}").status_code == 404

def test_wip_limit(server):
    u = user(server); b = board(u, wipLimit=2)
    card(u, b["id"], "x", column="doing"); y = card(u, b["id"], "y", column="doing")
    card(u, b["id"], "z", column="doing", code=409)
    t = card(u, b["id"], "t"); assert u.patch(f"/api/cards/{t['id']}", {"column": "doing"}).status_code == 409
    assert titles(u, b["id"], "todo") == ["t"]
    assert u.patch(f"/api/cards/{y['id']}", {"position": 0}).status_code == 200
    assert titles(u, b["id"], "doing") == ["y", "x"]
    assert u.patch(f"/api/boards/{b['id']}", {"wipLimit": 1}).status_code == 200
    assert u.patch(f"/api/cards/{y['id']}", {"column": "done"}).status_code == 200
    assert u.patch(f"/api/cards/{t['id']}", {"column": "doing"}).status_code == 409
    assert u.patch(f"/api/boards/{b['id']}", {"wipLimit": None}).status_code == 200
    assert u.patch(f"/api/cards/{t['id']}", {"column": "doing"}).status_code == 200

def test_delete_board_deletes_cards(server):
    u = user(server); b = board(u); c = card(u, b["id"])
    u.delete(f"/api/boards/{b['id']}"); assert u.patch(f"/api/cards/{c['id']}", {"title": "q"}).status_code == 404

def test_persistence(server):
    u = user(server); b = board(u, name="persist"); card(u, b["id"], "keep", column="done")
    server.restart()
    r = u.post("/api/auth/login", {"email": u.email, "password": PW}); assert r.status_code == 200
    u.token = r.json()["token"]
    assert titles(u, b["id"], "done") == ["keep"]
