"""
Tests for FacturXSecureParser v2 — 35 tests across 9 categories.

Categories:
  1. defusedxml dependency (2 tests)
  2. XXE protection — DTD, entities, external (4 tests)
  3. SQL injection detection (5 tests)
  4. XSS detection (4 tests)
  5. Path traversal detection (4 tests)
  6. Namespace validation (4 tests)
  7. EN16931 required element validation (4 tests)
  8. _safe_decimal validation (7 tests)
  9. Cross-validation + invisible text stubs (1 test)
"""
from __future__ import annotations

import importlib
import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.services.facturx_parser import (
    ALLOWED_NAMESPACES,
    REQUIRED_ELEMENTS,
    AlertLevel,
    FacturXSecureParser,
    ParseResult,
    SecurityAlert,
    _safe_decimal as _safe_decimal_via_instance,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CII_NS = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
_RAM_NS = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
_UDT_NS = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"


def _minimal_valid_xml(
    extra_content: str = "",
    ns: str = _CII_NS,
    extra_ns: str = "",
) -> bytes:
    """
    Build a minimal EN16931 CII XML with all REQUIRED_ELEMENTS present.
    """
    namespaces = f'xmlns:rsm="{_CII_NS}" xmlns:ram="{_RAM_NS}" xmlns:udt="{_UDT_NS}"'
    if extra_ns:
        namespaces += f" {extra_ns}"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice {namespaces}>
  <rsm:ExchangedDocumentContext>
    <ram:GuidelineSpecifiedDocumentContextParameter>
      <ram:ID>urn:cen.eu:en16931:2017</ram:ID>
    </ram:GuidelineSpecifiedDocumentContextParameter>
  </rsm:ExchangedDocumentContext>
  <rsm:ExchangedDocument>
    <ram:ID>INV-2024-001</ram:ID>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty>
        <ram:Name>ACME Corp</ram:Name>
      </ram:SellerTradeParty>
      <ram:BuyerTradeParty>
        <ram:Name>Client SA</ram:Name>
      </ram:BuyerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:TaxBasisTotalAmount>1000.00</ram:TaxBasisTotalAmount>
        <ram:GrandTotalAmount>1200.00</ram:GrandTotalAmount>
        <ram:DuePayableAmount>1200.00</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
  {extra_content}
</rsm:CrossIndustryInvoice>
""".encode("utf-8")


def _make_parser() -> FacturXSecureParser:
    return FacturXSecureParser()


def _parse_xml_directly(parser: FacturXSecureParser, xml: bytes) -> ParseResult:
    """Bypass PDF extraction and test XML parsing directly."""
    result = ParseResult(success=False)
    import hashlib
    result.xml_hash = hashlib.sha256(xml).hexdigest()
    root = parser._parse_xml_secure(xml, result)
    if root is not None:
        parser._validate_namespaces(root, result)
        parser._validate_required_elements(root, result)
        parser._scan_text_content(root, result)
        if not result.has_critical:
            parser._extract_data(root, result)
            result.success = not result.has_critical
    return result


# ---------------------------------------------------------------------------
# Category 1 — defusedxml dependency (2 tests)
# ---------------------------------------------------------------------------

class TestDefusedxmlDependency:
    def test_instantiation_succeeds_when_defusedxml_available(self):
        """FacturXSecureParser instantiates when defusedxml is installed."""
        parser = _make_parser()
        assert parser is not None

    def test_instantiation_raises_when_defusedxml_missing(self, monkeypatch):
        """RuntimeError is raised at init when defusedxml is absent — NO fallback."""
        monkeypatch.setitem(
            sys.modules,
            "defusedxml",
            None,  # type: ignore[arg-type]
        )
        # Reload module with patched import
        with patch(
            "app.services.facturx_parser._DEFUSEDXML_AVAILABLE", False
        ):
            with pytest.raises(RuntimeError, match="defusedxml is REQUIRED"):
                FacturXSecureParser()


# ---------------------------------------------------------------------------
# Category 2 — XXE protection (4 tests)
# ---------------------------------------------------------------------------

class TestXXEProtection:
    def test_dtd_attack_blocked(self):
        """forbid_dtd: DTD declaration raises CRITICAL alert."""
        xml = b"""<?xml version="1.0"?>
<!DOCTYPE root [<!ELEMENT root ANY>]>
<root/>"""
        parser = _make_parser()
        result = ParseResult(success=False)
        parser._parse_xml_secure(xml, result)
        criticals = [a for a in result.alerts if a.level == AlertLevel.CRITICAL]
        assert criticals, "DTD should be blocked"
        assert any("xxe_protection" in a.layer for a in criticals)

    def test_entity_expansion_blocked(self):
        """forbid_entities: entity expansion raises CRITICAL alert."""
        xml = b"""<?xml version="1.0"?>
<!DOCTYPE root [<!ENTITY xxe "malicious">]>
<root>&xxe;</root>"""
        parser = _make_parser()
        result = ParseResult(success=False)
        parser._parse_xml_secure(xml, result)
        criticals = [a for a in result.alerts if a.level == AlertLevel.CRITICAL]
        assert criticals

    def test_external_entity_blocked(self):
        """forbid_external: external entity reference raises CRITICAL alert."""
        xml = b"""<?xml version="1.0"?>
<!DOCTYPE root [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<root>&xxe;</root>"""
        parser = _make_parser()
        result = ParseResult(success=False)
        parser._parse_xml_secure(xml, result)
        criticals = [a for a in result.alerts if a.level == AlertLevel.CRITICAL]
        assert criticals

    def test_valid_xml_parses_without_xxe_alert(self):
        """Clean XML produces no XXE-related alerts."""
        parser = _make_parser()
        result = _parse_xml_directly(parser, _minimal_valid_xml())
        xxe_alerts = [a for a in result.alerts if a.layer == "xxe_protection"]
        assert not xxe_alerts


# ---------------------------------------------------------------------------
# Category 3 — SQL injection detection (5 tests)
# ---------------------------------------------------------------------------

class TestSQLInjectionDetection:
    def test_union_select_in_invoice_id(self):
        xml = _minimal_valid_xml(
            extra_content="<hack>UNION SELECT * FROM users</hack>"
        )
        parser = _make_parser()
        result = _parse_xml_directly(parser, xml)
        layers = [a.layer for a in result.alerts if a.level == AlertLevel.CRITICAL]
        assert "sql_injection" in layers

    def test_drop_table_blocked(self):
        xml = _minimal_valid_xml(
            extra_content="<note>DROP TABLE invoices</note>"
        )
        parser = _make_parser()
        result = _parse_xml_directly(parser, xml)
        assert any(a.layer == "sql_injection" for a in result.alerts)

    def test_comment_injection_blocked(self):
        """SQL comment -- in content triggers detection."""
        xml = _minimal_valid_xml(
            extra_content="<ref>ABC' -- injected</ref>"
        )
        parser = _make_parser()
        result = _parse_xml_directly(parser, xml)
        assert any(a.layer == "sql_injection" for a in result.alerts)

    def test_exec_stored_procedure_blocked(self):
        xml = _minimal_valid_xml(
            extra_content="<cmd>EXEC(xp_cmdshell 'dir')</cmd>"
        )
        parser = _make_parser()
        result = _parse_xml_directly(parser, xml)
        assert any(a.layer == "sql_injection" for a in result.alerts)

    def test_clean_xml_no_sql_alert(self):
        """Normal invoice XML does not trigger SQL injection alerts."""
        parser = _make_parser()
        result = _parse_xml_directly(parser, _minimal_valid_xml())
        sql_alerts = [a for a in result.alerts if a.layer == "sql_injection"]
        assert not sql_alerts


# ---------------------------------------------------------------------------
# Category 4 — XSS detection (4 tests)
# ---------------------------------------------------------------------------

class TestXSSDetection:
    def test_script_tag_blocked(self):
        xml = _minimal_valid_xml(
            extra_content="<note><![CDATA[<script>alert(1)</script>]]></note>"
        )
        parser = _make_parser()
        result = _parse_xml_directly(parser, xml)
        assert any(a.layer == "xss_detection" for a in result.alerts)

    def test_javascript_uri_blocked(self):
        xml = _minimal_valid_xml(
            extra_content="<link>javascript:alert(document.cookie)</link>"
        )
        parser = _make_parser()
        result = _parse_xml_directly(parser, xml)
        assert any(a.layer == "xss_detection" for a in result.alerts)

    def test_onerror_event_blocked(self):
        xml = _minimal_valid_xml(
            extra_content='<img src="x" onerror="alert(1)"/>'
        )
        parser = _make_parser()
        result = _parse_xml_directly(parser, xml)
        assert any(a.layer == "xss_detection" for a in result.alerts)

    def test_clean_xml_no_xss_alert(self):
        parser = _make_parser()
        result = _parse_xml_directly(parser, _minimal_valid_xml())
        assert not any(a.layer == "xss_detection" for a in result.alerts)


# ---------------------------------------------------------------------------
# Category 5 — Path traversal detection (4 tests)
# ---------------------------------------------------------------------------

class TestPathTraversalDetection:
    def test_dot_dot_slash_blocked(self):
        xml = _minimal_valid_xml(
            extra_content="<path>../../etc/passwd</path>"
        )
        parser = _make_parser()
        result = _parse_xml_directly(parser, xml)
        assert any(a.layer == "path_traversal" for a in result.alerts)

    def test_encoded_traversal_blocked(self):
        xml = _minimal_valid_xml(
            extra_content="<ref>%2e%2e%2fetc%2fpasswd</ref>"
        )
        parser = _make_parser()
        result = _parse_xml_directly(parser, xml)
        assert any(a.layer == "path_traversal" for a in result.alerts)

    def test_etc_passwd_literal_blocked(self):
        xml = _minimal_valid_xml(
            extra_content="<file>/etc/passwd</file>"
        )
        parser = _make_parser()
        result = _parse_xml_directly(parser, xml)
        assert any(a.layer == "path_traversal" for a in result.alerts)

    def test_clean_path_no_alert(self):
        xml = _minimal_valid_xml(
            extra_content="<attachment>invoices/2024/inv-001.pdf</attachment>"
        )
        parser = _make_parser()
        result = _parse_xml_directly(parser, xml)
        assert not any(a.layer == "path_traversal" for a in result.alerts)


# ---------------------------------------------------------------------------
# Category 6 — Namespace validation (4 tests)
# ---------------------------------------------------------------------------

class TestNamespaceValidation:
    def test_allowed_namespaces_pass(self):
        """CII + RAM + UDT namespaces produce no namespace warnings."""
        parser = _make_parser()
        result = _parse_xml_directly(parser, _minimal_valid_xml())
        ns_warnings = [a for a in result.alerts if a.layer == "namespace_validation"]
        assert not ns_warnings

    def test_unknown_namespace_raises_warning(self):
        xml = _minimal_valid_xml(
            extra_ns='xmlns:evil="http://evil.example.com/inject"',
            extra_content='<evil:tag xmlns:evil="http://evil.example.com/inject">x</evil:tag>',
        )
        parser = _make_parser()
        result = _parse_xml_directly(parser, xml)
        ns_warnings = [a for a in result.alerts if a.layer == "namespace_validation"]
        assert ns_warnings
        assert any("evil.example.com" in a.message for a in ns_warnings)

    def test_ubl_namespace_allowed(self):
        """UBL Invoice-2 namespace is in ALLOWED_NAMESPACES."""
        assert "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" in ALLOWED_NAMESPACES

    def test_all_cii_namespaces_in_allowed_set(self):
        """All CII-related namespaces are present in ALLOWED_NAMESPACES."""
        assert _CII_NS in ALLOWED_NAMESPACES
        assert _RAM_NS in ALLOWED_NAMESPACES
        assert _UDT_NS in ALLOWED_NAMESPACES


# ---------------------------------------------------------------------------
# Category 7 — EN16931 required element validation (4 tests)
# ---------------------------------------------------------------------------

class TestEN16931Validation:
    def test_all_required_elements_present(self):
        """Complete XML passes EN16931 validation with no missing-element errors."""
        parser = _make_parser()
        result = _parse_xml_directly(parser, _minimal_valid_xml())
        en_errors = [a for a in result.alerts if a.layer == "en16931_validation"]
        assert not en_errors, f"Unexpected EN16931 errors: {en_errors}"

    def test_missing_seller_trade_party(self):
        """XML without SellerTradeParty triggers EN16931 error."""
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice
  xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
  xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100">
  <rsm:ExchangedDocumentContext/>
  <rsm:ExchangedDocument/>
  <rsm:SupplyChainTradeTransaction>
    <ram:BuyerTradeParty/>
    <ram:SpecifiedTradeSettlementHeaderMonetarySummation/>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>"""
        parser = _make_parser()
        result = _parse_xml_directly(parser, xml)
        messages = [a.message for a in result.alerts if a.layer == "en16931_validation"]
        assert any("SellerTradeParty" in m for m in messages)

    def test_required_elements_set_content(self):
        """REQUIRED_ELEMENTS contains the 6 expected local names."""
        assert "ExchangedDocumentContext" in REQUIRED_ELEMENTS
        assert "SellerTradeParty" in REQUIRED_ELEMENTS
        assert "BuyerTradeParty" in REQUIRED_ELEMENTS
        assert "SpecifiedTradeSettlementHeaderMonetarySummation" in REQUIRED_ELEMENTS
        assert len(REQUIRED_ELEMENTS) == 6

    def test_minimal_xml_missing_all_required_elements(self):
        """Bare-minimum XML triggers multiple EN16931 errors."""
        xml = b"""<?xml version="1.0"?><root/>"""
        parser = _make_parser()
        result = _parse_xml_directly(parser, xml)
        en_errors = [a for a in result.alerts if a.layer == "en16931_validation"]
        assert len(en_errors) == len(REQUIRED_ELEMENTS)


# ---------------------------------------------------------------------------
# Category 8 — _safe_decimal validation (7 tests)
# ---------------------------------------------------------------------------

class TestSafeDecimal:
    def setup_method(self):
        self.parser = _make_parser()
        self.result = ParseResult(success=False)

    def test_valid_positive_amount(self):
        val = self.parser._safe_decimal("1200.00", "test", self.result)
        assert val == Decimal("1200.00")
        assert not self.result.alerts

    def test_valid_negative_amount(self):
        val = self.parser._safe_decimal("-50.50", "discount", self.result)
        assert val == Decimal("-50.50")

    def test_nan_rejected(self):
        val = self.parser._safe_decimal("NaN", "field", self.result)
        assert val is None
        assert any("NaN" in a.message for a in self.result.alerts)

    def test_infinity_rejected(self):
        val = self.parser._safe_decimal("Infinity", "field", self.result)
        assert val is None
        assert any("Infinity" in a.message for a in self.result.alerts)

    def test_scientific_notation_rejected(self):
        val = self.parser._safe_decimal("1.2e5", "field", self.result)
        assert val is None
        assert any("Scientific notation" in a.message for a in self.result.alerts)

    def test_amount_over_999m_rejected(self):
        val = self.parser._safe_decimal("1000000001.00", "field", self.result)
        assert val is None
        assert any("999M" in a.message for a in self.result.alerts)

    def test_invalid_format_rejected(self):
        val = self.parser._safe_decimal("not-a-number", "field", self.result)
        assert val is None
        assert any("Invalid decimal" in a.message for a in self.result.alerts)


# ---------------------------------------------------------------------------
# Category 9 — Integration: parse returns correct structure (5 tests)
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_parse_result_has_alerts_list(self):
        parser = _make_parser()
        result = _parse_xml_directly(parser, _minimal_valid_xml())
        assert isinstance(result.alerts, list)

    def test_parse_result_data_contains_amounts(self):
        parser = _make_parser()
        result = _parse_xml_directly(parser, _minimal_valid_xml())
        assert result.data.get("amount_ht") == Decimal("1000.00")
        assert result.data.get("amount_ttc") == Decimal("1200.00")

    def test_parse_result_data_contains_invoice_number(self):
        parser = _make_parser()
        result = _parse_xml_directly(parser, _minimal_valid_xml())
        assert result.data.get("invoice_number") == "INV-2024-001"

    def test_critical_alert_sets_success_false(self):
        """A CRITICAL alert (SQL injection) keeps success=False."""
        xml = _minimal_valid_xml(extra_content="<hack>DROP TABLE users</hack>")
        parser = _make_parser()
        result = _parse_xml_directly(parser, xml)
        assert result.has_critical
        assert result.success is False

    def test_security_alert_str_representation(self):
        alert = SecurityAlert(
            level=AlertLevel.CRITICAL,
            layer="sql_injection",
            message="SQL injection pattern detected",
            detail="near column X",
        )
        s = str(alert)
        assert "CRITICAL" in s
        assert "sql_injection" in s
        assert "near column X" in s
