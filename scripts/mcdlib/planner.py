"""Deterministic comparisons over complete, explicitly quoted baskets."""
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
import secrets
from datetime import datetime, timezone

NUTRIENTS = ("kcal", "protein_g", "sodium_mg", "calcium_mg")


def cents(value):
    if isinstance(value, bool):
        raise ValueError("An amount cannot be boolean")
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid amount") from None
    if not d.is_finite() or d < 0 or d != d.to_integral_value():
        raise ValueError("Amounts must be nonnegative integer cents")
    return int(d)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def nutrition(components):
    totals = {}
    for key in NUTRIENTS:
        values = []
        for item in components:
            v = item.get("nutrition", {}).get(key)
            if v is None:
                values = None
                break
            d = Decimal(str(v))
            if not d.is_finite() or d < 0:
                raise ValueError("Nutrient values must be finite and nonnegative")
            values.append(d * item["quantity"])
        totals[key] = float(sum(values)) if values else None
    return totals


def evaluate(candidate, request):
    c = dict(candidate)
    c["total_cents"] = cents(c["total_cents"])
    components = c.get("components", [])
    if not components:
        raise ValueError("A candidate must list its actual edible components")
    for item in components:
        if not item.get("name") or isinstance(item.get("quantity"), bool) or not isinstance(item.get("quantity"), int) or item["quantity"] < 1:
            raise ValueError("Each component needs a name and positive integer quantity")
    c["nutrition"] = nutrition(components)
    counts = Counter()
    for item in components:
        counts[item.get("category", "unknown")] += item["quantity"]
    reasons = []
    for category, amount in request.get("required_categories", {}).items():
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ValueError("Required component counts must be nonnegative integers")
        if counts[category] < amount:
            reasons.append(f"missing {amount - counts[category]} {category}")
    names = " ".join(x["name"].casefold() for x in components)
    for term in request.get("excluded_terms", []):
        if term.casefold() in names:
            reasons.append(f"contains excluded item: {term}")
    quantities = Counter()
    for item in components:
        quantities[item.get("product_code", item["name"])] += item["quantity"]
    for code, amount in request.get("required_products", {}).items():
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ValueError("Required product counts must be nonnegative integers")
        if quantities[code] < amount:
            reasons.append(f"missing required product: {code}")
    budget = request.get("budget_cents")
    c["budget_remaining_cents"] = None if budget is None else cents(budget) - c["total_cents"]
    if c["budget_remaining_cents"] is not None and c["budget_remaining_cents"] < 0:
        reasons.append("over budget")
    for constraint, nutrient, is_minimum in (("max_kcal", "kcal", False), ("max_sodium_mg", "sodium_mg", False), ("min_protein_g", "protein_g", True), ("min_calcium_mg", "calcium_mg", True)):
        if constraint in request:
            v = c["nutrition"][nutrient]
            target = request[constraint]
            if not isinstance(target, (int, float)) or isinstance(target, bool) or not Decimal(str(target)).is_finite() or target < 0:
                raise ValueError(f"Invalid nutrition target: {constraint}")
            if v is None:
                reasons.append(f"{nutrient} unknown")
            elif (v < target if is_minimum else v > target):
                reasons.append(f"violates {constraint}")
    c["reasons"] = reasons
    c["eligible"] = not reasons
    c["preference_score"] = sum(item["quantity"] for item in components if any(t.casefold() in item["name"].casefold() for t in request.get("likes", [])))
    c["recent_matches"] = sum(item["quantity"] for item in components if item["name"] in request.get("recent_items", []))
    return c


def compare(candidates, request):
    if not candidates:
        raise ValueError("No successfully quoted candidates supplied")
    seen = set()
    evaluated = []
    for c in candidates:
        if c["id"] in seen:
            raise ValueError("Candidate IDs must be unique")
        seen.add(c["id"])
        evaluated.append(evaluate(c, request))
    eligible = sorted((c for c in evaluated if c["eligible"]), key=lambda c: (c["total_cents"], c["id"]))
    picks = {}
    if eligible:
        picks["cheaper"] = eligible[0]["id"]
        picks["familiar"] = min(eligible, key=lambda c: (-c["preference_score"], c["total_cents"]))["id"]
        # Only display nutrient-aware choices when that nutrient is actually known.
        metric = "sodium_mg" if "max_sodium_mg" in request else "kcal"
        direction = 1
        if "min_protein_g" in request:
            metric, direction = "protein_g", -1
        known = [c for c in eligible if c["nutrition"].get(metric) is not None]
        if known:
            picks["nutrition"] = min(known, key=lambda c: (direction * c["nutrition"][metric], c["total_cents"]))["id"]
        picks["try_something_else"] = min(eligible, key=lambda c: (c["recent_matches"], c["total_cents"]))["id"]
    adjustments = []
    if not eligible:
        budget_only = [c for c in evaluated if c["reasons"] == ["over budget"]]
        if budget_only:
            cheapest = min(budget_only, key=lambda c: c["total_cents"])
            adjustments.append({"kind": "budget", "candidate_id": cheapest["id"], "extra_cents": -cheapest["budget_remaining_cents"], "message": "This complete quoted meal meets the other requirements. Ask whether to increase the budget or quote a changed meal."})
        else:
            adjustments.append({"kind": "constraints", "candidates": [{"id": c["id"], "reasons": c["reasons"]} for c in sorted(evaluated, key=lambda c: (len(c["reasons"]), c["total_cents"]))[:3]], "message": "Ask which requirement may change, or resolve missing nutrition data; do not silently relax it."})
    return {"scope": "Compared candidates only; not a global optimum", "request": request, "candidates": evaluated, "eligible_ids": [c["id"] for c in eligible], "recommendations": picks, "adjustments": adjustments}


def random_pick(report, avoid_recent=False):
    available = [c for c in report["candidates"] if c["eligible"]]
    if not available:
        raise ValueError("No eligible candidates to choose from")
    if avoid_recent:
        minimum = min(c["recent_matches"] for c in available)
        available = [c for c in available if c["recent_matches"] == minimum]
    return secrets.choice(available)


def delta(before, after):
    def basket(c):
        result = Counter()
        for item in c["components"]:
            result[item["name"]] += item["quantity"]
        return result
    old, new = basket(before), basket(after)
    return {"before_cents": cents(before["total_cents"]), "after_cents": cents(after["total_cents"]), "net_change_cents": cents(after["total_cents"]) - cents(before["total_cents"]), "added": dict(new - old), "removed": dict(old - new), "unchanged": dict(old & new), "note": "Whole-basket difference, not a standalone price for the changed item"}


def split_bill(total, people, weights=None):
    total = cents(total)
    if not isinstance(people, int) or isinstance(people, bool) or people < 1:
        raise ValueError("People must be a positive integer")
    weights = [Decimal(str(x)) for x in (weights if weights is not None else [1] * people)]
    if len(weights) != people or any(not w.is_finite() or w < 0 for w in weights) or sum(weights) <= 0:
        raise ValueError("Weights must match the group and have a positive sum")
    exact = [Decimal(total) * w / sum(weights) for w in weights]
    amounts = [int(x) for x in exact]
    remainder = total - sum(amounts)
    for i in sorted(range(people), key=lambda i: (-(exact[i] - amounts[i]), i))[:remainder]:
        amounts[i] += 1
    return {"total_cents": total, "shares_cents": amounts, "note": "Reference allocation only; no payment or transfer is made"}


def quote_total(body):
    """The official calculate-price contract returns cent-denominated totals."""
    data = body.get("data", body)
    if not isinstance(data, dict):
        raise ValueError("Quote response has no structured data object")
    # Observed official response: data.price is payable, in cents.
    # originalPrice/productPrice are not substitutes for the payable total.
    if data.get("price") is not None:
        return cents(data["price"])
    raise ValueError("No recognized payable-total field; inspect response rather than guessing")


def quote_candidate(client, candidate):
    from .client import assert_success
    from .storage import private_write, state_dir
    import uuid
    args = candidate["arguments"]
    if not args.get("items"):
        raise ValueError("A quote needs a nonempty items array")
    result = client.call("calculate-price", args)
    private_write(state_dir() / "quote-attempts" / f"{uuid.uuid4().hex}.json", {"tool": "calculate-price", "arguments": args, "result": result, "recorded_at": datetime.now(timezone.utc).isoformat()})
    body = assert_success(result)
    return {**candidate, "total_cents": quote_total(body), "quote": {"source": "official-mcp", "tool": "calculate-price", "quoted_at": datetime.now(timezone.utc).isoformat(), "arguments_sha256": fingerprint(args), "result": result}}


def compose_candidate(spec, table=None):
    """Build roundList and edible components from saved official detail records."""
    from .client import assert_success
    from .storage import read_json
    table = table or {}
    items, components = [], []
    for line in spec["lines"]:
        record = read_json(line["detail_record"])
        if record.get("tool") != "query-meal-detail":
            raise ValueError("Compose needs actual query-meal-detail records")
        context = {k: spec["context"].get(k) for k in ("storeCode", "beType", "orderType", "beCode", "reservationDate")}
        if context != {k: record["arguments"].get(k) for k in context}:
            raise ValueError("Detail and plan store/mode/reservation must match")
        detail = assert_success(record["result"])["data"]
        quantity = line.get("quantity", 1)
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
            raise ValueError("Meal quantity must be a positive integer")
        item = {"productCode": detail["code"], "quantity": quantity}
        rounds = []
        for group in detail.get("rounds", []):
            chosen = line.get("selections", {}).get(str(group["id"]))
            if chosen is None:
                chosen = [{"code": c["code"], "quantity": c.get("quantity", 1)} for c in group["choices"] if c.get("isDefault") == 1 and c.get("quantity", 1) > 0]
            choices = {c["code"]: c for c in group["choices"]}
            units = sum(c["quantity"] for c in chosen)
            if units < group.get("minQuantity", group.get("quantity", 1)) or units > group.get("maxQuantity", group.get("quantity", 1)):
                raise ValueError("Selected round quantities do not satisfy the official detail")
            if len({c["code"] for c in chosen}) != len(chosen):
                raise ValueError("Duplicate choices in one round; use quantity instead")
            for choice in chosen:
                if choice["code"] not in choices or not isinstance(choice["quantity"], int) or isinstance(choice["quantity"], bool) or choice["quantity"] < 1:
                    raise ValueError("Choice is absent from the actual detail or has invalid quantity")
                actual = choices[choice["code"]]
                maximum = actual.get("maxQuantity", -1)
                if maximum >= 0 and choice["quantity"] > maximum:
                    raise ValueError("Choice exceeds official maximum quantity")
                name = actual["name"]
                nutrition_name = line.get("nutrition_names", {}).get(choice["code"], name)
                components.append({"name": name, "product_code": choice["code"], "category": line.get("categories", {}).get(choice["code"], "unknown"), "quantity": quantity * choice["quantity"], "nutrition": table.get(nutrition_name, {}) if not choice.get("modification") else {}})
            rounds.append({"round": str(group["id"]), "comboItemList": chosen})
        if rounds:
            item["roundList"] = rounds
        else:
            components.append({"name": detail["name"], "product_code": detail["code"], "category": line.get("category", "unknown"), "quantity": quantity, "nutrition": table.get(detail["name"], {})})
        if "modification" in line:
            item["modification"] = line["modification"]
            # A custom preparation may change nutrition; do not claim original totals.
            for component in components[-sum(len(g["comboItemList"]) for g in rounds) if rounds else -1:]:
                component["nutrition"] = {}
        for key in ("couponId", "couponCode"):
            if key in line:
                item[key] = line[key]
        items.append(item)
    return {"id": spec["id"], "label": spec.get("label", spec["id"]), "arguments": {**spec["context"], "items": items}, "components": components}
