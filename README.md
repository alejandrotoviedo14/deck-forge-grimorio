# Deck Forge — Grimorio

Constructor de mazos Commander a partir de tu colección de ManaBox.

**Disponible online** → [deck-forge-grimorio-production.up.railway.app](https://deck-forge-grimorio-production.up.railway.app/)

**Cero tokens de Claude consumidos en tiempo de ejecución.** Todo se ejecuta en el servidor con tu colección exportada de ManaBox.

---

## Uso web (recomendado)

Accede desde cualquier dispositivo, sin instalar nada:

1. Abre la URL de arriba
2. Exporta tu colección desde ManaBox (`Settings → Export → CSV`)
3. Sube el CSV en la pestaña **I. Colección**
4. Analiza tu pool en **II. Analizar**
5. Forja un mazo en **III. Forjar**
6. Visualiza y descarga en **IV. Grimorio**

---

## Uso local (CLI)

---

## Instalación

```powershell
pip install requests pandas pyedhrec
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
│   ├── classifier.py       # detecta roles de cada carta (ramp, draw, removal...)
│   ├── archetypes.py       # 9 arquetipos con slots rebalanceados (v3)
│   ├── builder.py          # ensambla el mazo — score compuesto + EDHREC + multi-rol (v3)
│   ├── edhrec_advisor.py   # integración con EDHREC para ranking por comandante
│   ├── bracket.py          # estima bracket WotC
│   ├── exporters.py        # HTML multi-mazo con modal zoom, lista, ordenación
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

`ingest.py` usa el bulk data de Scryfall (descarga única ~300MB) en lugar de llamadas individuales. **Segundos en lugar de 5-10 minutos. Sin cookies. Sin configuración.**

```powershell
python ingest.py --real real.csv --fake fake.csv --output collection_enriched.json
```

La primera ejecución descarga el bulk (~100-300MB). Las siguientes son instantáneas — se reutiliza durante 7 días.

| Formato | Comando |
|---------|---------|
| CSV de ManaBox (real + fake) | `python ingest.py --real real.csv --fake fake.csv` |
| Solo real | `python ingest.py --real real.csv` |
| Lista de texto (Moxfield/Archidekt) | `python ingest.py --list mi_coleccion.txt` |
| Forzar re-descarga del bulk | Añadir `--refresh-bulk` |

---

## Uso

Hay dos formas de ejecutar Deck Forge:

- **`forge.py`** — lenguaje natural, comandos cortos. Recomendado para uso diario.
- **`deck_forge.py`** — CLI completo con flags explícitos. Para automatización o casos avanzados.

---

## Comandos rápidos con `forge.py`

```powershell
python forge.py analizar
python forge.py mazos
python forge.py construir mazo rojo
python forge.py construir simic counters
python forge.py construir goblins
python forge.py construir reanimator negro verde
python forge.py upgrade vorel
python forge.py mejorar teneb hasta bracket 2
```

| Tipo | Palabras reconocidas |
|------|---------------------|
| **Acciones** | `analizar`, `construir`, `mejorar`/`upgrade`, `mazos`/`listar` |
| **Colores** | `blanco`, `azul`, `negro`, `rojo`, `verde` |
| **Guilds** | `azorius`, `dimir`, `rakdos`, `gruul`, `selesnya`, `orzhov`, `izzet`, `golgari`, `boros`, `simic` |
| **Shards** | `esper`, `grixis`, `jund`, `naya`, `bant`, `abzan`, `jeskai`, `sultai`, `mardu`, `temur` |
| **Arquetipos** | `counters`, `equipment`/`voltron`, `aristocrats`/`tokens`/`sacrifice`, `spellslinger`, `tribal`/`goblins`/`elves`/`vampires`/`dragons`/`zombies`, `blink`/`flicker`, `landfall`, `lifegain`, `reanimator`/`graveyard` |
| **Bracket** | `bracket 2`, `hasta 3` |

---

## Comandos completos con `deck_forge.py`

```powershell
# Analizar pool
python deck_forge.py analyze --collection collection_enriched.json

# Construir 1 mazo (con EDHREC activo por defecto)
python deck_forge.py build `
  --collection collection_enriched.json `
  --real-csv real.csv `
  --commander "Teneb, the Harvester" `
  --output-dir .\decks

# Construir sin consultar EDHREC (más rápido, scoring local)
python deck_forge.py build `
  --collection collection_enriched.json `
  --real-csv real.csv `
  --commander "Teneb, the Harvester" `
  --output-dir .\decks `
  --no-edhrec

# Construir varios mazos
python deck_forge.py multi `
  --collection collection_enriched.json `
  --real-csv real.csv `
  --commanders "Vorel of the Hull Clade" "Eivor, Battle-Ready" "Izoni, Thousand-Eyed" `
  --output-dir .\decks

# Ver mazos guardados
python deck_forge.py decks --output-dir .\decks

# Proponer mejoras
python deck_forge.py upgrade --deck teneb --collection collection_enriched.json --output-dir .\decks
python deck_forge.py upgrade --deck teneb --target-bracket 2 --collection collection_enriched.json --output-dir .\decks
python deck_forge.py upgrade --deck teneb --max-price 5 --collection collection_enriched.json --output-dir .\decks
python deck_forge.py upgrade --deck teneb --no-purchases --collection collection_enriched.json --output-dir .\decks
```

---

## Cómo funciona el builder (v3)

### 1. Score compuesto por carta

En lugar de ordenar solo por EDHREC rank (que penaliza cartas nuevas o poco conocidas), cada carta recibe un **score compuesto**:

| Componente | Peso sin EDHREC | Peso con EDHREC |
|---|---|---|
| Sinergia con arquetipo (oracle text) | 40% | 25% |
| EDHREC score para este comandante | — | 40% |
| Manabase friendliness (pips de color) | 25% | 20% |
| Encaje en la curva actual del mazo | 20% | 15% |
| EDHREC rank genérico | 15% | — |

**Multi-rol bonus:** cartas que cumplen varios roles útiles simultáneamente (ej: ramp + draw, removal + cuerpo) reciben +15% por cada rol extra. Esto premia la versatilidad que es clave en Commander.

### 2. Integración con EDHREC

Al construir un mazo, el builder consulta EDHREC para el comandante específico:
- **High synergy cards**: cartas que aparecen MÁS en listas de este comandante vs. el promedio general
- **Top cards**: las más jugadas con este comandante
- **Commander cards**: todas las categorías recomendadas

Las recomendaciones se cruzan con tu pool real. Las cartas en EDHREC reciben score más alto; las que no aparecen reciben score neutro (0.3) — no se penalizan, porque pueden ser buenas cartas simplemente menos conocidas.

Los datos se cachean en `~/.deck_forge_cache/edhrec/` durante 48h para evitar peticiones repetidas.

### 3. Slots rebalanceados (v3)

Los slots de cada arquetipo ahora priorizan **Ramp → Draw → Removal** antes de los slots específicos del arquetipo. Esto garantiza que el mazo siempre tenga una base funcional sólida antes de especializarse.

El arquetipo Equipment pasó de 18 equipos a 12, con predicado de criaturas de soporte que requiere sinergia real (no solo CMC≤3).

---

## El grimorio HTML

Cada `build` genera/actualiza `decks/decks.html` con:

- Sidebar con todos los mazos
- Hero por mazo con imagen del comandante
- Stats: cartas, CMC medio, manabase, bracket
- Estrategia + wincons del arquetipo
- Bracket detail con game changers, fast mana, tutores
- Gaps para subir bracket
- Grid de cartas con imágenes Scryfall + tooltip al hover
- **Modal zoom** al hacer click en cualquier carta (X, Escape o click fuera)
- **Toggle Cartas / Lista**
- **Ordenación** por defecto, alfabético, CMC (asc/desc), tipo, popularidad EDHREC

### Grimorio online

```
https://alejandrotoviedo14.github.io/deck-forge-grimorio/
```

Para actualizar tras un build:
```powershell
Copy-Item "decks\decks.html" -Destination "index.html" -Force
git add index.html
git commit -m "update grimorio"
git push
```

---

## Arquetipos disponibles (9)

| Key | Nombre | Slots (orden) |
|-----|--------|---------------|
| `counters` | +1/+1 Counters / Proliferate | Ramp → Draw → Removal → Payoffs → Threats |
| `equipment` | Equipment Voltron | Ramp → Removal → Draw → Equipment → Synergy → Soporte |
| `aristocrats` | Tokens / Sacrifice / Drain | Ramp → Draw → Removal → Tokens → Sac Outlets → Death Payoffs → Wincons |
| `spellslinger` | Spellslinger / Cantrips | Payoffs → Counters → Burn → Draw → Ramp |
| `tribal` | Tribal / Kindred | Ramp → Draw → Removal → Lords → Criaturas |
| `blink` | Blink / ETB Abuse | Ramp → Draw → Removal → ETB Payoffs → Blink Enablers |
| `landfall` | Landfall / Land Matters | Land Ramp → Draw → Removal → Payoffs → Threats |
| `lifegain` | Lifegain / Life Matters | Ramp → Draw → Removal → Payoffs → Life Sources → Wincons |
| `reanimator` | Reanimator / Graveyard | Ramp → Draw → Removal → Reanimation → Enablers → Targets |

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

## Cache de EDHREC

Los datos de EDHREC se guardan en `~/.deck_forge_cache/edhrec/` (un JSON por comandante).
TTL: 48 horas. Para forzar re-consulta:

```powershell
Remove-Item "$env:USERPROFILE\.deck_forge_cache\edhrec\*" -Force
```

---

## Garantías

- ✓ Nunca usa cartas de `fake.csv`
- ✓ Singleton estricto (1 copia por carta)
- ✓ Siempre 100 cartas exactas
- ✓ Todas las cartas tienen Scryfall ID exacto → importación sin fricciones en ManaBox
- ✓ EDHREC falla gracefully — si no hay conexión, usa scoring local sin interrumpir

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
| v9 | `forge.py`: CLI en lenguaje natural. HTML: modal zoom, toggle Cartas/Lista, ordenación. |
| v10 | Builder v3: score compuesto (sinergia + manabase + curva + rank). Multi-rol bonus. Integración EDHREC por comandante. Slots rebalanceados: Ramp → Draw → Removal primero en todos los arquetipos. Equipment: 18→12 equipos, criaturas de soporte con sinergia real. `--no-edhrec` flag. |
