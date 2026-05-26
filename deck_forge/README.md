# Deck Forge

Constructor local de mazos Commander a partir de tu colección de ManaBox.

**Cero tokens de Claude consumidos en tiempo de ejecución.** Todo se ejecuta en tu máquina con tu `collection_enriched.json` ya generado.

---

## Instalación

```powershell
pip install requests pandas browser-cookie3
```

---

## Estructura del proyecto

```
deck_forge/
├── deck_forge.py           # CLI completo (acciones + flags)
├── forge.py                # CLI en lenguaje natural (wrapper)
├── ingest.py               # genera collection_enriched.json (Scryfall bulk)
├── enrich_collection.py    # generador alternativo legacy (deprecated)
├── core/
│   ├── __init__.py
│   ├── pool.py             # carga collection_enriched.json + filtra fakes
│   ├── classifier.py       # detecta roles (ramp, draw, removal...)
│   ├── archetypes.py       # 9 arquetipos
│   ├── builder.py          # ensambla el mazo de 100 cartas
│   ├── bracket.py          # estima bracket WotC
│   ├── exporters.py        # ManaBox CSV, Moxfield txt, HTML multi-mazo
│   ├── commander_score.py  # scoring compuesto de comandantes
│   ├── deck_index.py       # índice persistente de mazos construidos
│   └── upgrader.py         # análisis de gaps + swaps + compras Scryfall
├── data/
│   └── game_changers.json  # lista oficial WotC
└── templates/
    └── deck.html           # template HTML (legacy)
```

---

## Paso 0: Generar la colección enriquecida

`ingest.py` usa el bulk data de Scryfall (descarga única de ~300MB) en lugar de llamadas individuales a la API. **Resultado: segundos en lugar de 5-10 minutos. Sin cookies. Sin configuración.**

```powershell
python ingest.py --real real.csv --fake fake.csv --output collection_enriched.json
```

La primera ejecución descarga el bulk (~100-300MB). Las siguientes son instantáneas — el bulk se reutiliza durante 7 días.

**Formatos de entrada soportados:**

| Formato | Comando |
|---------|---------|
| CSV de ManaBox (real + fake) | `python ingest.py --real real.csv --fake fake.csv` |
| Solo real | `python ingest.py --real real.csv` |
| Lista de texto (Moxfield/Archidekt) | `python ingest.py --list mi_coleccion.txt` |
| Forzar re-descarga del bulk | Añadir `--refresh-bulk` |

**Formato de lista de texto:**
```
1 Sol Ring
4 Lightning Bolt (M21)
Counterspell
// Las líneas con // se ignoran
```

---

## Uso

Hay dos formas de ejecutar Deck Forge:

- **`forge.py`** — lenguaje natural, comandos cortos. Recomendado para uso diario.
- **`deck_forge.py`** — CLI completo con flags explícitos. Recomendado para automatización o casos avanzados.

---

## Comandos rápidos con `forge.py`

```powershell
# Analizar el pool
python forge.py analizar

# Listar mazos guardados
python forge.py mazos

# Construir un mazo (por colores)
python forge.py construir mazo rojo
python forge.py construir mazo simic
python forge.py construir mazo grixis

# Construir un mazo (por arquetipo)
python forge.py construir goblins
python forge.py construir reanimator
python forge.py construir lifegain

# Combinar colores + arquetipo
python forge.py construir simic counters
python forge.py construir mazo negro verde reanimator

# Mejorar un mazo
python forge.py upgrade vorel
python forge.py mejorar teneb hasta bracket 2
```

**Vocabulario reconocido:**

| Tipo | Palabras |
|------|----------|
| **Acciones** | `analizar`, `construir`, `mejorar`/`upgrade`, `mazos`/`listar` |
| **Colores** | `blanco`, `azul`, `negro`, `rojo`, `verde` |
| **Guilds (2 colores)** | `azorius`, `dimir`, `rakdos`, `gruul`, `selesnya`, `orzhov`, `izzet`, `golgari`, `boros`, `simic` |
| **Shards (3 colores)** | `esper`, `grixis`, `jund`, `naya`, `bant`, `abzan`, `jeskai`, `sultai`, `mardu`, `temur` |
| **Arquetipos** | `counters`, `equipment`/`voltron`, `aristocrats`/`tokens`/`sacrifice`, `spellslinger`/`spells`, `tribal`/`kindred`/`goblins`/`elves`, `blink`/`flicker`, `landfall`/`lands`, `lifegain`/`life`, `reanimator`/`graveyard` |
| **Bracket** | `bracket 2`, `hasta 3` |

Si la frase es ambigua, `forge.py` te muestra cómo refinarla.

---

## Comandos completos con `deck_forge.py`

### Analizar el pool

```powershell
python deck_forge.py analyze --collection collection_enriched.json
```

Flags opcionales: `--min-colors N` (default 2), `--top N` (default 20), `--require-legal`.

### Construir 1 mazo

```powershell
python deck_forge.py build `
  --collection collection_enriched.json `
  --real-csv real.csv `
  --commander "Teneb, the Harvester" `
  --output-dir .\decks
```

O por colores + arquetipo:
```powershell
python deck_forge.py build `
  --collection collection_enriched.json `
  --real-csv real.csv `
  --colors BGW --archetype reanimator `
  --output-dir .\decks
```

### Construir varios mazos

```powershell
python deck_forge.py multi `
  --collection collection_enriched.json `
  --real-csv real.csv `
  --commanders "Vorel of the Hull Clade" "Eivor, Battle-Ready" "Izoni, Thousand-Eyed" `
  --output-dir .\decks
```

### Ver mazos guardados

```powershell
python deck_forge.py decks --output-dir .\decks
```

### Proponer mejoras (upgrade)

```powershell
# Sube 1 bracket por defecto
python deck_forge.py upgrade --deck teneb --collection collection_enriched.json --output-dir .\decks

# Bracket objetivo concreto
python deck_forge.py upgrade --deck teneb --target-bracket 2 --collection collection_enriched.json --output-dir .\decks

# Con presupuesto de compra diferente (default: €10)
python deck_forge.py upgrade --deck teneb --max-price 5 --collection collection_enriched.json --output-dir .\decks

# Solo pool, sin consultar Scryfall
python deck_forge.py upgrade --deck teneb --no-purchases --collection collection_enriched.json --output-dir .\decks
```

---

## El grimorio HTML

Cada `build` genera/actualiza un `decks/decks.html` rico con:

- **Sidebar** con todos los mazos guardados
- **Hero** por mazo con imagen del comandante en blur + retrato grande
- **Stats**: cartas, CMC medio, manabase, bracket
- **Estrategia + wincons** del arquetipo
- **Bracket detail** con game changers, fast mana, tutores detectados
- **Gaps** para subir bracket
- **Grid de cartas con imágenes Scryfall** + tooltip al hover
- **Modal zoom** al hacer click en cualquier carta (X o Escape para cerrar)
- **Toggle vista Cartas / Lista**
- **Ordenación** por defecto, alfabético, CMC (asc/desc), tipo, popularidad EDHREC

### Grimorio online

Si tienes el proyecto en GitHub Pages, el grimorio se sirve en:
```
https://TU_USUARIO.github.io/deck-forge-grimorio/
```

Para actualizar después de un build:
```powershell
Copy-Item "decks\decks.html" -Destination "index.html" -Force
git add index.html
git commit -m "update grimorio"
git push
```

---

## Arquetipos disponibles

| Key | Nombre | Se detecta cuando el comandante... |
|-----|--------|------------------------------------|
| `counters` | +1/+1 Counters / Proliferate | Tiene "+1/+1 counter", "proliferate" |
| `equipment` | Equipment Voltron | Es criatura con "equipment", "equipped creature" |
| `aristocrats` | Tokens / Sacrifice / Drain | Tiene "creature dies", "create token", "sacrifice" |
| `spellslinger` | Cantrips / Magecraft | Tiene "whenever you cast", "magecraft" |
| `tribal` | Tribal / Kindred | Tiene "you control get +", "of that creature type" |
| `blink` | Blink / ETB Abuse | Tiene "exile...then return", "whenever a creature enters" |
| `landfall` | Landfall / Land Matters | Tiene "landfall", "whenever a land enters" |
| `lifegain` | Lifegain / Life Matters | Tiene "whenever you gain life" |
| `reanimator` | Reanimator / Graveyard | Tiene "from your graveyard to the battlefield" |

---

## Outputs por mazo

| Archivo | Para qué sirve |
|---------|----------------|
| `{commander}_manabox.csv` | Importa directo en ManaBox (Settings → Import) |
| `{commander}_moxfield.txt` | Pega en Moxfield/Archidekt al crear deck |
| `decks/decks.html` | Grimorio local con todos los mazos |
| `decks/decks_index.json` | Índice interno — no tocar manualmente |
| `index.html` | Copia del grimorio para GitHub Pages |

---

## Cómo funciona la clasificación

`classifier.py` opera en dos capas:

**Capa 1 — Oracle text (principal):** lee el texto de reglas de cada carta y detecta patrones. `"search your library for basic land"` → ramp. `"draw a card"` → draw. `"destroy target"` → removal. Funciona porque WotC usa lenguaje de reglas estandarizado y consistente.

**Capa 2 — Scryfall Tagger tags (opcional, legacy):** disponible solo si el JSON fue generado con `enrich_collection.py --tagger`. Mejora marginalmente la precisión. No requerido para uso normal.

---

## Scoring de comandantes

| Componente | Peso | Qué mide |
|---|---|---|
| **Densidad de sinergia** | 50% | % de cartas en la identidad que sirven al arquetipo detectado |
| **Techo de bracket** | 30% | Bracket máximo alcanzable desde tu pool |
| **Popularidad EDHREC** | 20% | Desempate suave |

---

## Garantías

- ✓ Nunca usa cartas de `fake.csv` (incluso si también aparecen en `real.csv`)
- ✓ Singleton estricto (1 copia por carta)
- ✓ Siempre 100 cartas exactas (rellena con básicas proporcionales a los colores)
- ✓ Todas las cartas tienen Scryfall ID exacto → importación sin fricciones en ManaBox

---

## Limitaciones conocidas

**Heurística de bracket ≠ ManaBox exacto.** El score se basa en señales públicas. Si difieren, el de ManaBox manda.

**Detección de arquetipo simplificada.** Si tu comandante es híbrido, el script elige uno por orden de prioridad. Fuerza con `--archetype X` (o el alias correspondiente en `forge.py`).

**Pool real sin compras soporta bracket 1.** Para bracket 2: Sol Ring + Arcane Signet + Command Tower (~€5).

**Sugerencias de compra requieren conexión.** El comando `upgrade` consulta Scryfall en tiempo real. Usa `--no-purchases` sin internet.

---

## Changelog

| Versión | Cambios |
|---------|---------|
| v1 | `analyze`, `build`, `multi`. 4 arquetipos. Pool real sin fakes. |
| v2 | Power Score percentil 1-10. Score compuesto de comandantes. |
| v3 | Bracket estimado real. Exporters ManaBox CSV + Moxfield txt + HTML. |
| v4 | Scryfall Tagger opcional. Classifier v2. 5 arquetipos nuevos (9 total). |
| v5 | `decks` + `upgrade`. Auto-detección de cookie Tagger. |
| v6 | `upgrade` con sugerencias de compra reales desde Scryfall. `--max-price`, `--no-purchases`. |
| v7 | HTML multi-mazo con imágenes Scryfall, roles, wincons, bracket detail. GitHub Pages. |
| v8 | `ingest.py`: Scryfall bulk data. Segundos en lugar de minutos. Soporte para listas de texto. |
| v9 | `forge.py`: CLI en lenguaje natural (`construir mazo rojo`, `upgrade vorel`...). HTML: modal zoom al click en cartas, toggle vista Cartas/Lista, ordenación por nombre/CMC/tipo/rank. |