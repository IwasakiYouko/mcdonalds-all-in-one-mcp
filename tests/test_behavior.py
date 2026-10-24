"""Observable decision, accounting, protocol and mutation-boundary tests."""
import copy
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from mcdlib import actions
from mcdlib.catalog import ALL_TOOLS, MODULES, READ_TOOLS, WRITE_TOOLS, validate
from mcdlib.client import decode_message, payload, assert_success, MCPError
from mcdlib.cli import demo_plan
from mcdlib.planner import compare, delta, random_pick, split_bill, nutrition, quote_total, fingerprint, compose_candidate
from mcdlib.records import expiry_report, window_allows, spending_report, save_order, nutrition_table, normalize_orders, normalize_coupons
from mcdlib.reports import render_html, render_csv, public_report, invitation
from mcdlib.storage import state_dir, private_write, read_json, profile_update, profile_get, PROJECT


def response(data):
    return {"content": [{"type": "text", "text": json.dumps({"success": True, "code": 200, "data": data})}]}


class FakeClient:
    def __init__(self, prices=None, fail_write=False):
        self.calls = []
        self.prices = list(prices or [2600])
        self.fail_write = fail_write
        self.decision = {"activityCode": "TEST", "drawDecision": {"resourceEligible": True, "nextConsumption": {"type": "POINTS", "amount": 10}, "fallbackConsumption": None}}

    def tools(self):
        snapshot = read_json(PROJECT / "references/tool-schemas.json")
        return {t["name"]: t for t in snapshot["tools"]}

    def call(self, name, arguments):
        self.calls.append((name, copy.deepcopy(arguments)))
        if name == "query-lottery-info":
            return response(self.decision)
        if name == "calculate-price":
            amount = self.prices.pop(0) if len(self.prices) > 1 else self.prices[0]
            return response({"price": amount, "takeWayList": [{"code": "eat-in"}]})
        if self.fail_write and name in WRITE_TOOLS:
            raise MCPError("Network outcome unknown")
        return response({"accepted": True})


class PrivateStateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"MCD_STATE_DIR": self.temp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_preferences_roundtrip_and_remove(self):
        profile_update({"budget_cents": 3000, "likes": ["fish"]})
        profile_update({"drink_preference": "plain tea"}, ["likes"])
        self.assertEqual(profile_get(), {"budget_cents": 3000, "drink_preference": "plain tea"})
        self.assertEqual((state_dir() / "profile.json").stat().st_mode & 0o777, 0o600)

    def test_credentials_cannot_be_preferences(self):
        with self.assertRaises(ValueError):
            profile_update({"token": "not-a-real-secret"})
        with self.assertRaises(ValueError):
            profile_update({"likes": "fish"})

    def test_state_inside_repository_rejected(self):
        with patch.dict(os.environ, {"MCD_STATE_DIR": str(PROJECT / "private")}):
            with self.assertRaises(ValueError):
                state_dir()

    def test_ledger_update_deduplicates_same_order(self):
        order = {"id": "local-test", "ordered_at": "2026-10-20T12:00:00+08:00", "status": "pending", "paid_cents": 2600, "source": "demo", "items": []}
        save_order(order)
        save_order({**order, "status": "paid"})
        orders = read_json(state_dir() / "orders.json")
        self.assertEqual(len(orders), 1)
        self.assertEqual(spending_report(orders)["total_paid_cents"], 2600)

    def test_draft_requires_exact_confirmation(self):
        c = FakeClient()
        draft = actions.prepare(c, "auto-bind-coupons", {}, "Claim currently available coupons")
        with self.assertRaises(ValueError):
            actions.execute(c, draft["id"], "yes")
        self.assertFalse(c.calls)

    def test_draft_executes_once(self):
        c = FakeClient()
        draft = actions.prepare(c, "auto-bind-coupons", {}, "Claim coupons")
        actions.execute(c, draft["id"], draft["id"])
        with self.assertRaises(ValueError):
            actions.execute(c, draft["id"], draft["id"])
        self.assertEqual(sum(n == "auto-bind-coupons" for n, _ in c.calls), 1)

    def test_timeout_cannot_replay_mutation(self):
        c = FakeClient(fail_write=True)
        draft = actions.prepare(c, "auto-bind-coupons", {}, "Claim coupons")
        with self.assertRaises(MCPError):
            actions.execute(c, draft["id"], draft["id"])
        with self.assertRaises(ValueError):
            actions.execute(c, draft["id"], draft["id"])
        self.assertEqual(len(c.calls), 1)

    def test_changed_draft_rejected(self):
        c = FakeClient()
        draft = actions.prepare(c, "auto-bind-coupons", {}, "Claim coupons")
        draft["summary"] = "Changed action"
        private_write(state_dir() / "drafts" / f"{draft['id']}.json", draft)
        with self.assertRaises(ValueError):
            actions.execute(c, draft["id"], draft["id"])
        self.assertFalse(c.calls)

    def test_expired_draft_rejected(self):
        c = FakeClient()
        with patch.object(actions, "TTL_SECONDS", -1):
            draft = actions.prepare(c, "auto-bind-coupons", {}, "Claim coupons")
        with self.assertRaises(ValueError):
            actions.execute(c, draft["id"], draft["id"])
        self.assertFalse(c.calls)

    def test_lottery_checks_actual_next_consumption(self):
        c = FakeClient()
        draft = actions.prepare(c, "draw-lottery", {}, "One draw using 10 points")
        c.decision["drawDecision"]["nextConsumption"]["amount"] = 20
        # Real RPC responses deserialize a new object each time.
        stored = read_json(state_dir() / "drafts" / f"{draft['id']}.json")
        self.assertEqual(stored["review"]["nextConsumption"]["amount"], 10)
        with self.assertRaises(ValueError):
            actions.execute(c, draft["id"], draft["id"])
        self.assertFalse(any(n == "draw-lottery" for n, _ in c.calls))

    def test_lottery_ineligible_resources_never_draw(self):
        c = FakeClient()
        c.decision["drawDecision"]["resourceEligible"] = False
        with self.assertRaises(ValueError):
            actions.prepare(c, "draw-lottery", {}, "One draw")
        self.assertFalse(any(n == "draw-lottery" for n, _ in c.calls))

    def test_order_price_change_invalidates_confirmation(self):
        c = FakeClient(prices=[2700])
        quote_args = {"storeCode": "1450713", "beType": 1, "orderType": 1, "items": [{"productCode": "TEST-ONLY", "quantity": 1}]}
        evidence = {"arguments": quote_args, "total_cents": 2600, "quote": {"source": "official-mcp", "quoted_at": datetime.now(timezone.utc).isoformat(), "arguments_sha256": fingerprint(quote_args), "result": response({"price": 2600, "takeWayList": [{"code": "eat-in"}]})}}
        draft = actions.prepare(c, "create-order", {**quote_args, "takeWayCode": "eat-in"}, "TEST ONLY, one meal CNY 26", evidence)
        with self.assertRaises(ValueError):
            actions.execute(c, draft["id"], draft["id"])
        self.assertFalse(any(n == "create-order" for n, _ in c.calls))

    def test_changed_order_needs_fresh_quote(self):
        c = FakeClient()
        args = {"storeCode": "1450713", "beType": 1, "orderType": 1, "items": [{"productCode": "TEST-ONLY", "quantity": 1}]}
        evidence = {"arguments": args, "total_cents": 2600, "quote": {"source": "official-mcp", "quoted_at": datetime.now(timezone.utc).isoformat(), "arguments_sha256": fingerprint(args), "result": response({"price": 2600})}}
        changed = {**args, "items": [{"productCode": "TEST-ONLY", "quantity": 2}], "takeWayCode": "eat-in"}
        with self.assertRaises(ValueError):
            actions.prepare(c, "create-order", changed, "Two meals", evidence)

    def test_compose_uses_actual_choices_and_no_double_count(self):
        record = {"tool": "query-meal-detail", "arguments": {"storeCode": "123", "beType": 1, "orderType": 1}, "result": response({"code": "MEAL", "name": "Meal", "rounds": [{"id": 1, "quantity": 1, "minQuantity": 1, "maxQuantity": 1, "choices": [{"code": "B", "name": "Burger", "isDefault": 1, "quantity": 1, "maxQuantity": -1}]}]})}
        path = state_dir() / "detail.json"
        private_write(path, record)
        spec = {"id": "A", "context": record["arguments"], "lines": [{"detail_record": str(path), "quantity": 2, "categories": {"B": "main"}}]}
        result = compose_candidate(spec, {"Burger": {"kcal": 300}})
        self.assertEqual(result["arguments"]["items"][0]["quantity"], 2)
        self.assertEqual(len(result["components"]), 1)
        self.assertEqual(nutrition(result["components"])["kcal"], 600)
        spec["lines"][0]["selections"] = {"1": [{"code": "INVENTED", "quantity": 1}]}
        with self.assertRaises(ValueError):
            compose_candidate(spec)

    def test_mall_cost_change_requires_new_confirmation(self):
        class MallClient(FakeClient):
            price = "0"
            def call(self, name, args):
                self.calls.append((name, args))
                if name == "mall-product-detail":
                    return response({"spuId": 10, "shopId": 2, "spuCategory": 1, "skuList": [{"skuId": 20, "points": "200", "price": self.price, "extTradePrice": "10.9"}]})
                if name == "query-my-account":
                    return response({"availablePoint": "250.5"})
                return response({"accepted": True})
        c = MallClient()
        args = {"skuId": 20, "spuCategory": "1"}
        evidence = {"tool": "mall-product-detail", "arguments": {"spuId": 10}, "result": response({})}
        draft = actions.prepare(c, "mall-create-order", args, "200 points, no upfront cash; review usage payment", evidence)
        self.assertEqual(draft["review"]["points_total"], "200")
        c.price = "5"
        with self.assertRaises(ValueError):
            actions.execute(c, draft["id"], draft["id"])
        self.assertFalse(any(name == "mall-create-order" for name, _ in c.calls))

    def test_mall_event_product_cannot_use_item_redemption(self):
        class EventOnlyClient(FakeClient):
            def call(self, name, args):
                self.calls.append((name, args))
                return response({"shopId": 5, "spuCategory": 1})
        c = EventOnlyClient()
        with self.assertRaises(ValueError):
            actions.prepare(c, "mall-create-order", {"skuId": 20, "spuCategory": "1"}, "Wrong product route", {"tool": "mall-product-detail", "arguments": {"spuId": 10}, "result": response({})})
        self.assertFalse(any(name == "mall-create-order" for name, _ in c.calls))

    def test_event_capacity_loss_prevents_booking(self):
        class EventClient(FakeClient):
            capacity = 5
            def call(self, name, args):
                self.calls.append((name, args))
                if name == "query-party-store-session":
                    return response([{"id": 30, "leftNum": self.capacity, "timeStart": "12:00", "timeEnd": "13:00", "price": 5000, "partyMin": 2, "partyMax": 10}])
                if name == "mall-product-detail":
                    return response({"shopId": 5, "partyType": 2, "skuList": [{"skuId": 20, "points": "0", "price": "50", "extTradePrice": "0"}]})
                return response({})
        c = EventClient()
        args = {"partyType": 2, "spuId": 10, "skuId": 20, "code": "100", "storeCode": "123", "dateStr": "2026-10-25", "id": 30, "leftNum": 5, "count": 4, "timeStart": "12:00", "timeEnd": "13:00"}
        evidence = {"tool": "query-party-store-session", "arguments": {"spuId": 10, "storeCode": "123", "dateStr": "2026-10-25"}, "result": response([])}
        draft = actions.prepare(c, "party-order-create", args, "Four participants in the selected shared session", evidence)
        c.capacity = 3
        with self.assertRaises(ValueError):
            actions.execute(c, draft["id"], draft["id"])
        self.assertFalse(any(name == "party-order-create" for name, _ in c.calls))


class DecisionsTest(unittest.TestCase):
    def setUp(self):
        self.plan = demo_plan()

    def test_cheapest_complete_meal_with_budget(self):
        result = compare(self.plan["candidates"], self.plan["request"])
        self.assertEqual(result["recommendations"]["cheaper"], "B")
        self.assertEqual(result["candidates"][1]["budget_remaining_cents"], 500)

    def test_missing_nutrition_does_not_become_zero(self):
        self.plan["candidates"][0]["components"][0]["nutrition"].pop("kcal")
        result = compare(self.plan["candidates"], self.plan["request"])
        self.assertFalse(result["candidates"][0]["eligible"])
        self.assertIsNone(result["candidates"][0]["nutrition"]["kcal"])

    def test_drinks_alone_cannot_satisfy_complete_meal(self):
        candidate = self.plan["candidates"][0]
        candidate["components"] = [candidate["components"][-1]]
        candidate["total_cents"] = 100
        result = compare([candidate], self.plan["request"])
        self.assertFalse(result["eligible_ids"])

    def test_required_item_is_not_removed_for_price(self):
        req = {**self.plan["request"], "required_products": {"DEMO-FISH": 1}}
        result = compare(self.plan["candidates"], req)
        self.assertEqual(result["eligible_ids"], ["C"])

    def test_minimum_budget_adjustment_uses_other_constraints(self):
        req = {**self.plan["request"], "budget_cents": 2000}
        result = compare(self.plan["candidates"], req)
        self.assertFalse(result["eligible_ids"])
        self.assertEqual(result["adjustments"][0]["extra_cents"], 500)

    def test_random_pick_always_eligible(self):
        req = {**self.plan["request"], "budget_cents": 2500}
        result = compare(self.plan["candidates"], req)
        self.assertEqual(random_pick(result)["id"], "B")

    def test_avoid_recent_selects_new_main(self):
        req = {**self.plan["request"], "max_kcal": 900}
        result = compare(self.plan["candidates"], req)
        self.assertEqual(random_pick(result, True)["id"], "C")

    def test_delta_reports_whole_meal_not_unit_price(self):
        result = delta(self.plan["candidates"][0], self.plan["candidates"][1])
        self.assertEqual(result["net_change_cents"], -100)
        self.assertEqual(result["removed"], {"Demo cola": 1})
        self.assertEqual(result["added"], {"Demo plain tea": 1})

    def test_reference_split_preserves_every_cent(self):
        self.assertEqual(split_bill(100, 3)["shares_cents"], [34, 33, 33])
        self.assertEqual(split_bill(101, 3, [2, 1, 1])["shares_cents"], [51, 25, 25])

    def test_no_fake_payable_total_from_list_price(self):
        self.assertEqual(quote_total({"data": {"price": 2600, "originalPrice": 3850}}), 2600)
        with self.assertRaises(ValueError):
            quote_total({"data": {"originalPrice": 3850}})


class TimeAccountingReportsTest(unittest.TestCase):
    def test_history_yuan_converted_once_and_combo_expanded(self):
        record = {"tool": "order-list", "result": response({"list": [{"orderId": "TEST", "createTime": "2026-10-20 12:00:00", "orderStatus": "订单已完成", "realTotalAmount": "30.7", "orderProductList": [{"productCode": "MEAL", "productName": "Meal", "quantity": 2, "comboItemList": [{"productCode": "BURGER", "name": "Burger", "quantity": 1}]}]}]})}
        orders, skipped = normalize_orders(record)
        self.assertFalse(skipped)
        self.assertEqual(orders[0]["paid_cents"], 3070)
        self.assertEqual(orders[0]["items"][0]["quantity"], 2)
        self.assertEqual(len(orders[0]["items"]), 1)

    def test_unknown_order_status_not_assumed_paid(self):
        orders, skipped = normalize_orders({"tool": "order-list", "result": response({"list": [{"orderStatus": "NEW-UNKNOWN-STATUS"}]})})
        self.assertFalse(orders)
        self.assertEqual(len(skipped), 1)

    def test_unresolved_weekday_encoding_not_scheduled(self):
        record = {"tool": "query-my-coupons", "result": response({"coupons": [{"title": "TEST", "tradeEndDateTime": "2026-10-30 23:59:59", "weekdays": [0], "isAllTradeTime": 1, "totalAvailableCount": 1}]})}
        assets = normalize_coupons(record)
        self.assertFalse(assets[0]["rules_known"])
        result = expiry_report(assets, [{"at": "2026-10-25T12:00:00+08:00"}], "2026-10-24T12:00:00+08:00")
        self.assertIsNone(result["assets"][0]["usable_now_by_time"])
        self.assertIsNone(result["schedule"][0]["coupon"])

    def test_coupon_delivery_channel_not_used_for_pickup(self):
        asset = {"name": "Delivery", "rules_known": True, "channels": ["delivery"], "expires_at": "2026-10-30T23:59:59+08:00"}
        report = expiry_report([asset], [{"at": "2026-10-25T12:00:00+08:00", "channel": "pickup"}], "2026-10-24T12:00:00+08:00")
        self.assertIsNone(report["schedule"][0]["coupon"])

    def test_coupon_respects_weekday_and_breakfast_window(self):
        coupon = {"expires_at": "2026-10-26T23:59:59+08:00", "weekdays": [1, 2, 3, 4, 5], "windows": [["05:00", "10:29"]]}
        self.assertFalse(window_allows(coupon, "2026-10-24T09:00:00+08:00"))
        self.assertTrue(window_allows(coupon, "2026-10-26T09:00:00+08:00"))
        self.assertFalse(window_allows(coupon, "2026-10-26T12:00:00+08:00"))

    def test_unknown_expiry_is_not_infinite_and_not_scheduled(self):
        report = expiry_report([{"name": "Unknown-date coupon", "rules_known": True}], [{"at": "2026-10-25T12:00:00+08:00"}], "2026-10-24T12:00:00+08:00")
        self.assertEqual(report["assets"][0]["status"], "date unknown")
        self.assertIsNone(report["schedule"][0]["coupon"])

    def test_coupon_is_not_scheduled_more_than_quantity(self):
        coupon = {"name": "One coupon", "expires_at": "2026-10-26T23:59:59+08:00", "rules_known": True}
        report = expiry_report([coupon], [{"at": "2026-10-25T12:00:00+08:00"}, {"at": "2026-10-26T12:00:00+08:00"}], "2026-10-24T12:00:00+08:00")
        self.assertEqual([x["coupon"] for x in report["schedule"]], ["One coupon", None])

    def test_pending_cancelled_and_fully_refunded_not_spending(self):
        orders = [{"id": str(i), "ordered_at": "2026-10-20T12:00:00+08:00", "status": status, "paid_cents": amount, "source": "demo", "items": []} for i, (status, amount) in enumerate([("paid", 2600), ("pending", 3000), ("cancelled", 2000), ("fully_refunded", 2600), ("paid", 0)])]
        report = spending_report(orders)
        self.assertEqual(report["total_paid_cents"], 2600)
        self.assertEqual(report["counted_paid_orders"], 2)
        self.assertEqual(report["positive_spend_average_cents"], 2600)

    def test_nutrition_table_exact_match_and_duplicate(self):
        raw = "[2]{productName,energyKcal,protein,sodium,calcium}:\n  Tea,0,0,0,0\n  Tea,0,0,0,0"
        self.assertEqual(nutrition_table(raw)["Tea"]["kcal"], 0)
        with self.assertRaises(ValueError):
            nutrition_table(raw.replace("Tea,0,0,0,0", "Tea,2,0,0,0", 1))

    def test_share_report_removes_raw_identifiers_and_escapes_html(self):
        plan = demo_plan()
        plan["candidates"][0]["label"] = '<img src=x onerror="alert(1)">'
        plan["candidates"][0]["arguments"] = {"phone": "private-phone", "couponCode": "private-code"}
        report = compare(plan["candidates"], plan["request"])
        raw = render_html(report)
        self.assertNotIn("private-phone", raw)
        self.assertNotIn("private-code", raw)
        self.assertNotIn('<img src=x', raw)
        self.assertIn("&lt;img", raw)
        self.assertIn("default-src 'none'", raw)

    def test_csv_neutralizes_formula_cells(self):
        plan = demo_plan()
        plan["candidates"][0]["label"] = "=1+1"
        self.assertIn("'=1+1", render_csv(compare(plan["candidates"], plan["request"])))

    def test_invitation_does_not_claim_reservation(self):
        text = invitation({"title": "Lunch", "store_name": "Test", "date": "2026-10-25", "time": "12:00", "people": 4})
        self.assertIn("does not create or confirm", text)


class ProtocolTests(unittest.TestCase):
    def test_sse_selects_matching_response_and_handles_crlf(self):
        raw = 'event: message\r\ndata: {"jsonrpc":"2.0","method":"progress"}\r\n\r\nevent: message\r\ndata: {"jsonrpc":"2.0","id":2,"result":{"ok":true}}\r\n\r\n'
        self.assertTrue(decode_message(raw, 2)["result"]["ok"])
        with self.assertRaises(MCPError):
            decode_message(raw, 3)

    def test_nested_schema_rejects_stringified_array(self):
        schema = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {"type": "object", "required": ["quantity"], "properties": {"quantity": {"type": "integer"}}}}}}
        validate({"items": [{"quantity": 1}]}, schema)
        with self.assertRaises(ValueError):
            validate({"items": "[{\"quantity\":1}]"}, schema)
        with self.assertRaises(ValueError):
            validate({"items": [{"quantity": True}]}, schema)

    def test_business_failure_not_successful_transport(self):
        with self.assertRaises(MCPError):
            assert_success({"isError": True, "content": []})
        with self.assertRaises(MCPError):
            assert_success({"content": [{"type": "text", "text": '{"success":false,"code":500}'}]})

    def test_mode_mapping_rejects_mixed_context(self):
        with self.assertRaises(ValueError):
            actions.context_check("query-meals", {"beType": 2, "orderType": 1})
        with self.assertRaises(ValueError):
            actions.context_check("query-meals", {"beType": 5, "orderType": 1})
        actions.context_check("query-meals", {"beType": 5, "orderType": 1, "beCode": "TEST"})

    def test_portable_demo_runs_without_credentials(self):
        proc = subprocess.run([sys.executable, str(PROJECT / "scripts/mcd.py"), "demo"], text=True, capture_output=True, env={**os.environ, "MCD_MCP_TOKEN": ""})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("SYNTHETIC DEMO", json.loads(proc.stdout)["scope"])


if __name__ == "__main__":
    unittest.main()
