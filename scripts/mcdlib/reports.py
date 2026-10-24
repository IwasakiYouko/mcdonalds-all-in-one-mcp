"""Offline reports from whitelisted fields; no credentials or raw API responses."""
import csv
import html
import io
import json
from pathlib import Path


def money(value):
    return "unknown" if value is None else f"CNY {value / 100:.2f}"


def public_report(report):
    """Whitelist public fields rather than guessing every possible sensitive key."""
    if "candidates" in report:
        return {"scope": report.get("scope"), "eligible_ids": report.get("eligible_ids", []), "recommendations": report.get("recommendations", {}), "adjustments": report.get("adjustments", []), "candidates": [{"id": str(c["id"]), "label": c.get("label", c["id"]), "total_cents": c["total_cents"], "budget_remaining_cents": c.get("budget_remaining_cents"), "eligible": c["eligible"], "reasons": c.get("reasons", []), "nutrition": c.get("nutrition", {}), "components": [{"name": i["name"], "quantity": i["quantity"]} for i in c["components"]], "quoted_at": c.get("quote", {}).get("quoted_at"), "source": c.get("quote", {}).get("source", "user-supplied")} for c in report["candidates"]]}
    allowed = {"scope", "record_count", "counted_paid_orders", "total_paid_cents", "positive_spend_average_cents", "coverage_from", "coverage_to", "daily_spend_cents", "frequent_items", "sources", "warnings"}
    if "total_paid_cents" in report:
        return {k: v for k, v in report.items() if k in allowed}
    raise ValueError("Export accepts a meal comparison or spending summary, not raw account/API data")


def render_html(report, title="McDonald's All-in-One"):
    data = public_report(report)
    esc = lambda value: html.escape(str(value), quote=True)
    cards = []
    if "candidates" in data:
        for c in data["candidates"]:
            meal = " · ".join(f"{i['name']} × {i['quantity']}" for i in c["components"])
            nutrients = " · ".join(f"{key}: {value if value is not None else 'unknown'}" for key, value in c["nutrition"].items())
            status = "Within your requirements" if c["eligible"] else "; ".join(c["reasons"])
            cards.append(f"<article><span class='badge'>{esc(c['source'])}</span><h2>{esc(c['label'])}</h2><p>{esc(meal)}</p><strong>{esc(money(c['total_cents']))}</strong><p>{esc(status)}</p><p>Budget remaining: {esc(money(c['budget_remaining_cents']))}</p><p>{esc(nutrients)}</p><small>Quoted: {esc(c['quoted_at'] or 'not provided')}</small></article>")
    else:
        cards.append(f"<article><h2>Recorded spending</h2><strong>{esc(money(data['total_paid_cents']))}</strong><p>{esc(data['counted_paid_orders'])} paid orders in the recorded data</p><p>{esc(data.get('coverage_from'))} → {esc(data.get('coverage_to'))}</p></article>")
        for day, amount in data.get("daily_spend_cents", {}).items():
            cards.append(f"<article class='day'><b>{esc(day)}</b><span>{esc(money(amount))}</span></article>")
    return """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; base-uri 'none'; form-action 'none'"><title>""" + esc(title) + """</title><style>
:root{color-scheme:dark;font-family:system-ui,sans-serif;background:#131310;color:#f6f3e9}body{max-width:1080px;margin:0 auto;padding:36px 22px}header{border-top:6px solid #ffcf36;padding-top:24px}h1{font-size:clamp(28px,5vw,48px);letter-spacing:-.04em;line-height:1.06}header p,small{color:#bfbdb0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:18px;margin:30px 0}article{border:1px solid #454437;background:#212119;border-radius:18px;padding:24px}h2{font-size:20px}strong{font-size:32px;color:#ffcf36}.badge{font:12px monospace;color:#ffcf36}p{line-height:1.6}.day{display:flex;justify-content:space-between;gap:24px}footer{font-size:13px;color:#bfbdb0}footer p{max-width:80ch}@media print{body{background:white;color:black}article{background:white;color:black;break-inside:avoid}strong{color:black}header p,small,footer{color:#555}}
</style><header><span class="badge">MCDONALD'S ALL-IN-ONE · COMMUNITY SKILL</span><h1>""" + esc(title) + "</h1><p>" + esc(data.get("scope", "")) + "</p></header><main class='grid'>" + "".join(cards) + "</main><footer><p>Private identifiers, coupon codes, contact details and raw tool responses are excluded. Meal choices and amounts can still be personal; review before sharing.</p><p>Prices are historical quotes. Verify again before buying. Nutrition is reference data. Independent community project, not an official McDonald's product.</p></footer></html>"


def render_csv(report):
    data = public_report(report)
    buf = io.StringIO()
    writer = csv.writer(buf)
    def safe(value):
        value = str(value)
        return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value
    if "candidates" in data:
        writer.writerow(["candidate", "meal", "total_cents", "budget_remaining_cents", "eligible", "source", "quoted_at"])
        for c in data["candidates"]:
            writer.writerow([safe(c["label"]), safe("; ".join(f"{i['name']} x{i['quantity']}" for i in c["components"])), c["total_cents"], c["budget_remaining_cents"], c["eligible"], c["source"], c["quoted_at"]])
    else:
        writer.writerow(["day", "paid_cents"])
        writer.writerows(data.get("daily_spend_cents", {}).items())
    return buf.getvalue()


def invitation(event):
    required = {"title", "store_name", "date", "time", "people"}
    if not required <= set(event):
        raise ValueError("Invitation needs title, store_name, date, time and people")
    return f"{event['title']}\n{event['date']} {event['time']}\nMeet at {event['store_name']}\nGroup size: {event['people']}\n" + (f"Reference cost per person: {money(event['per_person_cents'])}\n" if "per_person_cents" in event else "") + f"{event.get('note', 'Please confirm your attendance and food preferences.')}\nInvitation draft only; it does not create or confirm a reservation.\n"
