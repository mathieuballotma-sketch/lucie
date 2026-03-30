"""
FacturXSecureParser v2 — Production-ready secure FacturX/ZUGFeRD PDF+XML parser.

Security layers (in order of application):
  1. XXE prevention via defusedxml (mandatory — no fallback)
  2. SQL injection detection
  3. XSS detection
  4. Path traversal detection
  5. EN16931 namespace + required-element validation
  6. _safe_decimal: reject NaN, Infinity, scientific notation, >999M
  7. PDF/XML cross-validation (amounts TTC/HT, vendor, invoice number)
  8. Invisible text detection via pdfplumber

Usage:
    parser = FacturXSecureParser()
    result = parser.parse(pdf_bytes)
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
import zlib
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

try:
    import defusedxml.ElementTree as ET
    from defusedxml import DefusedXmlException
    _DEFUSEDXML_AVAILABLE = True
except ImportError:
    _DEFUSEDXML_AVAILABLE = False

try:
    import pdfplumber
    _PDFPLUMBER_AVAILABLE = True
except ImportError:
    _PDFPLUMBER_AVAILABLE = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Security patterns
# ---------------------------------------------------------------------------

SQL_INJECTION_PATTERN = re.compile(
    r"(?:'|--|;|/\*|\*/|xp_|UNION\s+SELECT|DROP\s+TABLE|INSERT\s+INTO"
    r"|DELETE\s+FROM|UPDATE\s+\w+\s+SET|EXEC\s*\(|EXECUTE\s*\(|CAST\s*\("
    r"|CONVERT\s*\(|CHAR\s*\(|NCHAR\s*\(|VARCHAR\s*\(|ALTER\s+TABLE"
    r"|CREATE\s+TABLE|TRUNCATE\s+TABLE)",
    re.IGNORECASE,
)

XSS_PATTERN = re.compile(
    r"(?:<script|javascript:|vbscript:|on\w+\s*=|<iframe|<object|<embed"
    r"|<link\s+href|<meta\s+http-equiv|data:text/html|expression\s*\()",
    re.IGNORECASE,
)

PATH_TRAVERSAL_PATTERN = re.compile(
    r"(?:\.\./|\.\.\\|%2e%2e%2f|%2e%2e/|\.\.%2f|%252e%252e|/etc/passwd"
    r"|/etc/shadow|/proc/self|\\windows\\system32)",
    re.IGNORECASE,
)

_SCIENTIFIC_NOTATION = re.compile(r"[eE][+\-]?\d")
_MAX_AMOUNT = Decimal("999000000")  # 999 million

# ---------------------------------------------------------------------------
# EN16931 constants
# ---------------------------------------------------------------------------

ALLOWED_NAMESPACES: frozenset[str] = frozenset({
    "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
    "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "urn:un:unece:uncefact:data:standard:QualifiedDataType:100",
    "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
})

# EN16931 required element local names (CII profile)
REQUIRED_ELEMENTS: frozenset[str] = frozenset({
    "ExchangedDocumentContext",
    "ExchangedDocument",
    "SupplyChainTradeTransaction",
    "SellerTradeParty",
    "BuyerTradeParty",
    "SpecifiedTradeSettlementHeaderMonetarySummation",
})

_FACTURX_FILENAMES = (
    "factur-x.xml",
    "ZUGFeRD-invoice.xml",
    "zugferd-invoice.xml",
    "xrechnung.xml",
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class AlertLevel(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class SecurityAlert:
    level: AlertLevel
    layer: str
    message: str
    detail: str = ""

    def __str__(self) -> str:
        suffix = f" — {self.detail}" if self.detail else ""
        return f"[{self.level}][{self.layer}] {self.message}{suffix}"


@dataclass
class ParseResult:
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    alerts: list[SecurityAlert] = field(default_factory=list)
    xml_hash: str = ""

    @property
    def has_critical(self) -> bool:
        return any(a.level == AlertLevel.CRITICAL for a in self.alerts)

    def alerts_by_level(self, level: AlertLevel) -> list[SecurityAlert]:
        return [a for a in self.alerts if a.level == level]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class FacturXSecureParser:
    """
    Secure parser for FacturX / ZUGFeRD invoices embedded in PDF.

    Raises RuntimeError at instantiation if defusedxml is not installed.
    There is NO fallback — defusedxml is mandatory for XXE protection.
    """

    def __init__(self) -> None:
        if not _DEFUSEDXML_AVAILABLE:
            raise RuntimeError(
                "defusedxml is REQUIRED for FacturXSecureParser. "
                "Install it with: pip install defusedxml. "
                "No fallback is provided — XXE protection cannot be guaranteed."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, pdf_bytes: bytes) -> ParseResult:
        """
        Parse a FacturX PDF and return a ParseResult with security alerts.

        Returns ParseResult.success=True only when no CRITICAL alerts are raised.
        """
        result = ParseResult(success=False)

        xml_bytes = self._extract_xml_from_pdf(pdf_bytes, result)
        if xml_bytes is None:
            result.alerts.append(SecurityAlert(
                level=AlertLevel.ERROR,
                layer="pdf_extraction",
                message="No FacturX XML attachment found in PDF",
            ))
            return result

        result.xml_hash = hashlib.sha256(xml_bytes).hexdigest()

        root = self._parse_xml_secure(xml_bytes, result)
        if root is None:
            return result

        self._validate_namespaces(root, result)
        self._validate_required_elements(root, result)
        self._scan_text_content(root, result)

        if not result.has_critical:
            self._extract_data(root, result)
            if _PDFPLUMBER_AVAILABLE:
                self._cross_validate_pdf_xml(pdf_bytes, result)
                self._detect_invisible_text(pdf_bytes, result)
            result.success = not result.has_critical

        return result

    # ------------------------------------------------------------------
    # PDF extraction
    # ------------------------------------------------------------------

    def _extract_xml_from_pdf(
        self, pdf_bytes: bytes, result: ParseResult
    ) -> bytes | None:
        """Extract embedded FacturX XML from PDF attachment stream."""
        try:
            if not pdf_bytes.startswith(b"%PDF"):
                return None

            if b"/EmbeddedFile" not in pdf_bytes:
                return None

            for filename in _FACTURX_FILENAMES:
                fname_bytes = filename.encode()
                idx = pdf_bytes.find(fname_bytes)
                if idx != -1:
                    stream_xml = self._extract_stream_near(pdf_bytes, idx)
                    if stream_xml and self._looks_like_xml(stream_xml):
                        return stream_xml

            return None

        except Exception as exc:
            result.alerts.append(SecurityAlert(
                level=AlertLevel.ERROR,
                layer="pdf_extraction",
                message="PDF extraction error",
                detail=str(exc),
            ))
            return None

    def _extract_stream_near(self, pdf_bytes: bytes, idx: int) -> bytes | None:
        """Extract the nearest compressed or raw XML stream at position idx."""
        search_window = pdf_bytes[idx: idx + 131072]

        for marker in (b"stream\r\n", b"stream\n"):
            stream_start = search_window.find(marker)
            if stream_start != -1:
                stream_content = search_window[stream_start + len(marker):]
                end_marker = stream_content.find(b"endstream")
                if end_marker == -1:
                    continue
                raw = stream_content[:end_marker].strip()
                try:
                    decompressed = zlib.decompress(raw)
                    if self._looks_like_xml(decompressed):
                        return decompressed
                except Exception:
                    pass
                if self._looks_like_xml(raw):
                    return raw

        return None

    @staticmethod
    def _looks_like_xml(data: bytes) -> bool:
        stripped = data.lstrip()
        return stripped.startswith(b"<?xml") or stripped.startswith(b"<")

    # ------------------------------------------------------------------
    # Secure XML parsing — triple XXE protection
    # ------------------------------------------------------------------

    def _parse_xml_secure(
        self, xml_bytes: bytes, result: ParseResult
    ) -> Any | None:
        """
        Parse XML with triple XXE protection:
          forbid_dtd=True, forbid_entities=True, forbid_external=True
        """
        try:
            root = ET.fromstring(
                xml_bytes,
                forbid_dtd=True,
                forbid_entities=True,
                forbid_external=True,
            )
            return root
        except DefusedXmlException as exc:
            result.alerts.append(SecurityAlert(
                level=AlertLevel.CRITICAL,
                layer="xxe_protection",
                message="XXE / malicious XML construct detected and blocked",
                detail=str(exc),
            ))
            return None
        except ET.ParseError as exc:
            result.alerts.append(SecurityAlert(
                level=AlertLevel.ERROR,
                layer="xml_parsing",
                message="XML parse error",
                detail=str(exc),
            ))
            return None

    # ------------------------------------------------------------------
    # Namespace validation (EN16931)
    # ------------------------------------------------------------------

    def _validate_namespaces(self, root: Any, result: ParseResult) -> None:
        """Recursively validate that all element namespaces are in ALLOWED_NAMESPACES."""
        self._walk_namespaces(root, result, depth=0)

    def _walk_namespaces(self, element: Any, result: ParseResult, depth: int) -> None:
        if depth > 500:
            result.alerts.append(SecurityAlert(
                level=AlertLevel.ERROR,
                layer="namespace_validation",
                message="XML nesting depth limit exceeded (>500)",
            ))
            return
        tag = element.tag
        if tag.startswith("{"):
            ns = tag[1: tag.index("}")]
            if ns not in ALLOWED_NAMESPACES:
                result.alerts.append(SecurityAlert(
                    level=AlertLevel.WARNING,
                    layer="namespace_validation",
                    message=f"Unexpected namespace: {ns}",
                    detail=f"Element tag: {tag}",
                ))
        for child in element:
            self._walk_namespaces(child, result, depth + 1)

    # ------------------------------------------------------------------
    # Required element validation (EN16931)
    # ------------------------------------------------------------------

    def _validate_required_elements(self, root: Any, result: ParseResult) -> None:
        """Check that all EN16931 required element local names are present."""
        found_locals: set[str] = set()
        self._collect_local_names(root, found_locals)
        for elem_name in sorted(REQUIRED_ELEMENTS - found_locals):
            result.alerts.append(SecurityAlert(
                level=AlertLevel.ERROR,
                layer="en16931_validation",
                message=f"Required EN16931 element missing: {elem_name}",
            ))

    def _collect_local_names(self, element: Any, found: set[str]) -> None:
        tag = element.tag
        local = tag.split("}")[-1] if "}" in tag else tag
        found.add(local)
        for child in element:
            self._collect_local_names(child, found)

    # ------------------------------------------------------------------
    # Injection scanning
    # ------------------------------------------------------------------

    def _scan_text_content(self, root: Any, result: ParseResult) -> None:
        """Scan all text nodes and attribute values for injection patterns."""
        self._scan_element(root, result)

    def _scan_element(self, element: Any, result: ParseResult) -> None:
        for text in (element.text, element.tail):
            if text:
                self._check_injection(text, element.tag, result)
        for attr_name, attr_val in element.attrib.items():
            self._check_injection(attr_val, f"{element.tag}@{attr_name}", result)
        for child in element:
            self._scan_element(child, result)

    def _check_injection(self, text: str, location: str, result: ParseResult) -> None:
        if SQL_INJECTION_PATTERN.search(text):
            result.alerts.append(SecurityAlert(
                level=AlertLevel.CRITICAL,
                layer="sql_injection",
                message="SQL injection pattern detected",
                detail=f"Location: {location}, Value: {text[:120]}",
            ))
        if XSS_PATTERN.search(text):
            result.alerts.append(SecurityAlert(
                level=AlertLevel.CRITICAL,
                layer="xss_detection",
                message="XSS pattern detected",
                detail=f"Location: {location}, Value: {text[:120]}",
            ))
        if PATH_TRAVERSAL_PATTERN.search(text):
            result.alerts.append(SecurityAlert(
                level=AlertLevel.CRITICAL,
                layer="path_traversal",
                message="Path traversal pattern detected",
                detail=f"Location: {location}, Value: {text[:120]}",
            ))

    # ------------------------------------------------------------------
    # Data extraction
    # ------------------------------------------------------------------

    def _extract_data(self, root: Any, result: ParseResult) -> None:
        """Extract invoice data into result.data."""

        def find_text(local_name: str) -> str | None:
            for elem in root.iter():
                tag_local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if tag_local == local_name and elem.text:
                    return elem.text.strip()
            return None

        data: dict[str, Any] = {}

        invoice_id = find_text("ID")
        if invoice_id:
            data["invoice_number"] = invoice_id

        seller_name = find_text("Name")
        if seller_name:
            data["seller_name"] = seller_name

        tax_basis = find_text("TaxBasisTotalAmount")
        if tax_basis:
            val = self._safe_decimal(tax_basis, "TaxBasisTotalAmount", result)
            if val is not None:
                data["amount_ht"] = val

        grand_total = find_text("GrandTotalAmount")
        if grand_total:
            val = self._safe_decimal(grand_total, "GrandTotalAmount", result)
            if val is not None:
                data["amount_ttc"] = val

        due_amount = find_text("DuePayableAmount")
        if due_amount:
            val = self._safe_decimal(due_amount, "DuePayableAmount", result)
            if val is not None:
                data["amount_due"] = val

        result.data = data

    # ------------------------------------------------------------------
    # Safe decimal
    # ------------------------------------------------------------------

    def _safe_decimal(
        self, value: str, field_name: str, result: ParseResult
    ) -> Decimal | None:
        """
        Parse a decimal value with strict validation.
        Rejects: NaN, Infinity, scientific notation, amounts > 999M, invalid format.
        """
        stripped = value.strip()

        if _SCIENTIFIC_NOTATION.search(stripped):
            result.alerts.append(SecurityAlert(
                level=AlertLevel.ERROR,
                layer="safe_decimal",
                message=f"Scientific notation rejected in {field_name}",
                detail=f"Value: {stripped}",
            ))
            return None

        try:
            d = Decimal(stripped)
        except InvalidOperation:
            result.alerts.append(SecurityAlert(
                level=AlertLevel.ERROR,
                layer="safe_decimal",
                message=f"Invalid decimal value in {field_name}",
                detail=f"Value: {stripped}",
            ))
            return None

        if d.is_nan():
            result.alerts.append(SecurityAlert(
                level=AlertLevel.ERROR,
                layer="safe_decimal",
                message=f"NaN rejected in {field_name}",
                detail=f"Value: {stripped}",
            ))
            return None

        if d.is_infinite():
            result.alerts.append(SecurityAlert(
                level=AlertLevel.ERROR,
                layer="safe_decimal",
                message=f"Infinity rejected in {field_name}",
                detail=f"Value: {stripped}",
            ))
            return None

        if d > _MAX_AMOUNT:
            result.alerts.append(SecurityAlert(
                level=AlertLevel.ERROR,
                layer="safe_decimal",
                message=f"Amount exceeds 999M limit in {field_name}",
                detail=f"Value: {d}",
            ))
            return None

        return d

    # ------------------------------------------------------------------
    # PDF/XML cross-validation
    # ------------------------------------------------------------------

    def _cross_validate_pdf_xml(
        self, pdf_bytes: bytes, result: ParseResult
    ) -> None:
        """Cross-validate extracted XML data against visible PDF text content."""
        if not result.data:
            return

        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception as exc:
            result.alerts.append(SecurityAlert(
                level=AlertLevel.WARNING,
                layer="cross_validation",
                message="Could not extract PDF text for cross-validation",
                detail=str(exc),
            ))
            return

        def _check_field(value: str, label: str) -> None:
            if value and value not in text:
                result.alerts.append(SecurityAlert(
                    level=AlertLevel.WARNING,
                    layer="cross_validation",
                    message=f"{label} from XML not found in PDF text",
                    detail=f"Value: {value}",
                ))

        _check_field(result.data.get("invoice_number", ""), "Invoice number")
        _check_field(result.data.get("seller_name", ""), "Seller name")

        for key, label in (("amount_ttc", "TTC amount"), ("amount_ht", "HT amount")):
            amount = result.data.get(key)
            if amount is not None:
                # Accept both dot and comma decimal separators
                if str(amount) not in text and str(amount).replace(".", ",") not in text:
                    result.alerts.append(SecurityAlert(
                        level=AlertLevel.WARNING,
                        layer="cross_validation",
                        message=f"{label} from XML not found in PDF text",
                        detail=f"Value: {amount}",
                    ))

    # ------------------------------------------------------------------
    # Invisible text detection
    # ------------------------------------------------------------------

    def _detect_invisible_text(
        self, pdf_bytes: bytes, result: ParseResult
    ) -> None:
        """Detect invisible text via pdfplumber char rendering modes and colors."""
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    chars = page.chars or []
                    invisible_count = 0
                    for char in chars:
                        # Rendering mode 3 = invisible in PDF spec
                        if char.get("text_rendering_mode") == 3:
                            invisible_count += 1
                        # White text (common steganography trick)
                        color = char.get("non_stroking_color")
                        if color in ((1, 1, 1), 1, (1.0, 1.0, 1.0)):
                            invisible_count += 1
                    if invisible_count > 5:
                        result.alerts.append(SecurityAlert(
                            level=AlertLevel.WARNING,
                            layer="invisible_text",
                            message=f"Invisible text detected on page {page_num}",
                            detail=f"{invisible_count} invisible characters",
                        ))
        except Exception as exc:
            result.alerts.append(SecurityAlert(
                level=AlertLevel.INFO,
                layer="invisible_text",
                message="Invisible text check skipped",
                detail=str(exc),
            ))
