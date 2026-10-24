# Actual McDonald's MCP integration

## Service and authentication

- Official endpoint: `https://mcp.mcd.cn`
- Transport: MCP Streamable HTTP; JSON-RPC initialization, server session headers, JSON/SSE responses and paginated tools/list.
- Authentication: private bearer Token from environment or a private credentials file outside the repository.
- Read the [official integration guide](https://github.com/M-China/mcd-mcp-server) and the [official service rules](https://cdn.mcd.cn/cms/pages/MCPServerRules.html). The service is intended for mainland China.

The included client actually connects to this service. It is not a local imitation of the McDonald's server. `doctor` initializes a session, discovers tool contracts and calls now-time-info. `call` validates live arguments and executes a named read-only official tool. `quote` makes real calculate-price calls. The offline demo is separately and explicitly labeled synthetic.

## Business value and flow

The Skill turns 35 low-level tools into eleven connected workflows. It helps the user choose a complete meal, understand real costs, use rewards and maintain private records without switching between separate skills.

### Meal choice and price comparison

User's requirements → actual store selection → query-meals + query-store-coupons → query-meal-detail → expand actual choices → optional list-nutrition-foods → compose complete candidates → calculate-price per candidate → constraint check and comparison → optional report.

The deterministic comparison applies required components, exclusions, budget and nutrient constraints **before** ranking. It shows actual remaining budget and can explain a minimum budget shortfall. A substitution rebuilds and re-quotes the whole basket. Topping-up advice compares the final two totals rather than a coupon's headline discount.

Real read-only validation on 2026-10-24 used a publicly selected Shanghai store as a test location, not an inferred user location. It successfully quoted:

| Candidate | Whole meal | Official payable total | Matched reference energy |
|---|---|---:|---:|
| A | 吉士汉堡包 + 中薯条 + 可乐中杯 | CNY 26.00 | 730 kcal |
| B | 吉士汉堡包 + 中薯条 + 无糖可口可乐中杯 | CNY 26.00 | 583 kcal |
| C | 麦香鸡 + 中薯条 + 可乐中杯 | CNY 28.00 | 805 kcal |

These are historical test quotes, not current nationwide prices. The no-sugar substitution was an actual allowed round choice and was re-quoted. Its sodium differed too, so it was not described as universally better. The private comparison and standalone report were actually generated. No order was created.

### Rewards, events and account workflows

- Coupon inventory and claimable coupons are separate from current-store eligibility. Known date/time restrictions inform an expiry list; user-provided meal opportunities can be scheduled conservatively.
- Points and mall products use actual account/detail queries. Old products can remain in a listing after downTime; current dates and detail availability are checked. Structured points/price/extTradePrice fields are presented instead of extracting prices from marketing text.
- Event products use city → store → date → session selection before a confirmed event order.
- Lottery preparation reads the server's resourceEligible/nextConsumption decision, rechecks it before one confirmed draw and never uses trial/automatic draws.
- Historical food orders can be imported into a private ledger. The observed history's realTotalAmount is yuan, while calculate-price's data.price is cents. Combo children are expanded without counting their parent again.
- Feedback queries read actual satisfaction/reward information for an actual order; they do not submit feedback or create a reward.

See [tool-coverage.md](references/tool-coverage.md) for every tool and its tested/discovered status, and the mode-specific workflows linked from SKILL.md.

## Controlled account changes

Seven write tools are separated from the 28 read-only tools. The generic call command refuses writes. A reviewed exact-action draft has a digest, a five-minute lifetime and a single-attempt marker. execute requires the matching confirmed draft ID. A changed payload, changed quote/consumption or expired draft stops execution. Mall drafts refresh product/SKU costs and points resources; event drafts refresh the selected session and SKU. Uncertain outcomes are checked before considering another action; no write is automatically retried.

The agent must still obtain actual user confirmation. A command-line flag or generated ID is not evidence that a user agreed. Native MCP calls follow the same semantic confirmation rules. Real payment is performed by the user in the official channel.

## What is and is not validated

All 35 tool names and input contracts were discovered live. Multiple official read queries and complete food quotes succeeded; see VALIDATION.md for the concrete set. Local tests verify arithmetic, adapters, constraints, private exports and mutation boundaries using isolated fixtures/FakeClient.

Food ordering/payment, address creation, claiming coupons, point redemption, event booking, cancellation and lottery draws were **not executed live** during development. Their native workflows, schema bindings and bridge guards are implemented; this does not claim a completed payment or successful redemption. Some read tools require a chosen address, order or event and are documented/discovered without a live business test. Do not interpret generic 35-tool coverage as 35 successful live business calls.

## Public versus private evidence

Public files contain code, workflows, tool schemas, synthetic examples and aggregate validation facts. Token, account balances, addresses, contacts, order IDs, coupon codes and raw personal responses are excluded. Raw local evidence is stored privately outside the repository. The official CONTEST_DECLARATION.md is copied byte-for-byte and verified by SHA-256. No fabricated WorkBuddy context is included.
