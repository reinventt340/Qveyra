import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.schemas.invoice import normalize_invoice_fields
from app.services.local_ocr import fill_missing_values
from app.services.document_router import detect_document_type
from app.services.invoice_extraction import process_invoice_file
from app.services.receipt_extraction import process_receipt_file
from app.services.storage import load_output_json, save_output_json
from app.services.auth import authenticate_user
from app.services.validation import validate_fields
from app.services.reports import create_confirmation_pdf, email_confirmation
from app.services.connectors import export_to_configured_sources
from app.services.mysql_store import get_mysql_store

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Invoice/Receipt Extractor API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/auth/login")
async def login(data: dict):
    user = authenticate_user(str(data.get("username", "")), str(data.get("password", "")))
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {"ok": True, "user": user}


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    filename = f"{uuid.uuid4().hex}_{file.filename}"
    dest = UPLOAD_DIR / filename
    try:
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)
    finally:
        file.file.close()

    doc_type = detect_document_type(str(dest))
    if doc_type == "receipt":
        res = process_receipt_file(str(dest))
    else:
        res = process_invoice_file(str(dest))
    res["validation"] = validate_fields(res.get("fields", {}))
    payload = save_output_json(filename, res, OUTPUT_DIR)

    return {
        "ok": True,
        "payload": payload,
        "preview_url": f"/files/{filename}",
    }


@app.post("/confirm")
async def confirm(data: dict):
    out_file = data.get("output_file")
    fields = data.get("fields")
    if not out_file or not fields:
        raise HTTPException(status_code=400, detail="output_file and fields required")

    out_path = OUTPUT_DIR / out_file
    if not out_path.exists():
        raise HTTPException(status_code=404, detail="output file not found")

    try:
        payload = load_output_json(out_path)
        payload["result"]["fields"] = fill_missing_values(normalize_invoice_fields(fields))
        payload["result"]["validation"] = validate_fields(payload["result"]["fields"])
        confirmed_by = data.get("confirmed_by")
        store = get_mysql_store()
        store.initialize()
        document_id = store.save_confirmed_record(
            payload["result"]["fields"],
            {
                "filename": payload.get("filename"),
                "source_document_reference": payload.get("filename"),
            },
            str(confirmed_by) if confirmed_by else None,
        )
        payload["result"]["database_record_id"] = document_id
        payload["result"]["confirmation_status"] = "Saved"
        pdf_path = create_confirmation_pdf(payload, OUTPUT_DIR)
        payload["result"]["confirmation_pdf"] = pdf_path.name
        confirmed_fields = payload["result"]["fields"]
        confirmed_supplier = confirmed_fields.get("supplier")
        email_context = {
            "invoice_number": confirmed_fields.get("invoice_number") or confirmed_fields.get("receipt_reference"),
            "supplier_name": confirmed_supplier.get("name") if isinstance(confirmed_supplier, dict) else confirmed_supplier,
            "total": f"{confirmed_fields.get('currency', '')} {confirmed_fields.get('total', '')}".strip(),
        }
        payload["result"]["email_delivery"] = email_confirmation(pdf_path, context=email_context)
        payload["result"]["data_sources"] = export_to_configured_sources(payload)
        with open(out_path, "w", encoding="utf-8") as fh:
            import json

            json.dump(payload, fh, ensure_ascii=False, indent=2)
        return {
            "ok": True,
            "saved": str(out_path),
            "confirmation_pdf": f"/outputs/{pdf_path.name}",
            "database_record_id": document_id,
            "validation": payload["result"]["validation"],
            "email_delivery": payload["result"]["email_delivery"],
            "data_sources": payload["result"]["data_sources"],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/finance/dashboard")
async def finance_dashboard():
    try:
        return {"ok": True, **get_mysql_store().dashboard()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/finance/documents")
async def finance_documents(search: str | None = None, limit: int = 100):
    try:
        return {"ok": True, "documents": get_mysql_store().list_documents(search, limit)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/finance/documents/{document_id}")
async def finance_document_detail(document_id: str):
    try:
        document = get_mysql_store().document_detail(document_id)
        if not document:
            raise HTTPException(status_code=404, detail="confirmed document not found")
        return {"ok": True, "document": document}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/finance/reports/{report_type}")
async def finance_report(report_type: str = "invoice_summary"):
    try:
        return {"ok": True, **get_mysql_store().report(report_type)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/finance/suppliers")
async def finance_suppliers(search: str | None = None, limit: int = 200):
    try:
        return {"ok": True, "suppliers": get_mysql_store().list_suppliers(search, limit)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/finance/customers")
async def finance_customers(search: str | None = None, limit: int = 200):
    try:
        return {"ok": True, "customers": get_mysql_store().list_customers(search, limit)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/finance/payments")
async def finance_payments(search: str | None = None, limit: int = 200):
    try:
        return {"ok": True, "payments": get_mysql_store().list_payments(search, limit)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/files/{name}")
async def serve_file(name: str):
    path = UPLOAD_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path)


@app.get("/outputs/{name}")
async def get_output(name: str):
    path = OUTPUT_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="output not found")
    return FileResponse(path)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
