#!/usr/bin/env python3
"""
deck_forge.py — Constructor local de mazos Commander.

Uso:
    # Construir 1 mazo eligiendo comandante explícito
    python deck_forge.py build \\
        --collection collection_enriched.json \\
        --commander "Vorel of the Hull Clade" \\
        --output-dir ./decks

    # Construir 1 mazo dejando que el script elija comandante por colores
    python deck_forge.py build \\
        --collection collection_enriched.json \\
        --colors GU --archetype counters \\
        --output-dir ./decks

    # Análisis del pool: ¿qué bracket máximo soporta tu colección?
    python deck_forge.py analyze \\
        --collection collection_enriched.json

    # Construir varios mazos en HTML único
    python deck_forge.py multi \\
        --collection collection_enriched.json \\
        --commanders "Vorel of the Hull Clade" "Eivor, Battle-Ready" "Izoni, Thousand-Eyed" \\
        --output-dir ./decks

REQUISITOS:
    pip install pandas

INPUTS:
    collection_enriched.json — generado por ingest.py
    real.csv  — el CSV original de ManaBox (necesario para export ManaBox CSV)

OUTPUTS por mazo:
    {commander_name}_manabox.csv   (importable a ManaBox)
    {commander_name}_moxfield.txt  (importable a Moxfield)
    decks.html                      (vista HTML con todos los mazos)
"""

import argparse
import csv
import json
import sys
from pathlib import Path

# Cargar variables de entorno desde .env si existe
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass  # python-dotenv no instalado, usar variables del sistema

# Hack para permitir import relativo desde cualquier ubicación
sys.path.insert(0, str(Path(__file__).parent))

from core.pool import load_collection, build_real_pool, index_by_name
from core.builder import build_deck, BuiltDeck
from core.bracket import estimate_bracket, estimate_max_bracket_for_pool
from core.exporters import to_moxfield_txt, to_manabox_csv, to_html_multi, build_multi_html_from_index
from core.archetypes import ARCHETYPES
from core.deck_index import register_deck, get_deck, print_deck_list, load_index
from core.upgrader import analyze_upgrade


def _load_basics_data(real_csv: Path) -> dict[str, dict]:
    """Lee el CSV original y extrae datos de las básicas presentes."""
    basics = {}
    with open(real_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["Name"]
            if name in ("Plains", "Island", "Swamp", "Mountain", "Forest"):
                if name not in basics:
                    basics[name] = {
                        "set_code": row.get("Set code", ""),
                        "set_name": row.get("Set name", ""),
                        "collector_number": row.get("Collector number", ""),
                        "foil": row.get("Foil", "normal"),
                        "rarity": row.get("Rarity", ""),
                        "manabox_id": row.get("ManaBox ID", ""),
                        "scryfall_id": row.get("Scryfall ID", ""),
                        "language": row.get("Language", "en"),
                        "condition": row.get("Condition", "near_mint"),
                    }
    return basics


def _safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")


def cmd_analyze(args):
    """Analiza el pool y reporta qué bracket máximo soporta."""
    from core.commander_score import score_commanders

    collection = load_collection(args.collection)
    pool = build_real_pool(collection)

    print(f"\n=== ANÁLISIS DEL POOL ===")
    print(f"Cartas en real (CSV): {len(collection['real'])}")
    print(f"Cartas en fake (excluidas): {len(collection['fake'])}")
    print(f"Pool real verdadero (sin fakes): {len(pool)} cartas únicas")

    max_b, reason = estimate_max_bracket_for_pool(pool)
    print(f"\nBracket máximo estimado SIN COMPRAS: {max_b}")
    print(f"Razón: {reason}")

    # Conteo por color identity
    print(f"\nProfundidad por identidad de mazo (cartas jugables, bicolor+):")
    identities_to_check = [
        ("U","W"), ("B","W"), ("R","W"), ("G","W"),
        ("B","U"), ("R","U"), ("G","U"),
        ("B","R"), ("B","G"), ("G","R"),
    ]
    for ci in identities_to_check:
        ci_set = set(ci)
        count = sum(1 for c in pool
                    if set(c.get("color_identity", [])).issubset(ci_set))
        ci_str = "".join(sorted(ci))
        print(f"  {ci_str:5s}: {count:4d} cartas")

    # Top comandantes por SCORE (sinergia + bracket + rank)
    print(f"\n=== TOP COMANDANTES (multicolor, score compuesto) ===")
    print("Score basado en: densidad de sinergia (50%) + bracket alcanzable (30%) + popularidad EDHREC (20%)")
    print()

    scores = score_commanders(pool, min_colors=args.min_colors,
                               require_legal=args.require_legal)
    print(f"Total comandantes candidatos ({args.min_colors}+ colores): {len(scores)}")

    top_n = args.top
    print(f"\nTop {top_n}:")
    print("-" * 130)
    for s in scores[:top_n]:
        print(f"  {s.summary_line()}")
    print()

    # Desglose detallado del #1
    if scores:
        top = scores[0]
        print(f"=== DESGLOSE DEL #1: {top.name} ===")
        print(f"  Identidad de color: {top.colors}")
        print(f"  Arquetipo detectado: {top.archetype.name if top.archetype else 'NO DETECTADO'}")
        if top.archetype:
            print(f"  Estrategia: {top.archetype.description}")
        print(f"  Score total: {top.total_score:.1f}/100")
        print(f"    - Densidad de sinergia: {top.synergy_density:.1f}% ({top.synergy_raw}/{top.synergy_total} cartas en identidad)")
        print(f"    - Techo de bracket: {top.bracket_ceiling:.2f}/5.0")
        print(f"    - Popularidad EDHREC: {top.rank_score:.1f}/100")


def cmd_build(args):
    """Construye un solo mazo."""
    collection = load_collection(args.collection)
    pool = build_real_pool(collection)
    basics = _load_basics_data(Path(args.real_csv))

    deck = build_deck(
        pool,
        commander_name=args.commander,
        colors=args.colors,
        archetype_key=args.archetype,
        use_edhrec=not getattr(args, 'no_edhrec', False),
    )

    full_list = deck.all_cards_with_basics(basics)
    bracket = estimate_bracket(full_list)

    print(f"\n=== MAZO CONSTRUIDO ===")
    print(f"Comandante: {deck.commander['name']}")
    print(f"Colores: {deck.colors}")
    print(f"Arquetipo: {deck.archetype.name}")
    print(f"Cartas: {deck.card_count} + {deck.needed_basics} básicas = {deck.card_count + deck.needed_basics}")
    print()
    print(bracket.summary())
    print()

    # Output files
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    safe = _safe_filename(deck.commander["name"])

    # Moxfield txt
    txt_path = output_dir / f"{safe}_moxfield.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(to_moxfield_txt(deck, basics))
    print(f"✓ Moxfield txt: {txt_path}")

    # ManaBox CSV
    csv_path = output_dir / f"{safe}_manabox.csv"
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write(to_manabox_csv(deck, args.real_csv, basics))
    print(f"✓ ManaBox CSV: {csv_path}")

    # HTML
    html_path = output_dir / f"{safe}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(to_html_multi([deck], [bracket], args.real_csv, basics))
    print(f"✓ HTML: {html_path}")

    # Registrar en índice con datos HTML completos
    from core.exporters import _build_deck_data_json
    html_data = _build_deck_data_json(deck, bracket)
    register_deck(
        output_dir=output_dir,
        deck_key=safe,
        commander_card=deck.commander,
        archetype_key=deck.archetype.key,
        colors=deck.colors,
        bracket=bracket.bracket,
        bracket_score=bracket.score,
        cards=[dc.card for dc in deck.cards],
        needed_basics=deck.needed_basics,
        html_data=html_data,
    )
    print(f"✓ Registrado en índice ({output_dir / 'decks_index.json'})")

    # Regenerar decks.html multi-mazo con todos los mazos del índice
    index = load_index(output_dir)
    multi_html_path = output_dir / "decks.html"
    with open(multi_html_path, "w", encoding="utf-8") as f:
        f.write(build_multi_html_from_index(output_dir, index.get("decks", {})))
    print(f"✓ Grimorio actualizado: {multi_html_path}")


def cmd_multi(args):
    """Construye múltiples mazos en un solo HTML."""
    collection = load_collection(args.collection)
    pool = build_real_pool(collection)
    basics = _load_basics_data(Path(args.real_csv))

    decks = []
    brackets = []
    for cname in args.commanders:
        try:
            d = build_deck(pool, commander_name=cname,
                           use_edhrec=not getattr(args, 'no_edhrec', False))
            full = d.all_cards_with_basics(basics)
            b = estimate_bracket(full)
            decks.append(d)
            brackets.append(b)
            print(f"✓ {cname} → bracket {b.bracket} (score {b.score:.2f}), arquetipo {d.archetype.name}")
        except Exception as e:
            print(f"✗ {cname}: {e}")

    if not decks:
        print("Ningún mazo construido.")
        return

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Individual exports
    for d in decks:
        safe = _safe_filename(d.commander["name"])
        with open(output_dir / f"{safe}_moxfield.txt", "w", encoding="utf-8") as f:
            f.write(to_moxfield_txt(d, basics))
        with open(output_dir / f"{safe}_manabox.csv", "w", encoding="utf-8") as f:
            f.write(to_manabox_csv(d, args.real_csv, basics))

    # Combined HTML
    html_path = output_dir / "decks.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(to_html_multi(decks, brackets, args.real_csv, basics))
    print(f"\n✓ HTML combinado: {html_path}")
    print(f"✓ {len(decks)} mazos exportados a CSV ManaBox + Moxfield txt")

    # Registrar todos en índice
    for d, b in zip(decks, brackets):
        register_deck(
            output_dir=output_dir,
            deck_key=_safe_filename(d.commander["name"]),
            commander_card=d.commander,
            archetype_key=d.archetype.key,
            colors=d.colors,
            bracket=b.bracket,
            bracket_score=b.score,
            cards=[dc.card for dc in d.cards],
            needed_basics=d.needed_basics,
        )
    print(f"✓ {len(decks)} mazos registrados en índice")




def cmd_decks(args):
    """Lista todos los mazos construidos y guardados."""
    output_dir = Path(args.output_dir)
    print_deck_list(output_dir)


def cmd_upgrade(args):
    """Analiza un mazo guardado y propone swaps para subir de bracket."""
    output_dir = Path(args.output_dir)

    # Buscar el mazo en el índice
    deck_data = get_deck(output_dir, args.deck)
    if not deck_data:
        print(f"\nERROR: Mazo '{args.deck}' no encontrado en {output_dir}.")
        print(f"\nMazos disponibles:")
        print_deck_list(output_dir)
        return

    print(f"\nAnalizando: {deck_data['commander']} ({deck_data['archetype']})")
    print(f"Bracket actual: {deck_data['bracket']} (score {deck_data['bracket_score']:.2f})")

    # Cargar pool real
    collection = load_collection(args.collection)
    pool = build_real_pool(collection)

    # Target bracket
    target = args.target_bracket
    if target is None:
        target = min(deck_data["bracket"] + 1, 4)
    print(f"Bracket objetivo: {target}")

    if target > 4:
        print("\nBracket 5 (cEDH) requiere compras específicas — fuera del scope de upgrade.")
        return

    if target <= deck_data["bracket"]:
        print(f"\nEl mazo ya está en bracket {deck_data['bracket']}. Pasa --target-bracket N para un objetivo más alto.")
        return

    # Ejecutar análisis
    report = analyze_upgrade(
        deck_cards=deck_data["cards"],
        commander=deck_data["commander_card"],
        archetype_key=deck_data["archetype"],
        pool=pool,
        target_bracket=target,
        allow_purchases=not args.no_purchases,
        max_price=args.max_price,
        min_suggestions=5,
        max_suggestions=15,
    )
    report.print()


def main():
    parser = argparse.ArgumentParser(
        description="Constructor local de mazos Commander a partir de tu colección.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # analyze
    pa = sub.add_parser("analyze", help="Analiza el pool y reporta bracket máximo")
    pa.add_argument("--collection", required=True, help="Path a collection_enriched.json (generado por ingest.py)")
    pa.add_argument("--min-colors", type=int, default=2,
                    help="Mínimo de colores en color identity (default: 2 = bicolor)")
    pa.add_argument("--top", type=int, default=20,
                    help="Cuántos comandantes top mostrar (default: 20)")
    pa.add_argument("--require-legal", action="store_true",
                    help="Si se pasa, filtra por banlist oficial de Commander (default: ignora banlist)")

    # build
    pb = sub.add_parser("build", help="Construye 1 mazo")
    pb.add_argument("--collection", required=True)
    pb.add_argument("--real-csv", required=True, help="Path al CSV original de ManaBox (real.csv)")
    pb.add_argument("--commander", help="Nombre exacto del comandante")
    pb.add_argument("--colors", help="Identidad de colores ej. GU, WUB")
    pb.add_argument("--archetype", choices=list(ARCHETYPES.keys()),
                    help="counters | equipment | aristocrats | spellslinger")
    pb.add_argument("--output-dir", default="./decks_output")
    pb.add_argument("--no-edhrec", action="store_true",
                    help="Desactiva la integración con EDHREC (más rápido, scoring local)")
    pb.add_argument("--no-critic", action="store_true",
                    help="Desactiva la revisión LLM del mazo")

    # multi
    pm = sub.add_parser("multi", help="Construye varios mazos en un único HTML")
    pm.add_argument("--collection", required=True)
    pm.add_argument("--real-csv", required=True)
    pm.add_argument("--commanders", nargs="+", required=True,
                    help="Lista de comandantes separados por espacio")
    pm.add_argument("--output-dir", default="./decks_output")
    pm.add_argument("--no-edhrec", action="store_true",
                    help="Desactiva la integración con EDHREC")
    pm.add_argument("--no-critic", action="store_true",
                    help="Desactiva la revisión LLM del mazo")

    # decks
    pd = sub.add_parser("decks", help="Lista los mazos guardados")
    pd.add_argument("--output-dir", default="./decks_output",
                    help="Directorio donde están los mazos (default: ./decks_output)")

    # upgrade
    pu = sub.add_parser("upgrade", help="Propone swaps para subir de bracket")
    pu.add_argument("--deck", required=True,
                    help="Key o nombre parcial del comandante (ej. 'teneb', 'vorel')")
    pu.add_argument("--collection", required=True,
                    help="Path a collection_enriched.json (generado por ingest.py)")
    pu.add_argument("--target-bracket", type=int, choices=[2, 3, 4],
                    help="Bracket objetivo (default: bracket actual + 1)")
    pu.add_argument("--max-price", type=float, default=10.0,
                    help="Precio EUR maximo por carta en sugerencias de compra (default: 10.0)")
    pu.add_argument("--no-purchases", action="store_true",
                    help="No consultar Scryfall para sugerencias de compra")
    pu.add_argument("--output-dir", default="./decks_output")

    args = parser.parse_args()

    if args.cmd == "analyze":
        cmd_analyze(args)
    elif args.cmd == "build":
        cmd_build(args)
    elif args.cmd == "multi":
        cmd_multi(args)
    elif args.cmd == "decks":
        cmd_decks(args)
    elif args.cmd == "upgrade":
        cmd_upgrade(args)


if __name__ == "__main__":
    main()
