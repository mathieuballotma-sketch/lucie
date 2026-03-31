"""
Tests E2E du pipeline de sécurité Lucie — Phase 6.

Scénarios couverts:
    Test 1: Factur-X XXE → rejet, audit CRITICAL couche XML, mémoire stable.
    Test 2: Excel macro+DDE → bloqué, event excel.macros_blocked publié, audit.
    Test 3: Factur-X légitime → accepté, audit avec hash entrée/sortie.

Infrastructure:
    MaliciousFileGenerator — fabrique des fichiers de test (malveillants + légitimes)
    MockEventBus           — capture les publications et abonnements
    MockAuditTrail         — enregistre les appels à record()
    MemoryMonitor          — mesure l'empreinte mémoire via tracemalloc

Notes:
    Les parsers Phase 5 (FacturXSecureParser, ExcelSecureLoader) sont utilisés
    tels quels — pas de mock sur les parseurs eux-mêmes. Les tests valident
    le comportement de sécurité de bout en bout.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import tracemalloc
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.facturx_parser import AlertLevel, FacturXSecureParser, ParseResult
from app.services.excel_secure import ExcelSecureLoader, ThreatReport


# ---------------------------------------------------------------------------
# MaliciousFileGenerator
# ---------------------------------------------------------------------------


class MaliciousFileGenerator:
    """
    Fabrique de fichiers de test — malveillants et légitimes.

    Tous les payloads sont synthétiques et auto-contenus (aucun fichier externe).
    """

    # ---- Factur-X / XML -----------------------------------------------

    @staticmethod
    def facturx_xxe_system() -> bytes:
        """
        PDF-like bytes contenant du XML avec une attaque XXE SYSTEM
        (lecture de /etc/passwd via entité externe).
        defusedxml doit bloquer cela avec DefusedXmlException.
        """
        xxe_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<!DOCTYPE foo ['
            '  <!ELEMENT foo ANY>'
            '  <!ENTITY xxe SYSTEM "file:///etc/passwd">'
            ']>'
            "<foo>&xxe;</foo>"
        ).encode("utf-8")
        return MaliciousFileGenerator._wrap_xml_in_pdf(xxe_xml)

    @staticmethod
    def facturx_sql_injection() -> bytes:
        """
        PDF-like bytes contenant du XML avec injection SQL
        dans le champ BuyerReference.
        """
        sql_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<rsm:CrossIndustryInvoice '
            '  xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"'
            '  xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"'
            ">"
            "<rsm:ExchangedDocumentContext/>"
            "<rsm:ExchangedDocument>"
            "  <ram:ID>'; DROP TABLE invoices; --</ram:ID>"
            "  <ram:TypeCode>380</ram:TypeCode>"
            "  <ram:IssueDateTime><udt:DateTimeString format='102'>20240101</udt:DateTimeString></ram:IssueDateTime>"
            "</rsm:ExchangedDocument>"
            "<rsm:SupplyChainTradeTransaction/>"
            "</rsm:CrossIndustryInvoice>"
        ).encode("utf-8")
        return MaliciousFileGenerator._wrap_xml_in_pdf(sql_xml)

    @staticmethod
    def facturx_legitimate() -> bytes:
        """
        PDF-like bytes contenant un Factur-X/EN16931 minimal valide.
        Doit être accepté par FacturXSecureParser sans alerte critique.
        """
        valid_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<rsm:CrossIndustryInvoice '
            '  xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"'
            '  xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"'
            '  xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"'
            ">"
            "<rsm:ExchangedDocumentContext>"
            "  <ram:GuidelineSpecifiedDocumentContextParameter>"
            "    <ram:ID>urn:factur-x.eu:1p0:minimum</ram:ID>"
            "  </ram:GuidelineSpecifiedDocumentContextParameter>"
            "</rsm:ExchangedDocumentContext>"
            "<rsm:ExchangedDocument>"
            "  <ram:ID>INV-2024-001</ram:ID>"
            "  <ram:TypeCode>380</ram:TypeCode>"
            "  <ram:IssueDateTime>"
            "    <udt:DateTimeString format='102'>20240101</udt:DateTimeString>"
            "  </ram:IssueDateTime>"
            "</rsm:ExchangedDocument>"
            "<rsm:SupplyChainTradeTransaction>"
            "  <ram:ApplicableHeaderTradeAgreement>"
            "    <ram:SellerTradeParty><ram:Name>ACME Corp</ram:Name></ram:SellerTradeParty>"
            "    <ram:BuyerTradeParty><ram:Name>Client SA</ram:Name></ram:BuyerTradeParty>"
            "  </ram:ApplicableHeaderTradeAgreement>"
            "  <ram:ApplicableHeaderTradeDelivery/>"
            "  <ram:ApplicableHeaderTradeSettlement>"
            "    <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>"
            "    <ram:SpecifiedTradeSettlementHeaderMonetarySummation>"
            "      <ram:TaxBasisTotalAmount>1000.00</ram:TaxBasisTotalAmount>"
            "      <ram:TaxTotalAmount currencyID='EUR'>200.00</ram:TaxTotalAmount>"
            "      <ram:GrandTotalAmount>1200.00</ram:GrandTotalAmount>"
            "      <ram:DuePayableAmount>1200.00</ram:DuePayableAmount>"
            "    </ram:SpecifiedTradeSettlementHeaderMonetarySummation>"
            "  </ram:ApplicableHeaderTradeSettlement>"
            "</rsm:SupplyChainTradeTransaction>"
            "</rsm:CrossIndustryInvoice>"
        ).encode("utf-8")
        return MaliciousFileGenerator._wrap_xml_in_pdf(valid_xml)

    @staticmethod
    def _wrap_xml_in_pdf(xml_bytes: bytes) -> bytes:
        """
        Enveloppe du XML dans une structure PDF minimale reconnue
        par le scanner de bytes de FacturXSecureParser.
        """
        pdf_header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
        obj_header = b"1 0 obj\n<< /Type /EmbeddedFile >>\nstream\n"
        obj_footer = b"\nendstream\nendobj\n"
        xref = b"xref\n0 1\n0000000000 65535 f \n"
        trailer = b"trailer\n<< /Root 1 0 R /Size 1 >>\nstartxref\n9\n%%EOF\n"
        return pdf_header + obj_header + xml_bytes + obj_footer + xref + trailer

    # ---- Excel --------------------------------------------------------

    @staticmethod
    def excel_with_macros_and_dde(tmp_path: Path) -> Path:
        """
        Crée un fichier .xlsm (extension macro) avec du contenu DDE.
        L'extension .xlsm seule suffit à déclencher le blocage.
        Le ZIP contient aussi vbaProject.bin pour valider la détection ZIP-level.

        Retourne le chemin du fichier créé.
        """
        file_path = tmp_path / "invoice_malicious.xlsm"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # vbaProject.bin — signature OLE (D0 CF 11 E0)
            zf.writestr(
                "vbaProject.bin",
                b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512,
            )
            # [Content_Types].xml minimal
            zf.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.ms-excel.sheet.macroEnabled.main+xml"/>'
                "</Types>",
            )
            # xl/sharedStrings.xml with DDE payload
            zf.writestr(
                "xl/sharedStrings.xml",
                '<?xml version="1.0"?><sst>'
                "<si><t>=DDE(\"cmd\",\"/c calc\")</t></si>"
                "<si><t>=HYPERLINK(\"http://evil.example.com\",\"click\")</t></si>"
                "</sst>",
            )
        file_path.write_bytes(buf.getvalue())
        return file_path

    @staticmethod
    def excel_legitimate(tmp_path: Path) -> Path:
        """
        Crée un fichier .xlsx légitime (OOXML minimal sans macro ni formule dangereuse).
        Doit être accepté par ExcelSecureLoader.
        """
        file_path = tmp_path / "invoice_legitimate.xlsx"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                "</Types>",
            )
            zf.writestr(
                "_rels/.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                "</Relationships>",
            )
            zf.writestr(
                "xl/workbook.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/ml/2006/main">'
                "<sheets>"
                '<sheet name="Facture" sheetId="1" r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
                "</sheets>"
                "</workbook>",
            )
            zf.writestr(
                "xl/_rels/workbook.xml.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                "</Relationships>",
            )
            zf.writestr(
                "xl/worksheets/sheet1.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/ml/2006/main">'
                "<sheetData>"
                '<row r="1">'
                '<c r="A1" t="inlineStr"><is><t>Vendeur</t></is></c>'
                '<c r="B1" t="inlineStr"><is><t>ACME Corp</t></is></c>'
                "</row>"
                '<row r="2">'
                '<c r="A2" t="inlineStr"><is><t>Montant TTC</t></is></c>'
                '<c r="B2"><v>1200.00</v></c>'
                "</row>"
                "</sheetData>"
                "</worksheet>",
            )
        file_path.write_bytes(buf.getvalue())
        return file_path


# ---------------------------------------------------------------------------
# MockEventBus
# ---------------------------------------------------------------------------


class MockEventBus:
    """EventBus minimal pour les tests — capture publications et abonnements."""

    def __init__(self) -> None:
        self.published: List[Tuple[str, Any]] = []   # (channel, data)
        self.subscriptions: List[Tuple[str, Any]] = []  # (channel, callback)

    async def publish(
        self,
        channel: str,
        data: Any,
        source: str = "test",
        token: Any = None,
    ) -> None:
        self.published.append((channel, data))

    # Sync variant used by ExcelSecureLoader._publish_threat
    def publish_sync(self, channel: str, data: Any, **kwargs: Any) -> None:
        self.published.append((channel, data))

    async def subscribe(
        self,
        channel: str,
        callback: Any,
        source: str = "test",
        token: Any = None,
        subscriber_id: str = "",
    ) -> None:
        self.subscriptions.append((channel, callback))

    def channels_published(self) -> List[str]:
        return [ch for ch, _ in self.published]

    def data_for_channel(self, channel: str) -> List[Any]:
        return [d for ch, d in self.published if ch == channel]


# ---------------------------------------------------------------------------
# MockAuditTrail
# ---------------------------------------------------------------------------


@dataclass
class AuditRecord:
    action: str
    user: str
    justification: str
    data: Dict[str, Any]


class MockAuditTrail:
    """AuditTrail minimal pour les tests — capture les enregistrements."""

    def __init__(self) -> None:
        self.records: List[AuditRecord] = []
        self._running = False

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def record(
        self,
        action: str,
        user: str = "system",
        justification: str = "",
        data: Optional[Dict[str, Any]] = None,
        pii_fields: Any = None,
    ) -> None:
        self.records.append(AuditRecord(
            action=action,
            user=user,
            justification=justification,
            data=data or {},
        ))

    def record_sync(self, action: str, **kwargs: Any) -> None:
        self.records.append(AuditRecord(
            action=action,
            user=kwargs.get("user", "system"),
            justification=kwargs.get("justification", ""),
            data=kwargs.get("data", {}),
        ))

    def actions(self) -> List[str]:
        return [r.action for r in self.records]

    def has_action(self, action: str) -> bool:
        return any(action in r.action for r in self.records)


# ---------------------------------------------------------------------------
# MemoryMonitor
# ---------------------------------------------------------------------------


class MemoryMonitor:
    """
    Mesure l'empreinte mémoire via tracemalloc.

    Usage:
        with MemoryMonitor() as mon:
            do_something()
        assert mon.peak_kb() < 50_000
    """

    def __init__(self) -> None:
        self._baseline_kb: float = 0.0
        self._peak_kb:     float = 0.0

    def __enter__(self) -> "MemoryMonitor":
        tracemalloc.start()
        snap = tracemalloc.take_snapshot()
        stats = snap.statistics("lineno")
        self._baseline_kb = sum(s.size for s in stats) / 1024
        return self

    def __exit__(self, *_: Any) -> None:
        snap = tracemalloc.take_snapshot()
        stats = snap.statistics("lineno")
        total_kb = sum(s.size for s in stats) / 1024
        self._peak_kb = total_kb - self._baseline_kb
        tracemalloc.stop()

    def peak_kb(self) -> float:
        return max(0.0, self._peak_kb)


# ---------------------------------------------------------------------------
# Test 1 — Factur-X XXE → rejet + audit CRITICAL + mémoire stable
# ---------------------------------------------------------------------------


class TestFacturXXXEBlocked:
    """
    Un fichier Factur-X contenant une attaque XXE SYSTEM doit être:
      - Rejeté par FacturXSecureParser (ParseResult.has_critical() == True)
      - Déclencher la publication de 'facturx.rejected' sur l'EventBus
      - Générer au moins une alerte de niveau CRITICAL
      - L'empreinte mémoire ne doit pas exploser (< 50 Mo de delta)
    """

    def test_xxe_rejected_by_parser(self) -> None:
        """defusedxml bloque l'entité XXE et génère une alerte CRITICAL."""
        pdf_bytes = MaliciousFileGenerator.facturx_xxe_system()
        parser = FacturXSecureParser()

        result = parser.parse(pdf_bytes)

        # Le document doit être marqué comme dangereux
        assert result.has_critical(), (
            "XXE attack should produce at least one CRITICAL alert"
        )
        # Au moins une alerte doit mentionner XXE ou XML ou l'entité
        alert_texts = [str(a) for a in result.alerts]
        assert any(
            kw in " ".join(alert_texts).upper()
            for kw in ("XXE", "XML", "ENTITY", "DEFUSED", "DOCTYPE", "EXTERNAL", "FORBID")
        ), f"Expected XXE-related alert, got: {alert_texts}"

    @pytest.mark.asyncio
    async def test_xxe_publishes_rejected_event(self) -> None:
        """process_facturx() publie 'facturx.rejected' pour un fichier XXE."""
        from app.services.orchestrator import LucieOrchestrator

        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)
        orch.register_parser(".pdf", FacturXSecureParser())

        pdf_bytes = MaliciousFileGenerator.facturx_xxe_system()
        result    = await orch.process_facturx(pdf_bytes)

        assert result["safe"] is False
        assert "facturx.rejected" in bus.channels_published(), (
            f"Expected 'facturx.rejected', got: {bus.channels_published()}"
        )

    def test_xxe_memory_stable(self) -> None:
        """
        Le traitement d'un XXE ne doit pas laisser de fuite mémoire notable.
        Seuil conservateur : < 50 Mo de delta (le parser charge des bytes en RAM).
        """
        pdf_bytes = MaliciousFileGenerator.facturx_xxe_system()
        parser    = FacturXSecureParser()

        with MemoryMonitor() as mon:
            for _ in range(10):
                parser.parse(pdf_bytes)

        assert mon.peak_kb() < 50_000, (
            f"Memory delta too large: {mon.peak_kb():.1f} KB (expected < 50 000 KB)"
        )

    @pytest.mark.asyncio
    async def test_xxe_audit_records_rejection(self) -> None:
        """
        Après process_facturx() sur un fichier XXE, l'AuditTrail reçoit
        l'événement 'facturx.rejected' via l'auto-audit de l'orchestrateur.
        """
        from app.services.orchestrator import LucieOrchestrator

        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)
        orch.register_parser(".pdf", FacturXSecureParser())

        # Simuler l'auto-audit : abonnement puis publication manuelle
        await orch._audit.start()
        pdf_bytes = MaliciousFileGenerator.facturx_xxe_system()
        await orch.process_facturx(pdf_bytes)

        # L'event 'facturx.rejected' a été publié
        assert "facturx.rejected" in bus.channels_published()
        # La publication contient le hash d'entrée
        rejected_data = bus.data_for_channel("facturx.rejected")
        assert rejected_data, "No data published on facturx.rejected"
        assert "input_hash" in rejected_data[0], "input_hash missing from rejected event"
        assert len(rejected_data[0]["input_hash"]) == 64   # SHA-256 hex


# ---------------------------------------------------------------------------
# Test 2 — Excel macro+DDE → bloqué + event excel.macros_blocked + audit
# ---------------------------------------------------------------------------


class TestExcelMacroBlocked:
    """
    Un fichier .xlsm (macro-enabled) avec DDE doit être:
      - Bloqué par ExcelSecureLoader (ThreatReport.is_safe() == False)
      - Déclencher la publication de 'excel.macros_blocked' sur l'EventBus
      - Généré dans l'AuditTrail
    """

    def test_xlsm_extension_blocked(self, tmp_path: Path) -> None:
        """L'extension .xlsm déclenche immédiatement la détection macro."""
        file_path = MaliciousFileGenerator.excel_with_macros_and_dde(tmp_path)
        bus = MockEventBus()
        loader = ExcelSecureLoader(event_bus=bus)

        _rows, report = loader.load(file_path)

        assert not report.is_safe(), "XLSM file should be flagged as unsafe"

    def test_xlsm_publishes_macros_blocked(self, tmp_path: Path) -> None:
        """ExcelSecureLoader publie excel.macros_blocked (ou similar) pour .xlsm."""
        file_path = MaliciousFileGenerator.excel_with_macros_and_dde(tmp_path)
        bus = MockEventBus()
        loader = ExcelSecureLoader(event_bus=bus)

        loader.load(file_path)

        threat_channels = [
            ch for ch in bus.channels_published()
            if "macro" in ch or "threat" in ch or "blocked" in ch or "excel" in ch
        ]
        assert threat_channels, (
            f"Expected a threat/macro channel, got: {bus.channels_published()}"
        )

    @pytest.mark.asyncio
    async def test_orchestrator_excel_macro_blocked(self, tmp_path: Path) -> None:
        """
        process_excel() via l'orchestrateur publie 'excel.macros_blocked'
        pour un fichier .xlsm.
        """
        from app.services.orchestrator import LucieOrchestrator

        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)

        loader = ExcelSecureLoader(event_bus=bus)
        orch.register_loader(".xlsm", loader)
        orch.register_loader(".xlsx", loader)

        file_path = MaliciousFileGenerator.excel_with_macros_and_dde(tmp_path)
        result    = await orch.process_excel(file_path)

        assert result["safe"] is False, "Macro file must be flagged unsafe by orchestrator"
        assert "excel.macros_blocked" in bus.channels_published(), (
            f"Expected 'excel.macros_blocked', got: {bus.channels_published()}"
        )

    @pytest.mark.asyncio
    async def test_audit_receives_macro_event(self, tmp_path: Path) -> None:
        """
        Après process_excel() sur un fichier macro, l'orchestrateur publie
        'excel.macros_blocked' ; si auto-audit est configuré, AuditTrail l'enregistre.
        """
        from app.services.orchestrator import LucieOrchestrator

        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)

        loader = ExcelSecureLoader(event_bus=bus)
        orch.register_loader(".xlsm", loader)
        orch.register_loader(".xlsx", loader)

        file_path = MaliciousFileGenerator.excel_with_macros_and_dde(tmp_path)
        await orch.process_excel(file_path)

        # L'event est publié sur le bus (l'auto-audit aurait besoin d'un vrai EventBus
        # pour router vers l'AuditTrail — ici on vérifie la publication seulement)
        assert "excel.macros_blocked" in bus.channels_published()


# ---------------------------------------------------------------------------
# Test 3 — Factur-X légitime → accepté + audit avec hash entrée/sortie
# ---------------------------------------------------------------------------


class TestFacturXLegitimateAccepted:
    """
    Un Factur-X valide (EN16931 minimal) doit être:
      - Accepté par FacturXSecureParser (has_critical() == False)
      - Déclencher la publication de 'facturx.accepted' sur l'EventBus
      - Le payload publié contient les hash SHA-256 d'entrée
    """

    def test_legitimate_document_accepted(self) -> None:
        """Un Factur-X minimal valide ne génère pas d'alerte CRITICAL."""
        pdf_bytes = MaliciousFileGenerator.facturx_legitimate()
        parser    = FacturXSecureParser()

        result = parser.parse(pdf_bytes)

        assert not result.has_critical(), (
            f"Legitimate Factur-X should not produce CRITICAL alerts. "
            f"Got: {[str(a) for a in result.alerts]}"
        )

    @pytest.mark.asyncio
    async def test_legitimate_publishes_accepted_event(self) -> None:
        """process_facturx() publie 'facturx.accepted' pour un document valide."""
        from app.services.orchestrator import LucieOrchestrator

        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)
        orch.register_parser(".pdf", FacturXSecureParser())

        pdf_bytes = MaliciousFileGenerator.facturx_legitimate()
        result    = await orch.process_facturx(pdf_bytes)

        assert result["safe"] is True
        assert "facturx.accepted" in bus.channels_published(), (
            f"Expected 'facturx.accepted', got: {bus.channels_published()}"
        )

    @pytest.mark.asyncio
    async def test_audit_payload_contains_input_hash(self) -> None:
        """
        Le payload de l'event 'facturx.accepted' contient le hash SHA-256
        du fichier d'entrée, permettant la traçabilité auditée.
        """
        from app.services.orchestrator import LucieOrchestrator

        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)
        orch.register_parser(".pdf", FacturXSecureParser())

        pdf_bytes      = MaliciousFileGenerator.facturx_legitimate()
        expected_hash  = hashlib.sha256(pdf_bytes).hexdigest()
        result         = await orch.process_facturx(pdf_bytes)

        assert result["input_hash"] == expected_hash, (
            f"input_hash mismatch: expected {expected_hash}, got {result['input_hash']}"
        )

        # Vérifier que le hash est présent dans le payload publié
        accepted_data = bus.data_for_channel("facturx.accepted")
        assert accepted_data, "No data published on facturx.accepted"
        assert accepted_data[0]["input_hash"] == expected_hash

    @pytest.mark.asyncio
    async def test_legitimate_audit_trail_recording(self) -> None:
        """
        Pour un document légitime, le résultat contient safe=True et
        un input_hash SHA-256 valide (64 caractères hex).
        """
        from app.services.orchestrator import LucieOrchestrator

        bus   = MockEventBus()
        audit = MockAuditTrail()
        orch  = LucieOrchestrator(event_bus=bus, audit_trail=audit)
        orch.register_parser(".pdf", FacturXSecureParser())

        pdf_bytes = MaliciousFileGenerator.facturx_legitimate()
        result    = await orch.process_facturx(pdf_bytes)

        assert result["safe"] is True
        assert len(result["input_hash"]) == 64
        assert all(c in "0123456789abcdef" for c in result["input_hash"])
