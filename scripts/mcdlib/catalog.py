"""Explicit tool routing. Unrecognized tools are never silently treated as read-only."""
MODULES = {
    "store-address": ["delivery-query-addresses", "delivery-create-address", "delivery-query-stores", "query-nearby-stores"],
    "menu-pricing": ["query-meals", "query-meal-detail", "calculate-price"],
    "nutrition": ["list-nutrition-foods"],
    "coupons": ["available-coupons", "auto-bind-coupons", "query-my-coupons", "query-store-coupons"],
    "orders": ["create-order", "query-order", "order-list", "cancel-order"],
    "group-meals": ["query-meal-assistance", "query-promotions"],
    "points-mall": ["query-my-account", "mall-points-products", "mall-product-detail", "mall-create-order", "mall-order-list", "mall-order-detail"],
    "campaigns": ["campaign-calendar", "now-time-info"],
    "lottery": ["query-lottery-info", "draw-lottery", "query-my-prizes"],
    "events": ["query-party-city", "query-party-store", "query-party-store-date", "query-party-store-session", "party-order-create"],
    "feedback": ["query-survey-coupon"],
}
WRITE_TOOLS = frozenset({"delivery-create-address", "auto-bind-coupons", "create-order", "cancel-order", "mall-create-order", "draw-lottery", "party-order-create"})
ALL_TOOLS = frozenset(tool for group in MODULES.values() for tool in group)
READ_TOOLS = ALL_TOOLS - WRITE_TOOLS


def validate(value, schema, path="$", root=None):
    """Validate the JSON Schema features used by the discovered tool contracts.

    This is deliberately a small input validator, not a general JSON Schema engine.
    Unknown validation keywords fail closed so a server contract change is visible.
    """
    root = schema if root is None else root
    annotations = {"title", "description", "default", "examples", "$schema", "$id", "$defs", "definitions", "deprecated", "readOnly", "writeOnly", "format"}
    supported = {"$ref", "type", "enum", "const", "properties", "required", "additionalProperties", "items", "minItems", "maxItems", "uniqueItems", "minLength", "maxLength", "pattern", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "anyOf", "oneOf", "allOf", "minProperties", "maxProperties"}
    if schema is True:
        return
    if schema is False:
        raise ValueError(f"{path}: value is not allowed")
    unknown = set(schema) - annotations - supported
    if unknown:
        raise ValueError(f"{path}: unsupported schema constraints {sorted(unknown)}; use a compatible native MCP client")
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            raise ValueError(f"{path}: external schema references are unsupported")
        target = root
        for part in ref[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        validate(value, target, path, root)
    for kind in ("anyOf", "oneOf", "allOf"):
        if kind in schema:
            successes = 0
            for option in schema[kind]:
                try:
                    validate(value, option, path, root)
                    successes += 1
                except ValueError:
                    pass
            needed = len(schema[kind]) if kind == "allOf" else 1
            if successes < needed or (kind == "oneOf" and successes != 1):
                raise ValueError(f"{path}: does not satisfy {kind}")
    types = {"object": lambda x: isinstance(x, dict), "array": lambda x: isinstance(x, list), "string": lambda x: isinstance(x, str), "integer": lambda x: isinstance(x, int) and not isinstance(x, bool), "number": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool), "boolean": lambda x: isinstance(x, bool), "null": lambda x: x is None}
    expected = schema.get("type")
    if expected:
        expected = expected if isinstance(expected, list) else [expected]
        if not any(types.get(t, lambda _: False)(value) for t in expected):
            raise ValueError(f"{path}: expected {' or '.join(expected)}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: value is not in the allowed enum")
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"{path}: does not match const")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(f"{path}.{key}: required")
        props = schema.get("properties", {})
        for key, item in value.items():
            if key in props:
                validate(item, props[key], f"{path}.{key}", root)
            elif schema.get("additionalProperties") is False:
                raise ValueError(f"{path}.{key}: unexpected property")
            elif isinstance(schema.get("additionalProperties"), dict):
                validate(item, schema["additionalProperties"], f"{path}.{key}", root)
        for name, op in (("minProperties", lambda n, k: n < k), ("maxProperties", lambda n, k: n > k)):
            if name in schema and op(len(value), schema[name]):
                raise ValueError(f"{path}: violates {name}")
    if isinstance(value, list):
        for i, item in enumerate(value):
            validate(item, schema.get("items", {}), f"{path}[{i}]", root)
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            raise ValueError(f"{path}: invalid item count")
        if schema.get("uniqueItems"):
            import json
            if len({json.dumps(x, sort_keys=True) for x in value}) != len(value):
                raise ValueError(f"{path}: duplicate items")
    if isinstance(value, str):
        import re
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", float("inf")):
            raise ValueError(f"{path}: invalid string length")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise ValueError(f"{path}: does not match pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        import math
        if not math.isfinite(value):
            raise ValueError(f"{path}: number must be finite")
        checks = {"minimum": lambda x, b: x < b, "maximum": lambda x, b: x > b, "exclusiveMinimum": lambda x, b: x <= b, "exclusiveMaximum": lambda x, b: x >= b}
        for key, fails in checks.items():
            if key in schema and fails(value, schema[key]):
                raise ValueError(f"{path}: violates {key}")
        if "multipleOf" in schema and not math.isclose(value / schema["multipleOf"], round(value / schema["multipleOf"])):
            raise ValueError(f"{path}: violates multipleOf")
