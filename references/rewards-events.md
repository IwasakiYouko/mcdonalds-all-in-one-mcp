# Coupons, points, campaigns, events and feedback rewards

## Coupons and expiring benefits

- `available-coupons`: currently claimable coupons; missing expiry is unknown, not unlimited validity. Do not invent a couponId when one is not returned.
- `auto-bind-coupons`: claims all currently available coupons. Show the scope and obtain confirmation; it changes the user's account even if free.
- `query-my-coupons`: owned assets; use explicit page/pageSize strings and follow totalPages within documented limits when a full inventory is requested.
- `query-store-coupons`: eligibility at a specific store, dining mode and reservation time. Owned assets alone cannot prove usability for an order.

Preserve actual start/end timestamps, day-of-week restrictions, time windows, quantities and channels. “Two days until expiry” does not mean two usable meal opportunities. Don't manufacture visits or encourage an extra purchase just to use a coupon. Price both the unchanged intended meal and any top-up meal; explain the net change and added food. A coupon's headline face value is not a verified saving.

Use `expiry` with normalized assets and user-provided planned_meals. The helper assigns one coupon per opportunity, earliest known expiry first; this is a conservative scheduling suggestion, not a promise of stacking or future store eligibility. It does not create notifications. See [records-reports.md](records-reports.md) for the input format and account-data normalization.

## Points and mall

`query-my-account` returns decimal **strings** for points. Preserve Decimal precision. The observed API spelling is `currentMouthExpirePoint` (and nextMouth/lastMouth), not Month. Do not assume an exchange rate from points to cash or guess an exact expiry timestamp that is not returned.

`mall-points-products` lists virtual coupons, goods and event products. Use actual catRuleIds when filtering. Check upTime/downTime against server time; status=2 by itself does not prove a listing is currently redeemable. For a shortlisted item call `mall-product-detail`, present SKU, points, extra cash, stock, dates and the returned purchase notice. Notices are display text; use structured SKU fields for calculations and validation, not numbers extracted from prose. A redemption coupon may require paying extra when it is later used.

`mall-create-order` is for shopId=2 item/coupon redemption. Virtual spuCategory="1"; physical "2" requires a chosen addressId. Select an actual skuId from detail, verify resources and explain all costs before confirmation. One item per order; multiple requested redemptions are handled sequentially with each previous result inspected. Do not retry an uncertain redemption. `mall-order-list` and `mall-order-detail` return mall history and status; food cancellation is not a mall cancellation feature.

## Lottery

Call `query-lottery-info` before discussing an actual draw. Show the official activity period, prizes and `drawDecision.nextConsumption`; read `resourceEligible` for eligibility. A zero availableTimes does not necessarily prohibit a points-funded draw. Explain fallbackConsumption if configured.

After explicit confirmation for **this one draw and its actual cost**, call `draw-lottery` once. Recheck if consumption changes. No auto-draw, repeated draw, trial draw or automatic retry. Inspect status.code and return the actual result. `query-my-prizes` is paginated; pageNum/pageSize are strings in the observed schema. Official probabilities are not provided, so do not claim a reliable expected return or infer odds from prize counts.

## Campaign calendar

`campaign-calendar` without arguments returns the current month's calendar; specifiedDate returns the anchored nearby activity dates described by the live schema. Use `now-time-info` for current dates. Explain whether an activity is past, current or upcoming based on timestamps, not cached labels such as “today”. An upcoming campaign does not prove a lower future price. Compare a coupon's actual usable dates with an event date only as a timing suggestion.

## Parties and experiences

1. Find an actual shopId=5 event product through mall-points-products; query detail and let the user choose the product and booking type (partyType 1 private, 2 shared).
2. `query-party-city(spuId)` → let the user choose a real city.
3. `query-party-store(code, latitude, longitude, spuId)` → choose a store. City coordinates are the actual values returned by the previous tool, not a guess.
4. `query-party-store-date(spuId, storeCode)` → choose an actual date.
5. `query-party-store-session(spuId, storeCode, dateStr)` → choose an actual session and headcount.
6. Show product/SKU, type, city/store/date/start/end, participants, remaining spaces and full costs; obtain explicit confirmation for the exact booking before `party-order-create`.

Wait for a user selection at each step rather than silently choosing a city, store or session. The two live names contain **party-store**; old README spellings query-partystore-date/session are not callable names. Capacity can change; availability is rechecked before creating a draft. Return only the actual booking status. `invite` creates text the user can copy; it does not send a message, reserve seats or imply a completed booking.

## Feedback rewards

Use `query-survey-coupon` with an actual orderId explicitly supplied by the user or obtained from an upstream order query. It reads a satisfaction-answer description and associated reward title, redemption time/status and dining method. It does not submit a survey or create a new reward. Do not infer missing answers, codes or eligibility.
