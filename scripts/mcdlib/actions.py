"""Two-step, short-lived, single-attempt mutation drafts."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import os
import secrets
from decimal import Decimal
from .catalog import WRITE_TOOLS, validate
from .client import assert_success
from .planner import fingerprint, quote_total
from .storage import state_dir, private_write, read_json

TTL_SECONDS = 300


def context_check(tool, args):
    if tool not in {"calculate-price", "create-order", "query-meals", "query-meal-detail", "query-store-coupons", "query-promotions", "query-meal-assistance"}:
        return
    if "storeCode" in args and (not isinstance(args["storeCode"], str) or not args["storeCode"].isdigit()):
        raise ValueError("storeCode must be the actual numeric string returned by the store query")
    mode = args.get("beType")
    if mode is not None:
        expected = {1: 1, 5: 1, 2: 2, 6: 2}.get(mode)
        if expected is None or args.get("orderType") != expected:
            raise ValueError("beType and orderType do not match")
        if mode == 1 and args.get("beCode"):
            raise ValueError("Pickup must omit beCode")
        if mode in (2, 5, 6) and not args.get("beCode"):
            raise ValueError("This mode requires the store's matching beCode")
    if tool in {"calculate-price", "create-order"}:
        if not args.get("items"):
            raise ValueError("A nonempty items list is required")
        for item in args["items"]:
            if not item.get("productCode") or isinstance(item.get("quantity"), bool) or not isinstance(item.get("quantity"), int) or item["quantity"] < 1:
                raise ValueError("Every item requires productCode and a positive integer quantity")
    if tool == "create-order":
        if args["orderType"] == 2 and not args.get("addressId"):
            raise ValueError("Delivery orders require a confirmed addressId")
        if args["orderType"] == 1 and not args.get("takeWayCode"):
            raise ValueError("Pickup orders require a takeWayCode from the quote")
        if mode == 6 and not args.get("gmServiceCode"):
            raise ValueError("Group orders require the selected assistance service code")


def lottery_decision(client):
    result = client.call("query-lottery-info", {})
    body = assert_success(result)
    data = body.get("data", body)
    decision = data.get("drawDecision", {})
    if decision.get("resourceEligible") is not True:
        raise ValueError("The server reports no eligible resources for a draw")
    if not decision.get("nextConsumption"):
        raise ValueError("The server did not return the next draw's actual consumption")
    return {"activityCode": data.get("activityCode"), "nextConsumption": decision["nextConsumption"], "fallbackConsumption": decision.get("fallbackConsumption")}


def quote_evidence(client, args, evidence):
    if not evidence or "quote" not in evidence:
        raise ValueError("Creating a food order requires the saved official quote candidate as evidence")
    quote = evidence["quote"]
    stamp = datetime.fromisoformat(quote["quoted_at"])
    age = (datetime.now(timezone.utc) - stamp).total_seconds()
    if age < 0 or age > TTL_SECONDS or quote.get("source") != "official-mcp":
        raise ValueError("Quote expired or is not official; quote again and review the new total")
    properties = client.tools()["calculate-price"]["inputSchema"].get("properties", {})
    quote_args = {k: v for k, v in args.items() if k in properties}
    if fingerprint(quote_args) != quote.get("arguments_sha256") or quote_args != evidence.get("arguments"):
        raise ValueError("Order differs from the reviewed quote; quote the changed basket again")
    body = assert_success(quote["result"])
    total = quote_total(body)
    if total != evidence["total_cents"]:
        raise ValueError("Quote total mismatch")
    if args["orderType"] == 1:
        choices = body.get("data", {}).get("takeWayList", [])
        if not any(str(x.get("code")) == str(args["takeWayCode"]) for x in choices):
            raise ValueError("Selected takeWayCode is absent from the quote")
    return {"quote_arguments": quote_args, "total_cents": total, "quoted_at": quote["quoted_at"]}


def mall_review(client, arguments, evidence):
    from .records import time_value
    if not evidence or evidence.get("tool") != "mall-product-detail":
        raise ValueError("Attach a saved mall-product-detail record")
    detail_args = evidence["arguments"]
    data = assert_success(client.call("mall-product-detail", detail_args)).get("data", {})
    if data.get("shopId") != 2 or str(data.get("spuCategory")) != arguments["spuCategory"]:
        raise ValueError("This redemption requires a shopId=2 product of the selected category")
    now = datetime.now(timezone.utc)
    if data.get("downDate") and time_value(data["downDate"]) < now:
        raise ValueError("This product's redemption period has ended")
    if data.get("upDate") and time_value(data["upDate"]) > now:
        raise ValueError("This product's redemption period has not started")
    sku = next((s for s in data.get("skuList", []) if s.get("skuId") == arguments["skuId"]), None)
    if sku is None:
        raise ValueError("SKU is not present in the actual product detail")
    count = arguments.get("count", 1)
    cost = Decimal(str(sku["points"])) * count
    if not cost.is_finite() or cost < 0:
        raise ValueError("Invalid structured point cost")
    balance = assert_success(client.call("query-my-account", {})).get("data", {})
    if cost > Decimal(str(balance["availablePoint"])):
        raise ValueError("Insufficient available points")
    return {"detail_arguments": detail_args, "spuId": data["spuId"], "skuId": sku["skuId"], "count": count, "points_total": str(cost), "price_yuan_per_item": str(sku["price"]), "extTradePrice_yuan_per_item": str(sku.get("extTradePrice", "unknown")), "note": "Display both structured cash fields and the actual purchase notice; extTradePrice may be payable when using the redeemed coupon"}


def event_review(client, arguments, evidence):
    if not evidence or evidence.get("tool") != "query-party-store-session":
        raise ValueError("Attach a saved query-party-store-session record")
    session_args = evidence["arguments"]
    if any(session_args.get(k) != arguments.get(k) for k in ("spuId", "storeCode", "dateStr")):
        raise ValueError("Event order does not match the reviewed store/date/product")
    body = assert_success(client.call("query-party-store-session", session_args))
    data = body.get("data", [])
    sessions = data if isinstance(data, list) else data.get("sessions", data.get("list", []))
    selected = next((s for s in sessions if str(s.get("id")) == str(arguments["id"])), None)
    if selected is None:
        raise ValueError("Session is absent from the fresh response; inspect its current shape or select another session")
    if "leftNum" not in selected or arguments["count"] > selected["leftNum"]:
        raise ValueError("The selected session does not have enough confirmed remaining spaces")
    if arguments["count"] < selected.get("partyMin", 1) or arguments["count"] > selected.get("partyMax", selected["leftNum"]):
        raise ValueError("Headcount is outside this session's actual minimum/maximum")
    if "price" not in selected:
        raise ValueError("The session did not return its price; inspect its current contract before booking")
    for key in ("timeStart", "timeEnd"):
        if selected.get(key) != arguments[key]:
            raise ValueError("The session time changed; review again")
    detail = assert_success(client.call("mall-product-detail", {"spuId": arguments["spuId"]})).get("data", {})
    if detail.get("shopId") != 5:
        raise ValueError("Event booking requires shopId=5")
    if detail.get("partyType") in (1, 2) and detail["partyType"] != arguments["partyType"]:
        raise ValueError("This event does not support the selected booking type")
    if not any(s.get("skuId") == arguments["skuId"] for s in detail.get("skuList", [])):
        raise ValueError("Event SKU is not present in the current detail")
    sku = next(s for s in detail["skuList"] if s["skuId"] == arguments["skuId"])
    return {"session_arguments": session_args, "id": arguments["id"], "timeStart": selected["timeStart"], "timeEnd": selected["timeEnd"], "session_price_cents": selected["price"], "sku_fields": sku, "partyType": arguments["partyType"], "count": arguments["count"], "note": "Actual event notice determines how booking type and participant count affect the total; show it before confirmation"}


def prepare(client, tool, arguments, summary, evidence=None):
    if tool not in WRITE_TOOLS:
        raise ValueError("prepare is only for the seven known write tools")
    if not summary.strip():
        raise ValueError("Provide a human-readable summary of the exact action")
    validate(arguments, client.tools()[tool]["inputSchema"])
    context_check(tool, arguments)
    review = {}
    if tool == "create-order":
        review = quote_evidence(client, arguments, evidence)
    elif tool == "draw-lottery":
        review = lottery_decision(client)
    elif tool == "mall-create-order":
        if arguments.get("spuCategory") not in ("1", "2") or arguments.get("count", 1) < 1:
            raise ValueError("Select a valid item type and positive redemption quantity")
        if arguments.get("spuCategory") == "2" and not arguments.get("addressId"):
            raise ValueError("Physical goods need a confirmed delivery address")
        if not evidence or evidence.get("tool") != "mall-product-detail":
            raise ValueError("Attach the saved mall-product-detail record; review SKU, shopId=2, stock, points and extra cash")
        assert_success(evidence["result"])
        review = mall_review(client, arguments, evidence)
    elif tool == "party-order-create":
        required = ("spuId", "skuId", "code", "storeCode", "dateStr", "id", "timeStart", "timeEnd", "leftNum", "count")
        if any(arguments.get(k) is None for k in required) or arguments.get("partyType") not in (1, 2) or arguments["count"] < 1 or arguments["count"] > arguments["leftNum"]:
            raise ValueError("Select an actual event, city, store, date, session, booking type and valid headcount")
        if not evidence or evidence.get("tool") != "query-party-store-session":
            raise ValueError("Attach the saved session record and review the exact session and costs")
        assert_success(evidence["result"])
        review = event_review(client, arguments, evidence)
    draft_id = secrets.token_hex(8)
    now = datetime.now(timezone.utc)
    draft = {"id": draft_id, "tool": tool, "arguments": arguments, "summary": summary, "review": review, "created_at": now.isoformat(), "expires_at": (now + timedelta(seconds=TTL_SECONDS)).isoformat(), "status": "awaiting-confirmation"}
    draft["digest"] = fingerprint({k: draft[k] for k in ("id", "tool", "arguments", "summary", "review", "created_at", "expires_at")})
    private_write(state_dir() / "drafts" / f"{draft_id}.json", draft)
    return draft


def execute(client, draft_id, confirmation):
    if not draft_id.isalnum() or len(draft_id) != 16:
        raise ValueError("Invalid draft identifier")
    if confirmation != draft_id:
        raise ValueError("Confirmation must match the exact reviewed draft ID")
    path = state_dir() / "drafts" / f"{draft_id}.json"
    draft = read_json(path)
    if draft.get("tool") not in WRITE_TOOLS:
        raise ValueError("Unknown write tool")
    expected = fingerprint({k: draft[k] for k in ("id", "tool", "arguments", "summary", "review", "created_at", "expires_at")})
    if draft.get("digest") != expected or draft["id"] != draft_id:
        raise ValueError("Draft was changed; prepare and review it again")
    if draft["status"] != "awaiting-confirmation" or datetime.now(timezone.utc) > datetime.fromisoformat(draft["expires_at"]):
        raise ValueError("Draft expired or has already been attempted; do not repeat an uncertain transaction")
    lock = path.with_suffix(".attempt")
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    except FileExistsError:
        raise ValueError("This draft has already been attempted; query the actual order before taking another action") from None
    # Mark the draft before any network operation; timeouts must not allow replay.
    draft["status"] = "attempted"
    private_write(path, draft)
    try:
        context_check(draft["tool"], draft["arguments"])
        if draft["tool"] == "create-order":
            review = draft["review"]
            result = client.call("calculate-price", review["quote_arguments"])
            if quote_total(assert_success(result)) != review["total_cents"]:
                raise ValueError("Price changed; prepare a fresh quote and obtain new confirmation")
        elif draft["tool"] == "draw-lottery":
            if lottery_decision(client) != draft["review"]:
                raise ValueError("Draw consumption changed; show the new consumption and obtain confirmation again")
        elif draft["tool"] == "mall-create-order":
            if mall_review(client, draft["arguments"], {"tool": "mall-product-detail", "arguments": draft["review"]["detail_arguments"]}) != draft["review"]:
                raise ValueError("Redemption terms changed; review and confirm a new draft")
        elif draft["tool"] == "party-order-create":
            if event_review(client, draft["arguments"], {"tool": "query-party-store-session", "arguments": draft["review"]["session_arguments"]}) != draft["review"]:
                raise ValueError("Event terms changed; review and confirm a new draft")
        result = client.call(draft["tool"], draft["arguments"])
        draft["result"] = result
        draft["status"] = "response-received"
        private_write(path, draft)
        assert_success(result)
        return result
    except Exception:
        # Keep the single-attempt marker, including when the remote outcome is unknown.
        draft["status"] = "stopped-check-outcome"
        private_write(path, draft)
        raise
