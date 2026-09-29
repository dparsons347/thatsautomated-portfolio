# Parse and check what Claude read off an invoice.
#
# This file is pasted as-is into the "Validate extraction" Python Code node in
# n8n, so it sticks to what that sandbox allows: json, re, datetime and decimal
# only, no dunder names, no I/O. extract.py and the tests import it normally.

import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CONFIDENCE_THRESHOLD = 0.85
TOLERANCE = Decimal("0.05")
REQUIRED_CONFIDENCE = ["vendor", "invoice_number", "invoice_date", "line_items", "total"]
CENT = Decimal("0.01")


def parse_model_output(raw):
    """Pull the JSON object out of whatever the model sent back.

    Returns (data, error). Handles code fences and prose around the object.
    """
    if raw is None:
        return None, "empty model output"
    text = str(raw).strip()
    if not text:
        return None, "empty model output"
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None, "could not parse model output (no JSON object)"
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None, "could not parse model output (invalid JSON)"
    if not isinstance(data, dict):
        return None, "could not parse model output (not an object)"
    return data, ""


def to_money(value):
    """Number, '1,234.50', '$99' -> Decimal rounded to cents. None if not a number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        text = repr(value)
    else:
        text = re.sub(r"[,$\s]", "", str(value))
        if text.startswith("(") and text.endswith(")"):
            text = "-" + text[1:-1]
    if not text:
        return None
    try:
        return Decimal(text).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def to_number(value):
    """Quantities can be fractional (2.5 hours), so no rounding here."""
    if value is None or isinstance(value, bool):
        return None
    text = repr(value) if isinstance(value, (int, float)) else re.sub(r"[,\s]", "", str(value))
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def parse_date(value):
    """ISO first, then US formats. Returns a date or None."""
    if not value:
        return None
    text = str(value).strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2}|\d{4})$", text)
        if not m:
            return None
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def fmt(amount):
    if amount is None:
        return "none"
    sign = "-" if amount < 0 else ""
    return sign + "$" + "{:,.2f}".format(abs(amount))


def as_float(amount):
    return None if amount is None else float(amount)


def clean_str(value):
    if value is None:
        return ""
    return str(value).strip()


def check_extraction(raw, today=None, threshold=CONFIDENCE_THRESHOLD, tolerance=TOLERANCE, stop_reason=None):
    """Validate one extraction.

    Returns a flat dict ready to store: status is "ready" or "needs_review",
    review_reasons lists what stops auto-posting, warnings lists things worth
    a look that do not.
    """
    today = today or date.today()
    reasons = []
    warnings = []
    if stop_reason == "max_tokens":
        reasons.append("model output was cut off (max_tokens)")
    data, error = parse_model_output(raw)
    if error:
        return {
            "status": "needs_review", "review_reasons": reasons + [error], "warnings": [],
            "document_type": "", "vendor_name": "", "invoice_number": "", "invoice_date": "",
            "due_date": "", "po_number": "", "currency": "", "subtotal": None, "tax": None,
            "total": None, "line_sum": None, "line_items": [], "handwritten": False,
            "min_confidence": None, "notes": "",
        }

    vendor = data.get("vendor")
    vendor_name = clean_str(vendor.get("name") if isinstance(vendor, dict) else vendor)
    invoice_number = clean_str(data.get("invoice_number"))
    doc_type = clean_str(data.get("document_type")).lower() or "invoice"
    currency = (clean_str(data.get("currency")) or "USD").upper()
    po_number = clean_str(data.get("po_number"))
    notes = clean_str(data.get("notes"))
    handwritten = data.get("handwritten") is True

    if doc_type != "invoice":
        reasons.append("document looks like a " + doc_type + ", not an invoice")
    if not vendor_name:
        reasons.append("vendor name missing")
    if not invoice_number:
        reasons.append("invoice number missing")
    if currency != "USD":
        reasons.append("currency is " + currency + ", books are in USD")

    invoice_date = parse_date(data.get("invoice_date"))
    if data.get("invoice_date") and invoice_date is None:
        reasons.append("invoice date not readable: " + clean_str(data.get("invoice_date")))
    elif invoice_date is None:
        reasons.append("invoice date missing")
    else:
        if invoice_date > today + timedelta(days=30):
            reasons.append("invoice date " + invoice_date.isoformat() + " is in the future")
        elif invoice_date < today - timedelta(days=730):
            warnings.append("invoice date " + invoice_date.isoformat() + " is over two years old")

    due_date = parse_date(data.get("due_date"))
    if data.get("due_date") and due_date is None:
        warnings.append("due date not readable: " + clean_str(data.get("due_date")))
    if due_date and invoice_date and due_date < invoice_date:
        warnings.append("due date is before the invoice date")

    subtotal = to_money(data.get("subtotal"))
    tax = to_money(data.get("tax"))
    total = to_money(data.get("total"))
    if total is None:
        reasons.append("total missing")
    elif total <= 0:
        reasons.append("total is " + fmt(total) + ", expected a positive amount")

    items = []
    raw_items = data.get("line_items")
    if not isinstance(raw_items, list):
        raw_items = []
    for n, row in enumerate(raw_items, start=1):
        if not isinstance(row, dict):
            continue
        qty = to_number(row.get("quantity"))
        price = to_money(row.get("unit_price"))
        amount = to_money(row.get("amount"))
        if amount is None and qty is not None and price is not None:
            amount = (qty * price).quantize(CENT, rounding=ROUND_HALF_UP)
            warnings.append("line " + str(n) + ": amount missing, used quantity x price")
        if qty is not None and price is not None and amount is not None:
            expected = (qty * price).quantize(CENT, rounding=ROUND_HALF_UP)
            if abs(expected - amount) > tolerance:
                reasons.append("line " + str(n) + ": " + "{:f}".format(qty.normalize()) + " x " + fmt(price)
                               + " = " + fmt(expected) + " but the amount says " + fmt(amount))
        if amount is None:
            reasons.append("line " + str(n) + ": no amount")
        items.append({
            "description": clean_str(row.get("description")),
            "quantity": None if qty is None else float(qty),
            "unit_price": as_float(price),
            "amount": as_float(amount),
        })

    line_sum = None
    if items and all(i["amount"] is not None for i in items):
        line_sum = sum((to_money(i["amount"]) for i in items), Decimal("0.00"))

    if subtotal is not None and line_sum is not None and abs(subtotal - line_sum) > tolerance:
        reasons.append("lines add to " + fmt(line_sum) + " but the subtotal says " + fmt(subtotal)
                       + " (" + fmt(abs(subtotal - line_sum)) + " off)")

    base = subtotal if subtotal is not None else line_sum
    if total is not None:
        if base is None:
            reasons.append("no line items or subtotal to check the total against")
        else:
            expected_total = base + (tax or Decimal("0.00"))
            if abs(expected_total - total) > tolerance:
                label = "subtotal" if subtotal is not None else "lines"
                reasons.append(label + " " + fmt(base) + " + tax " + fmt(tax or Decimal("0.00"))
                               + " = " + fmt(expected_total) + " but the total says " + fmt(total)
                               + " (" + fmt(abs(expected_total - total)) + " off)")

    conf = data.get("confidence")
    if not isinstance(conf, dict):
        conf = {}
    scores = []
    for field in REQUIRED_CONFIDENCE:
        score = to_number(conf.get(field))
        if score is None:
            reasons.append("no confidence reported for " + field)
            continue
        scores.append(score)
        if score < Decimal(str(threshold)):
            reasons.append("low confidence on " + field + " (" + str(float(score)) + ")")

    if handwritten:
        warnings.append("handwritten values")

    return {
        "status": "needs_review" if reasons else "ready",
        "review_reasons": reasons,
        "warnings": warnings,
        "document_type": doc_type,
        "vendor_name": vendor_name,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date.isoformat() if invoice_date else "",
        "due_date": due_date.isoformat() if due_date else "",
        "po_number": po_number,
        "currency": currency,
        "subtotal": as_float(subtotal),
        "tax": as_float(tax),
        "total": as_float(total),
        "line_sum": as_float(line_sum),
        "line_items": items,
        "handwritten": handwritten,
        "min_confidence": float(min(scores)) if scores else None,
        "notes": notes,
    }
