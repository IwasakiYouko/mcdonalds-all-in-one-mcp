# Preferences, records and shareable results

## Remember preferences when requested

Read preferences with `profile show`. Persist only what the user asks to remember. Preferences may contain city, store_preference, budget_cents, meal_mode, likes, dislikes, drink_preference, track_nutrition, max_kcal, max_sodium_mg, min_protein_g and language. They are not a place for credentials, phone numbers or delivery addresses.

```bash
python3 scripts/mcd.py profile set --json '{"budget_cents":3000,"likes":["fish"],"drink_preference":"no-sugar cola"}'
python3 scripts/mcd.py profile unset --keys drink_preference
python3 scripts/mcd.py profile clear
```

“Just this time” belongs in the current request, not the saved profile. Today's stated requirements override saved preferences. Store preferences are hints; actual availability and context still come from MCP. With permission to inspect recorded orders, put recent component names into request.recent_items for variety and the avoid-recent random chooser.

## Record actual spending

After the user asks to sync history, call order-list and save the response privately. Import the observed server shape with:

```bash
python3 scripts/mcd.py ledger import-mcp --file /private/path/order-list-response.json
python3 scripts/mcd.py ledger report --output /private/path/spending.json
python3 scripts/mcd.py export /private/path/spending.json --output /private/path/spending.html --title 'Your recorded McDonald’s spending'
```

The importer maps recognized actual statuses, converts realTotalAmount from yuan to integer cents once, expands combo children and upserts by order ID. An unfamiliar status is skipped with an explanation; inspect the response before adding a mapping. order-list is a recent snapshot and may omit older orders. Do not infer a full calendar month/year from it.

For a newly placed order, query its actual payment status before recording consumption. For user-provided manual records, `ledger add --file /private/path/order.json` accepts id, ordered_at (ISO timestamp), status, paid_cents, source and items. Source is official-mcp only for data actually obtained from MCP; manual records use manual and fixtures use demo. Items have name and quantity. Do not store unnecessary contacts, addresses or raw account identifiers in the ledger.

Paid/completed/partially-refunded orders are spending. Pending, cancelled and fully-refunded orders are excluded. Zero-paid orders count as visits but do not lower the positive-spend average. If a partial refund's net amount is unknown, disclose that totals may be overstated. `ledger report --start ISO --end ISO` filters recorded data; `ledger clear` deletes the ledger. Reports show actual coverage dates, source labels and warnings. No health diagnosis is derived from spending or food trends.

## Expiry and realistic usage suggestions

`expiry /private/path/coupons-response.json --from-coupons` reads the observed structured query-my-coupons fields. It does not assume an unfamiliar weekday encoding. For a complete inventory follow the API's actual pages; one page is not automatically every coupon. Missing validity stays unknown. Display unresolved restrictions and recheck store eligibility when planning an order.

For scheduling across known meal opportunities, normalize assets explicitly and provide the user's planned times:

```json
{
  "assets": [{
    "name": "Example breakfast coupon",
    "kind": "coupon",
    "starts_at": "2026-10-24T00:00:00+08:00",
    "expires_at": "2026-10-30T23:59:59+08:00",
    "weekdays": [1,2,3,4,5],
    "windows": [["05:00","10:29"]],
    "quantity": 1,
    "channel": "pickup",
    "rules_known": true,
    "store_eligibility": "not checked"
  }],
  "planned_meals": [{"at":"2026-10-26T09:00:00+08:00","channel":"pickup"}]
}
```

This example is synthetic; real hours/rules come from the user's coupons. Normalized weekdays are ISO Monday=1…Sunday=7. Use rules_known=true only when all relevant time restrictions have been resolved. Asset kinds can also be points or prize, with amount and known expires_at; don't invent an exact expiry timestamp from “this month” if the service does not provide it. The helper never schedules points/prizes as coupons. Unknown-expiry and unknown-rule coupons are not scheduled. The default is one coupon per supplied visit, earliest known expiry first; it does not create visits, guarantee stacking, or create a background reminder.

## Reports, cards, invitations and reference splits

`export` supports HTML, CSV and JSON from meal comparisons or spending summaries. HTML is standalone, responsive, printable and has no scripts, CDN or network requests. Use its meal cards as a shareable comparison; the recipient can open the HTML or print to PDF. This release produces HTML cards, not PNG images or voice recordings. Keep quoted_at and source labels so old prices are not mistaken for current prices.

Public report fields are whitelisted: contact details, account IDs, order IDs, coupon codes and raw API responses are omitted. Meal names/dates/spending may still be personal; ask before publishing or sending an actual user's report. CSV text cells are neutralized against spreadsheet formulas.

```bash
python3 scripts/mcd.py split --total-cents 10000 --people 3
python3 scripts/mcd.py split --total-cents 10000 --people 3 --weights 2 1 1
python3 scripts/mcd.py invite /private/path/event.json
```

An invitation needs title, store_name, date, time, people and optionally per_person_cents and note. Keep participant meal requirements in the group summary. Reference splits preserve the exact total using largest remainders. Invitations are drafts for the user to copy; do not send messages or imply a booking/payment has happened.
