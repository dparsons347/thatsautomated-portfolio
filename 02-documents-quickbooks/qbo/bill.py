# Decide whether an extracted invoice can be posted to QuickBooks, and build
# the Bill if it can.
#
# This file is pasted as-is into the "Plan the Bill" Python Code node in n8n,
# so it sticks to what that sandbox allows: json, re and decimal only, no
# dunder names, no I/O. client.py and the tests import it normally.

import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CENT = Decimal("0.01")
DOC_NUMBER_MAX = 21          # QuickBooks limit on Bill.DocNumber
PRIVATE_NOTE_MAX = 4000
DESCRIPTION_MAX = 4000

# Expense account per vendor, by the account's FullyQualifiedName in QuickBooks.
# Anything not listed goes to DEFAULT_ACCOUNT. Names, not IDs, so the same map
# works against any company that has these accounts.
DEFAULT_ACCOUNT = "Job Expenses:Job Materials"
VENDOR_ACCOUNTS = {
    "ellis equipment rental": "Equipment Rental",
    "tim philip masonry": "Job Expenses:Job Materials:Decks and Patios",
}
TAX_LINE_DESCRIPTION = "Sales tax"

VENDOR_QUERY = "select Id, DisplayName, CompanyName, Active from Vendor where Active = true maxresults 1000"
ACCOUNT_QUERY = ("select Id, Name, FullyQualifiedName, AccountType from Account "
                 "where Active = true maxresults 1000")

SUFFIXES = {"inc", "incorporated", "llc", "ltd", "co", "corp", "corporation", "company", "the"}


def money(value):
    """Number or numeric string -> Decimal cents, or None."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    text = repr(value) if isinstance(value, (int, float)) else re.sub(r"[,$\s]", "", str(value))
    try:
        return Decimal(text).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def normalize_name(name):
    """'Norton Lumber & Building Materials, Inc.' -> 'norton lumber and building materials'"""
    text = str(name or "").lower().replace("&", " and ")
    text = re.sub("['’]", "", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    words = [w for w in text.split() if w not in SUFFIXES]
    return " ".join(words)


def match_vendor(name, vendors):
    """Find the QuickBooks vendor for an extracted vendor name.

    vendors: list of Vendor objects from the query API (Id, DisplayName,
    CompanyName). Exact match after normalizing wins. Otherwise a single
    vendor whose name contains the other (or is contained in it) is accepted
    when the shorter name is at least 60% of the longer one. Anything else is
    no match, because posting to the wrong vendor is worse than a review.

    Returns (vendor or None, reason).
    """
    target = normalize_name(name)
    if not target:
        return None, "no vendor name to match"
    exact = []
    partial = []
    for v in vendors or []:
        names = {normalize_name(v.get("DisplayName")), normalize_name(v.get("CompanyName"))} - {""}
        if target in names:
            exact.append(v)
            continue
        for n in names:
            short, long_ = sorted([n, target], key=len)
            if short and short in long_ and len(short) >= 0.6 * len(long_):
                partial.append(v)
                break
    if len(exact) == 1:
        return exact[0], ""
    if len(exact) > 1:
        return None, "vendor \"" + str(name) + "\" matches " + str(len(exact)) + " QuickBooks vendors"
    if len(partial) == 1:
        return partial[0], ""
    if len(partial) > 1:
        names = ", ".join(sorted(str(v.get("DisplayName")) for v in partial))
        return None, "vendor \"" + str(name) + "\" could be any of: " + names
    return None, "vendor \"" + str(name) + "\" is not in QuickBooks"


def find_account(full_name, accounts):
    """Account object whose FullyQualifiedName (or Name) matches, case-insensitive."""
    want = str(full_name or "").strip().lower()
    for a in accounts or []:
        if str(a.get("FullyQualifiedName", "")).lower() == want:
            return a
    for a in accounts or []:
        if str(a.get("Name", "")).lower() == want:
            return a
    return None


def account_for_vendor(vendor, accounts):
    """Returns (account or None, reason)."""
    key = normalize_name(vendor.get("DisplayName"))
    wanted = VENDOR_ACCOUNTS.get(key, DEFAULT_ACCOUNT)
    acct = find_account(wanted, accounts)
    if acct is None and wanted != DEFAULT_ACCOUNT:
        acct = find_account(DEFAULT_ACCOUNT, accounts)
    if acct is None:
        return None, "expense account \"" + wanted + "\" not found in QuickBooks"
    return acct, ""


def quote(value):
    """Escape a value for a QuickBooks query string literal."""
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def duplicate_query(vendor_id, doc_number):
    return ("select Id, DocNumber, TotalAmt, TxnDate from Bill where VendorRef = " + quote(vendor_id)
            + " and DocNumber = " + quote(doc_number))


def parse_lines(doc):
    raw = doc.get("line_items_json")
    if raw is None:
        raw = doc.get("line_items")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else []
        except ValueError:
            return None
    if not isinstance(raw, list):
        return None
    return [r for r in raw if isinstance(r, dict)]


def build_bill(doc, vendor, account):
    """Bill payload for the QuickBooks API, or (None, reasons) if it can't be built.

    One AccountBasedExpense line per invoice line, plus a tax line when the
    invoice shows tax. The lines must add up to the invoice total to the cent,
    so the Bill in QuickBooks always matches the paper.
    """
    reasons = []
    doc_number = str(doc.get("invoice_number") or "").strip()
    if not doc_number:
        reasons.append("invoice number missing")
    elif len(doc_number) > DOC_NUMBER_MAX:
        reasons.append("invoice number is longer than QuickBooks allows (" + str(DOC_NUMBER_MAX) + ")")
    if not doc.get("invoice_date"):
        reasons.append("invoice date missing")
    total = money(doc.get("total"))
    if total is None or total <= 0:
        reasons.append("total missing or not positive")
    rows = parse_lines(doc)
    if not rows:
        reasons.append("no line items to post")
        rows = []

    acct_ref = {"value": str(account.get("Id")), "name": account.get("FullyQualifiedName") or account.get("Name")}
    lines = []
    line_sum = Decimal("0.00")
    for n, row in enumerate(rows, start=1):
        amount = money(row.get("amount"))
        if amount is None:
            reasons.append("line " + str(n) + " has no amount")
            continue
        line_sum += amount
        desc = str(row.get("description") or "").strip()
        qty = row.get("quantity")
        price = row.get("unit_price")
        if qty not in (None, "", 1, 1.0) and price not in (None, ""):
            desc = desc + " (" + ("{:g}".format(float(qty))) + " @ " + "{:,.2f}".format(float(price)) + ")"
        lines.append({
            "LineNum": len(lines) + 1,
            "Amount": float(amount),
            "Description": desc[:DESCRIPTION_MAX],
            "DetailType": "AccountBasedExpenseLineDetail",
            "AccountBasedExpenseLineDetail": {"AccountRef": acct_ref},
        })
    tax = money(doc.get("tax"))
    if tax is not None and tax != 0:
        line_sum += tax
        lines.append({
            "LineNum": len(lines) + 1,
            "Amount": float(tax),
            "Description": TAX_LINE_DESCRIPTION,
            "DetailType": "AccountBasedExpenseLineDetail",
            "AccountBasedExpenseLineDetail": {"AccountRef": acct_ref},
        })
    if total is not None and lines and line_sum != total:
        reasons.append("Bill lines add to $" + "{:,.2f}".format(line_sum) + " but the invoice total is $"
                       + "{:,.2f}".format(total))
    if reasons:
        return None, reasons

    note_parts = ["Posted by the AP intake workflow from " + str(doc.get("filename") or "an emailed file")]
    if doc.get("po_number"):
        note_parts.append("PO " + str(doc.get("po_number")))
    if doc.get("sha256"):
        note_parts.append("sha256 " + str(doc.get("sha256"))[:12])
    if doc.get("id") is not None:
        note_parts.append("p2_documents row " + str(doc.get("id")))
    bill = {
        "VendorRef": {"value": str(vendor.get("Id")), "name": vendor.get("DisplayName")},
        "DocNumber": doc_number,
        "TxnDate": str(doc.get("invoice_date")),
        "Line": lines,
        "PrivateNote": ". ".join(note_parts)[:PRIVATE_NOTE_MAX],
    }
    if doc.get("due_date"):
        bill["DueDate"] = str(doc.get("due_date"))
    return bill, []


def plan_bill(doc, vendors, accounts):
    """Everything n8n needs to decide the next step for one document.

    action is "post" (bill and duplicate_query are set) or "review"
    (review_reasons says why).
    """
    base = {"action": "review", "vendor_id": "", "vendor_display_name": "", "account_id": "",
            "bill": None, "duplicate_query": "", "review_reasons": []}
    vendor, why = match_vendor(doc.get("vendor_name"), vendors)
    if vendor is None:
        base["review_reasons"] = [why]
        return base
    base["vendor_id"] = str(vendor.get("Id"))
    base["vendor_display_name"] = vendor.get("DisplayName") or ""
    account, why = account_for_vendor(vendor, accounts)
    if account is None:
        base["review_reasons"] = [why]
        return base
    base["account_id"] = str(account.get("Id"))
    bill, reasons = build_bill(doc, vendor, account)
    if reasons:
        base["review_reasons"] = reasons
        return base
    base["action"] = "post"
    base["bill"] = bill
    base["duplicate_query"] = duplicate_query(vendor.get("Id"), bill["DocNumber"])
    return base


def query_rows(response, entity):
    """Pull the list of objects out of a query API response."""
    if not isinstance(response, dict):
        return []
    qr = response.get("QueryResponse") or {}
    rows = qr.get(entity) or []
    return rows if isinstance(rows, list) else []
