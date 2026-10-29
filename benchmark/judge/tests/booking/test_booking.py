import pytest
from conftest import uniq, Api

PW = "s3cret-pass-XYZ"
_state = {}

def user(server):
    a = Api(server); email = f"{uniq()}@example.com"
    r = a.post("/api/auth/register", {"email": email, "password": PW, "name": "N " + uniq()}); assert r.status_code == 201, r.text
    r2 = a.post("/api/auth/login", {"email": email, "password": PW}); assert r2.status_code == 200, r2.text
    a.token = r2.json()["token"]; a.id = r.json()["id"]; a.role = r.json()["role"]; a.email = email; return a

@pytest.fixture(scope="session", autouse=True)
def admin(server):
    if "admin" not in _state: _state["admin"] = user(server)
    return _state["admin"]

def room(adm, tz="Europe/Rome", open_="08:00", close="20:00"):
    r = adm.post("/api/rooms", {"name": uniq("Room "), "timezone": tz, "openTime": open_, "closeTime": close})
    assert r.status_code == 201, r.text; return r.json()

def book(a, rid, start, end, title="mtg", recurrence=None, code=201):
    body = {"title": title, "start": start, "end": end}
    if recurrence: body["recurrence"] = recurrence
    r = a.post(f"/api/rooms/{rid}/bookings", body); assert r.status_code == code, r.text; return r.json()

def starts(lst): return [b["start"] for b in lst]

def test_index_html(api):
    r = api.get("/"); assert r.status_code == 200 and "text/html" in r.headers.get("content-type", "")

def test_roles(server, admin):
    assert admin.role == "admin"
    m = user(server); assert m.role == "member"
    assert m.post("/api/rooms", {"name": uniq(), "timezone": "Europe/Rome", "openTime": "08:00", "closeTime": "20:00"}).status_code == 403
    assert Api(server).get("/api/rooms").status_code == 401

@pytest.mark.parametrize("body", [
    {"timezone": "Mars/Base", "openTime": "08:00", "closeTime": "20:00"},
    {"timezone": "Europe/Rome", "openTime": "08:10", "closeTime": "20:00"},
    {"timezone": "Europe/Rome", "openTime": "20:00", "closeTime": "08:00"},
    {"timezone": "Europe/Rome", "openTime": "8am", "closeTime": "20:00"},
    {"timezone": "Europe/Rome", "openTime": "08:00", "closeTime": "25:00"},
])
def test_room_validation(admin, body):
    assert admin.post("/api/rooms", {"name": uniq(), **body}).status_code == 400

def test_room_duplicate_and_get(admin):
    r = room(admin); assert r["timezone"] == "Europe/Rome" and r["openTime"] == "08:00"
    assert admin.post("/api/rooms", {"name": r["name"].upper(), "timezone": "UTC", "openTime": "08:00", "closeTime": "09:00"}).status_code == 409
    assert admin.get(f"/api/rooms/{r['id']}").json()["name"] == r["name"]
    assert admin.get("/api/rooms/999999").status_code == 404
    ids = [x["id"] for x in admin.get("/api/rooms").json()]; assert ids == sorted(ids) and r["id"] in ids

def test_single_booking_utc_normalized(server, admin):
    r = room(admin); m = user(server)
    res = book(m, r["id"], "2027-03-22T09:00:00+01:00", "2027-03-22T10:00:00+01:00")
    assert isinstance(res, list) and len(res) == 1
    b = res[0]
    assert b["start"] == "2027-03-22T08:00:00.000Z" and b["end"] == "2027-03-22T09:00:00.000Z"
    assert b["seriesId"] is None and b["userId"] == m.id and b["roomId"] == r["id"]
    assert m.get(f"/api/bookings/{b['id']}").json()["start"] == b["start"]

def test_weekly_recurrence_across_dst(server, admin):
    r = room(admin); m = user(server)
    res = book(m, r["id"], "2027-03-22T08:00:00Z", "2027-03-22T09:00:00Z", recurrence={"freq": "weekly", "count": 3})
    assert starts(res) == ["2027-03-22T08:00:00.000Z", "2027-03-29T07:00:00.000Z", "2027-04-05T07:00:00.000Z"]
    assert [b["end"] for b in res] == ["2027-03-22T09:00:00.000Z", "2027-03-29T08:00:00.000Z", "2027-04-05T08:00:00.000Z"]
    sids = {b["seriesId"] for b in res}; assert len(sids) == 1 and None not in sids

def test_daily_recurrence_new_york(server, admin):
    r = room(admin, tz="America/New_York", open_="09:00", close="17:00"); m = user(server)
    res = book(m, r["id"], "2027-03-13T09:00:00-05:00", "2027-03-13T10:00:00-05:00", recurrence={"freq": "daily", "count": 3})
    assert starts(res) == ["2027-03-13T14:00:00.000Z", "2027-03-14T13:00:00.000Z", "2027-03-15T13:00:00.000Z"]

def test_opening_hours_local_dst_aware(server, admin):
    r = room(admin, tz="America/New_York", open_="09:00", close="17:00"); m = user(server)
    book(m, r["id"], "2027-03-15T13:00:00Z", "2027-03-15T14:00:00Z")            # 09:00 EDT ok
    book(m, r["id"], "2027-03-12T13:00:00Z", "2027-03-12T14:00:00Z", code=400)  # 08:00 EST
    book(m, r["id"], "2027-03-16T20:00:00Z", "2027-03-16T21:00:00Z")            # 16:00-17:00 EDT, ends at close: ok
    book(m, r["id"], "2027-03-17T20:30:00Z", "2027-03-17T21:15:00Z", code=400)  # ends 17:15 EDT

@pytest.mark.parametrize("start,end", [
    ("2027-04-01T09:10:00+02:00", "2027-04-01T10:00:00+02:00"),   # not aligned
    ("2027-04-01T09:00:30+02:00", "2027-04-01T10:00:00+02:00"),   # seconds
    ("2027-04-01T09:00:00+02:00", "2027-04-01T09:00:00+02:00"),   # zero length
    ("2027-04-01T10:00:00+02:00", "2027-04-01T09:00:00+02:00"),   # end before start
    ("2027-04-01T09:00:00+02:00", "2027-04-01T13:15:00+02:00"),   # > 4h
    ("2027-04-01T09:00:00", "2027-04-01T10:00:00"),               # no offset
    ("2027-04-01T07:45:00+02:00", "2027-04-01T08:30:00+02:00"),   # before open
    ("2027-04-01T19:30:00+02:00", "2027-04-01T20:15:00+02:00"),   # after close
    ("2020-04-01T09:00:00+02:00", "2020-04-01T10:00:00+02:00"),   # past
    ("tomorrow", "later"),
])
def test_booking_validation(server, admin, start, end):
    r = room(admin); book(admin, r["id"], start, end, code=400)

def test_booking_limits_ok(admin):
    r = room(admin)
    book(admin, r["id"], "2027-04-01T08:00:00+02:00", "2027-04-01T12:00:00+02:00")     # exactly 4h, at open
    book(admin, r["id"], "2027-04-01T19:45:00+02:00", "2027-04-01T20:00:00+02:00")     # 15 min, ends at close

@pytest.mark.parametrize("rec", [{"freq": "monthly", "count": 2}, {"freq": "weekly", "count": 0}, {"freq": "weekly", "count": 53}, {"freq": "daily", "count": 2.5}])
def test_recurrence_validation(admin, rec):
    r = room(admin); book(admin, r["id"], "2027-04-01T09:00:00+02:00", "2027-04-01T10:00:00+02:00", recurrence=rec, code=400)

def test_conflicts_and_touching(server, admin):
    r = room(admin); m = user(server); r2 = room(admin)
    book(m, r["id"], "2027-04-02T10:00:00+02:00", "2027-04-02T11:00:00+02:00")
    resp = m.post(f"/api/rooms/{r['id']}/bookings", {"title": "x", "start": "2027-04-02T10:30:00+02:00", "end": "2027-04-02T11:30:00+02:00"})
    assert resp.status_code == 409 and resp.json()["conflicts"] == ["2027-04-02T08:30:00.000Z"]
    book(m, r["id"], "2027-04-02T11:00:00+02:00", "2027-04-02T12:00:00+02:00")     # touching ok
    book(m, r["id"], "2027-04-02T09:00:00+02:00", "2027-04-02T10:00:00+02:00")     # touching ok
    book(m, r2["id"], "2027-04-02T10:30:00+02:00", "2027-04-02T11:30:00+02:00")    # other room ok

def test_recurrence_all_or_nothing(server, admin):
    r = room(admin); m = user(server)
    book(m, r["id"], "2027-04-13T09:30:00+02:00", "2027-04-13T10:30:00+02:00")
    book(m, r["id"], "2027-04-27T08:00:00+02:00", "2027-04-27T09:15:00+02:00")
    resp = m.post(f"/api/rooms/{r['id']}/bookings", {"title": "s", "start": "2027-04-06T09:00:00+02:00", "end": "2027-04-06T10:00:00+02:00",
                                                    "recurrence": {"freq": "weekly", "count": 4}})
    assert resp.status_code == 409
    assert resp.json()["conflicts"] == ["2027-04-13T07:00:00.000Z", "2027-04-27T07:00:00.000Z"]
    assert len(m.get(f"/api/rooms/{r['id']}/bookings").json()) == 2

def test_list_bookings_range(server, admin):
    r = room(admin); m = user(server)
    book(m, r["id"], "2027-05-03T14:00:00Z", "2027-05-03T15:00:00Z")
    book(m, r["id"], "2027-05-03T09:00:00Z", "2027-05-03T10:00:00Z")
    book(m, r["id"], "2027-05-04T09:00:00Z", "2027-05-04T10:00:00Z")
    allb = m.get(f"/api/rooms/{r['id']}/bookings").json(); assert starts(allb) == sorted(starts(allb)) and len(allb) == 3
    sel = m.get(f"/api/rooms/{r['id']}/bookings", params={"from": "2027-05-03T09:30:00Z", "to": "2027-05-03T14:00:00Z"}).json()
    assert starts(sel) == ["2027-05-03T09:00:00.000Z"]
    assert m.get(f"/api/rooms/{r['id']}/bookings", params={"from": "garbage"}).status_code == 400

def test_delete_permissions(server, admin):
    r = room(admin); a = user(server); b = user(server)
    x = book(a, r["id"], "2027-05-10T09:00:00Z", "2027-05-10T10:00:00Z")[0]
    y = book(a, r["id"], "2027-05-10T11:00:00Z", "2027-05-10T12:00:00Z")[0]
    assert b.delete(f"/api/bookings/{x['id']}").status_code == 403
    assert a.delete(f"/api/bookings/{x['id']}").status_code == 204
    assert admin.delete(f"/api/bookings/{y['id']}").status_code == 204
    assert a.get(f"/api/bookings/{x['id']}").status_code == 404
    assert a.delete(f"/api/bookings/{x['id']}").status_code == 404

def test_delete_series_scope(server, admin):
    r = room(admin); m = user(server)
    s = book(m, r["id"], "2027-06-07T09:00:00+02:00", "2027-06-07T10:00:00+02:00", recurrence={"freq": "weekly", "count": 4})
    assert m.delete(f"/api/bookings/{s[3]['id']}").status_code == 204
    assert len(m.get(f"/api/rooms/{r['id']}/bookings").json()) == 3
    assert m.delete(f"/api/bookings/{s[1]['id']}", params={"scope": "series"}).status_code == 204
    left = m.get(f"/api/rooms/{r['id']}/bookings").json(); assert [b["id"] for b in left] == [s[0]["id"]]
    s2 = book(m, r["id"], "2027-06-08T09:00:00+02:00", "2027-06-08T10:00:00+02:00", recurrence={"freq": "daily", "count": 2})
    assert s2[0]["seriesId"] != s[0]["seriesId"]

def test_me_bookings(server, admin):
    r1 = room(admin); r2 = room(admin); m = user(server)
    book(m, r2["id"], "2027-07-02T09:00:00Z", "2027-07-02T10:00:00Z"); book(m, r1["id"], "2027-07-01T09:00:00Z", "2027-07-01T10:00:00Z")
    book(admin, r1["id"], "2027-07-01T12:00:00Z", "2027-07-01T13:00:00Z")
    mine = m.get("/api/me/bookings").json(); assert starts(mine) == ["2027-07-01T09:00:00.000Z", "2027-07-02T09:00:00.000Z"]

def _slots(n_from, n_to, excl):
    out = []
    for mins in range(n_from, n_to + 1, 15):
        if mins not in excl: out.append(f"{mins // 60:02d}:{mins % 60:02d}")
    return out

def test_availability_basic(admin):
    r = room(admin)
    book(admin, r["id"], "2027-03-23T09:00:00+01:00", "2027-03-23T10:00:00+01:00")
    j = admin.get(f"/api/rooms/{r['id']}/availability", params={"date": "2027-03-23", "duration": 60}).json()
    assert j["timezone"] == "Europe/Rome" and j["date"] == "2027-03-23"
    assert j["slots"] == _slots(8 * 60, 19 * 60, {8 * 60 + 15, 8 * 60 + 30, 8 * 60 + 45, 9 * 60, 9 * 60 + 15, 9 * 60 + 30, 9 * 60 + 45})

def test_availability_on_dst_day(admin):
    r = room(admin)
    book(admin, r["id"], "2027-03-28T07:00:00Z", "2027-03-28T07:30:00Z")   # 09:00-09:30 CEST (DST starts that night)
    j = admin.get(f"/api/rooms/{r['id']}/availability", params={"date": "2027-03-28", "duration": 30}).json()
    assert j["slots"] == _slots(8 * 60, 19 * 60 + 30, {8 * 60 + 45, 9 * 60, 9 * 60 + 15})

@pytest.mark.parametrize("params", [{"date": "2027-02-30", "duration": 60}, {"date": "2027-03-01", "duration": 50},
                                    {"date": "2027-03-01", "duration": 255}, {"date": "x", "duration": 60}])
def test_availability_validation(admin, params):
    r = room(admin); assert admin.get(f"/api/rooms/{r['id']}/availability", params=params).status_code == 400

def test_delete_room(admin):
    r = room(admin); b = book(admin, r["id"], "2027-08-02T09:00:00+02:00", "2027-08-02T10:00:00+02:00")[0]
    assert admin.delete(f"/api/rooms/{r['id']}").status_code == 204
    assert admin.get(f"/api/rooms/{r['id']}").status_code == 404 and admin.get(f"/api/bookings/{b['id']}").status_code == 404

def test_persistence(server, admin):
    r = room(admin); b = book(admin, r["id"], "2027-09-06T09:00:00+02:00", "2027-09-06T10:00:00+02:00", recurrence={"freq": "daily", "count": 2})
    server.restart()
    a = Api(server); lg = a.post("/api/auth/login", {"email": admin.email, "password": PW}); a.token = lg.json()["token"]
    assert lg.json()["user"]["role"] == "admin"
    assert starts(a.get(f"/api/rooms/{r['id']}/bookings").json()) == starts(b)
    admin.token = a.token
