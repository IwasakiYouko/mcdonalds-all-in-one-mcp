# McDonald's All-in-One

**Don't know what to eat? Let me help!**

One English-language Agent Skill for McDonald's China: choose a meal, compare actual prices, use your rewards and keep your dining preferences in one place. Talk to it in English or Chinese.

**不知道吃什么？让我帮你想想！** 查优惠、配餐、比价、管理积分和订单，一句话说出需求就好。

Independent community entry for the [2026 McDonald's Developer Innovation Challenge](https://github.com/M-China/mcd-developer-innovation-challenge). Uses the official MCP service in mainland China. Not an official McDonald's product.

## What you can say

| Say this | Get this |
|---|---|
| “30 yuan, a burger, fries and a drink. What should I eat?” | A few complete, officially quoted options with budget remaining |
| “Keep the burger. Change the drink.” | A new whole-meal quote, the exact change and the difference in price |
| “Does adding food to use this coupon actually save money?” | The two full totals and the net cost of topping up |
| “I'd like less sodium and at least 20 g of protein.” | Options checked against actual matching nutrition data |
| “I can't decide. Pick something I haven't had recently.” | A random qualifying choice, with recent-meal avoidance |
| “Which coupons and points are about to expire?” | An expiry list and realistic usage-window suggestions |
| “Remember my lunch budget and drink preference.” | Editable private preferences; temporary exceptions stay temporary |
| “What have I spent on McDonald's recently?” | A local spending report and dining calendar with actual coverage dates |
| “Lunch for eight, total budget 400 yuan.” | Group options, total cost, per-person references and meal lists |
| “Find a weekend party or tasting event.” | Actual cities, stores, dates and sessions, followed by booking only when confirmed |
| “Check my order and the reward coupon linked to its feedback.” | Actual order/feedback-reward status |
| “Save the comparison so I can share it.” | A standalone HTML meal card/report, or CSV/JSON export |

If no complete meal fits, it explains what is missing and offers a change. Required items and budgets are not silently dropped. A suggestion never places an order by itself.

## Try it in 30 seconds

Python **3.9+**, an OS time-zone database and no third-party Python packages:

```bash
git clone https://github.com/IwasakiYouko/mcdonalds-all-in-one-mcp.git
cd mcdonalds-all-in-one-mcp
python3 scripts/mcd.py demo --output /tmp/mcd-demo.html
```

Open `/tmp/mcd-demo.html` in a browser. This demo uses **clearly labeled synthetic meals and prices** and makes no network calls. A checked-in [demo report](examples/demo-report.html) shows the output format. No Token is needed for offline helpers.

## Use it as a Skill

Keep this folder intact. Put it in your agent's supported skill directory, or tell your agent to read this project's [SKILL.md](SKILL.md). For example, Codex's user skill location is `~/.codex/skills/mcdonalds-all-in-one-mcp/`; WorkBuddy's is `~/.workbuddy/skills/mcdonalds-all-in-one-mcp/`. On a machine where this repository already exists, a symlink avoids maintaining two copies:

```bash
mkdir -p ~/.codex/skills
ln -s /absolute/path/mcdonalds-all-in-one-mcp ~/.codex/skills/mcdonalds-all-in-one-mcp
```

Use a native McDonald's MCP connector if your agent has one. Otherwise the Skill uses the included Python bridge directly. Native configuration example: [mcp-config.example.json](mcp-config.example.json). Environment-variable expansion is host-specific; configure the Token through your client's supported private secret mechanism.

### Connect the official service

Apply for your own Token at the [official open platform](https://open.mcd.cn/mcp). Enter it privately for the bridge:

```bash
read -rsp 'McDonald’s MCP Token: ' MCD_MCP_TOKEN
export MCD_MCP_TOKEN
python3 scripts/mcd.py doctor
```

Alternatively use the private credentials file described in [bridge.md](references/bridge.md). No real credential belongs in the repository or in a shared configuration example.

Then ask the agent:

> 不知道吃什么，预算 30 元，要汉堡、配餐和饮料。帮我查一下附近门店，比较几种吃法，先别下单。

The agent gathers any missing store/location information, reads the real menu, checks applicable coupons and quotes the complete choices. You do not have to write JSON to use the Skill. The CLI also exposes the helpers for developers and reproducible workflows.

## Eleven modules, all 35 tools

Store & Address · Menu & Pricing · Nutrition Planner · Coupon Manager · Order Manager · Group Meal Planner · Points & Rewards · Campaign Calendar · Lottery Assistant · Events & Parties · Feedback Rewards.

See the [complete tool coverage table](references/tool-coverage.md), [live integration and evidence](MCP_INTEGRATION.md) and [validation record](VALIDATION.md). All 35 discovered contracts have explicit routing; known mutations use a separate confirmed-action flow. Discovery coverage does not mean every business operation has been executed live.

## Useful commands

```bash
python3 scripts/mcd.py tools                         # local coverage inventory
python3 scripts/mcd.py tools --live --name query-meals
python3 scripts/mcd.py call campaign-calendar        # saves response privately
python3 scripts/mcd.py profile show
python3 scripts/mcd.py split --total-cents 10000 --people 3
python3 scripts/mcd.py --help
```

The agent can use `compose` → `quote` → `export` to turn actual menu-detail records into a comparison and a shareable report. `delta`, `expiry`, `pick`, `ledger` and `invite` handle the smaller tasks. Input contracts and examples are in [bridge.md](references/bridge.md) and [records-reports.md](references/records-reports.md).

## Your data and your decisions

Preferences, responses, orders and drafts default to `~/.local/state/mcdonalds-all-in-one-mcp`, outside the public project. Private JSON uses restricted file permissions. You can remove saved preferences and orders with `profile clear` and `ledger clear`. Deleting the private state directory removes saved responses, reports and drafts too; credentials are stored separately.

Account changes—claiming coupons, adding an address, ordering, cancelling, redeeming points, booking an event or drawing a lottery—require review of the exact action and explicit confirmation. The bridge uses five-minute single-attempt drafts, checks food prices/lottery consumption again, and does not automatically retry uncertain transactions. Payment stays in the official app/payment page.

Exports omit identifiers, contacts, coupon codes and raw responses. Food names and spending can still be personal; review a report before sharing it. Historical coverage is shown, missing nutrition remains unknown and prices are rechecked before buying. This release has no background reminder, carbon-estimation or voice-playback service.

## Development and contest files

```bash
python3 -m unittest discover -s tests -v
```

The test suite exercises decision constraints, money/accounting, actual response adapters, report privacy, protocol handling and confirmed-action boundaries without live purchases. GitHub Actions checks Python 3.9 and 3.13. The Skill also passes the skill-creator validator.

Required submission files are included: README.md, the **unaltered official** CONTEST_DECLARATION.md, MCP_INTEGRATION.md, mcp-config.example.json and runnable source. Development used Codex; no WorkBuddy-only reward or fabricated WorkBuddy conversation is claimed.

Original code is MIT licensed. Official service metadata, contest declaration, service terms and trademarks retain their owners' terms. See [LICENSE](LICENSE) and the [official integration guide](https://github.com/M-China/mcd-mcp-server).
