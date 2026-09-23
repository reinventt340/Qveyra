import json

from app.schemas.invoice import get_invoice_schema_template
from app.prompts.invoice_prompt import (
    EXTRACT_SCHEMA_VERSION,
    COMMON_EXTRACTION_RULES,
    DOCUMENT_RULES,
    IDENTITY_RULES,
    ADDRESS_RULES,
    IDENTIFIER_RULES,
    DATE_RULES,
    CURRENCY_RULES,
    AMOUNT_RULES,
    LINE_ITEM_RULES,
    TAX_RULES,
    PAYMENT_RULES,
    OCR_RULES,
    DUPLICATION_RULES,
    MISSING_VALUE_RULES,
    OUTPUT_RULES,
)


RECEIPT_RULES = """
RECEIPT-SPECIFIC RULES:

1. The merchant/store/business is the supplier only when the receipt clearly
   identifies it as the seller/merchant.

2. Customer/buyer information may be absent. Never invent it.

3. A cashier, waiter, salesperson, attendant, or employee is not automatically
   the buyer or supplier.

4. Extract receipt number, transaction ID, authorization code, order number,
   check number, terminal ID, table number, or other identifiers separately.

5. Never confuse:
   receipt number
   order number
   transaction ID
   authorization code
   terminal ID
   table number
   check number
   loyalty number

6. Extract every purchased product/service line.

7. Restaurant receipts may contain:
   food
   beverages
   modifiers
   service charges
   gratuity
   tips
   discounts
   taxes
   deposits
   other charges

8. Do not treat tips or gratuity as tax.

9. Do not treat service charge as tax unless explicitly labeled as tax.

10. Keep these distinct:
    subtotal
    discount
    service charge
    tip
    tax
    total
    amount paid
    cash tendered
    change
    balance

11. Loyalty points, reward balances, cashier numbers, table numbers,
    terminal numbers, and order numbers are not automatically the receipt total.

12. If the receipt explicitly says Paid, PAID, Payment Received, Settled,
    Completed, or equivalent, preserve the status where the schema supports it.

13. Do not infer payment status merely because cash/card/UPI/etc. is shown.

14. Inspect the bottom-most portion of the receipt carefully. Important
    information is frequently printed there.

15. Extract small-print information such as tax registration numbers,
    merchant details, payment references, transaction information,
    contact information, and printed policies when supported by the schema.
"""


def build_receipt_prompt(schema=None) -> str:
    template = schema or get_invoice_schema_template()

    schema_json = json.dumps(
        template,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return f"""
Qveyra Receipt Extraction
Schema Version: {EXTRACT_SCHEMA_VERSION}

{COMMON_EXTRACTION_RULES}

{RECEIPT_RULES}

{DOCUMENT_RULES}

{IDENTITY_RULES}

{ADDRESS_RULES}

{IDENTIFIER_RULES}

{DATE_RULES}

{CURRENCY_RULES}

{AMOUNT_RULES}

{LINE_ITEM_RULES}

{TAX_RULES}

{PAYMENT_RULES}

{OCR_RULES}

{DUPLICATION_RULES}

{MISSING_VALUE_RULES}

{OUTPUT_RULES}

Before answering, internally verify that the entire receipt was inspected,
including the bottom-most text and small print.

VISIBLE + READABLE + SUPPORTED → EXTRACT
NOT VISIBLE → null / []
AMBIGUOUS / UNREADABLE → null / []
DERIVABLE BUT NOT PRINTED → DO NOT INVENT

JSON SCHEMA:
{schema_json}
""".strip()