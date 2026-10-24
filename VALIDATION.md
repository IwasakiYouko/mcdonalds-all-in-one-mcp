# Validation record

Date: 2026-10-24. Environment: Linux, Python 3.14. Local checks also run in GitHub Actions on Python 3.9 and 3.13.

## Automated local verification

- 44 behavioral tests passed with `python3 -m unittest discover -s tests -v`.
- Skill Creator quick_validate: passed.
- A no-Token synthetic demo generated examples/demo-report.html.
- Live-schema nested arrays, enum/type validation, monetary conversions, required meal components, nutrient unknowns, preferences, quantity expansion, coupon windows/channels, CSV/HTML export protection and positive-spend accounting are covered.
- FakeClient tests cover exact confirmation, changed/expired drafts, one-attempt execution after timeouts, food price changes, lottery consumption changes, mall cost changes and event capacity loss. No live write is performed by the tests or CI.

## Actual official MCP reads

Initialization and tools/list succeeded: 35 tool contracts; no missing or unclassified tool relative to the supported catalog. Read-only live queries/quotes succeeded for **21 distinct business tools**:

- `available-coupons`
- `calculate-price`
- `campaign-calendar`
- `list-nutrition-foods`
- `mall-order-list`
- `mall-points-products`
- `mall-product-detail`
- `now-time-info`
- `order-list`
- `query-lottery-info`
- `query-meal-detail`
- `query-meals`
- `query-my-account`
- `query-my-coupons`
- `query-my-prizes`
- `query-nearby-stores`
- `query-party-city`
- `query-party-store`
- `query-party-store-date`
- `query-party-store-session`
- `query-store-coupons`

Three complete meals were actually quoted and compared at a publicly chosen Shanghai test store; replacing a cola with the allowed no-sugar alternative was re-quoted. Payable prices were 2600, 2600 and 2800 cents. Nutrition was joined by exact component/serving names. A standalone HTML report was generated. These are historical test values, not current offers.

The actual coupon and history adapters were exercised on private response records. Account details, individual spending values and raw personal records are excluded from this repository.

One mall-detail query returned “商品已下架” for a listing whose redemption deadline was already past despite status=2. After checking the actual deadline, a different still-current product's detail succeeded. This is recorded as a business-data limitation, not silently retried as the same purchase. Mall discovery checks dates and current detail availability.

Event city, store, date and session queries succeeded. Actual sessions include minimum/maximum participants, remaining spaces and a cent-denominated price; event preflight checks these before a draft can execute.

## Limits

Seven account-changing tools were not executed live. No address was created, no coupon claimed, no order created or cancelled, no payment made, no points redeemed, no event booked and no lottery drawn during development. Remaining reads needing an actual selected address/order or another business context were discovered/documented without claiming successful business execution. Coverage is per-tool in references/tool-coverage.md.

Historical reports cover only records actually returned/saved; no complete-year claim. No background reminder, voice playback, carbon calculation or fabricated lottery probability is included. WorkBuddy was not used in development; no WorkBuddy-only bonus evidence is claimed.

## Public-source integrity

Official contest declaration SHA-256: `cd28101bcb29cc8fb24b372fe91ce6b42c4a1487a54e01f7ade0c8c6a84241b7`. Copied unchanged from the official contest repository. Public configuration contains only an environment-variable placeholder. Before publication, the complete staged tree is checked for the actual locally configured credential and generated personal data.
