"""CLI for live queries, deterministic planning, private state and reports."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import uuid
from . import actions
from .catalog import ALL_TOOLS, MODULES, READ_TOOLS, WRITE_TOOLS
from .client import Client, MCPError, assert_success, payload
from .planner import compare, delta, random_pick, quote_candidate, split_bill, compose_candidate
from .records import expiry_report, nutrition_table, save_order, spending_report, normalize_orders, normalize_coupons
from .reports import public_report, render_html, render_csv, invitation
from .storage import PROJECT, state_dir, read_json, private_write, profile_get, profile_update


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False))


def outside_project(path):
    path = Path(path).expanduser().resolve()
    if path == PROJECT or PROJECT in path.parents:
        raise ValueError("Private live data must be written outside the public project")
    return path


def record_call(client, tool, arguments):
    result = client.call(tool, arguments)
    return {"tool": tool, "arguments": arguments, "recorded_at": datetime.now(timezone.utc).isoformat(), "result": result}


def demo_plan():
    # Entirely synthetic, intentionally non-orderable product identifiers.
    def component(name, category, code, kcal, protein, sodium):
        return {"name": name, "category": category, "product_code": "DEMO-" + code, "quantity": 1, "nutrition": {"kcal": kcal, "protein_g": protein, "sodium_mg": sodium, "calcium_mg": 10}}
    def meal(key, label, price, parts):
        return {"id": key, "label": label, "total_cents": price, "components": parts, "quote": {"source": "synthetic-demo", "quoted_at": None}}
    burger = component("Demo chicken burger", "main", "CHICKEN", 390, 22, 800)
    fish = component("Demo fish burger", "main", "FISH", 330, 17, 540)
    fries = component("Demo fries", "side", "FRIES", 210, 3, 120)
    tea = component("Demo plain tea", "drink", "TEA", 2, 0, 0)
    cola = component("Demo cola", "drink", "COLA", 147, 0, 0)
    return {"request": {"budget_cents": 3000, "required_categories": {"main": 1, "side": 1, "drink": 1}, "max_kcal": 800, "likes": ["chicken"], "recent_items": ["Demo chicken burger"]}, "candidates": [meal("A", "Spend less", 2600, [burger, fries, cola]), meal("B", "Change the drink", 2500, [burger, fries, tea]), meal("C", "Try another main", 2900, [fish, fries, tea])]}


def parser():
    p = argparse.ArgumentParser(description="McDonald's All-in-One — Python 3.9+, standard library only")
    sub = p.add_subparsers(dest="command", required=True)
    tools = sub.add_parser("tools", help="List the eleven modules and 35 supported tools")
    tools.add_argument("--live", action="store_true")
    tools.add_argument("--name", help="Show the exact schema of one tool")
    sub.add_parser("doctor", help="Check authentication, tool coverage and server time; no account/business reads")
    call = sub.add_parser("call", help="Call one known read-only tool; saves raw output privately")
    call.add_argument("tool")
    call.add_argument("--args", help="JSON arguments file")
    call.add_argument("--save", help="Private response record path outside this project")
    call.add_argument("--show", action="store_true", help="Show response as well; personal queries may contain private information")
    quote = sub.add_parser("quote", help="Quote up to six complete candidates from actual menu/detail data")
    quote.add_argument("plan")
    quote.add_argument("--output", help="Private comparison path outside this project")
    compose = sub.add_parser("compose", help="Build actual meal selections from saved detail records, optionally join nutrition")
    compose.add_argument("input")
    compose.add_argument("--output", required=True)
    comp = sub.add_parser("compare", help="Compare an existing plan offline; no prices are fetched")
    comp.add_argument("plan")
    comp.add_argument("--output")
    change = sub.add_parser("delta", help="Compare two fully quoted baskets")
    change.add_argument("before")
    change.add_argument("after")
    pick = sub.add_parser("pick", help="Randomly choose an eligible already-compared meal")
    pick.add_argument("report")
    pick.add_argument("--avoid-recent", action="store_true")
    expiry = sub.add_parser("expiry", help="Report normalized assets and suggest uses at supplied meal times")
    expiry.add_argument("input")
    expiry.add_argument("--now")
    expiry.add_argument("--from-coupons", action="store_true", help="Read a saved query-my-coupons response; no schedule is inferred")
    profile = sub.add_parser("profile", help="Manage private preferences; temporary overrides stay in plan.request")
    profile.add_argument("action", choices=["show", "set", "unset", "clear"])
    profile.add_argument("--json", help="JSON object with preferences")
    profile.add_argument("--keys", nargs="+", default=[])
    ledger = sub.add_parser("ledger", help="Store normalized confirmed orders or summarize recorded spending")
    ledger.add_argument("action", choices=["add", "import-mcp", "report", "clear"])
    ledger.add_argument("--file", help="Normalized order JSON, or list of orders for an offline report")
    ledger.add_argument("--start")
    ledger.add_argument("--end")
    ledger.add_argument("--output")
    nutrition = sub.add_parser("nutrition", help="Normalize a saved official nutrition response")
    nutrition.add_argument("record")
    nutrition.add_argument("--name", help="Exact official food name; no fuzzy nutrient assignment")
    split = sub.add_parser("split", help="Allocate a reference bill without losing cents")
    split.add_argument("--total-cents", required=True, type=int)
    split.add_argument("--people", required=True, type=int)
    split.add_argument("--weights", nargs="+", type=float)
    invite = sub.add_parser("invite", help="Draft an invitation; no message is sent and no booking is made")
    invite.add_argument("event")
    export = sub.add_parser("export", help="Export whitelisted comparison/report fields")
    export.add_argument("report")
    export.add_argument("--format", choices=["html", "csv", "json"], default="html")
    export.add_argument("--output", required=True)
    export.add_argument("--title", default="Your meal, your choice")
    prepare = sub.add_parser("prepare", help="Prepare one mutation draft; does not execute it")
    prepare.add_argument("tool")
    prepare.add_argument("--args", required=True)
    prepare.add_argument("--summary", required=True)
    prepare.add_argument("--evidence", help="Saved official quote candidate, item detail or event-session record")
    execute = sub.add_parser("execute", help="Execute a reviewed draft once, after explicit user confirmation")
    execute.add_argument("draft")
    execute.add_argument("--confirm", required=True)
    demo = sub.add_parser("demo", help="Run synthetic meal comparisons and optionally generate a shareable HTML card")
    demo.add_argument("--output")
    return p


def run(args):
    if args.command == "tools":
        inventory = Client().tools() if args.live else {t["name"]: t for t in read_json(PROJECT / "references/tool-schemas.json")["tools"]}
        if args.name:
            if args.name not in inventory:
                raise ValueError("Unknown tool")
            emit(inventory[args.name])
        else:
            emit({"source": "live" if args.live else "bundled schema snapshot; use --live to refresh", "tool_count": len(inventory), "modules": MODULES, "write_tools": sorted(WRITE_TOOLS), "missing": sorted(ALL_TOOLS - set(inventory)), "new_unclassified": sorted(set(inventory) - ALL_TOOLS)})
    elif args.command == "doctor":
        client = Client()
        tools = client.tools()
        clock = assert_success(client.call("now-time-info", {}))
        emit({"connected": True, "server": client.server_info, "tool_count": len(tools), "missing": sorted(ALL_TOOLS - set(tools)), "new_unclassified": sorted(set(tools) - ALL_TOOLS), "server_time": clock.get("data"), "write_operations_executed": 0})
    elif args.command == "call":
        if args.tool not in READ_TOOLS:
            raise ValueError("call accepts only known read-only tools; use prepare/execute for a confirmed write")
        arguments = read_json(args.args) if args.args else {}
        actions.context_check(args.tool, arguments)
        client = Client()
        record = record_call(client, args.tool, arguments)
        target = outside_project(args.save) if args.save else state_dir() / "responses" / f"{args.tool}-{uuid.uuid4().hex[:10]}.json"
        private_write(target, record)
        assert_success(record["result"])
        if args.show:
            print(client.scrub(json.dumps(record, ensure_ascii=False, indent=2)))
        else:
            emit({"tool": args.tool, "record": str(target), "success": True})
    elif args.command == "compose":
        spec = read_json(args.input)
        table = {}
        if spec.get("nutrition_record"):
            record = read_json(spec["nutrition_record"])
            table = nutrition_table(assert_success(record["result"])["data"])
        plan = {"request": spec.get("request", {}), "candidates": [compose_candidate(c, table) for c in spec["candidates"]]}
        target = outside_project(args.output)
        private_write(target, plan)
        emit({"plan": str(target), "candidate_count": len(plan["candidates"]), "next": "quote this plan to get current payable totals"})
    elif args.command in ("quote", "compare"):
        plan = read_json(args.plan)
        request = {**profile_get(), **plan.get("request", {})}
        if "excluded_terms" not in request and request.get("dislikes"):
            request["excluded_terms"] = request["dislikes"]
        candidates = plan.get("candidates", [])
        if not 1 <= len(candidates) <= 6:
            raise ValueError("Supply one to six complete candidates")
        errors = []
        if args.command == "quote":
            client = Client()
            quoted = []
            context = None
            for candidate in candidates:
                arguments = candidate["arguments"]
                current = {k: arguments.get(k) for k in ("storeCode", "orderType", "beType", "beCode", "reservationDate")}
                if context is not None and current != context:
                    raise ValueError("A comparison must use one store, mode and reservation time")
                context = current
                actions.context_check("calculate-price", arguments)
                try:
                    quoted.append(quote_candidate(client, candidate))
                except (MCPError, ValueError) as e:
                    errors.append({"id": candidate["id"], "error": client.scrub(e)})
                    break  # stop on error; no schema probing or silent candidate churn
            candidates = quoted
        if not candidates:
            raise ValueError("No valid quote; " + json.dumps(errors, ensure_ascii=False))
        report = compare(candidates, request)
        report["errors"] = errors
        if args.command == "quote" or args.output:
            target = outside_project(args.output) if args.output else state_dir() / "comparisons" / f"{uuid.uuid4().hex[:12]}.json"
            private_write(target, report)
            emit({"private_report": str(target), "report": public_report(report), "errors": errors})
        else:
            emit(report)
    elif args.command == "delta":
        emit(delta(read_json(args.before), read_json(args.after)))
    elif args.command == "pick":
        chosen = random_pick(read_json(args.report), args.avoid_recent)
        emit({"id": chosen["id"], "label": chosen.get("label"), "total_cents": chosen["total_cents"], "components": [{"name": i["name"], "quantity": i["quantity"]} for i in chosen["components"]], "note": "Random selection only; no order created"})
    elif args.command == "expiry":
        data = read_json(args.input)
        emit(expiry_report(normalize_coupons(data), now=args.now) if args.from_coupons else expiry_report(data["assets"], data.get("planned_meals", []), args.now))
    elif args.command == "profile":
        if args.action == "show":
            emit(profile_get())
        elif args.action == "set":
            if not args.json:
                raise ValueError("Provide --json with the preferences the user asked to remember")
            emit(profile_update(json.loads(args.json)))
        elif args.action == "unset":
            emit(profile_update({}, args.keys))
        else:
            (state_dir() / "profile.json").unlink(missing_ok=True)
            emit({"profile_deleted": True})
    elif args.command == "ledger":
        path = state_dir() / "orders.json"
        if args.action == "add":
            if not args.file:
                raise ValueError("Provide a normalized order with --file")
            emit(save_order(read_json(args.file)))
        elif args.action == "import-mcp":
            if not args.file:
                raise ValueError("Provide a saved order-list response with --file")
            orders, skipped = normalize_orders(read_json(args.file))
            for order in orders:
                save_order(order)
            emit({"imported": len(orders), "skipped": skipped, "scope": "Only orders present in the saved response"})
        elif args.action == "clear":
            path.unlink(missing_ok=True)
            emit({"ledger_deleted": True})
        else:
            orders = read_json(args.file) if args.file else read_json(path) if path.exists() else []
            result = spending_report(orders, args.start, args.end)
            if args.output:
                private_write(outside_project(args.output), result)
            emit(result)
    elif args.command == "nutrition":
        record = read_json(args.record)
        body = assert_success(record.get("result", record))
        table = nutrition_table(body.get("data"))
        emit(table.get(args.name, {"error": "No exact nutrition match"}) if args.name else table)
    elif args.command == "split":
        emit(split_bill(args.total_cents, args.people, args.weights))
    elif args.command == "invite":
        print(invitation(read_json(args.event)))
    elif args.command == "export":
        report = read_json(args.report)
        text = render_html(report, args.title) if args.format == "html" else render_csv(report) if args.format == "csv" else json.dumps(public_report(report), ensure_ascii=False, indent=2)
        target = Path(args.output).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        # Even an exported report starts private; the user decides whether to share it.
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        emit({"export": str(target.resolve()), "format": args.format})
    elif args.command == "prepare":
        client = Client()
        draft = actions.prepare(client, args.tool, read_json(args.args), args.summary, read_json(args.evidence) if args.evidence else None)
        # Detailed draft/evidence stays private; show exact summary/cost to the user.
        emit({"id": draft["id"], "tool": draft["tool"], "summary": draft["summary"], "expires_at": draft["expires_at"], "cost_and_terms": draft["review"], "draft_file": str(state_dir() / "drafts" / f"{draft['id']}.json"), "next": "Show the exact draft and obtain explicit user confirmation before execute"})
    elif args.command == "execute":
        client = Client()
        result = actions.execute(client, args.draft, args.confirm)
        target = state_dir() / "responses" / f"action-{args.draft}.json"
        private_write(target, result)
        emit({"response_record": str(target), "note": "Inspect the actual response for order/payment/redemption status. A returned response is not proof of payment or full success."})
    elif args.command == "demo":
        data = demo_plan()
        report = compare(data["candidates"], data["request"])
        report["scope"] = "SYNTHETIC DEMO — invented menu and prices; no MCP calls, no orders"
        if args.output:
            target = Path(args.output).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(render_html(report, "Don't know what to eat? Let me help!"), encoding="utf-8")
        emit(public_report(report))


def main():
    args = parser().parse_args()
    try:
        run(args)
    except (ValueError, KeyError, TypeError, OSError, MCPError) as e:
        # Never include the configured credential in an error, even for malformed inputs.
        message = str(e)
        try:
            from .storage import token
            message = message.replace(token(), "[REDACTED]")
        except ValueError:
            pass
        print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
