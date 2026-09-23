from app.prompts.invoice_prompt import build_invoice_prompt
from app.schemas.invoice import get_invoice_schema_template, normalize_invoice_fields
from app.services.gemini_common import process_file_with_prompt
from app.services.local_ocr import fill_missing_values


def process_invoice_file(path: str):
    """Extract invoice fields from a file."""
    schema = get_invoice_schema_template()
    prompt = build_invoice_prompt(schema)
    result = process_file_with_prompt(path, prompt, schema)
    result["fields"] = fill_missing_values(normalize_invoice_fields(result["fields"]))
    return result
