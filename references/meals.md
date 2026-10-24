# Meals, stores, nutrition and food orders

## Decide what to eat

1. Read existing preferences only if useful. Current instructions override saved defaults. Collect the user's location/store, dining mode, time, budget, headcount, required meal components and exclusions as needed. Do not guess the user's location. Confirm whether “30 yuan” means total or per person for a group.
2. Query a store. Pickup uses `query-nearby-stores` with `beType=1`, drive-through `beType=5`; a location search uses `searchType=2`, `city`, `keyword`. A favorite search uses `searchType=1`. For delivery, query saved addresses, let the user choose, then call `delivery-query-stores` with the real addressId and `beType=2` or group `6`. Add an address only when requested and confirmed.
3. Query `query-meals` and `query-store-coupons` for the selected context. Query claimable/owned coupons when useful; claim only with concrete authorization. A menu's `currentPrice` may require a paid membership add-on (`withOrder`/`canWithOrder`); do not assume the user owns it or add it without asking.
4. Get `query-meal-detail` for the shortlisted meals. The argument is **code**, not productCode. Expand `rounds`: show defaults, allowed swaps and quantities. Mark `supportModify=true` as customizable; show detailed customization options when requested. A replacement must come from this detail, not a remembered menu.
5. Assemble about three complete, distinct baskets. Keep required items and quantities. For “main + side + drink”, do not suggest a cheap drink as a meal. Reuse the main when the user asks to keep it. Query `list-nutrition-foods` only when needed and join actual component/serving names; ambiguous matches stay unknown.
6. Call `calculate-price` for each whole basket. Compare confirmed payable totals, remaining budget, relevant nutrients and differences. Every altered basket requires a new quote: do not add/subtract menu prices from an old quote. Store time/context and mark saved quotes as historical.

Give fewer options if only one or two qualify. “Cheaper”, “closer to your taste” and “closer to your nutrition goal” are comparison labels, not three mandatory different answers. Low calories and low sodium can conflict; display the actual relevant values instead of saying one meal is universally healthier.

## Context and item parameters

| Mode | beType | orderType | beCode |
|---|---:|---:|---|
| Pickup | 1 | 1 | Omit |
| Drive-through | 5 | 1 | From the selected nearby store |
| McDelivery | 2 | 2 | From the selected delivery store |
| Enterprise group delivery | 6 | 2 | From the selected delivery store |

Use the store's actual supported reservation options; `reservationDate` is `yyyy-MM-dd HH:mm` and is omitted for immediate orders. Don't hardcode universal breakfast hours. After a mode/store/time change refresh menu, coupon eligibility and quotes.

`items` is a JSON **array**, not a JSON-encoded string. Each item needs a real productCode and positive quantity. Combo choices use `roundList: [{round: "1", comboItemList: [{code: "...", quantity: 1}]}]`. The parent quantity multiplies its component quantities. Selected customizations use `selectedKey`; where the source also supplies `unselectedKey`, include unselected items with that key. Do not invent these keys. Read the current nested schema before sending a custom selection.

## Deterministic helpers

The agent selects sensible candidates from real data; Python handles quantities and arithmetic. This is deliberately bounded candidate comparison, not an exhaustive optimizer.

- `compose input.json --output /private/path/plan.json`: build round selections and edible components from saved actual detail responses. Input format is documented in [bridge.md](bridge.md). Verify the meaning of classifications and explicit nutrition aliases before using them.
- `quote plan.json --output /private/path/comparison.json`: at most six whole-basket quotes in a single store/mode/time. Stops on the first API/schema failure and retains prior successful candidates. The resulting private comparison includes exact arguments and response evidence.
- `compare plan.json`: offline comparison of known totals. Offline values are not new live prices.
- `delta before-candidate.json after-candidate.json`: show added/removed/unchanged components and whole-basket net change. Use this for substitutions and a no-top-up versus top-up comparison. A basket difference is not the standalone price of one item.
- `pick comparison.json --avoid-recent`: randomly select only a qualifying quoted candidate; optional recent-meal avoidance. Selection does not place an order.

Normalized requests use budget_cents, required_categories (main/side/drink counts), required_products (actual component code to minimum quantity), excluded_terms, likes, recent_items, max_kcal, max_sodium_mg, min_protein_g and min_calcium_mg. Populate recent_items from actual authorized saved history. Negative/unknown nutrients must not pass a numeric limit. For exclusions involving ingredients/allergens, the available naming data may be insufficient: disclose that and ask the restaurant for confirmation.

## When nothing fits

Use the user's wording: “不知道吃什么？让我帮你想想！” / “Don't know what to eat? Let me help!”

Explain the specific gap. If a full quoted meal satisfies every requirement except price, show its actual shortfall. Offer to raise the budget or quote a changed side/drink. Otherwise identify the conflicting or unknown requirements and ask which can change. A proposed smaller meal must be quoted and compared before being presented as a valid solution.

## Group meals

For enterprise delivery query `query-promotions` and `query-meal-assistance` with the selected store/beCode, before final pricing. Promotions apply only where their products, times, service and rules match. Interpret structured rules to generate candidates; let official calculation verify the total. Report group total, headcount and per-person reference amount. `split --total-cents N --people N [--weights ...]` preserves every cent, using proportional reference shares when requested. It does not split a real payment. Keep individual food preferences and shared items in the planning summary.

## Food order lifecycle

After the user chooses to buy, quote the exact selected basket; show a final summary and obtain confirmation. `takeWayCode` for orderType=1 comes from the quote's `data.takeWayList`; delivery/group require addressId, and group requires gmServiceCode. `remark` is delivery-only and limited to 50 characters. Do not add a membership purchase while pricing.

The bridge's `prepare create-order` needs the **candidate object** from an official comparison as `--evidence`. Supply the same quote arguments plus appropriate address/takeWay fields. It rejects changed baskets, stale quotes and unsupported pickup methods. Once explicitly confirmed, execute once; re-quotation must still match the reviewed price. Return the real payment link; payment is performed in the official channel.

Use `query-order` for progress or after the user says they paid. Use `order-list` for recent history; no assumption of a complete year. Cancel only after the user identifies the actual order and confirms cancellation/reason; use the schema's string cancelReasonCode. `cancel-order` applies to food orders, not mall orders. A timeout after a mutation has an unknown outcome: query status and never blindly recreate it.
