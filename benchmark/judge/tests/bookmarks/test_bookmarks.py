import csv, io, time
import pytest
from conftest import uniq

def mk(api, url=None, title="T", tags=None, code=201):
    body = {"url": url or f"https://ex.com/{uniq()}", "title": title}
    if tags is not None: body["tags"] = tags
    r = api.post("/api/bookmarks", body); assert r.status_code == code, r.text
    return r.json()

def test_index_html(api):
    r = api.get("/"); assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "<form" in r.text.lower() or "<input" in r.text.lower()

def test_create_returns_fields(api):
    b = mk(api, title="  Hello  ", tags=["B", " a ", "b", ""])
    assert isinstance(b["id"], int) and b["title"] == "Hello"
    assert b["tags"] == ["a", "b"]
    assert b["createdAt"].endswith("Z") and "updatedAt" in b

def test_get_by_id_and_404(api):
    b = mk(api); r = api.get(f"/api/bookmarks/{b['id']}")
    assert r.status_code == 200 and r.json()["url"] == b["url"]
    assert api.get("/api/bookmarks/999999").status_code == 404

@pytest.mark.parametrize("body", [
    {"title": "x"}, {"url": "ftp://a.com", "title": "x"}, {"url": "notaurl", "title": "x"},
    {"url": "https://a.com/1", "title": "   "}, {"url": "https://a.com/2"},
    {"url": "https://a.com/3", "title": "x" * 201}, {"url": "https://a.com/4", "title": "x", "tags": "a,b"},
    {"url": "https://a.com/5", "title": "x", "tags": ["a" * 31]},
    {"url": "https://a.com/6", "title": "x", "tags": [f"t{i}" for i in range(11)]},
    {"url": 123, "title": "x"}, {"url": "https://a.com/7", "title": "x", "tags": [1, 2]},
])
def test_validation_400(api, body):
    r = api.post("/api/bookmarks", body); assert r.status_code == 400, r.text
    assert "error" in r.json()

def test_ten_tags_ok_after_dedupe(api):
    b = mk(api, tags=[f"t{i}" for i in range(10)] + ["T1", "t2"])
    assert len(b["tags"]) == 10

def test_duplicate_url_409(api):
    b = mk(api); r = api.post("/api/bookmarks", {"url": b["url"], "title": "again"}); assert r.status_code == 409

def test_list_sorted_newest_first(api):
    a = mk(api); time.sleep(0.01); b = mk(api)
    ids = [x["id"] for x in api.get("/api/bookmarks", params={"limit": 100}).json()]
    assert ids.index(b["id"]) < ids.index(a["id"])

def test_filter_tag_case_insensitive(api):
    t = uniq("tag"); a = mk(api, tags=[t]); mk(api, tags=["other"])
    r = api.get("/api/bookmarks", params={"tag": t.upper()}); assert r.status_code == 200
    assert [x["id"] for x in r.json()] == [a["id"]]

def test_search_q_title_and_url(api):
    w = uniq("word"); a = mk(api, title=f"About {w.upper()} here"); b = mk(api, url=f"https://ex.com/{w}/x")
    ids = {x["id"] for x in api.get("/api/bookmarks", params={"q": w}).json()}
    assert ids == {a["id"], b["id"]}

def test_combined_filters(api):
    t = uniq("tg"); w = uniq("w")
    a = mk(api, title=w, tags=[t]); mk(api, title=w); mk(api, tags=[t])
    assert [x["id"] for x in api.get("/api/bookmarks", params={"q": w, "tag": t}).json()] == [a["id"]]

def test_pagination_and_total(api):
    t = uniq("pg"); made = [mk(api, tags=[t])["id"] for _ in range(5)]
    r = api.get("/api/bookmarks", params={"tag": t, "limit": 2, "offset": 1})
    assert r.status_code == 200 and r.headers.get("X-Total-Count") == "5"
    assert [x["id"] for x in r.json()] == list(reversed(made))[1:3]

@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"limit": "abc"}, {"offset": -1}, {"limit": "2.5"}])
def test_pagination_invalid(api, params):
    assert api.get("/api/bookmarks", params=params).status_code == 400

def test_default_limit_50(api):
    for _ in range(52): mk(api)
    assert len(api.get("/api/bookmarks").json()) == 50

def test_patch_updates(api):
    b = mk(api, tags=["x"]); time.sleep(0.01)
    r = api.patch(f"/api/bookmarks/{b['id']}", {"title": " New ", "tags": ["Z", "y"]}); assert r.status_code == 200
    j = r.json(); assert j["title"] == "New" and j["tags"] == ["y", "z"] and j["url"] == b["url"]
    assert j["updatedAt"] != b["updatedAt"]
    assert api.get(f"/api/bookmarks/{b['id']}").json()["title"] == "New"

def test_patch_validation_and_conflict(api):
    a = mk(api); b = mk(api)
    assert api.patch(f"/api/bookmarks/{a['id']}", {"url": "bad"}).status_code == 400
    assert api.patch(f"/api/bookmarks/{a['id']}", {"url": b["url"]}).status_code == 409
    assert api.patch(f"/api/bookmarks/{a['id']}", {"url": a["url"]}).status_code == 200
    assert api.patch("/api/bookmarks/999999", {"title": "x"}).status_code == 404

def test_delete(api):
    b = mk(api); assert api.delete(f"/api/bookmarks/{b['id']}").status_code == 204
    assert api.get(f"/api/bookmarks/{b['id']}").status_code == 404
    assert api.delete(f"/api/bookmarks/{b['id']}").status_code == 404

def test_tags_counts_sorted(api):
    p = uniq("k")
    mk(api, tags=[p + "b", p + "a"]); mk(api, tags=[p + "b"]); mk(api, tags=[p + "c", p + "a"])
    tags = [t for t in api.get("/api/tags").json() if t["tag"].startswith(p)]
    assert tags == [{"tag": p + "a", "count": 2}, {"tag": p + "b", "count": 2}, {"tag": p + "c", "count": 1}]
    allt = api.get("/api/tags").json()
    assert all((allt[i]["count"], ) >= (allt[i + 1]["count"],) for i in range(len(allt) - 1))

def test_tags_disappear_after_delete(api):
    t = uniq("gone"); b = mk(api, tags=[t]); api.delete(f"/api/bookmarks/{b['id']}")
    assert t not in [x["tag"] for x in api.get("/api/tags").json()]

def test_export_csv(api):
    b = mk(api, title='He said "hi", ok', tags=["q", "p"])
    r = api.get("/api/export"); assert r.status_code == 200 and "text/csv" in r.headers.get("content-type", "")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == ["id", "url", "title", "tags", "createdAt"]
    ids = [int(x[0]) for x in rows[1:] if x]; assert ids == sorted(ids)
    row = [x for x in rows[1:] if x and int(x[0]) == b["id"]][0]
    assert row[2] == 'He said "hi", ok' and row[3] == "p|q"
    assert '"He said ""hi"", ok"' in r.text

def test_unknown_route_404(api):
    assert api.get("/api/nope").status_code == 404

def test_persistence_after_restart(server, api):
    b = mk(api, tags=["persist"]); server.restart()
    r = api.get(f"/api/bookmarks/{b['id']}"); assert r.status_code == 200 and r.json()["tags"] == ["persist"]
    n = mk(api); assert n["id"] > b["id"]
