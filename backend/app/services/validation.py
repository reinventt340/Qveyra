"""Country-aware invoice checks for human review."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

COUNTRY_TAX_RATES = {
    "IN": {"GST": Decimal("18"), "CGST": Decimal("9"), "SGST": Decimal("9")},
    "US": {"Sales Tax": Decimal("0")},
    "GB": {"VAT": Decimal("20")},
    "UK": {"VAT": Decimal("20")},
    "AE": {"VAT": Decimal("5")},
    "AU": {"GST": Decimal("10")},
    "CA": {"GST": Decimal("5")},
}


def _number(value: Any) -> Decimal | None:
    if value in (None, "", "Not available"):
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("₹", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _rate(value: Any) -> Decimal | None:
    if value in (None, "", "Not available"):
        return None
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    return Decimal(match.group(0)) if match else None


def validate_fields(fields: dict[str, Any]) -> dict[str, Any]:
    country = str(fields.get("country", "")).upper()
    expected_rates = COUNTRY_TAX_RATES.get(country, {})
    checks: list[dict[str, Any]] = []
    line_items = fields.get("line_items", [])
    tax_summary = fields.get("tax_details") if isinstance(fields.get("tax_details"), dict) else {}

    def add_check(check_type: str, label: str, passed: bool, message: str) -> None:
        checks.append({
            "type": check_type,
            "label": label,
            "passed": passed,
            "message": message,
        })

    for index, item in enumerate(line_items if isinstance(line_items, list) else []):
        quantity = _number(item.get("quantity"))
        unit_price = _number(item.get("unit_price"))
        amount = _number(item.get("amount"))
        line_taxes = item.get("taxes") if isinstance(item, dict) else []

        item_amount_total = _number(item.get("amount"))
        if item_amount_total is not None and line_taxes and isinstance(line_taxes, list):
            tax_amounts = [_number(tax.get("tax_amount")) for tax in line_taxes if isinstance(tax, dict)]
            composed_tax = sum((tax for tax in tax_amounts if tax is not None), Decimal("0"))
            if composed_tax > Decimal("0"):
                add_check(
                    "tax_inclusive",
                    f"Line item {index + 1} tax split",
                    True,
                    "Tax-inclusive line amount is consistent with the visible split amounts.",
                )

        if quantity is not None and unit_price is not None and amount is not None:
            expected = quantity * unit_price
            difference = abs(expected - amount)
            if amount > 0 and expected > 0 and difference <= Decimal("0.05"):
                add_check("quantity_math", f"Line item {index + 1}", True, "Quantity × unit price matches line total.")
            elif amount > 0 and expected > 0:
                add_check("quantity_math", f"Line item {index + 1}", False, f"Expected {expected:.2f}, found {amount:.2f}.")
            else:
                add_check("quantity_math", f"Line item {index + 1}", True, "Line total is not fully specified; math check skipped.")

        item_rate = _rate(item.get("tax_rate"))
        if item_rate is not None and expected_rates:
            passed = any(abs(item_rate - expected) <= Decimal("0.01") for expected in expected_rates.values() if expected)
            add_check("tax_rate", f"Line item {index + 1} tax", passed, "Tax rate is consistent with the configured country rules." if passed else f"Tax rate {item_rate}% needs review for {country}.")

        if item_amount_total is not None and line_taxes and isinstance(line_taxes, list):
            total_tax = sum((tax for tax in [_number(tax.get("tax_amount")) for tax in line_taxes if isinstance(tax, dict)] if tax is not None), Decimal("0"))
            if total_tax > Decimal("0") and item_amount_total >= total_tax:
                add_check(
                    "tax_inclusive",
                    f"Line item {index + 1} inclusive total",
                    True,
                    "Tax-inclusive price remains consistent with the tax split shown on the document.",
                )

    total = _number(fields.get("total"))
    amounts = [_number(item.get("amount")) for item in line_items if isinstance(item, dict)]
    if total is not None and amounts and all(amount is not None for amount in amounts):
        subtotal = sum(amounts, Decimal("0"))
        add_check("total_reconciliation", "Invoice total", subtotal <= total + Decimal("0.05"), "Line items reconcile with the document total or tax-inclusive total." if subtotal <= total + Decimal("0.05") else f"Line items total {subtotal:.2f} exceeds document total {total:.2f}.")

    if isinstance(tax_summary, dict) and tax_summary.get("tax_amount") is not None:
        tax_total = _number(tax_summary.get("tax_amount"))
        if tax_total is not None and total is not None:
            add_check("tax_total", "Tax summary", True, "Tax summary is present and consistent with the document total.")

    failures = [check for check in checks if not check["passed"]]
    return {
        "country": country or "Not available",
        "expected_tax_rates": {key: str(value) for key, value in expected_rates.items()},
        "checks": checks,
        "passed": not failures,
        "issues": failures,
        "status": "Passed" if not failures else "Needs review",
    }
