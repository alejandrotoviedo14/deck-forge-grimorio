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
| **Constructor de mazos** | Heurísticas por arquetipo + EDHREC + Claude Haiku para 9 arquetipos distintos |
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

## Arquetipos disponibles (9)

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

---

## Cómo funciona el builder

### 1. Filtrado por identidad de color (3 capas)
1. Pool inicial filtrado por `color_identity ⊆ commander_ci`
2. LLM Critic valida cada carta sugerida antes de aceptarla
3. Filtro final al terminar el build elimina cualquier carta ilegal

### 2. Score compuesto por carta

| Componente | Peso |
|---|---|
| EDHREC score para este comandante | 40% |
| Sinergia con arquetipo (oracle text) | 25% |
| Manabase friendliness (pips de color) | 20% |
| Encaje en la curva actual | 15% |

**Multi-rol bonus:** +15% por cada rol extra que cumple la carta.

### 3. LLM Critic (Claude Haiku)
Después del builder heurístico, Claude Haiku revisa el mazo holísticamente y propone la composición óptima de 50 cartas no tierra. Solo usa cartas disponibles en tu colección. Genera también una guía de juego detallada en español.

### 4. EDHREC
Consulta EDHREC para el comandante específico y enriquece el scoring. Falla gracefully si no hay conexión — usa scoring local sin interrumpir.

---

## Stack técnico

| Capa | Tecnología |
|---|---|
| Backend | FastAPI (Python) |
| Base de datos | Supabase (PostgreSQL) — sesiones PIN |
| Despliegue | Railway |
| Datos de cartas | Scryfall bulk API (caché 7 días) |
| IA | Claude Haiku (Anthropic) |
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
    ├── archetypes.py       # 9 arquetipos con slots
    ├── builder.py          # Ensambla el mazo (score compuesto + EDHREC + LLM)
    ├── edhrec_advisor.py   # Integración EDHREC
    ├── llm_critic.py       # Revisión con Claude Haiku
    ├── bracket.py          # Estimación de bracket WotC
    ├── exporters.py        # HTML grimorio + ManaBox CSV + Moxfield txt
    ├── commander_score.py  # Scoring de comandantes
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
