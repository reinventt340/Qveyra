"""Confirmed document PDF and email delivery helpers."""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

LOGO_PATH = Path(__file__).resolve().parents[3] / "frontend" / "public" / "company-logo.jpg"
BRAND_NAVY = colors.HexColor("#102a52")
BRAND_BLUE = colors.HexColor("#1b57d1")
BRAND_SOFT = colors.HexColor("#eef3ff")
BRAND_BORDER = colors.HexColor("#d7e1f5")
BRAND_MUTED = colors.HexColor("#5b6b82")


def _text(value: Any) -> str:
    if value in (None, "", "Not available"):
        return "Not available"
    return str(value)


def _party_name(value: Any) -> str:
    if isinstance(value, dict):
        return _text(value.get("name"))
    return _text(value)


def _party_address(value: Any, fallback: Any = None) -> str:
    if isinstance(value, dict) and value.get("address") not in (None, "", "Not available"):
        return _text(value.get("address"))
    return _text(fallback)


def _money(value: Any, currency: str | None = None) -> str:
    if value in (None, "", "Not available"):
        return "Not available"
    try:
        amount = f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return _text(value)
    return f"{currency} {amount}" if currency else amount


def create_confirmation_pdf(payload: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{Path(payload['output_file']).stem}_confirmed.pdf"
    fields = payload["result"].get("fields", {})
    currency = fields.get("currency")
    supplier = fields.get("supplier")
    customer = fields.get("customer")
    tax_details = fields.get("tax_details") if isinstance(fields.get("tax_details"), dict) else {}
    validation = payload["result"].get("validation", {})

    document = SimpleDocTemplate(
        str(output_file), pagesize=A4,
        rightMargin=34, leftMargin=34, topMargin=28, bottomMargin=30,
    )
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle("QveyraBody", parent=styles["BodyText"], fontSize=9.5, leading=13)
    label_style = ParagraphStyle("QveyraLabel", parent=styles["BodyText"], fontSize=8, textColor=BRAND_MUTED)
    value_style = ParagraphStyle("QveyraValue", parent=styles["BodyText"], fontSize=10, leading=14, textColor=BRAND_NAVY)
    right_value_style = ParagraphStyle("QveyraRightValue", parent=value_style, alignment=TA_RIGHT)
    header_cell_style = ParagraphStyle("QveyraHeaderCell", parent=styles["BodyText"], fontSize=9, textColor=colors.white, leading=12)

    elements: list[Any] = []

    logo = Image(str(LOGO_PATH), width=15 * mm, height=15 * mm) if LOGO_PATH.exists() else Paragraph("", body_style)
    brand_block = [
        Paragraph("<b>Qveyra</b>", ParagraphStyle("BrandTitle", parent=styles["Title"], fontSize=18, textColor=BRAND_NAVY, spaceAfter=0)),
        Paragraph("Intelligent document understanding for finance", ParagraphStyle("BrandTag", parent=body_style, fontSize=8.5, textColor=BRAND_MUTED)),
    ]
    header_table = Table(
        [[logo, brand_block, Paragraph("CONFIRMED<br/>DOCUMENT", ParagraphStyle("DocBadge", parent=styles["BodyText"], fontSize=10, alignment=TA_RIGHT, textColor=BRAND_BLUE, leading=13))]],
        colWidths=[22 * mm, 110 * mm, 60 * mm],
    )
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 6))
    divider = Table([[""]], colWidths=[527])
    divider.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 1.2, BRAND_BLUE)]))
    elements.append(divider)
    elements.append(Spacer(1, 14))

    meta_rows = [
        [Paragraph("Document number", label_style), Paragraph("Document date", label_style),
         Paragraph("Currency", label_style), Paragraph("Total amount", label_style)],
        [Paragraph(_text(fields.get("invoice_number") or fields.get("receipt_reference")), value_style),
         Paragraph(_text(fields.get("date") or fields.get("issue_date")), value_style),
         Paragraph(_text(currency), value_style),
         Paragraph(f"<b>{_money(fields.get('total'), currency)}</b>", value_style)],
    ]
    meta_table = Table(meta_rows, colWidths=[140, 110, 90, 187])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_SOFT),
        ("BOX", (0, 0), (-1, -1), 0.6, BRAND_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BRAND_BORDER),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 16))

    supplier_cell = [
        Paragraph("SUPPLIER / MERCHANT", label_style),
        Paragraph(f"<b>{_party_name(supplier) or _text(fields.get('document_type'))}</b>", value_style),
        Paragraph(_party_address(supplier, fields.get("supplier_address")), body_style),
    ]
    if isinstance(supplier, dict) and supplier.get("gstin"):
        supplier_cell.append(Paragraph(f"GSTIN: {supplier.get('gstin')}", body_style))
    customer_cell = [
        Paragraph("CUSTOMER / BILLED TO", label_style),
        Paragraph(f"<b>{_party_name(customer)}</b>", value_style),
        Paragraph(_party_address(customer, fields.get("billing_address")), body_style),
    ]
    parties_table = Table([[supplier_cell, customer_cell]], colWidths=[263, 264])
    parties_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, BRAND_BORDER),
        ("LINEAFTER", (0, 0), (0, 0), 0.6, BRAND_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 10),
    ]))
    elements.append(parties_table)
    elements.append(Spacer(1, 18))

    items = [[
        Paragraph("Description", header_cell_style), Paragraph("Qty", header_cell_style),
        Paragraph("Unit price", header_cell_style), Paragraph("Tax", header_cell_style),
        Paragraph("Amount", header_cell_style),
    ]]
    for item in fields.get("line_items", []) or []:
        if not isinstance(item, dict):
            continue
        tax_rate = item.get("tax_rate")
        tax_label = f"{tax_rate}%" if tax_rate not in (None, "", "Not available") else "Not available"
        items.append([
            Paragraph(_text(item.get("description")), body_style),
            Paragraph(_text(item.get("quantity")), body_style),
            Paragraph(_money(item.get("unit_price"), currency), body_style),
            Paragraph(tax_label, body_style),
            Paragraph(_money(item.get("amount"), currency), body_style),
        ])
    item_table = Table(items, colWidths=[232, 40, 85, 60, 110], repeatRows=1)
    item_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, BRAND_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fd")]),
        ("PADDING", (0, 0), (-1, -1), 7),
    ]))
    elements.append(item_table)
    elements.append(Spacer(1, 16))

    totals_rows = []
    if fields.get("subtotal") not in (None, "", "Not available"):
        totals_rows.append(("Subtotal", _money(fields.get("subtotal"), currency)))
    if tax_details.get("tax_amount") not in (None, "", "Not available"):
        totals_rows.append(("Tax", _money(tax_details.get("tax_amount"), currency)))
    totals_rows.append(("Total", _money(fields.get("total"), currency)))
    totals_table = Table(
        [[Paragraph(label, right_value_style), Paragraph(f"<b>{value}</b>" if label == "Total" else value, right_value_style)] for label, value in totals_rows],
        colWidths=[420, 107],
    )
    totals_table.setStyle(TableStyle([
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, BRAND_NAVY),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(totals_table)
    elements.append(Spacer(1, 20))

    status_color = "#1aa979" if validation.get("passed") else "#c53030"
    elements.append(Paragraph(
        f"Validation status: <font color='{status_color}'>{_text(validation.get('status'))}</font>",
        ParagraphStyle("ValidationStatus", parent=styles["Heading4"], fontSize=11),
    ))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(
        "This document reflects the confirmed information reviewed and approved in Qveyra.",
        ParagraphStyle("Footnote", parent=body_style, textColor=BRAND_MUTED),
    ))

    document.build(elements)
    return output_file


def email_confirmation(pdf_path: Path, recipient: str | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
    recipient = recipient or os.getenv("CONFIRMATION_RECIPIENT", "prs9061@gmail.com")
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_FROM", username or "")
    if not all([host, username, password, sender]):
        return {"sent": False, "status": "SMTP not configured", "recipient": recipient}

    context = context or {}
    invoice_number = context.get("invoice_number") or "Not available"
    supplier_name = context.get("supplier_name") or "Not available"
    total = context.get("total") or "Not available"

    message = EmailMessage()
    message["Subject"] = f"Qveyra confirmed document — {invoice_number}"
    message["From"] = sender
    message["To"] = recipient

    message.set_content(
        "Good morning,\n\n"
        f"The financial document {invoice_number} from {supplier_name} has been reviewed and confirmed in Qveyra.\n"
        f"Confirmed total: {total}\n\n"
        "The confirmed document is attached to this email as a PDF for your records.\n\n"
        "If anything looks incorrect, please review it in Qveyra before it is used downstream.\n\n"
        "Best regards,\n"
        "Qveyra — Intelligent Document Understanding for Finance"
    )

    html_body = f"""\
<html>
  <body style="margin:0;padding:0;background:#f4f6fb;font-family:Arial,Helvetica,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6fb;padding:32px 0;">
      <tr><td align="center">
        <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 12px 30px rgba(12,32,71,0.08);">
          <tr>
            <td style="background:#102a52;padding:22px 28px;">
              <table role="presentation" width="100%"><tr>
                <td width="46">{'<img src="cid:qveyra-logo" width="40" height="40" style="border-radius:8px;display:block;"/>' if LOGO_PATH.exists() else ''}</td>
                <td style="color:#ffffff;font-size:18px;font-weight:700;">Qveyra</td>
                <td align="right" style="color:#b9f5d0;font-size:11px;font-weight:700;letter-spacing:.06em;">CONFIRMED</td>
              </tr></table>
            </td>
          </tr>
          <tr>
            <td style="padding:28px;">
              <p style="margin:0 0 14px;color:#122033;font-size:15px;">Good morning,</p>
              <p style="margin:0 0 14px;color:#3a4a5e;font-size:14px;line-height:1.6;">
                The financial document <strong>{invoice_number}</strong> from <strong>{supplier_name}</strong>
                has been reviewed and confirmed in Qveyra.
              </p>
              <table role="presentation" width="100%" style="background:#eef3ff;border-radius:10px;margin:18px 0;">
                <tr>
                  <td style="padding:14px 18px;color:#5b6b82;font-size:12px;">Confirmed total</td>
                  <td align="right" style="padding:14px 18px;color:#102a52;font-size:18px;font-weight:700;">{total}</td>
                </tr>
              </table>
              <p style="margin:0 0 14px;color:#3a4a5e;font-size:14px;line-height:1.6;">
                The confirmed document is attached to this email as a PDF for your records.
              </p>
              <p style="margin:0 0 4px;color:#3a4a5e;font-size:14px;line-height:1.6;">
                If anything looks incorrect, please review it in Qveyra before it is used downstream.
              </p>
              <p style="margin:24px 0 0;color:#122033;font-size:14px;">Best regards,<br/>Qveyra — Intelligent Document Understanding for Finance</p>
            </td>
          </tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>
"""
    message.add_alternative(html_body, subtype="html")

    if LOGO_PATH.exists():
        html_part = message.get_payload()[-1]
        html_part.add_related(LOGO_PATH.read_bytes(), maintype="image", subtype="jpeg", cid="<qveyra-logo>")

    message.add_attachment(pdf_path.read_bytes(), maintype="application", subtype="pdf", filename=pdf_path.name)

    try:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(message)
        return {"sent": True, "status": "Sent", "recipient": recipient}
    except Exception as exc:
        return {"sent": False, "status": f"SMTP delivery failed: {exc}", "recipient": recipient}

