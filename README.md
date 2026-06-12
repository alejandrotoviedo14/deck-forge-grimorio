# Deck Forge — Grimorio

Constructor de mazos Commander a partir de tu colección de ManaBox. Disponible como aplicación web completa.

**🌐 Acceso online** → [deckforge.up.railway.app](https://deckforge.up.railway.app/)

**🎮 Simulador de mesa** → [deckforge.up.railway.app/simulator](https://deckforge.up.railway.app/simulator)

---

## ¿Qué es Deck Forge?

Deck Forge construye mazos de Commander optimizados a partir de las cartas que ya tienes en tu colección física. Sube tu CSV de ManaBox, selecciona un comandante y obtén un mazo de 100 cartas listo para jugar — con imágenes, guía de juego y exportación a ManaBox/Moxfield.

---

## Características

| Función | Descripción |
|---|---|
| **Constructor de mazos** | Heurísticas por arquetipo + EDHREC + Claude Sonnet para 19 arquetipos distintos |
| **Identidad de color estricta** | Tres capas de validación — ninguna carta ilegal puede entrar al mazo |
| **Grimorio** | Visor de mazos con imágenes Scryfall, filtros por color/tipo, ordenación, zoom |
| **Simulador de mesa** | Mesa de juego interactiva con todas las fases de turno, maná, combate y tokens |
| **Sesiones con PIN** | Colección y mazos guardados en Supabase — accesibles desde cualquier dispositivo con 6 dígitos |
| **Análisis de comandantes** | Puntúa los mejores comandantes para tu pool con score y bracket estimado |

---

## Uso rápido

1. Ve a [deckforge.up.railway.app](https://deckforge.up.railway.app/)
2. **I. Colección** — sube tu CSV de ManaBox (`Settings → Export → CSV`) y guarda tu PIN
3. **II. Analizar** — descubre los mejores comandantes para tu colección
4. **III. Forjar** — elige comandante y forja el mazo
5. **IV. Grimorio** — visualiza, filtra y descarga el mazo
6. **V. Simular** — prueba el mazo en una mesa de juego interactiva

### PIN de sesión
Al subir tu colección recibes un **PIN de 6 dígitos**. Introdúcelo en cualquier dispositivo para restaurar tu colección completa y todos los mazos forjados.

---

## Simulador de mesa

Accede en [/simulator](https://deckforge.up.railway.app/simulator).

| Función | Detalle |
|---|---|
| **Fases de turno** | Destapear → Mantenimiento → Robar → Principal → Combate → Final — cada fase hace algo real |
| **Zona de tierras** | Strip horizontal separado; tap para producir maná por color |
| **Pool de maná** | Muestra W/U/B/R/G/C disponible en tiempo real |
| **Campo de batalla** | Drag & drop libre; doble tap para tapear/destapear |
| **Comandante** | Zona propia con contador de impuesto (+2 por lanzamiento) |
| **Combate** | Declara atacantes tocando criaturas; resolución automática |
| **Tokens** | Crea tokens con nombre, P/T, color y cantidad personalizados |
| **Mulligan** | London mulligan con selector de cartas a devolver |
| **Zoom** | Toca cualquier carta para verla a tamaño completo |
| **Teclado** | D=robar, U=destapear, E=fase final, C=comandante, M=mulligan |

---

## Grimorio — controles

| Control | Opciones |
|---|---|
| **Agrupar** | Por categoría · Por tipo · Por color · Sin grupos (plano) |
| **Filtrar color** | Todos · W · U · B · R · G · Incoloro · Multicolor |
| **Ordenar** | Por defecto · Nombre A-Z · CMC ↑↓ · Tipo · Color · Popularidad |
| **Vista** | Cartas (grid) · Lista |

---

## Arquetipos disponibles (19)

### Clásicos
| Arquetipo | Descripción |
|---|---|
| `counters` | +1/+1 Counters / Proliferate |
| `equipment` | Equipment Voltron |
| `aristocrats` | Tokens / Sacrifice / Drain |
| `spellslinger` | Spellslinger / Cantrips |
| `tribal` | Tribal / Kindred |
| `blink` | Blink / ETB Abuse |
| `landfall` | Landfall / Land Matters |
| `lifegain` | Lifegain / Life Matters |
| `reanimator` | Reanimator / Graveyard |

### EDHREC / Scryfall (v4)
| Arquetipo | Descripción |
|---|---|
| `tokens` | Go-Wide / Token Swarm |
| `group_hug` | Group Hug / Wheels |
| `enchantress` | Enchantress / Enchantment Payoffs |
| `artifacts` | Artifacts / Treasure / Affinity |
| `voltron` | Voltron / Auras |
| `stax` | Stax / Prison / Hatebears |
| `mill` | Mill (opponent) |
| `big_mana` | Big Mana / X Spells / Ramp Payoffs |
| `superfriends` | Superfriends / Planeswalkers |
| `pillowfort` | Pillowfort / Defensive |

La detección de arquetipo prioriza los **themes reales de EDHREC** para ese
comandante (cómo lo juega la comunidad); si no hay datos, cae a heurística por
oracle text del comandante.

---

## Cómo funciona el builder

### 1. Filtrado por identidad de color (3 capas)
1. Pool inicial filtrado por `color_identity ⊆ commander_ci`
2. LLM Critic valida cada carta sugerida antes de aceptarla
3. Filtro final al terminar el build elimina cualquier carta ilegal

### 2. Score compuesto por carta

| Componente | Peso |
|---|---|
| Sinergia con el comandante (EDHREC) | 40% |
| Sinergia con el arquetipo (oracle text) | 25% |
| EDHREC rank general (calidad bruta) | 25% |
| Encaje en la curva actual (CMC) | 10% |

**Multi-rol bonus:** +15% por cada rol extra que cumple la carta.

### 3. Manabase y tierras (v4)
- **Básicas proporcionales a pips de color**: cuenta los símbolos `{W}{U}{B}{R}{G}` de
  todo el mazo y reparte las básicas según esa proporción (mínimo 2 por color),
  no a partes iguales.
- **Nº de tierras dinámico**: `31 + avgCMC×2 − ramp×0.4`, acotado entre 33 y 40 —
  mazos agresivos de curva baja con mucho ramp llevan menos tierras que los de
  big mana.

### 4. LLM Critic (Claude Sonnet 4.6)
Después del builder heurístico, Claude Sonnet revisa el mazo holísticamente y
propone la composición óptima de 50 cartas no tierra, usando como referencia el
**plan de slots del arquetipo detectado** (no un molde único para todos). Solo
usa cartas disponibles en tu colección. Genera también una guía de juego
detallada en español.

### 5. EDHREC
Consulta EDHREC para el comandante específico (themes, high-synergy cards) y
enriquece tanto la detección de arquetipo como el scoring. Falla gracefully si
no hay conexión — usa scoring local sin interrumpir.

### 6. Selección de comandante (v6)
El ranking de comandantes prioriza **tu colección**, no la popularidad en
EDHREC, y es **específico de cada comandante**:

- **`fit`**: mezcla la densidad del arquetipo que el texto del comandante pide
  (60%) con la mejor densidad de tu pool en sus colores (40%). Dos comandantes
  con la misma identidad de color ya no puntúan igual.
- **`tribal_fit`**: si el comandante referencia una tribu, cuenta cuántas
  criaturas de esa tribu tienes de verdad.
- Curva de densidad **suave y sin cap** — sin empates masivos donde la
  popularidad decidía el orden.
- La popularidad EDHREC es solo un desempate (5%). Comandantes poco jugados
  pero bien soportados por tu colección aparecen marcados con 💎 **nicho**.
- **Diversidad**: máx. 4 comandantes por identidad de color y 6 por arquetipo
  en el top.
- **💡 Descubrimientos de hoy**: 5 comandantes fuera del top-N que rotan cada
  día — las joyas del rango 21-60 también tienen su oportunidad.

---

## Stack técnico

| Capa | Tecnología |
|---|---|
| Backend | FastAPI (Python) |
| Base de datos | Supabase (PostgreSQL) — sesiones PIN |
| Despliegue | Railway |
| Datos de cartas | Scryfall bulk API (caché 7 días) |
| IA | Claude Sonnet 4.6 (Anthropic) |
| Frontend | HTML/CSS/JS vanilla |

---

## Estructura del proyecto

```
├── main.py                 # FastAPI — todos los endpoints
├── ingest.py               # Procesa CSV de ManaBox + Scryfall bulk
├── Dockerfile              # Imagen para Railway
├── web/
│   ├── index.html          # Interfaz web principal (5 pestañas)
│   └── simulator.html      # Mesa de juego interactiva
└── core/
    ├── pool.py             # Filtrado del pool y color identity
    ├── classifier.py       # Detecta roles de cada carta
    ├── archetypes.py       # 19 arquetipos con slots + EDHREC theme mapping
    ├── builder.py          # Ensambla el mazo (score compuesto + manabase + EDHREC + LLM)
    ├── edhrec_advisor.py   # Integración EDHREC
    ├── llm_critic.py       # Revisión con Claude Sonnet 4.6
    ├── bracket.py          # Estimación de bracket WotC
    ├── exporters.py        # HTML grimorio + ManaBox CSV + Moxfield txt
    ├── commander_score.py  # Scoring de comandantes (v5: prioriza tu colección)
    ├── deck_index.py       # Índice persistente de mazos
    └── upgrader.py         # Análisis de gaps y mejoras
```

---

## Garantías

- ✅ Nunca usa cartas de `fake.csv` (proxies excluidas)
- ✅ Singleton estricto (1 copia por carta)
- ✅ Siempre 100 cartas exactas
- ✅ Identidad de color validada en tres capas
- ✅ EDHREC falla gracefully — scoring local como fallback
- ✅ Sesiones persistentes vía PIN (Supabase)

---

## Changelog

| Versión | Cambios |
|---|---|
| v1–v9 | CLI local: analyze, build, multi, upgrade. 9 arquetipos. Scryfall bulk. forge.py lenguaje natural. |
| v10 | Builder v3: score compuesto, multi-rol, EDHREC por comandante. |
| v11 | **Web app**: FastAPI + Railway. UI con 4 pestañas. Grimorio online. |
| v12 | **UI MTG**: diseño parchment/gold, Cinzel, grimorio con imágenes y zoom. |
| v13 | **Wincons dinámicos**: extraídos de cartas reales del mazo, no hardcodeados. |
| v14 | **LLM Critic activo**: Claude Haiku revisa y mejora cada mazo. Guía de juego. |
| v15 | **Colecciones guardadas**: dropdowns en todas las pestañas, comandante del análisis pre-seleccionado. |
| v16 | **Simulador básico**: mesa de juego con mano, robar, mulligan, cementerio, exilio. |
| v17 | **PIN de sesión**: colección + mazos guardados en Supabase, accesibles desde cualquier dispositivo. |
| v18 | **Simulador completo**: fases de turno, pool de maná, tierras separadas, drag & drop, combate, tokens, commander zone. Mobile-first con Action Sheet. |
| v19 | **Grimorio mejorado**: agrupación por categoría/tipo/color/plano, filtro por color, sort por color. Fix: cartas visibles tras restaurar PIN. |
| v20 | **Color identity estricto**: 3 capas de validación — pool filter + LLM Critic validation + final safety filter. |
| v21 | **Siempre 100 cartas**: relleno inteligente por composite score cuando slots no llenan. Overflow guard. |
| v22 | **Conflictos entre mazos**: detecta cartas compartidas entre mazos del mismo PIN, elige la siguiente mejor alternativa automáticamente. |
| v23 | **Importar mazo de ManaBox** (Tab IV): sube CSV de tu mazo existente, detecta comandante, estima bracket, muestra conflictos con otros mazos del PIN. |
| v24 | **Versionado de mazos** (vorel → vorel_v2), fix color identity en fill del critic, tooltips ricos en grimorio (por qué está + impacto), sección de conflictos por mazo. |
| v25 | **Inteligencia superior (P1)**: fix doble invocación del Critic, review con Claude Sonnet, prompt con razonamiento paso a paso + reservas + razón/impacto por carta, scoring rebalanceado (40% sinergia comandante). |
| v26 | **Usabilidad (P2)**: forjar sin re-subir CSV (se sintetiza), barra de progreso por etapas, borrar mazos, PIN persistente con auto-restauración al recargar. |
| v27 | **Look & feel (P3)**: grimorio unificado con la estética pergamino/oro de la web. |
| v28 | **Simulador (P4)**: selector de color en tierras multicolor, persistencia de partida (reanudar al recargar). |
| v29 | **Referencia precon**: análisis profundo de Jeskai Striker (WotC 2025) como estándar Bracket 2. Proporciones canónicas integradas en el prompt de Claude Sonnet. |
| v30 | **Commander Spellbook**: detección de combos completos y "a 1 carta" en cada mazo. Sección de combos en el grimorio. |
| v31 | **Precios Scryfall**: precio por carta en tooltip, total del mazo en stats, top-10 más caras, distribución por rangos. |
| v32 | **EDHREC themes + inclusión %**: themes como pills, % de inclusión real de cada carta en mazos reales. |
| v33 | **Scryfall Tagger propio**: índice de 4952 cartas con 24 tags funcionales (mana-rock, cantrip, board-wipe…) construido desde oracle text. Classifier 10× más preciso. |
| v34 | **Dashboard visual del mazo**: curva de maná, distribución de tipos, radar de categorías, colores. Sinergias detectadas (10 tipos). Análisis enriquecido de comandantes (combos, precio, themes, relevancia). Búsqueda Scryfall integrada filtrada a colección. |
| v35 | **10 arquetipos nuevos** (tokens, group hug, enchantress, artifacts, voltron, stax, mill, big mana, superfriends, pillowfort) — total 19. UI sin animaciones. |
| v36 | **Manabase y arquetipo data-driven**: básicas proporcionales a pips de color, tierras dinámicas (31+avgCMC×2−ramp×0.4), arquetipo detectado por themes reales de EDHREC, Critic en Sonnet 4.6 con plan de slots por arquetipo, queries de upgrade para los 19 arquetipos. |
| v37 | **Selector de comandante por colección**: comandantes de nicho (poco datos en EDHREC) ya no se penalizan por popularidad — el ranking se basa en sinergia real con tu pool y poder alcanzable. Badge 💎 nicho en el análisis. |
| v38 | **Scoring específico del comandante (v6)**: fin de los empates — curva de densidad suave sin cap, `fit` que mezcla lo que el texto del comandante pide con lo que ofrece tu pool, soporte tribal real (cuenta tus Elfos/Dragones de verdad), diversidad por arquetipo además de por colores, y **💡 Descubrimientos de hoy**: 5 comandantes fuera del top que rotan a diario. |
| v39 | **Manabase v7 + simulación de manos + UI explicable**: utility lands puntuadas por los pips reales del mazo (penalización ETB tapped según curva, bonus por texto de utilidad); cada mazo se valida simulando 2000 manos iniciales (% jugables, jugada turno 1-2, mulligans medios) y se muestra al forjar; preview de carta flotante al pasar el ratón sobre cualquier comandante; mini-barras de desglose (fit/tribal) que explican el score. |
| v40 | **Prompt engineering v8 + bucle cerrado**: el Critic recibe el estado computado del draft (curva, pips, conteos por categoría) en lugar de inferirlo, datos reales de synergy+inclusión% de EDHREC por carta, paso de auto-verificación antes de responder (60 exactas, identidad de color, mínimos de ramp/draw/interacción) y objetivo de curva por arquetipo; el build se **autocorrige**: si <85% de manos simuladas son jugables, cambia relleno por básicas y re-simula antes de exportar; botón "🎲 Roba una mano de ejemplo" con las imágenes reales de 7 cartas del mazo recién forjado. |
| v41 | **Análisis 33× más rápido + UX accesible**: precomputación por arquetipo e identidad de color en el scoring de comandantes (18.4s → 0.56s en pool de 1500, resultados idénticos verificados); cursores estándar (fuera el martillo), contraste subido en todos los textos apagados (WCAG), tamaños mínimos legibles en tablas/tabs/etiquetas, tabs numeradas como asistente (1·Colección → 4·Grimorio) con tooltips, foco visible para teclado, targets táctiles de 44px en móvil y CTA de "siguiente paso" tras subir la colección. |
| v42 | **Rediseño completo (design system v10)**: un solo tema oscuro premium — se elimina el pergamino (causa de los botones dorados ilegibles sobre fondo claro), las 5 fuentes de fantasía, el texto en gradiente y los ornamentos. 2 fuentes (Cinzel solo marca, Inter UI), dorado únicamente como acento, botón primario dorado sólido con texto oscuro (~9.5:1), chips/segundarios oscuros con texto claro (~8:1), tarjetas planas elevadas, tablas/forms/simulador re-estilizados al sistema. CSS 26% más ligero. |
| v43 | **Fix monocultivo tribal (v11)**: el texto del comandante MANDA sobre su arquetipo (el pool solo mide soporte); densidad calculada solo sobre slots temáticos (sin Ramp/Draw/Removal compartidos ni catch-alls); `is_tribal_commander` estricto (kindred / chosen type / mención de su propia tribu, con plurales Elves/Wolves/Mice); prioridad de detección reordenada (triggers específicos antes que efectos amplios); el slot tribal de cuerpos se especializa a la tribu real al construir; predicados actualizados al wording moderno de Scryfall 2024 ("enters" sin "the battlefield"). Verificado: 48/48 comandantes en su arquetipo natural, top-20 con 5 arquetipos. |
