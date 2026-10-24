"""Local records, actual-use windows, and conservative spending summaries."""
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from .storage import state_dir, private_write, read_json
from .planner import cents

SHANGHAI = ZoneInfo("Asia/Shanghai")


def time_value(value):
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return result.replace(tzinfo=SHANGHAI) if result.tzinfo is None else result.astimezone(SHANGHAI)


def window_allows(asset, dt):
    """Respect explicit time-of-day/weekday rules; unknown rules stay unknown."""
    dt = time_value(dt)
    start, end = asset.get("starts_at"), asset.get("expires_at")
    if start and dt < time_value(start):
        return False
    if end and dt > time_value(end):
        return False
    if asset.get("weekdays") is not None and dt.isoweekday() not in asset["weekdays"]:
        return False
    if asset.get("windows"):
        minute = dt.hour * 60 + dt.minute
        def hm(value):
            h, m = map(int, value.split(":"))
            if not 0 <= h <= 23 or not 0 <= m <= 59:
                raise ValueError("Invalid time-of-day window")
            return h * 60 + m
        allowed = False
        for begin, finish in asset["windows"]:
            a, b = hm(begin), hm(finish)
            allowed |= (a <= minute <= b) if a <= b else (minute >= a or minute <= b)
        if not allowed:
            return False
    return True


def expiry_report(assets, planned_meals=(), now=None):
    now = time_value(now or datetime.now(SHANGHAI))
    rows = []
    for index, asset in enumerate(assets):
        expiry = time_value(asset["expires_at"]) if asset.get("expires_at") else None
        status = "expired" if expiry and expiry < now else "not started" if asset.get("starts_at") and time_value(asset["starts_at"]) > now else "date unknown" if expiry is None else "active"
        rows.append({"index": index, "name": asset["name"], "kind": asset.get("kind", "coupon"), "amount": asset.get("amount"), "expires_at": expiry.isoformat() if expiry else None, "status": status, "usable_now_by_time": window_allows(asset, now) if asset.get("rules_known") else None, "store_eligibility": asset.get("store_eligibility", "not checked"), "rules_known": asset.get("rules_known", False)})
    rows.sort(key=lambda x: (x["status"] == "expired", x["expires_at"] is None, x["expires_at"] or "", x["name"]))
    remaining = {i: asset.get("quantity", 1) for i, asset in enumerate(assets)}
    if any(isinstance(n, bool) or not isinstance(n, int) or n < 0 for n in remaining.values()):
        raise ValueError("Asset quantities must be nonnegative integers")
    schedule = []
    for meal in sorted(planned_meals, key=lambda m: time_value(m["at"])):
        at = time_value(meal["at"])
        if at < now:
            continue
        chosen = None
        for row in rows:
            asset = assets[row["index"]]
            if asset.get("kind", "coupon") != "coupon" or not asset.get("expires_at") or not asset.get("rules_known"):
                continue
            if remaining[row["index"]] < 1 or not window_allows(asset, at):
                continue
            if asset.get("channel") not in (None, "any", meal.get("channel")):
                continue
            if asset.get("channels") and meal.get("channel") not in asset["channels"]:
                continue
            if asset.get("store_eligibility") == "unavailable":
                continue
            chosen = row
            remaining[row["index"]] -= 1
            break
        schedule.append({"at": at.isoformat(), "coupon": chosen["name"] if chosen else None, "status": "time-window suggestion; verify at the chosen store" if chosen else "no known eligible coupon scheduled"})
    return {"as_of": now.isoformat(), "assets": rows, "schedule": schedule, "method": "Earliest known expiry first; one coupon per user-provided meal opportunity. No background reminder, no assumption about coupon stacking or future price."}


def save_order(order):
    required = {"id", "ordered_at", "status", "paid_cents", "source", "items"}
    if not required <= set(order):
        raise ValueError("Order needs id, ordered_at, status, paid_cents, source and items")
    if order["source"] not in ("official-mcp", "manual", "demo"):
        raise ValueError("Order source must be official-mcp, manual or demo")
    if order["status"] not in ("paid", "completed", "pending", "cancelled", "fully_refunded", "partially_refunded"):
        raise ValueError("Unknown order status; map the actual server status explicitly")
    cents(order["paid_cents"])
    time_value(order["ordered_at"])
    path = state_dir() / "orders.json"
    orders = read_json(path) if path.exists() else []
    # Updating an existing order never double counts it.
    orders = [o for o in orders if o["id"] != order["id"]]
    orders.append(order)
    private_write(path, orders)
    return {"stored_orders": len(orders), "source": order["source"]}


def spending_report(orders, start=None, end=None):
    selected = [o for o in orders if (not start or time_value(o["ordered_at"]) >= time_value(start)) and (not end or time_value(o["ordered_at"]) <= time_value(end))]
    days = {}
    items = {}
    warnings = []
    total = 0
    counted = 0
    positive = []
    for order in selected:
        if order["status"] not in ("paid", "completed", "partially_refunded"):
            continue
        amount = cents(order["paid_cents"])
        total += amount
        counted += 1
        if amount > 0:
            positive.append(amount)
        day = time_value(order["ordered_at"]).date().isoformat()
        days[day] = days.get(day, 0) + amount
        if order["status"] == "partially_refunded":
            warnings.append("Partial refund present; use actual net-paid amount if known, otherwise spending may be overstated")
        for item in order.get("items", []):
            name = item["name"]
            items[name] = items.get(name, 0) + item["quantity"]
    dates = sorted(o["ordered_at"] for o in selected)
    return {"scope": "Recorded orders only; not necessarily a complete month or year", "record_count": len(selected), "counted_paid_orders": counted, "total_paid_cents": total, "positive_spend_average_cents": round(sum(positive) / len(positive)) if positive else None, "coverage_from": dates[0] if dates else None, "coverage_to": dates[-1] if dates else None, "daily_spend_cents": dict(sorted(days.items())), "frequent_items": sorted(items.items(), key=lambda x: (-x[1], x[0])), "sources": sorted({o["source"] for o in selected}), "warnings": sorted(set(warnings))}


def nutrition_table(raw):
    """Parse the observed CSV-like nutrition table with explicit name matching."""
    import csv
    import io
    import re
    if not isinstance(raw, str):
        raise ValueError("Expected the official nutrition text table")
    lines = raw.splitlines()
    if not lines or not re.fullmatch(r"\[\d+\]\{[^}]+\}:", lines[0]):
        raise ValueError("Nutrition table shape changed; inspect the current response")
    columns = lines[0].split("{", 1)[1].split("}", 1)[0].split(",")
    data = {}
    for row in csv.reader(io.StringIO("\n".join(line.strip() for line in lines[1:]))):
        if not row:
            continue
        if len(row) != len(columns):
            raise ValueError("Nutrition row/column mismatch")
        obj = dict(zip(columns, row))
        nutrients = {}
        for external, local in (("energyKcal", "kcal"), ("protein", "protein_g"), ("sodium", "sodium_mg"), ("calcium", "calcium_mg")):
            nutrients[local] = None if obj[external] in ("null", "") else float(Decimal(obj[external]))
        name = obj["productName"]
        if name in data and data[name] != nutrients:
            raise ValueError(f"Conflicting nutrition records for {name}; do not silently choose one")
        data[name] = nutrients
    return data


def normalize_orders(record):
    """Normalize the observed history contract, keeping unknown statuses explicit."""
    from .client import assert_success
    if record.get("tool") != "order-list":
        raise ValueError("Expected an actual order-list response record")
    data = assert_success(record["result"])["data"]
    rows = data.get("list", []) if isinstance(data, dict) else data
    status_map = {"订单已完成": "completed", "已完成": "completed", "已支付": "paid", "待支付": "pending", "待付款": "pending", "已取消": "cancelled", "订单已取消": "cancelled", "已全额退款": "fully_refunded", "部分退款": "partially_refunded"}
    orders, skipped = [], []
    for row in rows:
        status = status_map.get(row.get("orderStatus"))
        if status is None:
            skipped.append({"reason": "Unrecognized orderStatus; inspect the actual response before mapping", "status": row.get("orderStatus")})
            continue
        yuan = Decimal(str(row["realTotalAmount"])) * 100
        if yuan != yuan.to_integral_value() or not yuan.is_finite() or yuan < 0:
            raise ValueError("History amount is not a valid yuan amount")
        items = []
        for item in row.get("orderProductList", []):
            if item.get("comboItemList"):
                items.extend({"name": child["name"], "product_code": child["productCode"], "quantity": item["quantity"] * child["quantity"]} for child in item["comboItemList"])
            else:
                items.append({"name": item["productName"], "product_code": item["productCode"], "quantity": item["quantity"]})
        orders.append({"id": row["orderId"], "ordered_at": time_value(row["createTime"]).isoformat(), "status": status, "paid_cents": int(yuan), "source": "official-mcp", "items": items})
    return orders, skipped


def normalize_coupons(record):
    """Read structured validity fields; leave unfamiliar weekday rules unscheduled."""
    from .client import assert_success
    if record.get("tool") != "query-my-coupons":
        raise ValueError("Expected a query-my-coupons response record")
    data = assert_success(record["result"])["data"]
    assets = []
    for row in data.get("coupons", []):
        periods = row.get("tradeTimePeriods", [])
        known = row.get("isAllTradeTime") == 1 or bool(periods)
        windows = []
        for period in periods:
            if not period.get("startTime") or not period.get("endTime"):
                known = False
                continue
            windows.append([period["startTime"][:5], period["endTime"][:5]])
        # The service's weekday encoding is not specified in the observed schema.
        # Do not assume numbering; preserve it as an unresolved restriction.
        if row.get("weekdays"):
            known = False
        modes = {1: "pickup", 2: "delivery", 5: "drive-through", 6: "group"}
        assets.append({"name": row["title"], "kind": "coupon", "starts_at": row.get("tradeStartDateTime"), "expires_at": row.get("tradeEndDateTime"), "quantity": max(0, row.get("totalAvailableCount", 0)), "windows": windows, "rules_known": known, "store_eligibility": "not checked", "unresolved_weekdays": row.get("weekdays", []), "channels": [modes[n] for n in row.get("beTypes", []) if n in modes]})
    return assets
