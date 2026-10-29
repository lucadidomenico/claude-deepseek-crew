# App: Bookmarks

A small web app to save and organize bookmarks with tags.

## Data model

Bookmark: `id` (int), `url` (string), `title` (string), `tags` (array of strings), `createdAt` (ISO string), `updatedAt` (ISO string).

Tag normalization: tags are trimmed and lower-cased; empty tags are dropped; duplicates are removed; the stored array is sorted alphabetically.

## Validation

- `url` is required, must be a string starting with `http://` or `https://`, max 2000 chars.
- `title` is required, a non-empty string after trimming (store trimmed), max 200 chars.
- `tags` is optional (default `[]`); if present it must be an array of strings, each at most 30 chars after trimming, at most 10 tags after normalization.
- Invalid input → `400`.
- URLs are unique: creating (or updating to) a URL that another bookmark already has → `409`.

## API

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

## UI

`GET /` serves a page that lists bookmarks, lets the user add one (url, title, comma-separated tags), filter by tag and search, and delete bookmarks.
