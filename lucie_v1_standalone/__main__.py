"""
Point d'entrée CLI du pipeline juridique V1 standalone.

Usage :
    python -m lucie_v1_standalone "Ma requête" [--document "Texte du doc"] [--force] [--quiet]
    python -m lucie_v1_standalone --help

Exemples :
    python -m lucie_v1_standalone "Mon employeur veut faire un licenciement économique"
    python -m lucie_v1_standalone "PSE en cours" --document "$(cat lettre.txt)"
    python -m lucie_v1_standalone "Analyse du dossier" --dossier ./mon_dossier/ --force
    python -m lucie_v1_standalone "Licenciement éco" --force --quiet
"""

import argparse
import asyncio
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m lucie_v1_standalone",
        description=(
            "Beaume V1 — Pipeline juridique droit social (licenciement économique).\n"
            "Analyse une requête et/ou un document via 5 agents Ollama enchaînés :\n"
            "  Router → Lecteur → Retriever → Rédacteur → Vérificateur\n\n"
            "Requiert Ollama en local (http://localhost:11434) avec gemma4:e4b chargé."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemples :\n"
            '  python -m lucie_v1_standalone "Mon employeur veut faire un licenciement économique"\n'
            '  python -m lucie_v1_standalone "PSE en cours" --document "$(cat lettre.txt)"\n'
            '  python -m lucie_v1_standalone "Analyse complète" --dossier ./mon_dossier/ --force\n'
            '  python -m lucie_v1_standalone "Licenciement éco" --force\n'
        ),
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help="Requête ou question juridique (ex: 'Mon employeur veut un licenciement économique').",
    )
    parser.add_argument(
        "--document", "-d",
        default=None,
        metavar="TEXTE",
        help="Texte du document à analyser (lettre de licenciement, convocation, etc.).",
    )
    parser.add_argument(
        "--dossier",
        default=None,
        metavar="CHEMIN",
        help="Chemin vers un dossier complet à analyser (jusqu'à 50 fichiers : PDF, Word, TXT, MD).",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        default=False,
        help="Bypass le filtrage du Router (utile pour tester avec n'importe quel texte).",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        default=False,
        help="Supprime les messages de progression, affiche uniquement le résultat final.",
    )
    return parser


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.query is None:
        parser.print_help()
        sys.exit(0)

    # Import ici pour ne pas payer le coût au --help
    from .pipeline import run
    from .setup import ensure_ready

    status = await ensure_ready(verbose=not args.quiet)
    if "ollama_not_running" in status["errors"] or "model_pull_failed" in status["errors"]:
        sys.exit(1)

    result = await run(
        query=args.query,
        document_text=args.document,
        dossier_path=args.dossier,
        force=args.force,
        verbose=not args.quiet,
    )

    print("\n" + "=" * 70)
    print(result)
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
