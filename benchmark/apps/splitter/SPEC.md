# App: Splitter (shared expenses)

A web app for groups of friends to track shared expenses and settle debts. All amounts are **integer cents**.

## Accounts and authentication

Exactly as follows:
- `POST /api/auth/register` body `{email, password, name}`: email valid (`x@y.tld`), stored lower-cased, unique → `409`; password ≥ 8 chars; `name` non-empty (trimmed) max 50 → else `400`. Success `201` `{id, email, name}`. Never return passwords or hashes. Store passwords hashed.
- `POST /api/auth/login` `{email, password}` → `200` `{token, user: {id, email, name}}`; bad credentials `401`.
- All other `/api/*` endpoints require `Authorization: Bearer <token>`, else `401`.

## Groups

Group: `id`, `name`, `createdBy`, `createdAt`, `members` (array of `{id, email, name}` sorted by `id`).

- `POST /api/groups` `{name}` → `201` group; the creator is a member. Name required non-empty max 100 → `400`.
- `GET /api/groups` → `200` groups the user belongs to, sorted by `id`.
- `GET /api/groups/:id` → `200` group.
- `POST /api/groups/:id/members` `{email}` → `201` group. Any member can add. Unknown email → `404`; already a member → `409`.
- Non-existent group → `404`; existing group the user is not a member of → `403` (for all group endpoints, including expenses/payments/balances/export).

## Expenses

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

## Payments (settling up)

`POST /api/groups/:id/payments` `{fromUserId, toUserId, amountCents}` → `201` `{id, groupId, fromUserId, toUserId, amountCents, createdAt}`. Both users must be members, different from each other, amount integer ≥ 1 → else `400`. A payment means `from` gave money to `to`.

`GET /api/groups/:id/payments` → `200` array sorted by `id`.

## Balances

`GET /api/groups/:id/balances` → `200` array `[{userId, name, balanceCents}]` with **one entry per member** sorted by `userId`.
`balanceCents` = (total paid for expenses) − (total of own shares) + (payments sent) − (payments received). Positive means the group owes this person money. Balances always sum to 0.

## Suggested settlements

`GET /api/groups/:id/settlements` → `200` array of `{fromUserId, toUserId, amountCents}` that would bring every balance to 0, computed **exactly** with this greedy algorithm:
1. Debtors = members with negative balance, creditors = members with positive balance.
2. Repeat while any debtor remains: take the debtor with the largest debt (most negative balance) and the creditor with the largest credit; ties are broken by lowest `userId`. Transfer `min(debt, credit)` from the debtor to the creditor, update both, drop whoever reaches 0.
The array lists the transfers in the order they were generated.

## Export

`GET /api/groups/:id/export.csv` → `200`, `Content-Type: text/csv`. Header `date,description,paidBy,amountCents` then one row per expense sorted by `date` ascending, then `id` ascending. `paidBy` is the payer's **name**. CSV quoting per RFC 4180 (wrap fields containing comma, quote or newline in double quotes, double inner quotes).

## UI

`GET /` serves a page where a user can register, log in, create a group, add members, add an equal-split expense and see balances and suggested settlements.
