# App: Sheets (spreadsheet engine)

A web spreadsheet with a formula engine. No accounts. The hard part is the engine: parsing, evaluation, dependencies, errors and structural edits — follow the rules below exactly.

## Grid

A sheet has columns `A`–`Z` and rows `1`–`1000`. A cell reference is a column letter + row number, case-insensitive on input (`a1` = `A1`); each part may be prefixed with `$` to make it absolute (`$A1`, `A$1`, `$A$1`). A reference outside the grid (e.g. `AA1`, `A0`, `A1001`) is a **`#REF!`** error when evaluated.

## Sheets API

- `POST /api/sheets` `{name}` → `201` `{id, name}`; name non-empty (trimmed) max 100 → else `400`.
- `GET /api/sheets` → `200` array of `{id, name}` sorted by id.
- `GET /api/sheets/:id` → `200` `{id, name, cells}` where `cells` is an object mapping every **non-empty** cell ref (canonical uppercase, e.g. `"B7"`) to `{input, value, type}`. Unknown sheet → `404` (for every endpoint below too).
- `DELETE /api/sheets/:id` → `204`.

## Cells API

- `PUT /api/sheets/:id/cells/:ref` `{input}` (`input` is a string, max 1000 chars; `""` clears the cell) → `200` `{ref, input, value, type}` for that cell after recalculation. Invalid ref in the URL (not A–Z / 1–1000) or non-string input → `400`.
- `GET /api/sheets/:id/cells/:ref` → `200` `{ref, input, value, type}`; an empty cell gives `{ref, input: "", value: null, type: "empty"}`.
- `POST /api/sheets/:id/cells` `{cells: {"A1": "1", "B1": "=A1+1", ...}}` → `200` `{cells: {...}}` with the resulting `{input, value, type}` of every ref listed. All inputs are applied first, then everything is recalculated (order of keys does not matter). Any invalid ref/input → `400` and nothing changes.

`type` is one of `"empty"`, `"number"`, `"string"`, `"boolean"`, `"error"`. `value` is: `null` (empty), a JSON number, a JSON string, a JSON boolean, or for errors the error code string (`"#DIV/0!"`, `"#VALUE!"`, `"#REF!"`, `"#NAME?"`, `"#NUM!"`, `"#CYCLE!"`, `"#ERROR!"`).

Values are always up to date: changing a cell immediately updates every cell that depends on it, directly or indirectly.

## Input interpretation

- `""` → empty.
- Starts with `=` → formula (the rest is parsed as an expression; a syntax error makes the value `#ERROR!`, the input is still stored).
- Matches a decimal number (`^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$`) → number.
- `TRUE` / `FALSE` (any case) → boolean.
- Starts with `'` → string without the leading apostrophe (`'123` is the string `"123"`).
- Anything else → string, as typed.

## Formula language

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

## Structural edits

- `POST /api/sheets/:id/rows/insert` `{at, count}` (integers, `1 ≤ at ≤ 1000`, `count ≥ 1`) → `200` `{ok: true}`: inserts `count` empty rows before row `at`. Cells in rows ≥ `at` move down by `count`; cells pushed beyond row 1000 are discarded. Every reference (relative **and** absolute) in every formula that points to a row ≥ `at` is shifted down by `count`; a range whose first row is < `at` and last row ≥ `at` grows. A reference shifted beyond row 1000 becomes `#REF!`.
- `POST /api/sheets/:id/rows/delete` `{at, count}` → `200` `{ok: true}`: deletes rows `at` … `at+count-1`; rows below move up. References to rows below the deleted block shift up. A single reference to a deleted cell is replaced by the text `#REF!` in the formula (which then evaluates to `#REF!`). A range is cut to its remaining rows; if all its rows are deleted the whole range is replaced by `#REF!`.
- `POST /api/sheets/:id/copy` `{from: "A1:B2", to: "D5"}` (`from` a ref or range, `to` the top-left target cell) → `200` `{ok: true}`: copies the inputs of the source block so that its top-left lands on `to` (target cells take the source's input, empty source cells clear their target; cells outside the grid are dropped). In copied formulas, the relative parts of each reference are shifted by the row/column offset, `$` parts are not; a reference shifted outside the grid is replaced by `#REF!`. The source block and target block may overlap (the copy uses the source inputs as they were before the copy).

When a structural edit rewrites a formula, each reference in it is written in canonical form (uppercase, `$` markers preserved, ranges as `A1:B2`); **all other text of the formula is kept exactly as typed** (spacing, function name case, literals).

Invalid bodies → `400`.

## Export

`GET /api/sheets/:id/export.csv` → `200`, `Content-Type: text/csv`: the **values** of the rectangle from `A1` to the last non-empty row and column (no lines if the sheet is empty). Numbers in `String(n)` form, booleans `TRUE`/`FALSE`, errors as their code, empties as empty fields, RFC 4180 quoting.

## UI

`GET /` serves a page showing a grid (at least A–J × 1–30) where the user can type inputs into cells and see values, with the selected cell's raw input in a formula bar.
