# App: Room Booking

A web app to book meeting rooms, with opening hours in the room's own time zone, recurring bookings and availability search.

## Accounts and roles

- `POST /api/auth/register` `{email, password, name}`: email valid (`x@y.tld`), stored lower-cased, unique → `409`; password ≥ 8 chars; name non-empty (trimmed) max 50 → else `400`. Success `201` `{id, email, name, role}`.
  The **first** registered user gets `role: "admin"`, everyone else `role: "member"`. Store passwords hashed; never return them.
- `POST /api/auth/login` `{email, password}` → `200` `{token, user: {id, email, name, role}}`; bad credentials `401`.
- All other `/api/*` endpoints require `Authorization: Bearer <token>`, else `401`.

## Rooms (admin only for writes)

Room: `{id, name, timezone, openTime, closeTime, createdAt}`.
- `timezone`: an IANA time zone name (e.g. `"Europe/Rome"`, `"America/New_York"`); invalid → `400`.
- `openTime`/`closeTime`: `"HH:MM"` 24h local times, minutes multiple of 15, `openTime < closeTime` (same day) → else `400`.
- `POST /api/rooms` `{name, timezone, openTime, closeTime}` → `201`. Name non-empty, max 100, unique (case-insensitive) → `409`. Non-admin → `403`.
- `GET /api/rooms` → `200` all rooms sorted by `id`. `GET /api/rooms/:id` → room or `404`.
- `DELETE /api/rooms/:id` → `204` (admin only, `403` otherwise), also deletes its bookings.

## Bookings

Booking: `{id, roomId, userId, title, start, end, seriesId}` where `start`/`end` are UTC ISO strings with milliseconds (`2027-03-22T08:00:00.000Z`) and `seriesId` is `null` for single bookings, or the same integer for all occurrences of one recurring booking (series ids are assigned from 1 upwards).

`POST /api/rooms/:id/bookings` body `{title, start, end, recurrence?}`:
- `start`/`end`: ISO 8601 date-times **with** a `Z` or `±HH:MM` offset (e.g. `2027-03-22T09:00:00+01:00`); anything else → `400`.
- Rules (each violation → `400`):
  - `title` non-empty, max 100.
  - `end > start`; duration between 15 minutes and 4 hours inclusive.
  - `start` and `end` are on 15-minute boundaries (`:00`, `:15`, `:30`, `:45`, zero seconds).
  - In the **room's time zone**, start and end fall on the **same local calendar day**, and `openTime ≤ local start` and `local end ≤ closeTime`.
  - `start` must be in the future (after the current server time).
- `recurrence` (optional): `{freq: "daily" | "weekly", count: n}` with integer `1 ≤ n ≤ 52`; otherwise `400`. It creates `n` occurrences: the first one is the given booking, each following one is 1 day (daily) or 7 days (weekly) later **in local wall-clock time of the room** (a 09:00–10:00 booking stays 09:00–10:00 local across daylight-saving changes, so its UTC time shifts). Every occurrence must satisfy the rules above, else `400`.
- Conflicts: two bookings in the same room conflict if their time ranges overlap (`a.start < b.end && b.start < a.end`; touching is fine). If any occurrence conflicts with an existing booking → `409` with body `{error, conflicts: [<UTC ISO start of each conflicting new occurrence>, ...]}` in chronological order, and **nothing** is created (all-or-nothing).
- Success → `201` with an array of the created bookings (chronological), even for a single booking.

Other endpoints:
- `GET /api/rooms/:id/bookings?from=<ISO>&to=<ISO>` → `200` bookings of the room overlapping `[from, to)` sorted by `start`; `from`/`to` optional (default: all). Invalid → `400`.
- `GET /api/bookings/:id` → `200` booking or `404`.
- `DELETE /api/bookings/:id` → `204`. Only the booking's owner or an admin, else `403`. Query `?scope=series` deletes this occurrence **and all later occurrences** of the same series (earlier ones are kept); default `scope=single` deletes only this one. `scope=series` on a non-recurring booking behaves like single.
- `GET /api/me/bookings` → `200` all bookings of the current user, any room, sorted by `start`.

## Availability

`GET /api/rooms/:id/availability?date=YYYY-MM-DD&duration=<minutes>` → `200`
`{date, timezone, slots: ["HH:MM", ...]}` listing every local start time on that local date, in 15-minute steps from `openTime`, such that a booking of `duration` minutes starting there ends at or before `closeTime`, does not conflict with any existing booking, and starts in the future. `duration` must be a multiple of 15 between 15 and 240, `date` a valid calendar date → else `400`.

## UI

`GET /` serves a page where a user can log in, see rooms, see a room's bookings for a day, check availability and create a booking.
