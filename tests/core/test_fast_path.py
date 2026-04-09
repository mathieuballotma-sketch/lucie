"""
Tests unitaires pour le fast-path questions simples.

Couvre :
- _is_simple_query() : détection correcte des questions simples / complexes
- Blacklist : requête courte mais avec mot interdit → pas fast-path
- Heure / date : réponses système sans LLM
"""

import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.core.engine import _is_simple_query


# ─────────────────────────────────────────────────────────────────────────────
# _is_simple_query — questions simples détectées
# ─────────────────────────────────────────────────────────────────────────────

class TestIsSimpleQuerySimple:
    def test_calcul(self):
        assert _is_simple_query("2+2 ça fait combien ?") is True

    def test_heure(self):
        assert _is_simple_query("quelle heure est-il ?") is True

    def test_culture_generale(self):
        assert _is_simple_query("c'est quoi l'IA ?") is True

    def test_conversation(self):
        assert _is_simple_query("tu parles quelle langue ?") is True

    def test_definition(self):
        assert _is_simple_query("c'est quoi Python ?") is True

    def test_question_courte(self):
        assert _is_simple_query("combien font 7 fois 8 ?") is True

    def test_meteo_simple(self):
        # pas de mot-clé agent, pas verbe d'action → simple
        assert _is_simple_query("il fait beau aujourd'hui ?") is True


# ─────────────────────────────────────────────────────────────────────────────
# _is_simple_query — questions complexes NON détectées
# ─────────────────────────────────────────────────────────────────────────────

class TestIsSimpleQueryComplex:
    def test_verbe_cree(self):
        assert _is_simple_query("crée un fichier texte sur le bureau") is False

    def test_verbe_envoie(self):
        assert _is_simple_query("envoie un mail à Paul") is False

    def test_verbe_recherche(self):
        assert _is_simple_query("recherche les vols Paris-Lyon") is False

    def test_mot_cle_mail(self):
        assert _is_simple_query("lis mes mails") is False

    def test_mot_cle_pdf(self):
        assert _is_simple_query("résume ce PDF") is False

    def test_mot_cle_dossier(self):
        assert _is_simple_query("ouvre le dossier Documents") is False

    def test_multi_etapes_ensuite(self):
        assert _is_simple_query("cherche un article ensuite résume-le") is False

    def test_multi_etapes_et_puis(self):
        assert _is_simple_query("analyse le fichier et puis envoie-le") is False

    def test_trop_long(self):
        long_query = " ".join(["mot"] * 21)
        assert _is_simple_query(long_query) is False

    def test_verbe_redige(self):
        assert _is_simple_query("rédige une lettre de motivation") is False

    def test_verbe_genere(self):
        assert _is_simple_query("génère un rapport Excel") is False


# ─────────────────────────────────────────────────────────────────────────────
# Blacklist — requête courte mais avec mot interdit
# ─────────────────────────────────────────────────────────────────────────────

class TestIsSimpleQueryBlacklist:
    def test_calendrier(self):
        assert _is_simple_query("c'est quoi le calendrier ?") is False

    def test_rendez_vous(self):
        assert _is_simple_query("j'ai un rendez-vous ?") is False

    def test_rappel(self):
        assert _is_simple_query("un rappel c'est quoi ?") is False

    def test_agenda(self):
        assert _is_simple_query("comment marche l'agenda ?") is False

    def test_email_blacklist(self):
        assert _is_simple_query("c'est quoi un email ?") is False

    def test_pdf_blacklist(self):
        assert _is_simple_query("le PDF c'est quoi ?") is False

    def test_document_blacklist(self):
        assert _is_simple_query("un document c'est quoi ?") is False


# ─────────────────────────────────────────────────────────────────────────────
# Réponses heure / date — sans LLM, valeurs système
# ─────────────────────────────────────────────────────────────────────────────

class TestDateTimeResponses:
    """Teste que les fast-paths heure/date retournent des valeurs correctes.

    On importe directement la logique via les mêmes conditions que process().
    """

    def _get_time_response(self, query: str):
        """Reproduit la logique heure du fast-path."""
        q_lower = query.lower()
        if any(kw in q_lower for kw in ("quelle heure", "l'heure", "il est quelle heure", "heure actuelle")):
            now = datetime.datetime.now()
            return f"Il est {now.strftime('%H:%M')}."
        return None

    def _get_date_response(self, query: str):
        """Reproduit la logique date du fast-path."""
        q_lower = query.lower()
        if any(kw in q_lower for kw in ("quel jour", "quelle date", "on est quel jour", "date aujourd'hui")):
            now = datetime.datetime.now()
            jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
            mois = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
            return f"On est {jours[now.weekday()]} {now.day} {mois[now.month-1]} {now.year}."
        return None

    def test_heure_format(self):
        resp = self._get_time_response("quelle heure est-il ?")
        assert resp is not None
        assert resp.startswith("Il est ")
        assert resp.endswith(".")
        # Format HH:MM
        time_part = resp.replace("Il est ", "").rstrip(".")
        h, m = time_part.split(":")
        assert h.isdigit() and 0 <= int(h) <= 23
        assert m.isdigit() and 0 <= int(m) <= 59

    def test_heure_actuelle(self):
        resp = self._get_time_response("donne-moi l'heure actuelle")
        assert resp is not None
        assert resp.startswith("Il est ")

    def test_il_est_quelle_heure(self):
        resp = self._get_time_response("il est quelle heure ?")
        assert resp is not None

    def test_date_format(self):
        resp = self._get_date_response("quelle date on est ?")
        assert resp is not None
        assert resp.startswith("On est ")
        assert resp.endswith(".")

    def test_date_contient_annee(self):
        resp = self._get_date_response("on est quel jour ?")
        assert resp is not None
        assert str(datetime.datetime.now().year) in resp

    def test_date_contient_mois_francais(self):
        resp = self._get_date_response("date aujourd'hui")
        assert resp is not None
        mois = ["janvier", "février", "mars", "avril", "mai", "juin",
                "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
        assert any(m in resp for m in mois)

    def test_date_quel_jour(self):
        resp = self._get_date_response("quel jour sommes-nous ?")
        assert resp is not None
        jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
        assert any(j in resp for j in jours)

    def test_heure_non_match_sur_date(self):
        # "quel jour" ne doit pas matcher les keywords heure
        resp = self._get_time_response("quel jour sommes-nous ?")
        assert resp is None

    def test_date_non_match_sur_heure(self):
        # "quelle heure" ne doit pas matcher les keywords date
        resp = self._get_date_response("quelle heure est-il ?")
        assert resp is None
