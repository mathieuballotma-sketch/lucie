"""Tests unitaires pour error_humanizer."""
import pytest
from app.utils.error_humanizer import humanize_error, _ERROR_MAP, _PATTERN_MAP


class TestExactMatch:
    """Chaque entrée du _ERROR_MAP est correctement traduite."""

    @pytest.mark.parametrize("technical,human", list(_ERROR_MAP.items()))
    def test_exact_error_map(self, technical, human):
        assert humanize_error(technical) == human

    def test_thalamus_indisponible(self):
        assert humanize_error("Aucun agent Thalamus disponible") == \
            "Je ne suis pas sûre de comprendre ta demande. Tu peux reformuler ?"

    def test_action_directe(self):
        assert humanize_error("Aucune action directe trouvee") == \
            "Je ne sais pas encore faire ça, mais je travaille dessus !"

    def test_pas_engine(self):
        assert humanize_error("Pas d'engine") == \
            "Je suis en train de démarrer, réessaie dans quelques secondes."

    def test_pas_engine_disponible(self):
        assert humanize_error("Pas d'engine disponible") == \
            "Je suis en train de démarrer, réessaie dans quelques secondes."


class TestPatternMatch:
    """Les patterns sont détectés (insensible à la casse)."""

    def test_timeout_lowercase(self):
        result = humanize_error("LLMTimeoutError: request timeout after 30s")
        assert result == "La requête a pris trop de temps. Réessaie, ça ira plus vite."

    def test_timeout_uppercase(self):
        result = humanize_error("TIMEOUT")
        assert result == "La requête a pris trop de temps. Réessaie, ça ira plus vite."

    def test_connection_refused(self):
        result = humanize_error("Error: Connection refused to localhost:11434")
        assert result == "Je n'arrive pas à me connecter au modèle IA. Vérifie qu'Ollama est lancé."

    def test_broken_pipe(self):
        result = humanize_error("OSError: Broken pipe")
        assert result == "La connexion au modèle a été interrompue. Je réessaie..."

    def test_model_not_found_takes_priority_over_not_found(self):
        # "model not found" doit matcher avant "not found"
        result = humanize_error("model not found: gemma4:e4b")
        assert result == "Le modèle IA n'est pas installé. Lance 'ollama pull gemma4:e4b' dans le terminal."

    def test_not_found(self):
        result = humanize_error("404 not found")
        assert result == "Le modèle IA demandé n'est pas installé. Lance 'ollama pull gemma4:e4b' dans le terminal."

    def test_out_of_memory(self):
        result = humanize_error("RuntimeError: out of memory on device cuda:0")
        assert result == "Pas assez de mémoire pour cette requête. Ferme quelques applications et réessaie."

    def test_connection_reset(self):
        result = humanize_error("ConnectionResetError: connection reset by peer")
        assert result == "La connexion au modèle a été réinitialisée. Je réessaie..."


class TestFallback:
    """Le fallback fonctionne pour les messages préfixés Erreur:/Error:."""

    def test_erreur_prefix_french(self):
        result = humanize_error("Erreur: quelque chose d'inattendu")
        assert result == "Quelque chose n'a pas fonctionné. Tu peux réessayer ou reformuler ta demande."

    def test_error_prefix_english(self):
        result = humanize_error("Error: something unexpected happened")
        assert result == "Quelque chose n'a pas fonctionné. Tu peux réessayer ou reformuler ta demande."

    def test_erreur_prefix_no_space(self):
        # "Erreur:" seul sans espace suivant — toujours un fallback
        result = humanize_error("Erreur:")
        assert result == "Quelque chose n'a pas fonctionné. Tu peux réessayer ou reformuler ta demande."


class TestPassthrough:
    """Les messages non-erreur passent tel quel."""

    def test_normal_response(self):
        msg = "Voici la réponse à ta question."
        assert humanize_error(msg) == msg

    def test_empty_string(self):
        assert humanize_error("") == ""

    def test_greeting(self):
        msg = "Bonjour ! Comment puis-je t'aider ?"
        assert humanize_error(msg) == msg

    def test_number_string(self):
        assert humanize_error("42") == "42"

    def test_unknown_technical_without_prefix(self):
        # Pas de préfixe Erreur:, pas de pattern → passthrough
        msg = "UnknownInternalState"
        assert humanize_error(msg) == msg
