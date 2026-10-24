# Tool coverage

Source: official tools/list, retrieved 2026-10-24T04:02:47.969385+00:00. All 35 discovered tools have explicit routing across eleven modules. Live contracts take precedence over this snapshot.

Read-only means no intended business mutation, not necessarily public data. Development validation did not execute any of the seven write tools. Native-agent workflows are described in the linked module references.

| Module | Official tool name | Mode | Validation |
|---|---|---|---|
| store-address | `delivery-query-addresses` | Read-only | Schema discovered; business read not exercised |
| store-address | `delivery-create-address` | Confirmed write | Schema discovered; transaction deliberately not executed |
| store-address | `delivery-query-stores` | Read-only | Schema discovered; business read not exercised |
| store-address | `query-nearby-stores` | Read-only | Live query/quote succeeded |
| menu-pricing | `query-meals` | Read-only | Live query/quote succeeded |
| menu-pricing | `query-meal-detail` | Read-only | Live query/quote succeeded |
| menu-pricing | `calculate-price` | Read-only | Live query/quote succeeded |
| nutrition | `list-nutrition-foods` | Read-only | Live query/quote succeeded |
| coupons | `available-coupons` | Read-only | Live query/quote succeeded |
| coupons | `auto-bind-coupons` | Confirmed write | Schema discovered; transaction deliberately not executed |
| coupons | `query-my-coupons` | Read-only | Live query/quote succeeded |
| coupons | `query-store-coupons` | Read-only | Live query/quote succeeded |
| orders | `create-order` | Confirmed write | Schema discovered; transaction deliberately not executed |
| orders | `query-order` | Read-only | Schema discovered; business read not exercised |
| orders | `order-list` | Read-only | Live query/quote succeeded |
| orders | `cancel-order` | Confirmed write | Schema discovered; transaction deliberately not executed |
| group-meals | `query-meal-assistance` | Read-only | Schema discovered; business read not exercised |
| group-meals | `query-promotions` | Read-only | Schema discovered; business read not exercised |
| points-mall | `query-my-account` | Read-only | Live query/quote succeeded |
| points-mall | `mall-points-products` | Read-only | Live query/quote succeeded |
| points-mall | `mall-product-detail` | Read-only | Live query/quote succeeded |
| points-mall | `mall-create-order` | Confirmed write | Schema discovered; transaction deliberately not executed |
| points-mall | `mall-order-list` | Read-only | Live query/quote succeeded |
| points-mall | `mall-order-detail` | Read-only | Schema discovered; business read not exercised |
| campaigns | `campaign-calendar` | Read-only | Live query/quote succeeded |
| campaigns | `now-time-info` | Read-only | Live query/quote succeeded |
| lottery | `query-lottery-info` | Read-only | Live query/quote succeeded |
| lottery | `draw-lottery` | Confirmed write | Schema discovered; transaction deliberately not executed |
| lottery | `query-my-prizes` | Read-only | Live query/quote succeeded |
| events | `query-party-city` | Read-only | Live query/quote succeeded |
| events | `query-party-store` | Read-only | Live query/quote succeeded |
| events | `query-party-store-date` | Read-only | Live query/quote succeeded |
| events | `query-party-store-session` | Read-only | Live query/quote succeeded |
| events | `party-order-create` | Confirmed write | Schema discovered; transaction deliberately not executed |
| feedback | `query-survey-coupon` | Read-only | Schema discovered; business read not exercised |

The generic bridge can call every listed read-only tool using its live schema. All known write tools have a prepare/execute path; food, lottery, mall and event paths have task-specific preflight checks. Unclassified newly added tools are not automatically callable through the generic read command.

Workflow references: [meals](meals.md), [rewards and events](rewards-events.md), [records and reports](records-reports.md), [bridge](bridge.md).
