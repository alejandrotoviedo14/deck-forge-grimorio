# Deck Forge

Constructor local de mazos Commander a partir de tu colección de ManaBox.

**Cero llamadas a APIs externas en tiempo de ejecución. Cero tokens de Claude consumidos.** Todo se ejecuta en tu máquina con tu `collection_enriched.json` ya generado.

---

## Instalación

```powershell
pip install requests pandas browser-cookie3
```

---

## Estructura del proyecto

```
deck_forge/
├── deck_forge.py           # CLI entry point
├── enrich_collection.py    # genera collection_enriched.json
├── core/
│   ├── __init__.py
│   ├── pool.py             # carga collection_enriched.json + filtra fakes
│   ├── classifier.py       # detecta roles (ramp, draw, removal...) — v2 con Tagger
│   ├── archetypes.py       # plantillas de arquetipo — v2 con 9 arquetipos
│   ├── builder.py          # ensambla el mazo de 100 cartas
│   ├── bracket.py          # estima bracket WotC
│   ├── exporters.py        # ManaBox CSV, Moxfield txt, HTML
│   ├── commander_score.py  # scoring compuesto de comandantes
│   ├── deck_index.py       # índice persistente de mazos construidos
│   └── upgrader.py         # análisis de gaps y propuesta de swaps
├── data/
│   └── game_changers.json  # lista oficial WotC
└── templates/
    └── deck.html           # template HTML
```

### Dónde va cada archivo nuevo

| Archivo recibido | Destino |
|------------------|---------|
| `deck_forge.py` | raíz del proyecto (reemplaza al actual) |
| `enrich_collection.py` | raíz del proyecto (reemplaza al actual) |
| `classifier.py` | `core/classifier.py` (reemplaza al actual) |
| `archetypes.py` | `core/archetypes.py` (reemplaza al actual) |
| `deck_index.py` | `core/deck_index.py` (archivo nuevo) |
| `upgrader.py` | `core/upgrader.py` (archivo nuevo) |

---

## Paso 0: Enriquecer la colección

Antes de usar `deck_forge.py` necesitas generar `collection_enriched.json` desde tus exports de ManaBox.

**Sin Tagger:**
```powershell
python enrich_collection.py `
  --real real.csv `
  --fake fake.csv `
  --output collection_enriched.json
```

**Con Scryfall Tagger (clasificación más precisa, recomendado):**
```powershell
python enrich_collection.py `
  --real real.csv `
  --fake fake.csv `
  --output collection_enriched.json `
  --tagger
```

La cookie de Tagger se detecta automáticamente desde Chrome, Edge, Brave o Firefox. Solo necesitas estar logueado en [tagger.scryfall.com](https://tagger.scryfall.com).

Si la auto-detección falla, pásala manualmente:
```powershell
python enrich_collection.py --real real.csv --fake fake.csv --output collection_enriched.json `
  --tagger --tagger-session "TU_COOKIE_AQUI"
```

> F12 → Application → Cookies → `tagger.scryfall.com` → copiar valor de `_scryfall_session`.

La primera ejecución tarda ~5-10 min. Las siguientes son instantáneas (cache en `~/.scryfall_cache/` y `~/.tagger_cache/`).

---

## Comandos

### Analizar el pool

```powershell
python deck_forge.py analyze --collection collection_enriched.json
```

Con más comandantes en el ranking:
```powershell
python deck_forge.py analyze --collection collection_enriched.json --top 40
```

Output: bracket máximo sin compras, profundidad por color identity, top N comandantes con score compuesto.

Flags opcionales: `--min-colors N` (default 2), `--top N` (default 20), `--require-legal`.

---

### Construir 1 mazo

**Eliges comandante:**
```powershell
python deck_forge.py build `
  --collection collection_enriched.json `
  --real-csv real.csv `
  --commander "Teneb, the Harvester" `
  --output-dir .\decks
```

**El script elige por colores + arquetipo:**
```powershell
python deck_forge.py build `
  --collection collection_enriched.json `
  --real-csv real.csv `
  --colors BGW --archetype reanimator `
  --output-dir .\decks
```

Al construir, el mazo queda **registrado automáticamente** en el índice (`decks_index.json`) para poder hacer upgrade después.

---

### Construir varios mazos a la vez

```powershell
python deck_forge.py multi `
  --collection collection_enriched.json `
  --real-csv real.csv `
  --commanders "Vorel of the Hull Clade" "Eivor, Battle-Ready" "Izoni, Thousand-Eyed" `
  --output-dir .\decks
```

---

### Ver mazos guardados

```powershell
python deck_forge.py decks --output-dir .\decks
```

Muestra todos los mazos construidos con su bracket actual, arquetipo, colores y fecha.

---

### Proponer mejoras (upgrade)

```powershell
# Sube 1 bracket por defecto
python deck_forge.py upgrade `
  --deck teneb `
  --collection collection_enriched.json `
  --output-dir .\decks

# O a un bracket concreto
python deck_forge.py upgrade `
  --deck teneb `
  --target-bracket 2 `
  --collection collection_enriched.json `
  --output-dir .\decks
```

`--deck` acepta nombre parcial: `teneb`, `vorel`, `izoni` funcionan igual que el nombre completo.

**Qué muestra el upgrade:**
- Gaps detectados: fast mana insuficiente, manabase débil, game changers, CMC alto...
- Swaps concretos: `QUITA X → METE Y` con razón, solo usando cartas de tu pool real
- Si no hay candidatos en el pool, indica qué comprar y precio aproximado

---

## Arquetipos disponibles

| Key | Nombre | Se detecta cuando el comandante... |
|-----|--------|------------------------------------|
| `counters` | +1/+1 Counters / Proliferate | Tiene "+1/+1 counter", "proliferate", "double the number" |
| `equipment` | Equipment Voltron | Es criatura con "equipment", "equipped creature", "historic" |
| `aristocrats` | Tokens / Sacrifice / Drain | Tiene "creature dies", "create token", "sacrifice" |
| `spellslinger` | Cantrips / Magecraft | Tiene "whenever you cast", "magecraft", "copy spell" |
| `tribal` | Tribal / Kindred | Tiene "you control get +", "of that creature type", "choose a creature type" |
| `blink` | Blink / ETB Abuse | Tiene "exile any number...then return", "whenever a creature enters" |
| `landfall` | Landfall / Land Matters | Tiene "landfall", "whenever a land enters the battlefield" |
| `lifegain` | Lifegain / Life Matters | Tiene "whenever you gain life", "equal to your life total" |
| `reanimator` | Reanimator / Graveyard | Tiene "from your graveyard to the battlefield" |

---

## Outputs por mazo

| Archivo | Para qué sirve |
|---------|----------------|
| `{commander}_manabox.csv` | Importa directo en ManaBox (Settings → Import) |
| `{commander}_moxfield.txt` | Pega en Moxfield/Archidekt al crear deck |
| `decks.html` | Vista interactiva con justificación carta por carta + bracket estimado |
| `decks_index.json` | Índice interno — no tocar manualmente |

---

## Cómo funciona la clasificación (v2)

El `classifier.py` opera en dos capas:

**Capa 1 — Scryfall Tagger tags** (si el JSON fue generado con `--tagger`): usa 87 tags curados para asignar roles con precisión humana.

**Capa 2 — Heurísticas de oracle_text** (fallback universal): si la carta no tiene `tagger_tags`, se analiza el texto. Cubre el 100% del catálogo.

El `collection_enriched.json` generado sin `--tagger` funciona perfectamente — todas las cartas usan la capa 2.

---

## Criterio de scoring de comandantes

| Componente | Peso | Qué mide |
|---|---|---|
| **Densidad de sinergia** | 50% | % de cartas en la identidad que sirven al arquetipo detectado |
| **Techo de bracket** | 30% | Bracket máximo alcanzable desde tu pool |
| **Popularidad EDHREC** | 20% | Desempate suave |

---

## Garantías del script

- ✓ Nunca usa cartas de `fake.csv` (incluso si también aparecen en `real.csv`)
- ✓ Singleton estricto (1 copia por carta)
- ✓ Siempre 100 cartas exactas (rellena con básicas proporcionales a los colores)
- ✓ Todas las cartas tienen Scryfall ID exacto → importación sin fricciones en ManaBox

---

## Limitaciones conocidas

**Heurística de bracket ≠ ManaBox exacto.** El score se basa en señales públicas. ManaBox usa un algoritmo propietario. Si difieren, el de ManaBox manda.

**Detección de arquetipo simplificada.** Si tu comandante es híbrido, el script elige uno por orden de prioridad. Puedes forzar con `--archetype X`.

**Pool real sin compras soporta bracket 1.** Para bracket 2: Sol Ring + Arcane Signet + Command Tower (~€5).

**Tagger API no es pública.** Si la cookie expira, `enrich_collection.py` continúa con heurísticas de oracle_text.

---

## Changelog

| Versión | Cambios |
|---------|---------|
| v1 | `analyze`, `build`, `multi`. 4 arquetipos. Pool real sin fakes. |
| v2 | Power Score percentil 1-10. Score compuesto de comandantes (sinergia + bracket + EDHREC). |
| v3 | Bracket estimado real con `game_changers.json`. Exporters ManaBox CSV + Moxfield txt + HTML. |
| v4 | Scryfall Tagger en `enrich_collection.py`. Classifier v2 (tags + fallback). 5 arquetipos nuevos. |
| v5 | `decks` — lista mazos guardados. `upgrade` — propone swaps por gap de bracket. Auto-detección de cookie Tagger desde navegador. |
