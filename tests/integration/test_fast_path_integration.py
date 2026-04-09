"""
Tests d'intégration pour le fast-path end-to-end.
Teste la détection, la blacklist et la performance.
"""
import time

import pytest

from app.core.engine import (
    _check_greeting,
    _check_capabilities,
    _is_simple_query,
    _GREETING_CACHE,
    _CAPABILITY_KEYWORDS,
    _SIMPLE_QUERY_BLACKLIST,
    _ACTION_VERBS,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fast-path activé — questions simples
# ─────────────────────────────────────────────────────────────────────────────

class TestSimpleQueriesDetected:
    def test_ca_va(self):
        assert _is_simple_query("ça va ?") is True

    def test_merci(self):
        assert _is_simple_query("merci") is True

    def test_ok(self):
        assert _is_simple_query("ok") is True

    def test_question_courte(self):
        assert _is_simple_query("c'est quoi Python ?") is True

    def test_calcul(self):
        assert _is_simple_query("2 + 2 ça fait combien ?") is True

    def test_question_langue(self):
        assert _is_simple_query("tu parles quelle langue ?") is True

    def test_definition_ia(self):
        assert _is_simple_query("c'est quoi l'IA ?") is True

    def test_heure(self):
        assert _is_simple_query("quelle heure est-il ?") is True

    def test_date(self):
        assert _is_simple_query("on est quel jour ?") is True


# ─────────────────────────────────────────────────────────────────────────────
# Fast-path désactivé — questions complexes
# ─────────────────────────────────────────────────────────────────────────────

class TestComplexQueriesNotSimple:
    def test_organise_fichiers(self):
        assert _is_simple_query("organise mes fichiers par date dans le dossier Documents") is False

    def test_envoie_mail(self):
        assert _is_simple_query("envoie un mail à Paul") is False

    def test_cree_fichier(self):
        assert _is_simple_query("crée un fichier texte sur le bureau") is False

    def test_question_trop_longue(self):
        long_query = " ".join(["mot"] * 25)
        assert _is_simple_query(long_query) is False

    def test_multi_step_puis(self):
        assert _is_simple_query("recherche Python et puis crée un résumé") is False


# ─────────────────────────────────────────────────────────────────────────────
# Blacklist — pas de fast-path même si la requête est courte
# ─────────────────────────────────────────────────────────────────────────────

class TestBlacklist:
    def test_rendez_vous_blacklisted(self):
        assert _is_simple_query("prends un rendez-vous") is False

    def test_calendrier_blacklisted(self):
        assert _is_simple_query("ouvre le calendrier") is False

    def test_rappel_blacklisted(self):
        assert _is_simple_query("crée un rappel") is False

    def test_mail_blacklisted(self):
        assert _is_simple_query("lis mon mail") is False

    def test_pdf_blacklisted(self):
        assert _is_simple_query("ouvre ce pdf") is False

    def test_agenda_blacklisted(self):
        assert _is_simple_query("mon agenda du jour") is False

    def test_document_blacklisted(self):
        assert _is_simple_query("lis ce document") is False

    def test_fichier_blacklisted(self):
        # "fichier" est dans _AGENT_KEYWORDS et _SIMPLE_QUERY_BLACKLIST
        assert _is_simple_query("ouvre ce fichier") is False

    def test_all_blacklist_keywords_work(self):
        """Chaque mot de la blacklist doit bloquer le fast-path."""
        for kw in _SIMPLE_QUERY_BLACKLIST:
            query = f"teste {kw} maintenant"
            assert _is_simple_query(query) is False, f"Blacklist failed for: {kw!r}"


# ─────────────────────────────────────────────────────────────────────────────
# Détection heure / date
# ─────────────────────────────────────────────────────────────────────────────

class TestTimeDateDetection:
    def test_quelle_heure_is_simple(self):
        assert _is_simple_query("quelle heure est-il ?") is True

    def test_heure_actuelle_is_simple(self):
        assert _is_simple_query("quelle est l'heure actuelle ?") is True

    def test_quel_jour_is_simple(self):
        assert _is_simple_query("quel jour sommes-nous ?") is True

    def test_quelle_date_is_simple(self):
        assert _is_simple_query("quelle date aujourd'hui ?") is True

    def test_time_keywords_match(self):
        """Les mots-clés temps/date sont bien dans les requêtes simples."""
        time_queries = [
            "quelle heure est-il",
            "l'heure actuelle",
            "il est quelle heure",
        ]
        for q in time_queries:
            assert _is_simple_query(q) is True, f"Expected simple: {q!r}"


# ─────────────────────────────────────────────────────────────────────────────
# Salutations — check_greeting
# ─────────────────────────────────────────────────────────────────────────────

class TestGreetingDetection:
    def test_bonjour_exact(self):
        result = _check_greeting("bonjour")
        assert result is not None
        assert result in _GREETING_CACHE["bonjour"]

    def test_bonjour_with_punctuation(self):
        result = _check_greeting("bonjour!")
        assert result is not None

    def test_merci_exact(self):
        result = _check_greeting("merci")
        assert result is not None

    def test_ca_va_exact(self):
        result = _check_greeting("ça va")
        assert result is not None

    def test_ok_exact(self):
        result = _check_greeting("ok")
        assert result is not None

    def test_non_greeting_returns_none(self):
        assert _check_greeting("organise mes fichiers") is None
        assert _check_greeting("cherche Python") is None
        assert _check_greeting("ouvre mon agenda") is None

    def test_fuzzy_match_typo(self):
        """Matching flou attrape les typos."""
        result = _check_greeting("bonjourr")  # typo
        assert result is not None

    def test_all_cache_keys_return_responses(self):
        """Chaque clé de _GREETING_CACHE doit retourner une réponse."""
        for key in _GREETING_CACHE:
            result = _check_greeting(key)
            assert result is not None, f"No response for greeting: {key!r}"
            assert result in _GREETING_CACHE[key]


# ─────────────────────────────────────────────────────────────────────────────
# Capacités — check_capabilities
# ─────────────────────────────────────────────────────────────────────────────

class TestCapabilityDetection:
    def test_que_sais_tu_faire(self):
        result = _check_capabilities("que sais-tu faire ?")
        assert result is not None
        assert "Fichiers" in result

    def test_tes_capacites(self):
        result = _check_capabilities("quelles sont tes capacités ?")
        assert result is not None

    def test_tu_peux_faire_quoi(self):
        result = _check_capabilities("tu peux faire quoi ?")
        assert result is not None

    def test_non_capability_returns_none(self):
        assert _check_capabilities("organise mes fichiers") is None
        assert _check_capabilities("quelle heure est-il") is None


# ─────────────────────────────────────────────────────────────────────────────
# Performance — fast-path < 100ms (code seul, sans LLM)
# ─────────────────────────────────────────────────────────────────────────────

class TestFastPathPerformance:
    def test_check_greeting_under_100ms(self):
        start = time.perf_counter()
        for _ in range(1000):
            _check_greeting("bonjour")
        elapsed_per_call = (time.perf_counter() - start) / 1000
        assert elapsed_per_call < 0.1, f"_check_greeting trop lent: {elapsed_per_call*1000:.2f}ms"

    def test_check_capabilities_under_100ms(self):
        start = time.perf_counter()
        for _ in range(1000):
            _check_capabilities("que sais-tu faire ?")
        elapsed_per_call = (time.perf_counter() - start) / 1000
        assert elapsed_per_call < 0.1

    def test_is_simple_query_under_100ms(self):
        start = time.perf_counter()
        for _ in range(1000):
            _is_simple_query("ça va ?")
        elapsed_per_call = (time.perf_counter() - start) / 1000
        assert elapsed_per_call < 0.1

    def test_greeting_single_call_under_1ms(self):
        start = time.perf_counter()
        _check_greeting("bonjour")
        elapsed = time.perf_counter() - start
        assert elapsed < 0.001, f"Un seul appel trop lent: {elapsed*1000:.2f}ms"
