"""MySQL persistence and reporting for confirmed financial records."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from dotenv import load_dotenv


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(BASE_DIR, ".env"), override=False)


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS finance_suppliers (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        address TEXT NULL,
        gstin VARCHAR(32) NULL,
        pan VARCHAR(32) NULL,
        country VARCHAR(8) NULL,
        state VARCHAR(128) NULL,
        state_code VARCHAR(16) NULL,
        tax_id VARCHAR(64) NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        UNIQUE KEY uq_supplier_identity (name, gstin, pan)
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS finance_customers (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        address TEXT NULL,
        gstin VARCHAR(32) NULL,
        pan VARCHAR(32) NULL,
        country VARCHAR(8) NULL,
        tax_id VARCHAR(64) NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        UNIQUE KEY uq_customer_identity (name, gstin, pan)
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS finance_documents (
        id CHAR(36) PRIMARY KEY,
        document_type VARCHAR(128) NULL,
        original_filename VARCHAR(512) NOT NULL,
        source_document_reference VARCHAR(512) NULL,
        invoice_number VARCHAR(128) NULL,
        order_number VARCHAR(128) NULL,
        po_number VARCHAR(128) NULL,
        reference_details TEXT NULL,
        invoice_date VARCHAR(64) NULL,
        supplier_id BIGINT NULL,
        customer_id BIGINT NULL,
        currency VARCHAR(8) NULL,
        subtotal DECIMAL(18, 2) NULL,
        discount DECIMAL(18, 2) NULL,
        total_tax DECIMAL(18, 2) NULL,
        cgst DECIMAL(18, 2) NULL,
        sgst DECIMAL(18, 2) NULL,
        igst DECIMAL(18, 2) NULL,
        total_amount DECIMAL(18, 2) NULL,
        amount_paid DECIMAL(18, 2) NULL,
        amount_in_words TEXT NULL,
        payment_status VARCHAR(64) NULL,
        place_of_supply VARCHAR(128) NULL,
        place_of_delivery VARCHAR(128) NULL,
        processing_status VARCHAR(32) NOT NULL,
        confirmation_status VARCHAR(32) NOT NULL,
        uploaded_at DATETIME NOT NULL,
        reviewed_at DATETIME NULL,
        confirmed_at DATETIME NULL,
        saved_at DATETIME NULL,
        confirmed_by VARCHAR(255) NULL,
        FOREIGN KEY (supplier_id) REFERENCES finance_suppliers(id),
        FOREIGN KEY (customer_id) REFERENCES finance_customers(id),
        INDEX ix_documents_date (invoice_date),
        INDEX ix_documents_status (confirmation_status),
        INDEX ix_documents_supplier (supplier_id)
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS finance_addresses (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        document_id CHAR(36) NOT NULL,
        role VARCHAR(32) NOT NULL,
        address TEXT NOT NULL,
        created_at DATETIME NOT NULL,
        FOREIGN KEY (document_id) REFERENCES finance_documents(id) ON DELETE CASCADE,
        INDEX ix_addresses_document_role (document_id, role)
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS finance_line_items (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        document_id CHAR(36) NOT NULL,
        description TEXT NULL,
        quantity DECIMAL(18, 4) NULL,
        unit VARCHAR(64) NULL,
        unit_price DECIMAL(18, 2) NULL,
        rate DECIMAL(18, 2) NULL,
        net_amount DECIMAL(18, 2) NULL,
        tax_amount DECIMAL(18, 2) NULL,
        gross_amount DECIMAL(18, 2) NULL,
        tax_rate DECIMAL(8, 3) NULL,
        hsn_code VARCHAR(64) NULL,
        sku VARCHAR(128) NULL,
        serial_number VARCHAR(128) NULL,
        currency VARCHAR(8) NULL,
        FOREIGN KEY (document_id) REFERENCES finance_documents(id) ON DELETE CASCADE,
        INDEX ix_line_items_document (document_id)
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS finance_taxes (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        document_id CHAR(36) NOT NULL,
        line_item_id BIGINT NULL,
        tax_type VARCHAR(32) NULL,
        tax_rate DECIMAL(8, 3) NULL,
        taxable_amount DECIMAL(18, 2) NULL,
        tax_amount DECIMAL(18, 2) NULL,
        cgst DECIMAL(18, 2) NULL,
        sgst DECIMAL(18, 2) NULL,
        igst DECIMAL(18, 2) NULL,
        FOREIGN KEY (document_id) REFERENCES finance_documents(id) ON DELETE CASCADE,
        FOREIGN KEY (line_item_id) REFERENCES finance_line_items(id) ON DELETE CASCADE,
        INDEX ix_taxes_document (document_id)
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS finance_payments (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        document_id CHAR(36) NOT NULL,
        payment_method VARCHAR(64) NULL,
        amount_paid DECIMAL(18, 2) NULL,
        transaction_id VARCHAR(128) NULL,
        reference VARCHAR(128) NULL,
        transaction_time VARCHAR(64) NULL,
        card_type VARCHAR(64) NULL,
        payment_status VARCHAR(64) NULL,
        FOREIGN KEY (document_id) REFERENCES finance_documents(id) ON DELETE CASCADE,
        INDEX ix_payments_document (document_id)
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS finance_audit_events (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        document_id CHAR(36) NOT NULL,
        event_type VARCHAR(64) NOT NULL,
        actor VARCHAR(255) NULL,
        event_at DATETIME NOT NULL,
        FOREIGN KEY (document_id) REFERENCES finance_documents(id) ON DELETE CASCADE
    ) ENGINE=InnoDB
    """,
)


def _value(value: Any) -> Any:
    return None if value in ("", "Not available") else value


def _number(value: Any) -> Any:
    value = _value(value)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class MySQLStore:
    """Small SQL repository whose public methods represent business operations."""

    def __init__(self) -> None:
        self._config = {
            "host": os.getenv("MYSQL_HOST"),
            "port": int(os.getenv("MYSQL_PORT", "3306")),
            "user": os.getenv("MYSQL_USER"),
            "password": os.getenv("MYSQL_PASSWORD"),
            "database": os.getenv("MYSQL_DATABASE"),
        }

    @property
    def configured(self) -> bool:
        return all(self._config.get(key) for key in ("host", "user", "database"))

    def _connect(self):
        if not self.configured:
            raise RuntimeError("MySQL is not configured. Set MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, and MYSQL_DATABASE.")
        try:
            import mysql.connector
        except ImportError as exc:
            raise RuntimeError("mysql-connector-python is required for confirmed financial records.") from exc
        return mysql.connector.connect(**self._config)

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        connection = self._connect()
        try:
            connection.start_transaction()
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.transaction() as connection:
            cursor = connection.cursor()
            try:
                for statement in SCHEMA_STATEMENTS:
                    cursor.execute(statement)
            finally:
                cursor.close()

    def save_confirmed_record(self, fields: dict[str, Any], metadata: dict[str, Any], confirmed_by: str | None) -> str:
        now = datetime.utcnow()
        document_id = str(uuid.uuid4())
        supplier = fields.get("supplier") if isinstance(fields.get("supplier"), dict) else {}
        customer = fields.get("customer") if isinstance(fields.get("customer"), dict) else {}
        supplier_name = _value(supplier.get("name") or fields.get("supplier")) or "Unnamed supplier"
        customer_name = _value(customer.get("name")) or "Unnamed customer"

        with self.transaction() as connection:
            cursor = connection.cursor()
            try:
                supplier_id = self._upsert_supplier(cursor, supplier_name, supplier, now)
                customer_id = self._upsert_customer(cursor, customer_name, customer, now)
                cursor.execute(
                    """INSERT INTO finance_documents
                    (id, document_type, original_filename, source_document_reference,
                     invoice_number, order_number, po_number, reference_details, invoice_date,
                     supplier_id, customer_id, currency, subtotal, discount, total_tax, cgst,
                     sgst, igst, total_amount, amount_paid, amount_in_words, payment_status,
                     place_of_supply, place_of_delivery, processing_status, confirmation_status,
                     uploaded_at, reviewed_at, confirmed_at, saved_at, confirmed_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        document_id, _value(fields.get("document_type")), metadata.get("filename"),
                        metadata.get("source_document_reference"), _value(fields.get("invoice_number")),
                        _value(fields.get("order_number")), _value(fields.get("po_number")),
                        _value(fields.get("notes")), _value(fields.get("date") or fields.get("issue_date")),
                        supplier_id, customer_id, _value(fields.get("currency")), _number(fields.get("subtotal")),
                        _number(fields.get("discount")), _number(fields.get("total_tax") or fields.get("tax_details", {}).get("total_tax")),
                        _number(fields.get("cgst") or fields.get("tax_details", {}).get("cgst")),
                        _number(fields.get("sgst") or fields.get("tax_details", {}).get("sgst")),
                        _number(fields.get("igst") or fields.get("tax_details", {}).get("igst")),
                        _number(fields.get("total")), _number(fields.get("amount_paid")),
                        _value(fields.get("amount_in_words")), _value(fields.get("payment_status") or fields.get("status")),
                        _value(fields.get("place_of_supply")), _value(fields.get("place_of_delivery")),
                        "confirmed", "confirmed", now, now, now, now, _value(confirmed_by),
                    ),
                )
                self._save_addresses(cursor, document_id, fields, now)
                self._save_line_items(cursor, document_id, fields, now)
                self._save_document_tax(cursor, document_id, fields, now)
                self._save_payment(cursor, document_id, fields)
                cursor.execute(
                    "INSERT INTO finance_audit_events (document_id, event_type, actor, event_at) VALUES (%s, %s, %s, %s)",
                    (document_id, "confirmed_and_saved", _value(confirmed_by), now),
                )
            finally:
                cursor.close()
        return document_id

    def _upsert_supplier(self, cursor: Any, name: str, supplier: dict[str, Any], now: datetime) -> int:
        values = (name, _value(supplier.get("gstin")), _value(supplier.get("pan")))
        cursor.execute("SELECT id FROM finance_suppliers WHERE name=%s AND gstin <=> %s AND pan <=> %s LIMIT 1", values)
        row = cursor.fetchone()
        data = (name, _value(supplier.get("address")), values[1], values[2], _value(supplier.get("country")), _value(supplier.get("state")), _value(supplier.get("state_code")), _value(supplier.get("tax_id")), now)
        if row:
            cursor.execute("UPDATE finance_suppliers SET address=%s, gstin=%s, pan=%s, country=%s, state=%s, state_code=%s, tax_id=%s, updated_at=%s WHERE id=%s", (*data[1:], row[0]))
            return int(row[0])
        cursor.execute("INSERT INTO finance_suppliers (name,address,gstin,pan,country,state,state_code,tax_id,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (*data, now))
        return int(cursor.lastrowid)

    def _upsert_customer(self, cursor: Any, name: str, customer: dict[str, Any], now: datetime) -> int:
        values = (name, _value(customer.get("gstin")), _value(customer.get("pan")))
        cursor.execute("SELECT id FROM finance_customers WHERE name=%s AND gstin <=> %s AND pan <=> %s LIMIT 1", values)
        row = cursor.fetchone()
        data = (name, _value(customer.get("address")), values[1], values[2], _value(customer.get("country")), _value(customer.get("tax_id")), now)
        if row:
            cursor.execute("UPDATE finance_customers SET address=%s, gstin=%s, pan=%s, country=%s, tax_id=%s, updated_at=%s WHERE id=%s", (*data[1:], row[0]))
            return int(row[0])
        cursor.execute("INSERT INTO finance_customers (name,address,gstin,pan,country,tax_id,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (*data, now))
        return int(cursor.lastrowid)

    def _save_addresses(self, cursor: Any, document_id: str, fields: dict[str, Any], now: datetime) -> None:
        supplier = fields.get("supplier") if isinstance(fields.get("supplier"), dict) else {}
        addresses = {
            "supplier": fields.get("supplier_address") or supplier.get("address"),
            "billing": fields.get("billing_address"),
            "shipping": fields.get("shipping_address"),
            "ship_from": fields.get("ship_from_address"),
            "ship_to": fields.get("ship_to_address"),
        }
        for role, address in addresses.items():
            if _value(address):
                cursor.execute("INSERT INTO finance_addresses (document_id, role, address, created_at) VALUES (%s,%s,%s,%s)", (document_id, role, address, now))

    def _save_line_items(self, cursor: Any, document_id: str, fields: dict[str, Any], now: datetime) -> None:
        tax_details = fields.get("tax_details") if isinstance(fields.get("tax_details"), dict) else {}
        for item in fields.get("line_items", []) if isinstance(fields.get("line_items"), list) else []:
            if not isinstance(item, dict):
                continue
            cursor.execute(
                """INSERT INTO finance_line_items
                (document_id, description, quantity, unit, unit_price, rate, net_amount,
                 tax_amount, gross_amount, tax_rate, hsn_code, sku, serial_number, currency)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (document_id, _value(item.get("description")), _number(item.get("quantity")), _value(item.get("unit")),
                 _number(item.get("unit_price")), _number(item.get("rate")), _number(item.get("amount")),
                 _number(item.get("tax_amount")), _number(item.get("gross_amount") or (_number(item.get("amount")) or 0) + (_number(item.get("tax_amount")) or 0)),
                 _number(item.get("tax_rate")), _value(item.get("hsn_code")), _value(item.get("sku")), _value(item.get("serial_number")), _value(item.get("currency") or fields.get("currency"))),
            )
            line_item_id = cursor.lastrowid
            for tax in item.get("taxes", []) if isinstance(item.get("taxes"), list) else []:
                if isinstance(tax, dict):
                    cursor.execute("INSERT INTO finance_taxes (document_id,line_item_id,tax_type,tax_rate,taxable_amount,tax_amount,cgst,sgst,igst) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (document_id, line_item_id, _value(tax.get("tax_type")), _number(tax.get("rate")), _number(item.get("amount")), _number(tax.get("tax_amount")), _number(tax.get("tax_amount")) if str(tax.get("tax_type", "")).upper() == "CGST" else None, _number(tax.get("tax_amount")) if str(tax.get("tax_type", "")).upper() == "SGST" else None, _number(tax.get("tax_amount")) if str(tax.get("tax_type", "")).upper() == "IGST" else None))

    def _save_document_tax(self, cursor: Any, document_id: str, fields: dict[str, Any], now: datetime) -> None:
        tax = fields.get("tax_details") if isinstance(fields.get("tax_details"), dict) else {}
        if any(_value(tax.get(key)) is not None for key in ("tax_type", "tax_rate", "taxable_amount", "tax_amount")):
            cursor.execute("INSERT INTO finance_taxes (document_id,tax_type,tax_rate,taxable_amount,tax_amount,cgst,sgst,igst) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (document_id, _value(tax.get("tax_type")), _number(tax.get("tax_rate")), _number(tax.get("taxable_amount")), _number(tax.get("tax_amount")), _number(tax.get("cgst") or fields.get("cgst")), _number(tax.get("sgst") or fields.get("sgst")), _number(tax.get("igst") or fields.get("igst"))))

    def _save_payment(self, cursor: Any, document_id: str, fields: dict[str, Any]) -> None:
        payment = fields.get("payment_details") if isinstance(fields.get("payment_details"), dict) else {}
        if any(_value(payment.get(key)) is not None for key in ("method", "reference")) or _value(fields.get("transaction_id")):
            cursor.execute("INSERT INTO finance_payments (document_id,payment_method,amount_paid,transaction_id,reference,transaction_time,card_type,payment_status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (document_id, _value(payment.get("method")), _number(fields.get("amount_paid")), _value(fields.get("transaction_id")), _value(payment.get("reference")), _value(fields.get("transaction_time")), _value(fields.get("card_type")), _value(fields.get("payment_status") or fields.get("status"))))

    def list_documents(self, search: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.transaction() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                where = "WHERE d.confirmation_status='confirmed'"
                params: list[Any] = []
                if search:
                    where += " AND (d.invoice_number LIKE %s OR s.name LIKE %s OR c.name LIKE %s OR d.order_number LIKE %s)"
                    params.extend([f"%{search}%"] * 4)
                cursor.execute(f"""SELECT d.id, d.document_type, d.original_filename, d.invoice_number,
                    d.order_number, d.invoice_date, s.name supplier, c.name customer, d.subtotal,
                    d.total_tax, d.total_amount total, d.amount_paid, d.currency, d.payment_status,
                    d.confirmed_at FROM finance_documents d
                    LEFT JOIN finance_suppliers s ON s.id=d.supplier_id
                    LEFT JOIN finance_customers c ON c.id=d.customer_id
                    {where} ORDER BY d.confirmed_at DESC LIMIT %s""", (*params, min(max(limit, 1), 500)))
                return cursor.fetchall()
            finally:
                cursor.close()

    def list_suppliers(self, search: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with self.transaction() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                where = ""
                params: list[Any] = []
                if search:
                    where = "WHERE s.name LIKE %s OR s.gstin LIKE %s"
                    params.extend([f"%{search}%", f"%{search}%"])
                cursor.execute(f"""SELECT s.id, s.name, s.address, s.gstin, s.pan, s.country, s.state_code,
                    COUNT(d.id) document_count, COALESCE(SUM(d.total_amount),0) total_value
                    FROM finance_suppliers s
                    LEFT JOIN finance_documents d ON d.supplier_id = s.id AND d.confirmation_status='confirmed'
                    {where} GROUP BY s.id ORDER BY total_value DESC LIMIT %s""", (*params, min(max(limit, 1), 500)))
                return cursor.fetchall()
            finally:
                cursor.close()

    def list_customers(self, search: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with self.transaction() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                where = ""
                params: list[Any] = []
                if search:
                    where = "WHERE c.name LIKE %s OR c.gstin LIKE %s"
                    params.extend([f"%{search}%", f"%{search}%"])
                cursor.execute(f"""SELECT c.id, c.name, c.address, c.gstin, c.pan, c.country,
                    COUNT(d.id) document_count, COALESCE(SUM(d.total_amount),0) total_value
                    FROM finance_customers c
                    LEFT JOIN finance_documents d ON d.customer_id = c.id AND d.confirmation_status='confirmed'
                    {where} GROUP BY c.id ORDER BY total_value DESC LIMIT %s""", (*params, min(max(limit, 1), 500)))
                return cursor.fetchall()
            finally:
                cursor.close()

    def list_payments(self, search: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with self.transaction() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                where = "WHERE d.confirmation_status='confirmed'"
                params: list[Any] = []
                if search:
                    where += " AND (p.transaction_id LIKE %s OR p.reference LIKE %s OR d.invoice_number LIKE %s)"
                    params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
                cursor.execute(f"""SELECT p.id, d.invoice_number, p.payment_method, p.amount_paid,
                    p.transaction_id, p.reference, p.transaction_time, p.card_type, p.payment_status,
                    d.currency, d.confirmed_at
                    FROM finance_payments p
                    JOIN finance_documents d ON d.id = p.document_id
                    {where} ORDER BY d.confirmed_at DESC LIMIT %s""", (*params, min(max(limit, 1), 500)))
                return cursor.fetchall()
            finally:
                cursor.close()

    def dashboard(self) -> dict[str, Any]:
        with self.transaction() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute("SELECT COUNT(*) total_documents, COALESCE(SUM(total_amount),0) total_value, COALESCE(SUM(total_tax),0) total_tax, COALESCE(SUM(amount_paid),0) total_paid, COUNT(DISTINCT supplier_id) suppliers, COUNT(DISTINCT customer_id) customers FROM finance_documents WHERE confirmation_status='confirmed'")
                kpis = cursor.fetchone() or {}
                cursor.execute("SELECT id, invoice_number, invoice_date, total_amount, currency, confirmed_at FROM finance_documents WHERE confirmation_status='confirmed' ORDER BY confirmed_at DESC LIMIT 8")
                return {"kpis": kpis, "recent_documents": cursor.fetchall()}
            finally:
                cursor.close()

    def report(self, report_type: str = "invoice_summary") -> dict[str, Any]:
        with self.transaction() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                if report_type == "supplier_analysis":
                    query = "SELECT s.name supplier, COUNT(*) document_count, SUM(d.total_amount) total_value, SUM(d.total_tax) total_tax, SUM(d.amount_paid) amount_paid FROM finance_documents d JOIN finance_suppliers s ON s.id=d.supplier_id WHERE d.confirmation_status='confirmed' GROUP BY s.id, s.name ORDER BY total_value DESC"
                elif report_type == "tax_report":
                    query = "SELECT COALESCE(t.tax_type,'Unknown') tax_type, SUM(t.taxable_amount) taxable_amount, SUM(t.tax_amount) tax_amount, SUM(t.cgst) cgst, SUM(t.sgst) sgst, SUM(t.igst) igst FROM finance_taxes t JOIN finance_documents d ON d.id=t.document_id WHERE d.confirmation_status='confirmed' GROUP BY t.tax_type ORDER BY tax_amount DESC"
                elif report_type == "payment_report":
                    query = "SELECT COALESCE(p.payment_method,'Unknown') payment_method, COUNT(*) payment_count, SUM(p.amount_paid) amount_paid FROM finance_payments p JOIN finance_documents d ON d.id=p.document_id WHERE d.confirmation_status='confirmed' GROUP BY p.payment_method ORDER BY amount_paid DESC"
                else:
                    query = "SELECT DATE_FORMAT(confirmed_at, '%Y-%m') period, COUNT(*) document_count, SUM(total_amount) total_value, SUM(total_tax) total_tax, AVG(total_amount) average_value FROM finance_documents WHERE confirmation_status='confirmed' GROUP BY DATE_FORMAT(confirmed_at, '%Y-%m') ORDER BY period"
                cursor.execute(query)
                return {"report_type": report_type, "rows": cursor.fetchall()}
            finally:
                cursor.close()

    def document_detail(self, document_id: str) -> dict[str, Any] | None:
        with self.transaction() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                cursor.execute("SELECT d.*, s.name supplier_name, s.address supplier_address, s.gstin supplier_gstin, s.pan supplier_pan, c.name customer_name, c.address customer_address, c.gstin customer_gstin, c.pan customer_pan FROM finance_documents d LEFT JOIN finance_suppliers s ON s.id=d.supplier_id LEFT JOIN finance_customers c ON c.id=d.customer_id WHERE d.id=%s AND d.confirmation_status='confirmed'", (document_id,))
                document = cursor.fetchone()
                if not document:
                    return None
                cursor.execute("SELECT * FROM finance_line_items WHERE document_id=%s ORDER BY id", (document_id,)); document["line_items"] = cursor.fetchall()
                cursor.execute("SELECT * FROM finance_taxes WHERE document_id=%s ORDER BY id", (document_id,)); document["taxes"] = cursor.fetchall()
                cursor.execute("SELECT * FROM finance_payments WHERE document_id=%s ORDER BY id", (document_id,)); document["payments"] = cursor.fetchall()
                cursor.execute("SELECT role, address FROM finance_addresses WHERE document_id=%s ORDER BY id", (document_id,)); document["addresses"] = cursor.fetchall()
                return document
            finally:
                cursor.close()


def get_mysql_store() -> MySQLStore:
    return MySQLStore()
