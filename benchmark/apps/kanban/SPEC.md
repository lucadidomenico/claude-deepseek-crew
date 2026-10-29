# App: Team Kanban

A multi-user kanban board with accounts, shared boards and cards.

## Accounts and authentication

- `POST /api/auth/register` body `{email, password}`.
  - `email`: required, must look like an email (`something@something.tld`), stored lower-cased, unique (case-insensitive) → duplicate `409`.
  - `password`: required string, at least 8 characters.
  - Invalid input → `400`. Success → `201` with `{id, email}`. **Never** return the password or its hash in any response.
  - Passwords must be stored hashed (e.g. bcrypt, scrypt, argon2, pbkdf2). The plain password must never be written to disk.
- `POST /api/auth/login` body `{email, password}` → `200` `{token, user: {id, email}}`; wrong email or password → `401`.
- All other `/api/*` endpoints require the header `Authorization: Bearer <token>`; missing/invalid token → `401`.
- `GET /api/me` → `200` `{id, email}`.
- `POST /api/auth/logout` → `204`; the token used becomes invalid afterwards (subsequent requests with it → `401`).

## Boards

Board: `id`, `name`, `ownerId`, `wipLimit` (integer ≥ 1 or `null`, default `null`), `createdAt`.

- `POST /api/boards` body `{name, wipLimit?}` → `201` board. `name` required non-empty (trimmed), max 100 chars → else `400`.
- `GET /api/boards` → `200` array of boards where the user is owner or member, sorted by `id` ascending.
- `GET /api/boards/:id` → `200` board object plus `members`: array of `{id, email}` of all users with access (owner included), sorted by `id`.
- `PATCH /api/boards/:id` body `{name?, wipLimit?}` → `200`. **Owner only.**
- `DELETE /api/boards/:id` → `204`, deletes its cards too. **Owner only.**
- `POST /api/boards/:id/members` body `{email}` → `201` with the members array (same format as above). **Owner only.** Unknown email → `404`. Already a member (or the owner) → `409`.
- `DELETE /api/boards/:id/members/:userId` → `204`. **Owner only.** The owner cannot be removed → `400`.

Access rules: a board that does not exist → `404`. A board that exists but the user is neither owner nor member → `403`. A member (not owner) calling an owner-only endpoint → `403`.

## Cards

Card: `id`, `boardId`, `title`, `description` (string, default `""`), `column` (one of `"todo"`, `"doing"`, `"done"`), `position` (integer, 0-based index within its column), `createdBy` (user id), `createdAt`, `updatedAt`.

- `POST /api/boards/:id/cards` body `{title, description?, column?}` → `201` card. `column` defaults to `"todo"`; the card is appended at the end of the column (position = current count). `title` required non-empty, max 200. Invalid column → `400`.
- `GET /api/boards/:id/cards` → `200` `{todo: [...], doing: [...], done: [...]}`, each array sorted by `position` ascending.
- `PATCH /api/cards/:id` body `{title?, description?, column?, position?}` → `200` updated card. Moving rules:
  - If `column` changes and `position` is omitted, the card goes to the end of the target column.
  - `position` is clamped to `[0, n]` where `n` is the number of other cards in the target column.
  - After any move, positions in **both** the source and target columns are contiguous `0..k-1`, preserving the relative order of the other cards.
- `DELETE /api/cards/:id` → `204`; positions in its column are compacted.
- Card endpoints follow the access rules of the card's board (non-existent card → `404`, no access → `403`). Any member can create/edit/move/delete cards.

## WIP limit

If a board has `wipLimit` set, the `doing` column may hold at most `wipLimit` cards. Creating a card in `doing` or moving a card into `doing` that would exceed the limit → `409` (the card is not changed). Reordering inside `doing` is always allowed. Lowering `wipLimit` below the current count is allowed (it only blocks new entries).

## UI

`GET /` serves a page where a user can register, log in, see their boards, open one and add/move cards between the three columns.
