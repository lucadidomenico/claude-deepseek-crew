# App: Office Suite (5 modules in one server)

One Node.js server hosting five independent modules. Each module is specified below exactly as if it were a standalone app,
but it is **mounted under its own path prefix**:

| module | prefix |
|---|---|
| Bookmarks | `/bookmarks` |
| Team Kanban | `/kanban` |
| Splitter | `/splitter` |
| Room Booking | `/booking` |
| Sheets | `/sheets` |

Mounting rule: every path of a module's spec is served under its prefix. For example the Bookmarks endpoint
`POST /api/bookmarks` is `POST /bookmarks/api/bookmarks`, and the Kanban UI `GET /` is `GET /kanban/`.
`GET /` (root) serves a small HTML home page linking to the five module UIs.

Modules are **independent**: separate users/accounts, separate tokens, separate data and ID sequences (e.g. the first
Kanban user and the first Splitter user both get id 1; the first registered *Room Booking* user is that module's admin).
A token issued by one module is not valid in another. All data lives under `DATA_DIR` and survives restarts.
Unknown routes (inside or outside a prefix) → 404.

The technical contract at the end of this document applies to the whole server.


---

(All paths in this module are relative to the prefix `/bookmarks`.)

## Module `/bookmarks` — Bookmarks

A small web app to save and organize bookmarks with tags.

### Data model

Bookmark: `id` (int), `url` (string), `title` (string), `tags` (array of strings), `createdAt` (ISO string), `updatedAt` (ISO string).

Tag normalization: tags are trimmed and lower-cased; empty tags are dropped; duplicates are removed; the stored array is sorted alphabetically.

### Validation

- `url` is required, must be a string starting with `http://` or `https://`, max 2000 chars.
- `title` is required, a non-empty string after trimming (store trimmed), max 200 chars.
- `tags` is optional (default `[]`); if present it must be an array of strings, each at most 30 chars after trimming, at most 10 tags after normalization.
- Invalid input → `400`.
- URLs are unique: creating (or updating to) a URL that another bookmark already has → `409`.

### API

- `POST /api/bookmarks` body `{url, title, tags?}` → `201` with the created bookmark.
- `GET /api/bookmarks` → `200` with an array of bookmarks sorted by `createdAt` descending (newest first; ties by `id` descending).
  Optional query parameters, combinable:
  - `tag=<tag>`: only bookmarks having that tag (match is case-insensitive).
  - `q=<text>`: only bookmarks whose title or url contains the text (case-insensitive).
  - `limit=<n>` (default 50, max 100) and `offset=<n>` (default 0) for pagination. Invalid values (non-integer, negative, limit 0 or > 100) → `400`.
  - The response also includes the header `X-Total-Count` with the number of matching bookmarks before pagination.
- `GET /api/bookmarks/:id` → `200` bookmark, or `404`.
- `PATCH /api/bookmarks/:id` body with any subset of `{url, title, tags}` → `200` updated bookmark (same validation; `updatedAt` changes). Unknown id → `404`.
- `DELETE /api/bookmarks/:id` → `204`, or `404`.
- `GET /api/tags` → `200` array of `{tag, count}` for every tag in use, sorted by `count` descending then `tag` ascending.
- `GET /api/export` → `200`, `Content-Type: text/csv`, a CSV file with header line `id,url,title,tags,createdAt` and one line per bookmark ordered by `id` ascending; `tags` joined with `|`; fields containing a comma, double quote or newline are wrapped in double quotes with inner quotes doubled (RFC 4180).

### UI

`GET /` serves a page that lists bookmarks, lets the user add one (url, title, comma-separated tags), filter by tag and search, and delete bookmarks.


---

(All paths in this module are relative to the prefix `/kanban`.)

## Module `/kanban` — Team Kanban

A multi-user kanban board with accounts, shared boards and cards.

### Accounts and authentication

- `POST /api/auth/register` body `{email, password}`.
  - `email`: required, must look like an email (`something@something.tld`), stored lower-cased, unique (case-insensitive) → duplicate `409`.
  - `password`: required string, at least 8 characters.
  - Invalid input → `400`. Success → `201` with `{id, email}`. **Never** return the password or its hash in any response.
  - Passwords must be stored hashed (e.g. bcrypt, scrypt, argon2, pbkdf2). The plain password must never be written to disk.
- `POST /api/auth/login` body `{email, password}` → `200` `{token, user: {id, email}}`; wrong email or password → `401`.
- All other `/api/*` endpoints require the header `Authorization: Bearer <token>`; missing/invalid token → `401`.
- `GET /api/me` → `200` `{id, email}`.
- `POST /api/auth/logout` → `204`; the token used becomes invalid afterwards (subsequent requests with it → `401`).

### Boards

Board: `id`, `name`, `ownerId`, `wipLimit` (integer ≥ 1 or `null`, default `null`), `createdAt`.

- `POST /api/boards` body `{name, wipLimit?}` → `201` board. `name` required non-empty (trimmed), max 100 chars → else `400`.
- `GET /api/boards` → `200` array of boards where the user is owner or member, sorted by `id` ascending.
- `GET /api/boards/:id` → `200` board object plus `members`: array of `{id, email}` of all users with access (owner included), sorted by `id`.
- `PATCH /api/boards/:id` body `{name?, wipLimit?}` → `200`. **Owner only.**
- `DELETE /api/boards/:id` → `204`, deletes its cards too. **Owner only.**
- `POST /api/boards/:id/members` body `{email}` → `201` with the members array (same format as above). **Owner only.** Unknown email → `404`. Already a member (or the owner) → `409`.
- `DELETE /api/boards/:id/members/:userId` → `204`. **Owner only.** The owner cannot be removed → `400`.

Access rules: a board that does not exist → `404`. A board that exists but the user is neither owner nor member → `403`. A member (not owner) calling an owner-only endpoint → `403`.

### Cards

Card: `id`, `boardId`, `title`, `description` (string, default `""`), `column` (one of `"todo"`, `"doing"`, `"done"`), `position` (integer, 0-based index within its column), `createdBy` (user id), `createdAt`, `updatedAt`.

- `POST /api/boards/:id/cards` body `{title, description?, column?}` → `201` card. `column` defaults to `"todo"`; the card is appended at the end of the column (position = current count). `title` required non-empty, max 200. Invalid column → `400`.
- `GET /api/boards/:id/cards` → `200` `{todo: [...], doing: [...], done: [...]}`, each array sorted by `position` ascending.
- `PATCH /api/cards/:id` body `{title?, description?, column?, position?}` → `200` updated card. Moving rules:
  - If `column` changes and `position` is omitted, the card goes to the end of the target column.
  - `position` is clamped to `[0, n]` where `n` is the number of other cards in the target column.
  - After any move, positions in **both** the source and target columns are contiguous `0..k-1`, preserving the relative order of the other cards.
- `DELETE /api/cards/:id` → `204`; positions in its column are compacted.
- Card endpoints follow the access rules of the card's board (non-existent card → `404`, no access → `403`). Any member can create/edit/move/delete cards.

### WIP limit

If a board has `wipLimit` set, the `doing` column may hold at most `wipLimit` cards. Creating a card in `doing` or moving a card into `doing` that would exceed the limit → `409` (the card is not changed). Reordering inside `doing` is always allowed. Lowering `wipLimit` below the current count is allowed (it only blocks new entries).

### UI

`GET /` serves a page where a user can register, log in, see their boards, open one and add/move cards between the three columns.


---

(All paths in this module are relative to the prefix `/splitter`.)

## Module `/splitter` — Splitter

A web app for groups of friends to track shared expenses and settle debts. All amounts are **integer cents**.

### Accounts and authentication

Exactly as follows:
- `POST /api/auth/register` body `{email, password, name}`: email valid (`x@y.tld`), stored lower-cased, unique → `409`; password ≥ 8 chars; `name` non-empty (trimmed) max 50 → else `400`. Success `201` `{id, email, name}`. Never return passwords or hashes. Store passwords hashed.
- `POST /api/auth/login` `{email, password}` → `200` `{token, user: {id, email, name}}`; bad credentials `401`.
- All other `/api/*` endpoints require `Authorization: Bearer <token>`, else `401`.

### Groups

Group: `id`, `name`, `createdBy`, `createdAt`, `members` (array of `{id, email, name}` sorted by `id`).

- `POST /api/groups` `{name}` → `201` group; the creator is a member. Name required non-empty max 100 → `400`.
- `GET /api/groups` → `200` groups the user belongs to, sorted by `id`.
- `GET /api/groups/:id` → `200` group.
- `POST /api/groups/:id/members` `{email}` → `201` group. Any member can add. Unknown email → `404`; already a member → `409`.
- Non-existent group → `404`; existing group the user is not a member of → `403` (for all group endpoints, including expenses/payments/balances/export).

### Expenses

`POST /api/groups/:id/expenses` body:

```json
{
  "description": "Dinner",
  "amountCents": 10000,
  "paidBy": 3,
  "date": "2026-10-01",
  "split": { "type": "equal" | "exact" | "percent" | "shares",
             "participants": [ { "userId": 3, "value": 50 }, ... ] }
}
```

Validation (`400` on failure): description non-empty max 200; `amountCents` integer ≥ 1; `paidBy` is a group member; `date` is `YYYY-MM-DD` (a real calendar date); `participants` non-empty, every `userId` is a group member, no duplicate userIds; `value` required (number) for `exact`, `percent`, `shares` and ignored for `equal`.

Computing each participant's **share** (integer cents, the shares always sum exactly to `amountCents`):
- `equal`: `floor(amount / n)` each; the remaining `amount mod n` cents are given one each to the participants **in the order listed**.
- `exact`: `value` is the participant's share in cents (integer ≥ 0); the values must sum to `amountCents`, else `400`.
- `percent`: values are numbers ≥ 0 that must sum to 100 (tolerance 0.001), else `400`. 
- `shares`: values are integers ≥ 0 (weights) with total > 0, else `400`.
- For `percent` and `shares` use the **largest remainder method**: each raw share is `amount × weight / totalWeight` (for percent, totalWeight = 100); everyone gets `floor(raw)`; the cents still missing are handed out one each to the participants with the largest fractional part of `raw`; ties are broken by order listed.

Response `201`: the expense `{id, groupId, description, amountCents, paidBy, date, createdBy, createdAt, split: {type, participants: [...as sent]}, shares: [{userId, amountCents}, ...]}` (shares in the order the participants were listed).

- `GET /api/groups/:id/expenses` → `200` array sorted by `date` descending, then `id` descending.
- `DELETE /api/groups/:id/expenses/:expenseId` → `204` (any member); unknown expense in that group → `404`.

### Payments (settling up)

`POST /api/groups/:id/payments` `{fromUserId, toUserId, amountCents}` → `201` `{id, groupId, fromUserId, toUserId, amountCents, createdAt}`. Both users must be members, different from each other, amount integer ≥ 1 → else `400`. A payment means `from` gave money to `to`.

`GET /api/groups/:id/payments` → `200` array sorted by `id`.

### Balances

`GET /api/groups/:id/balances` → `200` array `[{userId, name, balanceCents}]` with **one entry per member** sorted by `userId`.
`balanceCents` = (total paid for expenses) − (total of own shares) + (payments sent) − (payments received). Positive means the group owes this person money. Balances always sum to 0.

### Suggested settlements

`GET /api/groups/:id/settlements` → `200` array of `{fromUserId, toUserId, amountCents}` that would bring every balance to 0, computed **exactly** with this greedy algorithm:
1. Debtors = members with negative balance, creditors = members with positive balance.
2. Repeat while any debtor remains: take the debtor with the largest debt (most negative balance) and the creditor with the largest credit; ties are broken by lowest `userId`. Transfer `min(debt, credit)` from the debtor to the creditor, update both, drop whoever reaches 0.
The array lists the transfers in the order they were generated.

### Export

`GET /api/groups/:id/export.csv` → `200`, `Content-Type: text/csv`. Header `date,description,paidBy,amountCents` then one row per expense sorted by `date` ascending, then `id` ascending. `paidBy` is the payer's **name**. CSV quoting per RFC 4180 (wrap fields containing comma, quote or newline in double quotes, double inner quotes).

### UI

`GET /` serves a page where a user can register, log in, create a group, add members, add an equal-split expense and see balances and suggested settlements.


---

(All paths in this module are relative to the prefix `/booking`.)

## Module `/booking` — Room Booking

A web app to book meeting rooms, with opening hours in the room's own time zone, recurring bookings and availability search.

### Accounts and roles

- `POST /api/auth/register` `{email, password, name}`: email valid (`x@y.tld`), stored lower-cased, unique → `409`; password ≥ 8 chars; name non-empty (trimmed) max 50 → else `400`. Success `201` `{id, email, name, role}`.
  The **first** registered user gets `role: "admin"`, everyone else `role: "member"`. Store passwords hashed; never return them.
- `POST /api/auth/login` `{email, password}` → `200` `{token, user: {id, email, name, role}}`; bad credentials `401`.
- All other `/api/*` endpoints require `Authorization: Bearer <token>`, else `401`.

### Rooms (admin only for writes)

Room: `{id, name, timezone, openTime, closeTime, createdAt}`.
- `timezone`: an IANA time zone name (e.g. `"Europe/Rome"`, `"America/New_York"`); invalid → `400`.
- `openTime`/`closeTime`: `"HH:MM"` 24h local times, minutes multiple of 15, `openTime < closeTime` (same day) → else `400`.
- `POST /api/rooms` `{name, timezone, openTime, closeTime}` → `201`. Name non-empty, max 100, unique (case-insensitive) → `409`. Non-admin → `403`.
- `GET /api/rooms` → `200` all rooms sorted by `id`. `GET /api/rooms/:id` → room or `404`.
- `DELETE /api/rooms/:id` → `204` (admin only, `403` otherwise), also deletes its bookings.

### Bookings

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

### Availability

`GET /api/rooms/:id/availability?date=YYYY-MM-DD&duration=<minutes>` → `200`
`{date, timezone, slots: ["HH:MM", ...]}` listing every local start time on that local date, in 15-minute steps from `openTime`, such that a booking of `duration` minutes starting there ends at or before `closeTime`, does not conflict with any existing booking, and starts in the future. `duration` must be a multiple of 15 between 15 and 240, `date` a valid calendar date → else `400`.

### UI

`GET /` serves a page where a user can log in, see rooms, see a room's bookings for a day, check availability and create a booking.


---

(All paths in this module are relative to the prefix `/sheets`.)

## Module `/sheets` — Sheets

A web spreadsheet with a formula engine. No accounts. The hard part is the engine: parsing, evaluation, dependencies, errors and structural edits — follow the rules below exactly.

### Grid

A sheet has columns `A`–`Z` and rows `1`–`1000`. A cell reference is a column letter + row number, case-insensitive on input (`a1` = `A1`); each part may be prefixed with `$` to make it absolute (`$A1`, `A$1`, `$A$1`). A reference outside the grid (e.g. `AA1`, `A0`, `A1001`) is a **`#REF!`** error when evaluated.

### Sheets API

- `POST /api/sheets` `{name}` → `201` `{id, name}`; name non-empty (trimmed) max 100 → else `400`.
- `GET /api/sheets` → `200` array of `{id, name}` sorted by id.
- `GET /api/sheets/:id` → `200` `{id, name, cells}` where `cells` is an object mapping every **non-empty** cell ref (canonical uppercase, e.g. `"B7"`) to `{input, value, type}`. Unknown sheet → `404` (for every endpoint below too).
- `DELETE /api/sheets/:id` → `204`.

### Cells API

- `PUT /api/sheets/:id/cells/:ref` `{input}` (`input` is a string, max 1000 chars; `""` clears the cell) → `200` `{ref, input, value, type}` for that cell after recalculation. Invalid ref in the URL (not A–Z / 1–1000) or non-string input → `400`.
- `GET /api/sheets/:id/cells/:ref` → `200` `{ref, input, value, type}`; an empty cell gives `{ref, input: "", value: null, type: "empty"}`.
- `POST /api/sheets/:id/cells` `{cells: {"A1": "1", "B1": "=A1+1", ...}}` → `200` `{cells: {...}}` with the resulting `{input, value, type}` of every ref listed. All inputs are applied first, then everything is recalculated (order of keys does not matter). Any invalid ref/input → `400` and nothing changes.

`type` is one of `"empty"`, `"number"`, `"string"`, `"boolean"`, `"error"`. `value` is: `null` (empty), a JSON number, a JSON string, a JSON boolean, or for errors the error code string (`"#DIV/0!"`, `"#VALUE!"`, `"#REF!"`, `"#NAME?"`, `"#NUM!"`, `"#CYCLE!"`, `"#ERROR!"`).

Values are always up to date: changing a cell immediately updates every cell that depends on it, directly or indirectly.

### Input interpretation

- `""` → empty.
- Starts with `=` → formula (the rest is parsed as an expression; a syntax error makes the value `#ERROR!`, the input is still stored).
- Matches a decimal number (`^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$`) → number.
- `TRUE` / `FALSE` (any case) → boolean.
- Starts with `'` → string without the leading apostrophe (`'123` is the string `"123"`).
- Anything else → string, as typed.

### Formula language

Literals: numbers (same decimal syntax, without sign), strings in double quotes (`"a""b"` is `a"b`), `TRUE`, `FALSE` (any case). References and ranges (`A1:B3`, any two corners, normalised to top-left:bottom-right). Function calls `NAME(arg, ...)` (names case-insensitive). Parentheses. Whitespace is allowed between tokens.

Operators, from **lowest** to **highest** precedence (all binary operators are left-associative):
1. comparison `=`, `<>`, `<`, `>`, `<=`, `>=` → boolean
2. concatenation `&` → string
3. `+`, `-`
4. `*`, `/`
5. `^` (power)
6. unary `-` and `+` (so `-2^2` = `4`, and `2^-1` = `0.5`)

A range is only allowed as a function argument; anywhere else it is a `#VALUE!` error.

### Coercion
- Arithmetic (`+ - * / ^`, unary): number as is; boolean → 1/0; empty cell → 0; **any string → `#VALUE!`**.
- Concatenation `&`: number → JavaScript `String(n)` form (e.g. `3`, `0.5`, `1e+21`); boolean → `TRUE`/`FALSE`; empty → `""`.
- Comparison: an empty cell takes the "zero" value of the other side's type (`0`, `""`, `FALSE`; empty vs empty are equal). Two numbers compare numerically, two booleans with FALSE < TRUE, two strings **case-insensitively**. Different types → `#VALUE!`.
- Boolean conditions (IF): boolean as is; number → `≠ 0`; empty → FALSE; string → `#VALUE!`.

### Errors
- Division by zero → `#DIV/0!`. A numeric result that is not finite (e.g. `10^400`) → `#NUM!`. Unknown function or wrong number of arguments → `#NAME?`.
- Errors propagate: if an operand or a function argument evaluates to an error, the result is that error (the first one met, evaluating left to right). Exception: `IF` evaluates only the branch it selects.
- Circular references: every cell that is part of a cycle has value `#CYCLE!`; cells that depend on a cycle get `#CYCLE!` by normal propagation. Breaking the cycle restores normal values.
- A formula referring to a cell whose value is an error gets that error.

### Functions
For `SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT`: each argument is a range or an expression. Inside a range, only number cells count (empty, string and boolean cells are skipped, error cells propagate their error). A direct expression argument is coerced with the arithmetic rules (string → `#VALUE!`), except for `COUNT`, which counts direct arguments that evaluate to numbers and never errors on strings.
- `SUM(...)`; `AVERAGE(...)` (no numbers → `#DIV/0!`); `MIN(...)`, `MAX(...)` (no numbers → `0`); `COUNT(...)`.
- `IF(cond, a)` / `IF(cond, a, b)`: missing `b` → `FALSE`.
- `ROUND(x, digits)`: round half away from zero to `digits` decimals (digits may be negative: `ROUND(1234, -2)` = `1200`).
- `ABS(x)`.
- `CONCAT(...)`: joins all arguments with the `&` rules; ranges are read row by row, left to right, empties as `""`.
- `LEN(x)`: length of the `&`-string form of x.

### Structural edits

- `POST /api/sheets/:id/rows/insert` `{at, count}` (integers, `1 ≤ at ≤ 1000`, `count ≥ 1`) → `200` `{ok: true}`: inserts `count` empty rows before row `at`. Cells in rows ≥ `at` move down by `count`; cells pushed beyond row 1000 are discarded. Every reference (relative **and** absolute) in every formula that points to a row ≥ `at` is shifted down by `count`; a range whose first row is < `at` and last row ≥ `at` grows. A reference shifted beyond row 1000 becomes `#REF!`.
- `POST /api/sheets/:id/rows/delete` `{at, count}` → `200` `{ok: true}`: deletes rows `at` … `at+count-1`; rows below move up. References to rows below the deleted block shift up. A single reference to a deleted cell is replaced by the text `#REF!` in the formula (which then evaluates to `#REF!`). A range is cut to its remaining rows; if all its rows are deleted the whole range is replaced by `#REF!`.
- `POST /api/sheets/:id/copy` `{from: "A1:B2", to: "D5"}` (`from` a ref or range, `to` the top-left target cell) → `200` `{ok: true}`: copies the inputs of the source block so that its top-left lands on `to` (target cells take the source's input, empty source cells clear their target; cells outside the grid are dropped). In copied formulas, the relative parts of each reference are shifted by the row/column offset, `$` parts are not; a reference shifted outside the grid is replaced by `#REF!`. The source block and target block may overlap (the copy uses the source inputs as they were before the copy).

When a structural edit rewrites a formula, each reference in it is written in canonical form (uppercase, `$` markers preserved, ranges as `A1:B2`); **all other text of the formula is kept exactly as typed** (spacing, function name case, literals).

Invalid bodies → `400`.

### Export

`GET /api/sheets/:id/export.csv` → `200`, `Content-Type: text/csv`: the **values** of the rectangle from `A1` to the last non-empty row and column (no lines if the sheet is empty). Numbers in `String(n)` form, booleans `TRUE`/`FALSE`, errors as their code, empties as empty fields, RFC 4180 quoting.

### UI

`GET /` serves a page showing a grid (at least A–J × 1–30) where the user can type inputs into cells and see values, with the selected cell's raw input in a formula bar.
