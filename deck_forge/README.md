# Deck Forge

Constructor local de mazos Commander a partir de tu colección de ManaBox.

**Cero llamadas a APIs externas. Cero tokens de Claude consumidos.** Todo se ejecuta en tu máquina con tu `collection_enriched.json` ya generado.

---

## Instalación

Solo necesitas Python 3.10+ y pandas.

```powershell
pip install pandas
```

(Ya tienes pandas instalado de cuando ejecutaste `enrich_collection.py`.)

---

## Estructura del proyecto

```
deck_forge/
├── deck_forge.py           # CLI entry point
├── core/
│   ├── pool.py             # carga collection_enriched.json + filtra fakes
│   ├── classifier.py       # detecta roles (ramp, draw, removal...)
│   ├── archetypes.py       # plantillas de arquetipo
│   ├── builder.py          # ensambla el mazo de 100 cartas
│   ├── bracket.py          # estima bracket WotC
│   └── exporters.py        # ManaBox CSV, Moxfield txt, HTML
├── data/
│   └── game_changers.json  # lista oficial WotC
└── templates/
    └── deck.html           # template HTML
```

---

## Uso

### Modo 1: Análisis del pool

Antes de gastar tiempo construyendo, ¿qué bracket soporta tu colección?

```powershell
python deck_forge.py analyze --collection collection_enriched.json
```

Output:
- Bracket máximo estimado SIN compras
- Profundidad por identidad de color
- Top 15 comandantes legales más populares

### Modo 2: Construir 1 mazo

**Opción A: Eliges comandante**

```powershell
python deck_forge.py build `
  --collection collection_enriched.json `
  --real-csv real.csv `
  --commander "Vorel of the Hull Clade" `
  --output-dir .\decks
```

**Opción B: El script elige por colores + arquetipo**

```powershell
python deck_forge.py build `
  --collection collection_enriched.json `
  --real-csv real.csv `
  --colors GU --archetype counters `
  --output-dir .\decks
```

### Modo 3: Construir varios mazos a la vez

```powershell
python deck_forge.py multi `
  --collection collection_enriched.json `
  --real-csv real.csv `
  --commanders "Vorel of the Hull Clade" "Eivor, Battle-Ready" "Izoni, Thousand-Eyed" "The Twelfth Doctor" `
  --output-dir .\decks
```

Genera un `decks.html` con tabs entre los 4 mazos + CSV ManaBox + Moxfield txt para cada uno.

---

## Outputs por mazo

- **`{commander}_manabox.csv`** — Importa directo en ManaBox (Settings → Import)
- **`{commander}_moxfield.txt`** — Pega en Moxfield/Archidekt al crear deck
- **`decks.html`** — Vista interactiva con justificación carta por carta + bracket estimado

---

## Garantías del script

✓ **Nunca usa cartas que estén en `fake.csv`** (incluso si también aparecen en `real.csv`)
✓ Singleton estricto (1 copia por carta)
✓ Solo cartas legales en formato Commander según Scryfall
✓ Siempre 100 cartas exactas (rellena con básicas)
✓ Todas las cartas tienen Scryfall ID exacto = importación sin fricciones

---

## Criterio de selección de comandantes

El score de comandantes (en `analyze` y cuando no especificas `--commander`) se basa en:

| Componente | Peso | Qué mide |
|---|---|---|
| **Densidad de sinergia** | 50% | % de cartas en la identidad del comandante que sirven al arquetipo natural detectado. Un pool 5-color tiene MUCHAS cartas pero pocas pueden ser relevantes para un arquetipo concreto — la densidad lo penaliza correctamente. |
| **Techo de bracket** | 30% | Bracket score máximo alcanzable construyendo desde tu pool (game changers + fast mana + tutors disponibles). |
| **Popularidad EDHREC** | 20% | Solo como desempate suave: comandantes populares tienen más guías/contenido online. |

**Filtros aplicados por defecto:**
- Mínimo bicolor (`--min-colors 2`). Cambiable.
- Banlist de Commander **ignorada** (cartas baneadas son válidas como comandante si quieres). Activable con `--require-legal`.

**Ejemplos del output real con tu colección:**
- Equipment Voltron en RW: densidad ~36% — **muy fuerte** en tu pool (Eivor, Arbaaz, Kassandra)
- Counters GU: densidad ~25% — sólido (Vorel, Doctor 13)
- Tokens/Aristocrats BG: densidad ~24% — sólido (Izoni)
- Spellslinger UR: densidad ~15% — fino, mejor evitar

## Arquetipos soportados (v1)

| Key | Nombre | Cuándo se detecta |
|-----|--------|-------------------|
| `counters` | +1/+1 Counters / Proliferate | Comandante con "+1/+1 counter", "proliferate", "double counters" |
| `equipment` | Equipment Voltron | Comandante creature con "equipment" o "historic" |
| `aristocrats` | Tokens / Sacrifice / Drain | Comandante con "creature dies", "create token", "sacrifice" |
| `spellslinger` | Cantrips / Magecraft | Comandante con "whenever you cast", "magecraft", "copy spell", "demonstrate" |

Sesión 3: añadiremos más arquetipos (lifegain, reanimator, tribal, blink, voltron-creature) y modo `--upgrade`.

---

## Limitaciones conocidas

- **Heurística de bracket no es paridad exacta con ManaBox.** Mi score se basa en señales públicas (game changers WotC, fast mana, tutores, manabase score, CMC). ManaBox usa un algoritmo propietario. Si difieren, el de ManaBox manda.

- **Justificaciones genéricas.** En v1 las justificaciones por slot son plantillas ("Ramp: acelera el plan"). v2 puede generar texto más específico por carta.

- **Detección de arquetipo simple.** Si tu comandante es híbrido (ej. counters + tokens), el script elige uno. Puedes forzar con `--archetype X`.

- **Pool real verdadero solo soporta bracket 1-2 sin compras.** Esto NO es bug del script — es realidad de la colección. Si quieres bracket 3, compra Sol Ring + Arcane Signet + Command Tower (~€5).

---

## Próximas sesiones

- **Sesión 3:** Modo `--upgrade decklist.txt --target-bracket N` que analiza un mazo existente, identifica gaps y propone swaps desde tu pool.
- **Sesión 4 (opcional):** Más arquetipos. Generación de "qué comprar" automática.
