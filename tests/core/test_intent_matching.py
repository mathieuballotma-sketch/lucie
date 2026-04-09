"""
Tests unitaires pour le matching d'intention : mac_query et fast-path.

Couvre :
- _is_mac_action() : détection fuzzy des commandes système macOS
- _is_simple_query() : les commandes système ne doivent PAS bypasser le pipeline
"""

import pytest

from app.brain.cortex import _is_mac_action
from app.core.engine import _is_simple_query


# ─────────────────────────────────────────────────────────────────────────────
# _is_mac_action — commandes reconnues comme mac_query
# ─────────────────────────────────────────────────────────────────────────────

class TestIsMacActionPositif:
    def test_ouvre_mail(self):
        assert _is_mac_action("ouvre mail") is True

    def test_ouvr_mail_faute(self):
        """Faute de frappe : 'ouvr' doit être fuzzy-matché vers 'ouvre'."""
        assert _is_mac_action("ouvr mail") is True

    def test_lance_safari(self):
        assert _is_mac_action("lance safari") is True

    def test_ouvre_moi_mes_mails(self):
        assert _is_mac_action("ouvre moi mes mails") is True

    def test_va_sur_mail(self):
        assert _is_mac_action("va sur mail") is True

    def test_demarre_notes(self):
        assert _is_mac_action("démarre notes") is True

    def test_montre_safari(self):
        assert _is_mac_action("montre safari") is True

    def test_ferme_chrome(self):
        assert _is_mac_action("ferme chrome") is True

    def test_quitte_slack(self):
        assert _is_mac_action("quitte slack") is True

    def test_ouvre_finder(self):
        assert _is_mac_action("ouvre finder") is True

    def test_lance_terminal(self):
        assert _is_mac_action("lance terminal") is True

    def test_case_insensitive(self):
        assert _is_mac_action("Ouvre Mail") is True


# ─────────────────────────────────────────────────────────────────────────────
# _is_mac_action — requêtes qui NE doivent PAS matcher mac_query
# ─────────────────────────────────────────────────────────────────────────────

class TestIsMacActionNegatif:
    def test_quelle_heure_il_est(self):
        assert _is_mac_action("quelle heure il est") is False

    def test_question_simple(self):
        assert _is_mac_action("c'est quoi Python ?") is False

    def test_calcul(self):
        assert _is_mac_action("2+2 ça fait combien") is False

    def test_bonjour(self):
        assert _is_mac_action("bonjour") is False

    def test_envoie_mail(self):
        # "envoie" n'est pas un stem mac_action
        assert _is_mac_action("envoie un mail à Paul") is False

    def test_lis_mes_mails(self):
        # "lis" n'est pas un stem mac_action
        assert _is_mac_action("lis mes mails") is False

    def test_requete_vide(self):
        assert _is_mac_action("") is False


# ─────────────────────────────────────────────────────────────────────────────
# _is_simple_query — commandes système NE doivent PAS passer en fast-path
# ─────────────────────────────────────────────────────────────────────────────

class TestSimpleQuerySystemActions:
    def test_ouvre_mail_not_simple(self):
        assert _is_simple_query("ouvre mail") is False

    def test_ouvr_mail_not_simple(self):
        """'ouvr' doit bloquer le fast-path (blacklist 'mail' ou ACTION_VERBS 'ouvr')."""
        assert _is_simple_query("ouvr mail") is False

    def test_lance_safari_not_simple(self):
        assert _is_simple_query("lance safari") is False

    def test_demarre_notes_not_simple(self):
        assert _is_simple_query("démarre notes") is False

    def test_ferme_chrome_not_simple(self):
        assert _is_simple_query("ferme chrome") is False

    def test_quitte_slack_not_simple(self):
        assert _is_simple_query("quitte slack") is False

    def test_quelle_heure_is_simple(self):
        """Les questions simples restent dans le fast-path."""
        assert _is_simple_query("quelle heure il est") is True

    def test_question_courte_is_simple(self):
        assert _is_simple_query("c'est quoi l'IA ?") is True
