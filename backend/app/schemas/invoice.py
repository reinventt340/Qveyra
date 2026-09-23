"""Invoice data schema and normalization helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def get_invoice_schema_template() -> dict[str, Any]:
    """Return a comprehensive invoice extraction schema."""
    return {
        "document_type": None,
        "receipt_number": None,
        "transaction_id": None,
        "transaction_time": None,
        "amount_paid": None,
        "payment_status": None,
        "card_type": None,
        "masked_card_number": None,
        "account_billed": None,
        "service_period": None,
        "supplier": {
            "name": None,
            "address": None,
            "contact": None,
            "tax_id": None,
            "gstin": None,
            "pan": None,
            "state_code": None,
            "registration_number": None,
            "country": None,
        },
        "supplier_address": None,
        "supplier_contact": None,
        "supplier_tax_id": None,
        "customer": {
            "name": None,
            "address": None,
            "contact": None,
            "tax_id": None,
            "gstin": None,
            "pan": None,
        },
        "invoice_number": None,
        "po_number": None,
        "order_number": None,
        "date": None,
        "issue_date": None,
        "due_date": None,
        "order_date": None,
        "payment_terms": None,
        "subtotal": None,
        "discount": None,
        "total": None,
        "cgst": None,
        "sgst": None,
        "igst": None,
        "total_tax": None,
        "currency": None,
        "country": None,
        "country_code": None,
        "exchange_rate": None,
        "status": None,
        "notes": None,
        "terms_conditions": None,
        "place_of_supply": None,
        "place_of_delivery": None,
        "amount_in_words": None,
        "authorized_signatory": None,
        "line_items": [
            {
                "description": None,
                "quantity": None,
                "unit": None,
                "unit_price": None,
                "rate": None,
                "amount": None,
                "tax_rate": None,
                "tax_amount": None,
                "discount": None,
                "currency": None,
                "hsn_code": None,
                "sku": None,
                "serial_number": None,
                "taxes": [{
                    "tax_type": None,
                    "rate": None,
                    "tax_amount": None,
                }],
            }
        ],
        "tax_details": {
            "tax_type": None,
            "tax_rate": None,
            "taxable_amount": None,
            "tax_amount": None,
            "cgst": None,
            "sgst": None,
            "igst": None,
            "total_tax": None,
        },
        "bank_details": {
            "bank_name": None,
            "account_number": None,
            "iban": None,
            "swift_code": None,
            "branch": None,
        },
        "payment_details": {
            "method": None,
            "reference": None,
        },
        "receipt_reference": None,
        "billing_address": None,
        "shipping_address": None,
        "ship_from_address": None,
        "ship_to_address": None,
        "vat_number": None,
        "gst_number": None,
        "tax_identifier": None,
        "supplier_registration_number": None,
        "gstin": None,
    }


def _merge_template(template_value: Any, source_value: Any) -> Any:
    if isinstance(template_value, dict):
        source = source_value if isinstance(source_value, dict) else {}
        merged = deepcopy(template_value)
        for key, item in template_value.items():
            merged[key] = _merge_template(item, source.get(key))
        return merged

    if isinstance(template_value, list):
        if not isinstance(source_value, list) or not source_value:
            return deepcopy(template_value)
        example_item = template_value[0] if template_value else None
        if example_item is None:
            return deepcopy(source_value)
        if isinstance(example_item, dict):
            return [
                _merge_template(example_item, item) if isinstance(item, dict) else deepcopy(item)
                for item in source_value[:10]
            ]
        return deepcopy(source_value[:10])

    return deepcopy(source_value) if source_value is not None else deepcopy(template_value)


def normalize_invoice_fields(raw_fields: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize extraction output to a comprehensive invoice schema."""
    template = get_invoice_schema_template()
    if not raw_fields:
        return template

    normalized = _merge_template(template, raw_fields)

    def apply_alias(prefix: str, target: dict[str, Any]) -> None:
        for key, value in list(raw_fields.items()):
            if not isinstance(key, str) or not key.startswith(prefix):
                continue
            suffix = key[len(prefix):]
            if not suffix:
                continue
            canonical = suffix.lower().replace("_", "")
            if canonical == "name":
                target["name"] = value
            elif canonical == "address":
                target["address"] = value
            elif canonical == "contact":
                target["contact"] = value
            elif canonical == "taxid":
                target["tax_id"] = value
            elif canonical in {"gstin", "pan", "statecode", "registrationnumber", "country"}:
                target["state_code" if canonical == "statecode" else canonical] = value

    supplier_value = raw_fields.get("supplier")
    if isinstance(supplier_value, str):
        normalized["supplier"] = supplier_value
    elif isinstance(supplier_value, dict):
        normalized["supplier"] = _merge_template(template["supplier"], supplier_value)
    else:
        normalized["supplier"] = _merge_template(template["supplier"], {
            "name": raw_fields.get("supplier_name") or raw_fields.get("supplier"),
            "address": raw_fields.get("supplier_address"),
            "contact": raw_fields.get("supplier_contact"),
            "tax_id": raw_fields.get("supplier_tax_id"),
            "gstin": raw_fields.get("supplier_gstin") or raw_fields.get("gstin"),
            "pan": raw_fields.get("supplier_pan") or raw_fields.get("pan"),
            "state_code": raw_fields.get("supplier_state_code") or raw_fields.get("state_code"),
            "registration_number": raw_fields.get("supplier_registration_number") or raw_fields.get("supplier_tax_id"),
        })

    customer_value = raw_fields.get("customer")
    if isinstance(customer_value, dict):
        normalized["customer"] = _merge_template(template["customer"], customer_value)
    else:
        normalized["customer"] = _merge_template(template["customer"], {
            "name": raw_fields.get("customer_name"),
            "address": raw_fields.get("customer_address") or raw_fields.get("billing_address"),
            "contact": raw_fields.get("customer_contact"),
            "tax_id": raw_fields.get("customer_tax_id"),
            "gstin": raw_fields.get("customer_gstin"),
            "pan": raw_fields.get("customer_pan"),
        })

    if isinstance(normalized["supplier"], dict):
        apply_alias("supplier_", normalized["supplier"])
    if isinstance(normalized["customer"], dict):
        apply_alias("customer_", normalized["customer"])

    for key in ["cgst", "sgst", "igst", "total_tax"]:
        if key in raw_fields and raw_fields.get(key) is not None:
            normalized[key] = raw_fields[key]

    if isinstance(raw_fields.get("tax_details"), dict):
        normalized["tax_details"] = _merge_template(template["tax_details"], raw_fields["tax_details"])

    if isinstance(raw_fields.get("line_items"), list):
        normalized["line_items"] = []
        for item in raw_fields["line_items"]:
            if not isinstance(item, dict):
                normalized["line_items"].append(item)
                continue
            merged_item = _merge_template(template["line_items"][0], item)
            if "taxes" in item and isinstance(item["taxes"], list):
                merged_item["taxes"] = [
                    _merge_template(template["line_items"][0]["taxes"][0], tax)
                    if isinstance(tax, dict) else tax
                    for tax in item["taxes"]
                ]
            normalized["line_items"].append(merged_item)

    if normalized.get("supplier") is None:
        normalized["supplier"] = template["supplier"]

    return normalized
