"""
SafariResearchWorkflow — Navigation visible étape par étape dans Safari.

Orchestre ComputerControlAgent directement sans LLM planner.
Chaque étape est visible : un observateur voit Safari s'ouvrir,
les résultats Google apparaître, chaque site se charger, puis
la synthèse se coller dans Pages.

Workflow :
1. Ouvre Safari → recherche Google (nouvel onglet)
2. Extrait les 3 premiers liens via JavaScript
3. Visite chaque site UN PAR UN (nouvel onglet, pause visible)
4. Synthèse qwen2.5:7b
5. Ouvre Pages → colle la synthèse formatée
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.parse
from typing import Any, Callable, List, Optional

from app.agents.speed_config import ACTIVE_PROFILE
from app.utils.logger import logger


# ── Prompts dynamiques par fréquence Thalamus ────────────────────────────────

EXTRACTION_PROMPTS = {
    "finance_query": (
        "Tu extrais UNIQUEMENT depuis ce contenu web sur le sujet '{subject}' :\n"
        "- prix actuel\n- date et heure de la cotation\n"
        "- variation hausse ou baisse en %\n- devise\n"
        'Réponds en JSON strict sans markdown :\n'
        '{{"price": "", "date": "", "change": "", "currency": ""}}\n'
        "Si information absente → null."
    ),
    "code_query": (
        "Tu extrais UNIQUEMENT depuis ce contenu web sur le sujet '{subject}' :\n"
        "- langage concerné\n- problème ou concept principal\n"
        "- solution ou explication clé\n- exemple de code si présent\n"
        'Réponds en JSON strict sans markdown :\n'
        '{{"language": "", "issue": "", "solution": "", "example": ""}}'
    ),
    "research_query": (
        "Tu extrais UNIQUEMENT depuis ce contenu web sur le sujet '{subject}' :\n"
        "- fait principal vérifiable\n- chiffres et dates clés\n"
        "- source et contexte\n- conclusion principale\n"
        'Réponds en JSON strict sans markdown :\n'
        '{{"main_fact": "", "data": [], "context": "", "conclusion": ""}}'
    ),
    "general_query": (
        "Sur le sujet '{subject}', extrais depuis ce contenu web :\n"
        "- information principale\n- faits vérifiables max 3\n- conclusion\n"
        'Réponds en JSON strict sans markdown :\n'
        '{{"main": "", "facts": [], "conclusion": ""}}'
    ),
}

SYNTHESIS_PROMPTS = {
    "finance_query": (
        "Tu es un analyste financier.\n"
        "Synthétise ces données sur '{subject}'.\n"
        "Structure : Prix actuel et variation → Contexte marché → "
        "Comparaison des sources → Conclusion chiffrée.\n"
        "Chiffres et dates obligatoires."
    ),
    "code_query": (
        "Tu es un développeur expert.\n"
        "Synthétise ces informations sur '{subject}'.\n"
        "Structure : Réponse principale → Exemple de code → "
        "Points importants → Ressources recommandées."
    ),
    "research_query": (
        "Tu es un chercheur expert.\n"
        "Synthétise ces informations sur '{subject}'.\n"
        "Structure : Résultat principal → Données et chiffres clés → "
        "Points de divergence entre sources → Conclusion."
    ),
    "general_query": (
        "Synthétise ces informations sur '{subject}'.\n"
        "Structure : Résultat principal → Détails importants → "
        "Points de divergence → Conclusion."
    ),
}

VERIFY_RULES = {
    "finance_query": lambda d: (
        isinstance(d, dict)
        and d.get("price") not in (None, "")
        and d.get("date") not in (None, "")
    ),
    "code_query": lambda d: (
        isinstance(d, dict)
        and len(d.get("solution", "")) > 20
    ),
    "research_query": lambda d: (
        isinstance(d, dict)
        and len(d.get("main_fact", "")) > 10
    ),
    "general_query": lambda d: (
        isinstance(d, dict)
        and d.get("main") not in (None, "")
    ),
}

# ── JS extraction — linéarisé pour AppleScript do JavaScript ──────────────────

def _build_js_extract_content(char_limit: int) -> str:
    """Construit le JS d'extraction DOM ciblée (linéarisé)."""
    return (
        "var cl=" + str(char_limit) + ";"
        "var sels=['article','main','[role=main]','.content','.post',"
        "'.article-body','.entry-content','#content','.main-content'];"
        "for(var i=0;i<sels.length;i++){"
        "var el=document.querySelector(sels[i]);"
        "if(el&&el.innerText.length>200){"
        "return el.innerText.substring(0,cl);}}"
        "['nav','header','footer','aside','.cookie','.gdpr',"
        "'.popup','.modal','.ad','.advertisement','.banner',"
        "'.sidebar'].forEach(function(t){"
        "document.querySelectorAll(t).forEach(function(e){e.remove();});});"
        "return document.body.innerText.substring(0,cl);"
    )

JS_EXTRACT_LINKS = (
    "var links=[];"
    "var aa=document.querySelectorAll('a[href^=\\\"http\\\"]');"
    "for(var i=0;i<aa.length&&links.length<8;i++){"
    "var h=aa[i].href;"
    "if(!h)continue;"
    "if(h.indexOf('google')>=0||h.indexOf('youtube')>=0"
    "||h.indexOf('facebook')>=0||h.indexOf('twitter')>=0"
    "||h.indexOf('instagram')>=0||h.indexOf('accounts')>=0"
    "||h.indexOf('support')>=0||h.indexOf('policies')>=0"
    "||h.indexOf('javascript')>=0)continue;"
    "if(links.indexOf(h)<0)links.push(h);}"
    "links.join('|||');"
)


class SafariResearchWorkflow:
    """
    Workflow de recherche visible dans Safari.

    Bypass le PlannerAgent pour économiser 3-10s de LLM.
    Utilise directement les méthodes AppleScript de ComputerControlAgent.
    """

    def __init__(self, computer_agent: Any, provider_manager: Any) -> None:
        self.computer = computer_agent
        self.manager = provider_manager
        self.speed = ACTIVE_PROFILE
        self.subject: str = ""
        self._frequency: str = "general_query"

    def _decide_n_results(self, query: str) -> int:
        """
        Adapte le nombre de sites selon la complexité.
        Question simple → 1 site (rapide).
        Recherche approfondie → 3 sites.
        """
        q = query.lower()
        simple_indicators = [
            "en une phrase", "en 1 phrase",
            "en deux phrases", "en 2 phrases",
            "en trois phrases", "en 3 phrases",
            "définition", "c'est quoi", "qu'est-ce que",
            "kesako", "c est quoi",
        ]
        complex_indicators = [
            "compare", "comparaison", "analyse complète",
            "approfondi", "exhaustif", "historique",
            "évolution", "vs", "versus", "différence entre",
        ]
        if any(ind in q for ind in complex_indicators):
            return 3
        if any(ind in q for ind in simple_indicators):
            return 1
        # Par défaut : 2 sites (compromis)
        return 2

    async def run(
        self,
        query: str,
        n_results: Optional[int] = None,
        output_app: str = "Pages",
    ) -> str:
        """Exécute le workflow complet visible. Retourne la synthèse."""
        t0 = time.perf_counter()

        # Détecter la fréquence Thalamus
        try:
            from app.brain.synapses.thalamus import detect_frequency
            self._frequency = detect_frequency(query)
        except Exception:
            self._frequency = "general_query"

        # Adapter n_results si non forcé
        if n_results is None:
            n_results = self._decide_n_results(query)
        logger.info(f"🔍 SafariResearch: '{query}' → {n_results} site(s)")

        # Extraire le sujet et reformuler la requête Google
        subject = self._extract_subject(query)
        self.subject = subject
        search_query = await self._extract_search_query(query, self._frequency)
        logger.info(f"🎯 Sujet : '{subject}' | Google : '{search_query}' (fréquence: {self._frequency})")

        # Étape 1 : Ouvrir Safari + recherche Google
        await self._step1_search(search_query)

        # Étape 2 : Extraire les liens des résultats
        urls = await self._step2_extract_links(n_results)
        if not urls:
            return f"Aucun résultat trouvé pour : {query}"

        # Étape 3 : Visiter chaque site un par un
        contents = await self._step3_visit_sites(urls)

        # Étape 4 : Synthèse LLM (pipeline deux modèles)
        synthesis = await self._step4_synthesize(query, contents, urls)

        # Étape 5 : Ouvrir Pages + coller
        await self._step5_paste_in_pages(query, urls, synthesis, output_app)

        elapsed = time.perf_counter() - t0
        logger.info(f"✅ SafariResearch terminé en {elapsed:.1f}s")
        return synthesis

    # ── Extraction du sujet ─────────────────────────────────────────────────

    def _extract_subject(self, query: str) -> str:
        """Extrait le vrai sujet de recherche depuis la commande."""
        q = query.lower().strip()
        # Supprimer les instructions de commande
        patterns = [
            r"recherche\w*\s+le\s+",
            r"recherche\w*\s+la\s+",
            r"recherche\w*\s+les\s+",
            r"recherche\w*\s+",
            r"cherche\w*\s+le\s+",
            r"cherche\w*\s+la\s+",
            r"cherche\w*\s+",
            r",?\s*consulte\s+(trois|deux|quatre|\d+)\s+sites?\s*.*$",
            r",?\s*et\s+fais?\s+une\s+synth[eè]se?.*$",
            r",?\s*et\s+fis?\s+une\s+synth[eè]se?.*$",
            r",?\s*et\s+fait\s+une\s+synth[eè]se?.*$",
            r",?\s*fais?\s+une\s+synth[eè]se?.*$",
            r",?\s*consulte\s+.*$",
        ]
        for pattern in patterns:
            q = re.sub(pattern, "", q).strip(" ,.")
        return q.strip() or query

    async def _extract_search_query(self, query: str, frequency: str) -> str:
        """Reformule la requête utilisateur en requête Google optimale via LLM."""
        loop = asyncio.get_running_loop()
        suffix = {"finance_query": "prix aujourd'hui"}.get(frequency, "")
        llm_prompt = (
            f"Reformule cette commande vocale en une requête Google courte et efficace "
            f"(3-5 mots, sans verbes de commande comme 'ouvre', 'cherche', 'fais', "
            f"'safari', 'résume', 'synthèse').\n"
            f"Commande : {query}\n"
            f"Requête Google :"
        )
        try:
            llm_result: str = await loop.run_in_executor(
                None,
                lambda: str(self.manager.generate(
                    prompt=llm_prompt,
                    system=(
                        "Tu reformules des commandes vocales en requêtes Google optimales. "
                        "Réponds UNIQUEMENT avec la requête Google, sans explication, "
                        "sans guillemets, sans ponctuation finale."
                    ),
                    model="qwen2.5:7b",
                    temperature=0.1,
                    max_tokens=30,
                )),
            )
            cleaned = llm_result.strip().strip('"').strip("'").split("\n")[0].strip()
            if suffix:
                cleaned = f"{cleaned} {suffix}".strip()
            if cleaned and len(cleaned) > 3:
                logger.info(f"🔍 Requête LLM : '{query[:40]}' → '{cleaned}'")
                return cleaned
        except Exception as e:
            logger.warning(f"Reformulation LLM échouée, fallback mots-clés: {e}")

        # Fallback — extraction par mots-clés améliorée
        noise_words = {
            "ouvre", "ouvrir", "safari", "chrome", "firefox", "navigateur",
            "cherche", "recherche", "trouve", "trouver", "sur", "sites", "site", "web",
            "fais", "fait", "fait-moi", "moi", "une", "synthèse", "synthese",
            "syntèse", "syntese", "résumé", "resume", "résume", "résumer", "résuler",
            "les", "des", "du", "la", "le", "et", "dans", "pour", "avec", "par",
            "trois", "plusieurs", "donne", "donner",
            "stp", "svp", "merci", "consulte",
        }
        q = query.lower()
        for prefix in ("l'", "d'", "j'", "c'", "s'", "n'", "qu'"):
            q = q.replace(prefix, prefix[:-1] + " ")
        words = q.split()
        # Garder les mots >= 2 chars pour capturer "or", "ai", etc.
        fallback_cleaned = [w for w in words if w not in noise_words and len(w) >= 2]
        base = " ".join(fallback_cleaned[:6])
        fallback_result = f"{base} {suffix}".strip()
        logger.info(f"🔍 Requête fallback : '{query[:40]}' → '{fallback_result}'")
        return fallback_result or query

    def _verify_extraction(self, data: dict[str, Any], frequency: str) -> bool:
        """Vérifie que l'extraction contient ce qu'on cherchait."""
        rule: Callable[[dict[str, Any]], bool] = VERIFY_RULES.get(frequency, lambda d: True)
        try:
            result = rule(data)
            if not result:
                logger.warning(f"⚠️ Extraction non vérifiée ({frequency})")
            return bool(result)
        except Exception:
            return False

    def _parse_extraction(self, raw: str) -> dict[str, Any]:
        """Parse le résultat d'extraction LLM. Robuste aux réponses non-JSON."""
        if not raw:
            return {}
        clean = raw.strip().replace("```json", "").replace("```", "").strip()
        try:
            parsed: dict[str, Any] = json.loads(clean)
            return parsed
        except json.JSONDecodeError:
            logger.warning("⚠️ JSON invalide, fallback texte brut")
            return {"main": clean[:500], "facts": [], "conclusion": ""}

    def _calculate_char_limit(self, query: str, frequency: str) -> int:
        """Calcule la limite de chars selon la complexité réelle."""
        base = 2000
        words = len(query.split())
        if words > 10:
            base += 500
        if words > 15:
            base += 500
        if words > 25:
            base += 1000
        complexity_kw = [
            "compare", "analyse", "détail", "complet", "approfondi",
            "synthèse", "historique", "évolution", "maximum", "exhaustif",
        ]
        matches = sum(1 for kw in complexity_kw if kw in query.lower())
        base += matches * 500
        frequency_bonus = {
            "finance_query": 1000, "research_query": 1500,
            "document_query": 2000, "code_query": 1000,
        }
        base += frequency_bonus.get(frequency, 0)
        limit = max(2000, min(6000, base))
        logger.debug(f"📄 Chars calculés : {limit} ({words} mots)")
        return limit

    # ── Étapes internes ────────────────────────────────────────────────────

    async def _step1_search(self, query: str) -> None:
        """Étape 1 : Ouvre Safari et lance une recherche Google."""
        # Activer Safari
        await self.computer._run_applescript(
            'tell application "Safari" to activate', timeout=5.0,
        )
        await asyncio.sleep(self.speed.sleep_after_activate)

        # Ouvrir un nouvel onglet avec la recherche Google
        url_query = urllib.parse.quote_plus(query)
        search_url = f"https://www.google.com/search?q={url_query}"
        script = f'''
tell application "Safari"
    activate
    if (count of windows) = 0 then
        make new document with properties {{URL:"{search_url}"}}
    else
        tell front window
            set current tab to (make new tab with properties {{URL:"{search_url}"}})
        end tell
    end if
end tell
'''
        await self.computer._run_applescript(script, timeout=5.0)
        logger.info(f"🔍 Recherche Google : {query}")

        # Laisser les résultats charger (Google charge dynamiquement)
        await asyncio.sleep(1.5)

    async def _step2_extract_links(self, n: int) -> List[str]:
        """Étape 2 : Extrait les N premiers liens des résultats Google."""
        # Pause pour laisser le DOM se stabiliser
        await asyncio.sleep(0.5)

        # Sélecteur robuste — exclut navigation, pubs, réseaux sociaux
        js_code = JS_EXTRACT_LINKS
        script = f'''
tell application "Safari"
    do JavaScript "{js_code}" in current tab of front window
end tell
'''
        try:
            success, output = await self.computer._run_applescript(
                script, timeout=8.0,
            )
            logger.info(f"🔗 JS brut reçu : {str(output)[:300]}")
            if success and output:
                urls_raw = output.strip().split("|||")
                urls: List[str] = []
                seen_domains: set[str] = set()
                for u in urls_raw:
                    u = u.strip().split("#")[0].split("?srsltid=")[0]
                    if not u.startswith("http"):
                        continue
                    try:
                        domain = urllib.parse.urlparse(u).netloc
                        if domain and domain not in seen_domains:
                            seen_domains.add(domain)
                            urls.append(u)
                    except Exception:
                        continue
                urls = urls[:n]
                if urls:
                    logger.info(f"🔗 {len(urls)} liens extraits (dédupliqués)")
                    return urls
        except Exception as e:
            logger.warning(f"Extraction liens échouée: {e}")

        logger.warning("Aucune URL trouvée pour cette recherche")
        return []

    async def _step3_visit_sites(self, urls: List[str]) -> List[str]:
        """Étape 3 : Visite chaque site avec pipeline parallèle.

        Pendant le scroll visible sur le site N, l'extraction du site N-1
        tourne en arrière-plan → gain ~50% du temps total.
        """
        contents: List[str] = []
        extract_task: Optional[asyncio.Task[str]] = None

        for i, url in enumerate(urls):
            logger.info(f"📄 Lecture site {i + 1}/{len(urls)} : {url[:60]}")

            # Ouvrir dans un nouvel onglet
            open_script = f'''
tell application "Safari"
    tell front window
        set current tab to (make new tab with properties {{URL:"{url}"}})
    end tell
end tell
'''
            await self.computer._run_applescript(open_script, timeout=5.0)
            # Délai minimal pour que la page soit partiellement chargée
            await asyncio.sleep(1.0)

            # Lancer le scroll visible sur ce site
            scroll_task = asyncio.create_task(
                self._scroll_visible(i, url, len(urls))
            )

            # Pendant le scroll — récupérer l'extraction du site précédent
            if extract_task is not None:
                try:
                    content = await asyncio.wait_for(extract_task, timeout=8.0)
                    if content:
                        contents.append(content)
                except Exception as e:
                    logger.warning(f"Extraction background: {e}")

            # Attendre le scroll visible
            await scroll_task

            # Lancer extraction de CE site en background
            extract_task = asyncio.create_task(self._extract_content())

        # Récupérer la dernière extraction
        if extract_task is not None:
            try:
                content = await asyncio.wait_for(extract_task, timeout=8.0)
                if content:
                    contents.append(content)
            except Exception as e:
                logger.warning(f"Dernière extraction: {e}")

        return contents

    async def _scroll_visible(self, i: int, url: str, total: int) -> None:
        """Scroll humain réaliste sur le site courant (~5-6s visibles)."""
        logger.info(f"👁️ Analyse site {i+1}/{total} : {url[:50]}")
        # Scroll humain réaliste compressé (~3.5s vs 5.6s original — même comportement visible)
        scroll_script = '''
tell application "Safari" to activate
tell application "System Events"
    tell process "Safari"
        -- Regard initial sur la page
        delay 0.3

        -- Premier grand saut (page down)
        key code 121
        delay 0.4

        -- Pause lecture titre principal
        delay 0.4

        -- Deuxième grand saut
        key code 121
        delay 0.3

        -- Petit scroll fin pour ajuster
        key code 125
        delay 0.1
        key code 125
        delay 0.1

        -- Pause (lit un paragraphe)
        delay 0.5

        -- Grand saut encore
        key code 121
        delay 0.3

        -- Hésitation — remonte légèrement
        key code 126
        delay 0.1
        key code 126
        delay 0.1
        key code 126
        delay 0.1

        -- Pause (a trouvé quelque chose)
        delay 0.3

        -- Dernier grand saut vers le bas
        key code 121
        delay 0.3

        -- Petit ajustement final
        key code 125
        delay 0.1
        key code 126
        delay 0.1
    end tell
end tell
'''
        try:
            await self.computer._run_applescript(scroll_script, timeout=12.0)
        except Exception as e:
            logger.warning(f"Scroll échoué (non bloquant): {e}")
        logger.info(f"✅ Site {i+1} analysé")

    async def _extract_content(self) -> str:
        """Extrait le contenu texte ciblé de l'onglet courant via JavaScript."""
        char_limit = self._calculate_char_limit(self.subject, self._frequency)
        extract_js = _build_js_extract_content(char_limit)
        extract_script = f'''
tell application "Safari"
    do JavaScript "{extract_js}" in current tab of front window
end tell
'''
        try:
            success, output = await self.computer._run_applescript(
                extract_script, timeout=8.0,
            )
            if success and output:
                return str(output)[:char_limit]
        except Exception as e:
            logger.warning(f"Extraction contenu échouée: {e}")

        # Fallback : récupérer le source HTML brut via AppleScript
        fallback_script = '''
tell application "Safari"
    return source of current tab of front window
end tell
'''
        try:
            success, html = await self.computer._run_applescript(
                fallback_script, timeout=8.0,
            )
            if success and html and len(html) > 200:
                # Nettoyer les balises HTML basiquement
                import re as _re
                text = _re.sub(r'<[^>]+>', ' ', html)
                text = _re.sub(r'\s+', ' ', text).strip()
                logger.info(f"📄 Fallback HTML → {len(text)} chars")
                return text[:char_limit]
        except Exception as e:
            logger.warning(f"Fallback HTML échoué: {e}")
        return ""

    async def _step4_synthesize(
        self, query: str, contents: List[str], urls: Optional[List[str]] = None,
    ) -> str:
        """Étape 4 : Pipeline deux modèles — extraction (7b) puis synthèse (9b)."""
        if not contents:
            return f"Aucun contenu exploitable trouvé pour : {query}"

        loop = asyncio.get_running_loop()
        url_list = urls or [f"source {i+1}" for i in range(len(contents))]

        # ── Étape 4a : Extraction des faits via qwen2.5:7b (parallèle) ──
        logger.info(f"🧠 Extraction des faits ({len(contents)} sources en parallèle)...")

        async def _extract_one(content: str, url: str, index: int, total: int) -> str:
            # Prompt dynamique selon la fréquence Thalamus
            template = EXTRACTION_PROMPTS.get(
                self._frequency, EXTRACTION_PROMPTS["general_query"]
            )
            extract_prompt = (
                template.format(subject=self.subject)
                + f"\n\nURL source : {url}\n\nContenu :\n{content[:3000]}"
            )
            try:
                def _do_extract(p: str = extract_prompt) -> str:
                    return str(self.manager.generate(
                        prompt=p,
                        system="Extracteur de faits. Bullet points courts en français.",
                        model="qwen2.5:7b",
                        temperature=0.3,
                        max_tokens=300,
                    ))
                result: str = await loop.run_in_executor(None, _do_extract)
                logger.info(f"📋 Extraction {index}/{total} OK")
                return result
            except Exception as e:
                logger.warning(f"Extraction {index} échouée: {e}")
                return f"(extraction échouée pour source {index})"

        extraction_tasks = [
            _extract_one(
                contents[i],
                url_list[i] if i < len(url_list) else "inconnue",
                i + 1,
                len(contents),
            )
            for i in range(len(contents))
        ]
        extractions = list(await asyncio.gather(*extraction_tasks))

        # ── Étape 4b : Synthèse via qwen2.5:7b ──────────────────────────
        logger.info("🧠 Synthèse finale (qwen2.5:7b)...")

        sources_block = "\n\n".join(
            f"Source {i+1} ({url_list[i] if i < len(url_list) else '?'}) :\n{ext}"
            for i, ext in enumerate(extractions)
        )
        urls_text = ", ".join(url_list[:len(extractions)])
        # Prompt de synthèse dynamique selon la fréquence
        synth_template = SYNTHESIS_PROMPTS.get(
            self._frequency, SYNTHESIS_PROMPTS["general_query"]
        ).format(subject=self.subject)
        synth_prompt = (
            f"{synth_template}\n\n"
            f"Voici les données extraites de {len(extractions)} sources :\n\n"
            f"{sources_block}\n\n"
            f"Ignore le bruit (cookies, RGPD, publicités).\n"
            f"Sources consultées : {urls_text}"
        )

        synth_system = (
            "Tu es Lucie, assistante experte en recherche et synthèse d'information.\n\n"
            "Quand tu fais une synthèse tu :\n"
            "- Ignores le bruit (cookies, RGPD, pubs, menus de navigation)\n"
            "- Identifies les informations les plus récentes et fiables\n"
            "- Croises les sources pour détecter les contradictions\n"
            "- Mets en avant les chiffres clés et les faits vérifiables\n"
            "- Rédiges dans un français clair et professionnel\n"
            "- Structures TOUJOURS avec ces titres exacts, chacun suivi d'une ligne vide :\n"
            "  RÉSULTAT PRINCIPAL\n"
            "  DONNÉES CLÉS\n"
            "  ANALYSE\n"
            "  CONCLUSION\n"
            "- Sépares chaque section par une ligne vide\n"
            "- Cites tes sources à la fin\n\n"
            "Tu ne répètes jamais les mêmes informations.\n"
            "Tu signales si les sources se contredisent."
        )

        try:
            response = await loop.run_in_executor(
                None,
                lambda: self.manager.generate(
                    prompt=synth_prompt,
                    system=synth_system,
                    model="qwen2.5:7b",
                    temperature=0.5,
                    max_tokens=1024,
                ),
            )
            logger.info("✅ Synthèse générée")
            return str(response)
        except Exception as e:
            logger.error(f"Synthèse échouée: {e}")
            return f"Erreur lors de la synthèse : {e}"

    async def _step5_paste_in_pages(
        self,
        query: str,
        urls: List[str],
        synthesis: str,
        app: str,
    ) -> None:
        """Étape 5 : Ouvre Pages, crée un document, colle la synthèse formatée."""
        # Activer Pages et attendre qu'il soit prêt
        wait_script = f'''
tell application "{app}"
    activate
end tell
repeat 20 times
    try
        tell application "{app}"
            if (count of documents) > 0 then
                exit repeat
            end if
        end tell
    end try
    delay 0.5
end repeat
'''
        await self.computer._run_applescript(wait_script, timeout=15.0)
        await asyncio.sleep(0.3)

        # S'assurer qu'un document existe, sinon en créer un
        ensure_doc_script = f'''
tell application "{app}"
    activate
    if (count of documents) = 0 then
        make new document
    end if
end tell
'''
        await self.computer._run_applescript(ensure_doc_script, timeout=5.0)
        await asyncio.sleep(0.5)

        # Formater le texte avec en-tête + sources + synthèse
        sources_list = "\n".join(f"- {u}" for u in urls)
        full_text = (
            f"Synthèse — {query}\n\n"
            f"Sources :\n{sources_list}\n\n"
            f"{synthesis}"
        )

        # Copier dans le clipboard via pbcopy
        proc = await asyncio.create_subprocess_exec(
            "pbcopy",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate(input=full_text.encode("utf-8"))
        await asyncio.sleep(0.1)

        # Coller via Cmd+V
        paste_script = (
            'tell application "System Events" to keystroke "v" using command down'
        )
        await self.computer._run_applescript(paste_script, timeout=5.0)
        await asyncio.sleep(0.3)

        logger.info(f"✅ Synthèse collée dans {app}")
