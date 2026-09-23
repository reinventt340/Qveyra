from app.prompts.receipt_prompt import build_receipt_prompt
from app.schemas.invoice import get_invoice_schema_template, normalize_invoice_fields
from app.services.gemini_common import process_file_with_prompt
from app.services.local_ocr import fill_missing_values


def process_receipt_file(path: str):
    """Extract receipt fields from a file."""
    schema = get_invoice_schema_template()
    prompt = build_receipt_prompt(schema)
    result = process_file_with_prompt(path, prompt, schema)
    result["fields"] = fill_missing_values(normalize_invoice_fields(result["fields"]))
    return result
