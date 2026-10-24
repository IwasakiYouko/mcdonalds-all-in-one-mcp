# Portable MCP bridge

Run commands from this skill's root, or replace `scripts/mcd.py` with its absolute path. Requires Python 3.9+ and the OS time-zone database. No third-party Python package or local server is needed. Native MCP connectors remain usable; these scripts are deterministic helpers and an alternative official transport.

## Private credentials and state

Read the Token from MCD_MCP_TOKEN, otherwise from `~/.config/mcdonalds-all-in-one-mcp/credentials.json` containing a `token` string. The latter file and directory should be mode 600/700. Keep it outside the skill/repository; never print it or include it in a command argument, report or issue. To enter a Token without putting it in shell history:

```bash
read -rsp 'McDonald’s MCP Token: ' MCD_MCP_TOKEN
export MCD_MCP_TOKEN
```

The native-client example is [mcp-config.example.json](../mcp-config.example.json). `${MCD_MCP_TOKEN}` must be expanded by the host's supported secret/environment mechanism; copying the literal placeholder into an Authorization header will not authenticate.

Private state defaults to `~/.local/state/mcdonalds-all-in-one-mcp`; MCD_STATE_DIR can select another directory outside the project. JSON records are atomically written with private permissions. Response records can contain account details; do not publish them. A skill install should copy scripts/, references/, agents/ and SKILL.md together, or simply use the whole repository folder.

## Discovery and individual queries

```bash
python3 scripts/mcd.py doctor
python3 scripts/mcd.py tools
python3 scripts/mcd.py tools --live --name query-meals
python3 scripts/mcd.py call now-time-info
python3 scripts/mcd.py call query-nearby-stores --args /private/path/search.json
```

`call` accepts only the 28 known read-only tools. It saves a response record and prints its path. `--save /private/path/response.json` chooses a path. `--show` also prints content: use it only when disclosure is appropriate. Records contain tool, arguments, recorded_at and result. Inspect result with the host file reader. Transport success is not business success.

The client does JSON-RPC initialization, streamable HTTP/SSE decoding, session handling and live nested input validation. It refuses credential-bearing redirects. No automatic retry occurs. HTTP 401 means check credentials; 429 means stop and reduce request frequency (official quota 600/minute). Schema errors need evidence-based fixes; don't cycle through speculative payload variants.

## Compose and quote complete meals

The agent gathers official detail records and chooses meaningful options. `compose` builds the nested API payload and the edible-component list; it does not decide what the user wants. A compose specification has this shape (paths point to private records already fetched):

```json
{
  "request": {
    "budget_cents": 3000,
    "required_categories": {"main": 1, "side": 1, "drink": 1},
    "max_kcal": 800
  },
  "nutrition_record": "/private/path/nutrition-response.json",
  "candidates": [{
    "id": "A",
    "label": "Keep the main, change the drink",
    "context": {"storeCode": "ACTUAL_STORE_CODE", "beType": 1, "orderType": 1, "needTableware": false},
    "lines": [{
      "detail_record": "/private/path/meal-detail-response.json",
      "quantity": 1,
      "selections": {},
      "categories": {"ACTUAL_MAIN_CODE": "main", "ACTUAL_SIDE_CODE": "side", "ACTUAL_DRINK_CODE": "drink"}
    }]
  }]
}
```

Codes in this documentation are structural placeholders, not API arguments to run. An empty selections object uses actual defaults. To replace a round, use its actual string ID as the key and actual choice objects as the value: `"3": [{"code": "ACTUAL_CHOICE_CODE", "quantity": 1}]`. `nutrition_names` optionally maps a selected code to an explicitly verified official serving name. Unknown/modified nutrients remain unknown. Never classify the parent combo as a second main. Keep store/mode/time consistent between each saved detail and the composed context.

```bash
python3 scripts/mcd.py compose /private/path/compose.json --output /private/path/plan.json
python3 scripts/mcd.py quote /private/path/plan.json --output /private/path/comparison.json
python3 scripts/mcd.py export /private/path/comparison.json --output /private/path/meal-report.html
python3 scripts/mcd.py pick /private/path/comparison.json --avoid-recent
```

An already assembled plan contains request and candidates; each candidate contains id, label, arguments (the actual calculate-price parameters), and components. Each edible component has name, product_code, category, positive integer quantity and optional per-serving nutrition (`kcal`, `protein_g`, `sodium_mg`, `calcium_mg`). `quote` supplies total_cents and official evidence. Offline `compare` accepts total_cents already present, but does not verify or refresh prices.

Temporary preferences go into plan.request. They override stored profile values without changing them. Actual constraints and physical meal components are applied before sorting. Reports may select the same meal for two goals if it satisfies both; don't invent alternatives for presentation.

## Confirmed writes

```bash
python3 scripts/mcd.py prepare create-order --args /private/path/order.json --evidence /private/path/selected-candidate.json --summary 'Exact selected meal, store, method and confirmed total'
# Present the draft/costs and wait for the user's explicit confirmation.
python3 scripts/mcd.py execute DRAFT_ID --confirm DRAFT_ID
```

The selected-candidate file is the exact candidate object from the private official comparison, including arguments and quote. For mall-create-order attach a saved mall-product-detail response; for party-order-create attach the session response. The bridge rechecks mall costs/points and event SKU/session before execution. If a session response changes shape, it stops instead of guessing. Native connector workflows can handle a newly documented shape after inspection.

All seven write tools use the same draft lifecycle. Drafts expire after five minutes, bind exact arguments and are attempted once; a timeout also consumes the attempt. A food draft requires a recent official whole-basket quote and a valid pickup method/address. Price and lottery consumption are checked again before the write. Re-preparing is not a way to retry an unknown outcome: first inspect the real order/account state. Do not run prepare merely to “test” a purchase, or execute merely because a draft exists. Tests use a FakeClient and synthetic input, never a paid or points-consuming live action.
