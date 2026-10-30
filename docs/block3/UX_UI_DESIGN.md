# MCPCONECCT — Plan de rediseño UX/UI del escritorio Rust

> **Anexo de diseño del Bloque 3 — especificación v0.1 para implementación.**
>
> **Repositorio:** [MCPCONECCT](https://github.com/glender222/MCPCONECCT). **Archivo:** `docs/block3/UX_UI_DESIGN.md`. **Referencia técnica:** [README del Bloque 3](README.md) y [Bloque 2](../block2/README.md).
>
> **Naturaleza de la revisión:** auditoría estática del código de interfaz `desktop_app/src/app.rs` (2.595 líneas), `desktop_app/src/research_client.rs` y componentes asociados. **No se ha ejecutado la app ni inspeccionado una captura real en esta revisión.** Las observaciones sobre botones, navegación y estados son verificables en código; calidad final del aspecto y accesibilidad requiere capturas y pruebas visuales reales.
>
> **Este documento es un plan, no una implementación realizada.** La prioridad es mejorar la herramienta que ya existe sin romper los Bloques 1–3.

---

## 1. ¿El Bloque 3 cambia el diseño?

**Sí, parcialmente.** El Bloque 3 técnico ya exige:
- Rediseño funcional de Conexiones sin Burp ni lectura automática de cookies.
- Búsqueda y biblioteca centradas en el proyecto activo.
- Corrección de acciones incorrectas (`READ`, `research_type`, ingesta a `default_slr`).
- Estados de carga, errores, paginación, feedback y modularización de `app.rs`.
- Menús laterales, historial de búsquedas por proyecto y gestión de notas.
- Eliminación del modo web genérico y flujos no soportados.

**Pero NO especifica todavía** una experiencia visual coherente ni la prioridad/disposición óptima de cada control. Este anexo cubre ese vacío.

**Decisión:** introducir **Fase 3.4-UX — Diseño y ergonomía** dentro del Bloque 3, coordinada con la Fase 3.4 técnica. No crear un «Bloque 4» ni cambiar de `egui/eframe` solo por estética. Primero resolver semántica/función, luego componentes, diseño y prueba visual.

## 2. Objetivo del rediseño

MCPCONECCT debe sentirse como un **workspace académico nativo**, moderno, tranquilo, legible y eficiente, no como un panel de depuración con muchos botones. El foco del usuario es **buscar información científica, seleccionarla, organizarla por proyecto, leer su bibliografía y extraer evidencia**. Los agentes MCP son clientes auxiliares; el escritorio no debe imitar una interfaz de chat ni presentar una caja de conversación.

**Modelo visual propuesto:** editor/biblioteca de investigación con:
1. Barra lateral de proyectos y secciones.
2. Encabezado contextual del proyecto actual.
3. Superficie de trabajo principal.
4. Panel contextual de detalle/inspector cuando una publicación, búsqueda o evento se selecciona.
5. Barra secundaria discreta con estado real de backend/operación.

Inspiración de patrones, **no copia literal**: organización de colecciones tipo Zotero, densidad/estados tipo herramientas profesionales de productividad, navegación limpia tipo editor moderno. Conservar la identidad MCPCONECCT.

**Criterio de valor de un botón:** si no ayuda al objetivo del usuario actual, no corresponde a ese contexto o repite otra acción, debe moverse, fusionarse o retirarse. No «hacer todos los botones más bonitos» manteniendo las mismas decisiones incorrectas.

---

## 3. Problemas demostrados por el código

| ID | Evidencia | Problema de UX | Requisito |
|---|---|---|---|
| UI-01 | `app.rs:970–1194` | Barra lateral fija ~270 px, 9 pestañas, encabezados largos, panel central con scroll global | Jerarquía compacta, ancho adaptable y vistas de trabajo |
| UI-02 | `app.rs:975–980, 1011–1015, 1045–1077` | Texto de navegación forzado a blanco/colores de modo oscuro; tema claro puede quedar con bajo contraste | Colores semánticos por tema |
| UI-03 | `app.rs:1100–1122` | Estado Burp ocupa espacio de alto valor en el pie; refresco manual | Retirar Burp productivo, mostrar estado backend útil |
| UI-04 | `app.rs:1151–1173` | Título muy extenso más proyecto activo a la derecha: desborde posible en ventanas pequeñas | Header contextual adaptable |
| UI-05 | `app.rs:2234–2354` | Buscar, ingestar, desduplicar y exportar están en una fila junto con lote y enriquecimiento | Un flujo principal por etapa, controles secundarios progresivos |
| UI-06 | `app.rs:2236–2247` | «Corpus Central SLR (default_slr)» visible incluso al trabajar en otro proyecto | Resumen exclusivo del proyecto activo |
| UI-07 | `app.rs:1603–1611` | «Leído» manda `READING` | Corregir acción y modelo de control |
| UI-08 | `app.rs:1623–1626` | El resultado de `update_reading_status` se descarta y se refresca igualmente | Confirmación/errores visibles y control de carga |
| UI-09 | `app.rs:1330–1349` | Campo research_type editable no se envía en guardado | Estado de formulario fiel a la persistencia |
| UI-10 | `app.rs:1353–1375` | Archivar/desarchivar sin confirmación contextual | Acción secundaria y confirmación no destructiva |
| UI-11 | `app.rs:1400–1499` | Dos procesos de añadir/eliminar RQs/objetivos y un botón de guardado independiente, sin claro indicador «cambios no guardados» | Editor con borrador, dirty state y Guardar cambios |
| UI-12 | `app.rs:1528–1547` | Filtro de estado dispara refresh; búsqueda de texto requiere otro botón Filtrar | Debounce, aplicación explícita y resumen de filtros |
| UI-13 | `app.rs:1558–1620` | Cada publicación ocupa una tarjeta extensa con tres botones de estado, enlace y notas | Lista compacta + inspector de detalle + acciones contextuales |
| UI-14 | `app.rs:1654–1677` | Elegir publicación con ComboBox que carga múltiples títulos largos | Selector buscable o inspector desde biblioteca |
| UI-15 | `app.rs:1688–1829` | Formulario de notas y evidencia comparte área con un listado largo y etiquetas técnicas | Editor contextual y bloque de procedencia comprensible |
| UI-16 | `app.rs:1853–1963` | Importar y exportar en columnas rígidas, pegar texto como entrada principal y sin selector de archivo visible | Asistente ligero de importación y cuadro de exportación |
| UI-17 | `app.rs:1864–1865` | El texto «pegar o arrastrar» no demuestra implementación de arrastrar y soltar | Soportar DnD realmente o quitar promesa |
| UI-18 | `app.rs:1925–1927` | «Ámbito» muestra solo `ALL`; es un control visual sin alternativa | Solo mostrar scope si hay alternativas implementadas |
| UI-19 | `app.rs:1835–1837` | Título promete restauración, pero la vista no muestra flujo de restaurar | Implementar paso real o evitar afirmación |
| UI-20 | `app.rs:1966–2035, 2523–2549` | Historial de proyecto, historial MCP y función render_audit_tab duplicada/no incluida en ActiveTab | Unificar Actividad y trazabilidad |
| UI-21 | `app.rs:2037–2165` | Panel centrado en Burp, Firefox, proxy y pruebas repetidas | Tarjetas de proveedores con capacidades y acciones reales |
| UI-22 | `app.rs:2151–2163` | Selector de proveedor de proxy modifica `selected_db` usado también en búsqueda | Estado separado; evitar cambios sorpresa |
| UI-23 | `app.rs:2168–2183` | Botón carga una ecuación hardcodeada sobre un estudio específico | Mover ejemplos a menú; no representar como caso universal |
| UI-24 | `app.rs:2222–2229` | Campos traducidos editables sobre `trans.ieee.clone()`/otras copias; cambios no persistentes | Read-only + «Copiar» o editor real con estado |
| UI-25 | `app.rs:2434–2519` | Visor independiente de exportaciones solapa Intercambio | Integrar historial de exportaciones con panel contextual |
| UI-26 | `app.rs:2444–2448` | «Abrir Carpeta» usa `xdg-open` con ruta absoluta personal | Acceso multiplataforma y rutas dinámicas; si falla, mensaje |
| UI-27 | `app.rs:1133–1145, 1243–1266` | Barra de estado y toasts muestran feedback duplicado; colores codificados por emojis | Sistema de feedback claro, tipado y consistente |
| UI-28 | `app.rs:2255–2271` | Opciones de base y modo mezcladas con rango de años en una sola línea | Agrupar filtros; adaptar a tamaño de ventana |
| UI-29 | `app.rs:2388–2420` | Resultados crudos sin selección ni acciones de biblioteca por publicación; cita con controles repetidos en todas las tarjetas | Lista/resultados + detalle + acción primaria clara |
| UI-30 | `research_client.rs:140–349` | Cliente de investigación bloqueante; eventos pueden congelar dibujo UI | Operaciones async con progresos y cancelación |

**Evaluación:** los estilos actuales no son únicamente «feos»; el problema raíz es mezcla de responsabilidades, duplicación, falta de jerarquía y acciones que parecen válidas aunque no siempre lo sean.

---

## 4. Nueva arquitectura de información (IA)

### 4.1 Navegación principal propuesta

```text
MCPCONECCT                 [ + Nuevo proyecto ]
─────────────────────────────────────────────────
PROYECTOS                  [Buscar proyecto]
  ● Investigación GNN
    Seguridad IoT
    + 6 más                 [Ver todos / archivados]

ESPACIO DE TRABAJO
  Resumen
  Búsquedas                (historial por proyecto)
  Biblioteca               (resultados guardados)
  Actividad                (runs, cambios y agentes)

HERRAMIENTAS
  Conexiones               (Scopus, IEEE, Springer, WoS...)
  Editor de consultas      (básica/booleana, PICO opcional)
  Importar / exportar      (intercambio e historial exportado)

─────────────────────────────────────────────────
  Estado del servicio ●
  Ajustes · Apariencia
```

**Cambios frente a la IA actual:**
- «Alcance y Preguntas» pasa a **Resumen** (incluye descripción, preguntas, objetivos).
- «Búsqueda Multi-Base» pasa a **Búsquedas**, mostrando **lista de ejecuciones/consultas del proyecto** y editor para nueva búsqueda, no un chat.
- «Notas y Evidencia» queda integrada en el **detalle de cada publicación**; acceso transversal a notas puede existir en Biblioteca con filtro de anotaciones, sin otra pantalla vacía o redundante.
- «Historial & Auditoría» y la función no conectada `render_audit_tab` se consolidan en **Actividad** con filtros `Búsquedas / Cambios / Agentes`.
- «Visor de Exportaciones» se integra en **Importar / exportar** como historial + vista previa, no tab permanente.
- «Calibrador PICO & RSL» pasa a **Editor de consultas**, con PICO como herramienta optativa; no imponer metodología de revisión sistemática a todo proyecto.
- «Conexiones & Burp Suite» pasa a **Conexiones**. Burp no aparece en UI productiva.

No se deben eliminar funciones accesibles: si una sección se fusiona, debe existir ruta funcional a todas sus operaciones vigentes, salvo funciones inseguras/deprecadas definidas por el Bloque 3 técnico.

### 4.2 Modelo de selección

Siempre existe un `active_project_id` estable (UUID), no depender solo de `selected_project_idx`. Cada `active_search_run_id` y `active_publication_id` pertenece a ese proyecto. Cambiar de proyecto:
1. Interroga borradores sucios antes de descartarlos, guardarlos o cambiar contexto.
2. Invalida/cancela solicitudes de UI del proyecto anterior cuando corresponda.
3. Muestra skeleton o loading real; no reutiliza visualmente datos viejos bajo un proyecto nuevo.
4. Restablece filtros/contexto conforme a política explícita por proyecto.
5. Nunca dispara búsqueda/guardado en `default_slr`.

---

## 5. Wireframes funcionales (no capturas finales)

### 5.1 Búsquedas

```text
[Sidebar]  Investigación GNN / Búsquedas
           Encuentra y organiza fuentes científicas
           ───────────────────────────────────────────────────
           [ Nueva búsqueda ]       Fuente: [ IEEE Xplore ▾ ]  ● Acceso
           [ Palabras clave | Ecuación booleana ]
           ┌─────────────────────────────────────────────────┐
           │ ("graph neural network" OR GNN) AND anomaly     │
           │                                                 │
           └─────────────────────────────────────────────────┘
           [ 2020 — 2026 ▾ ] [Tipo documento ▾] [Más filtros ▾]
           [ Verificar ecuación ]            [ Buscar publicaciones ]

           Historial de búsquedas
           ✓  IEEE  |  Consulta 1  |  25 observaciones | Hoy
           !  Scopus|  Consulta 2  |  Sesión expirada  | Ayer

           Resultados de consulta seleccionada
           [Seleccionar todo] [Agregar seleccionados a biblioteca]
           ☐ Título del artículo, año, autores, fuente...
           ☐ Título del artículo, año, autores, fuente...
                            Panel de detalles → resumen/DOI/cita/notas
```

**Punto clave:** según integración del Bloque 3, decidir UNA de dos experiencias y mantenerla sin duplicación:
- **Modelo preferido:** «Buscar publicaciones» inicia `AcquisitionService` y guarda de inmediato observaciones/publicaciones en proyecto con `UNREAD`; resultados muestran lo adquirido; no se requiere un segundo botón «Ingestar Streaming». La acción «Agregar...» solo se muestra si se define un modo de previsualización/no persistencia realmente distinto.
- **Alternativa válida:** una búsqueda exploratoria no persistente y un segundo acto «Guardar resultados seleccionados». En ese caso debe almacenarse un estado de selección claro y explicarse qué se guarda y qué no. No llamar «Ingestar Streaming» a una operación incomprensible para el usuario.

**El equipo debe elegir y documentar uno; no construir ambos como botones inconexos.** Recomendación predeterminada: modelo único persistente, acorde con `research_start_search` de Bloque 2.

### 5.2 Biblioteca

```text
Investigación GNN / Biblioteca                       [Importar] [Exportar]
────────────────────────────────────────────────────────────────────────
Buscar por título, autor, DOI...        [Estado ▾] [Colección ▾] [Tipo ▾]
124 publicaciones · 18 leyendo · 23 leídas
☐  Título                                        Año   Fuente  Lectura
☐  Detection of...                              2025  IEEE    Leído
☐  A graph...                                   2024  Scopus  Sin leer
☐  Robust learning...                           2023  Crossref Leyendo
────────────────────────────────────────────────────────────────────────
[Primera] [Anterior]  Página 1 de 5  [Siguiente] [Última]

                   Inspector al seleccionar publicación:
                   Título completo
                   DOI / autores / revista / fuente realmente consultada
                   [Abrir artículo] [Copiar cita ▾] [Estado ▾] [···]
                   Resumen · Notas y evidencia · Observaciones
```

El inspector evita repetir botones largos en cada tarjeta. Un documento no debe parecer un «proyecto nuevo» solo porque tiene un encabezado visual grande.

### 5.3 Conexiones

```text
Conexiones                                           [Probar todas]
──────────────────────────────────────────────────────────────────
IEEE Xplore            ● Acceso público      [Probar] [Conectar]
Scopus                 ○ Autenticación       [Conectar] [Abrir portal]
SpringerLink           ! Acceso limitado     [Detalles] [Abrir portal]
Web of Science         ○ No configurado      [Configurar]

Detalles de IEEE:
  Mecanismo disponible: API oficial / portal...
  Capacidades: metadatos ✓ · búsqueda avanzada ✓ · exportación ✓
  Verificado: fecha/hora
  [Reconectar] [Desconectar] [Ver limitaciones]

Diagnóstico técnico avanzado (plegable, sin credenciales)
```

Nunca poner «Conectado institucional» solo porque abrió una pestaña o hubo HTTP 200; el diseño sigue los estados del Bloque 3 técnico.

---

## 6. Sistema de diseño: reglas visuales concretas

### 6.1 Personalidad visual

**Dirección recomendada:** «Academic Workspace Minimal». Sobria y profesional, con densidad media; más información útil y menos recuadros repetidos. No hacer una copia visual de ChatGPT, no llenar títulos de emojis ni usar animaciones decorativas.

### 6.2 Tokens semánticos

Crear `theme.rs` y `components/*` reutilizables. Propuesta de tokens (valores iniciales sujetos a revisión visual):

| Token | Oscuro | Claro | Uso |
|---|---|---|---|
| background | `#111318` | `#F7F8FA` | Fondo del workspace |
| sidebar | `#171A20` | `#FFFFFF` | Navegación |
| surface | `#1D222A` | `#FFFFFF` | Inspector / bloques |
| surface_hover | `#252B35` | `#F0F3F7` | Hover/selección suave |
| border | `#303743` | `#E3E7EE` | Delimitadores |
| text_primary | `#E9EDF3` | `#20242B` | Lectura |
| text_secondary | `#A3ACBA` | `#606B7B` | Metadatos |
| accent | `#6596F5` | `#285FD1` | Acción primaria/foco |
| success | `#4DBA83` | `#157A52` | Éxito real |
| warning | `#E1B35D` | `#956900` | Acceso limitado/atención |
| error | `#EA7373` | `#BA3030` | Error |

El contraste se evalúa por combinaciones reales de texto/fondo; los valores propuestos se ajustan si no cumplen WCAG AA para texto normal (4,5:1) e indicadores relevantes (3:1). **No usar `Color32::WHITE` para todo texto del sidebar en modo claro.**

### 6.3 Espaciado y dimensiones

- Grid base: **4 px**, con escalas 4/8/12/16/24/32.
- Sidebar: 240–290 px, redimensionable y con límite; opción de colapsar a iconos si resulta usable.
- Header contextual: ~56–64 px; breadcrumb compacto + proyecto, evitando dos grandes títulos por vista.
- Botones: altura táctil/clickable recomendable ~32–36 px en desktop y objetivos de ≥40 px para acciones críticas; iconos 16–18 px; etiquetas claras.
- Inputs: altura ~36 px; editor booleano multilinea con mínimo ~110 px y espacio de expansión.
- Inspector: ~320–420 px o 30–38 % del área disponible, redimensionable; al estrechar ventana, cambia a drawer o vista exclusiva.
- Texto: 22–24 px título de pantalla, 16–18 px subtítulo, 13–14 px cuerpo, 11–12 px metadatos; escalar con sistema.
- Radios: 6–10 px; bordes discretos, no 20 tarjetas `ui.group` idénticas en una lista.
- Estados de selección usan fondo, indicador, foco y texto, no solo color.
- Mantener `DarkModern` y `AcademicLight`, pero aplicar los mismos tokens y jerarquía en ambos.

No aplicar tamaños rígidos que desborden pantallas 1280×720; probar también 1440×900 y ≥1920×1080, además de escalas 125 %/150 %. Sin suponer DPI fijo.

### 6.4 Tipografía/iconografía

Usar fuente legible del sistema o una alternativa redistribuible correctamente licenciada ya disponible en runtime. No empaquetar fuentes externas sin licencias adecuadas. Conservar Unicode solo si renderiza consistentemente.

Sustituir emojis decorativos heterogéneos por iconografía unificada (egui assets o librería compatible, sin migrar de framework). Asociar texto de accesibilidad/tooltip a iconos. No confiar en emoji para representar semántica de error o éxito.

### 6.5 Componentes comunes

`PrimaryButton`, `SecondaryButton`, `DestructiveAction`, `IconButton`, `SearchInput`, `ProviderStatus`, `StatusPill`, `FilterChip`, `EmptyState`, `InlineError`, `ProgressIndicator`, `ConfirmDialog`, `InspectorPanel`, `PaginatedList`, `Toast`, `FormField` y `DirtyFormGuard`.

No inventar componentes si son simples wrappers sin beneficios; deben centralizar estilo, estado, accesibilidad y feedback.

---

## 7. Contrato funcional obligatorio de TODOS los controles

Antes de diseñar un botón, registrar:

| Campo | Pregunta |
|---|---|
| `control_id` | Identidad estable para tests y seguimiento |
| `location` | Vista/panel concreto |
| `intent` | ¿Qué necesidad del investigador resuelve? |
| `label` | Texto claro, idealmente verbo + objeto |
| `visual_priority` | Primaria / secundaria / terciaria / peligrosa |
| `visible_when` | ¿En qué contexto aparece? |
| `enabled_when` | ¿Qué permisos, proyecto, datos y backend requiere? |
| `action_handler` | Función real invocada; endpoint/servicio |
| `input` | ¿Qué datos y revisión utiliza? |
| `request_state` | Idle / loading / success / error / cancelled |
| `success_feedback` | Qué prueba realmente el éxito, y qué refresca |
| `error_feedback` | Cómo se conserva borrador y permite reintento |
| `confirm_policy` | Si modifica/destruye/archiva, ¿confirma? |
| `keyboard_access` | Foco, atajo, etiqueta y tooltip |
| `test_id` | Test que demuestra el resultado |

**Reglas generales**
- No mostrar acción primaria habilitada sin proyecto válido cuando es específica del proyecto.
- No dejar dos escrituras simultáneas del mismo formulario.
- Nunca actualizar badge «Guardado» solo por hacer clic; esperar confirmación de API.
- Un botón secundario no compite visualmente con la acción primaria.
- No crear controles que hagan exactamente lo mismo en una misma vista, salvo acción global y contextual justificadas.
- Acciones peligrosas requieren confirmación con impacto explicado; deshabilitar no sustituye explicar.
- Botones solo icono requieren tooltip y nombre accesible; `↻` aislado resulta ambiguo.
- Si el usuario cambia proyecto o filtro durante una petición, descartar respuesta obsoleta mediante `request_id` y scope.
- Los filtros de una vista no deben modificar de manera oculta los parámetros de otra.
- Mantener UX funcional cuando está offline: mostrar contenido cacheado identificado como tal, si existe; prohibir escrituras falsas.
- No usar spinner infinito: timeout, causa y reintento o cancelar.

---

## 8. Auditoría de controles actuales: decisiones por pantalla

Esta matriz es **instrucción funcional**, no solo cambio visual. Códigos de decisión: **MANTENER**, **CORREGIR**, **MOVER**, **FUSIONAR**, **RETIRAR**, **CONDICIONAR**, **AÑADIR SI IMPLEMENTADO**.

### 8.1 Controles globales, navegación y ventana crear proyecto

| Control/acción existente | Decisión | Comportamiento esperado |
|---|---|---|
| `+ Nuevo` en sidebar | MANTENER | Abrir creación con foco en nombre, Enter para crear si válido, Escape cancela |
| Selección de proyecto | CORREGIR | Selección por `project_id` estable; proteger borradores; actualizar todas las vistas sin bloqueo |
| Navegación de nueve pestañas | FUSIONAR | Usar nueva IA de sección 4 y preservar rutas útiles |
| `Modo Claro / Modo Oscuro` | MOVER | Menú Ajustes/Apariencia, opción accesible, persistir preferencia; no ocupar pie como botón largo |
| `↻` estado Burp | RETIRAR | No mostrar indicador productivo Burp |
| `↻` backend | CORREGIR | Acción «Reconectar servicio» solo ante error; indicador compacto de estado y tooltip |
| Badge «Backend Conectado» | MANTENER | Reflejar healthcheck real, fecha y estado sin engañar |
| Modal «Crear Proyecto» | CORREGIR | Validación inline, contraste, redacción y jerarquía clara |
| `Crear Proyecto` | MANTENER | Solo habilitar con nombre válido; loading y error conservando formulario; seleccionar creado |
| `Cancelar` creación | MANTENER | Cerrar con Escape; si hay datos no guardados, confirmar descarte cuando corresponda |
| Toast flotante + barra «Estado» | FUSIONAR | Toast transitorio para resultado breve, error persistente inline cuando requiere acción; barra solo estado global |
| Encabezado `Proyecto activo` | CORREGIR | Breadcrumb/selector estable y responsive; no repetir nombre en todas las tarjetas |

### 8.2 Resumen / Metadatos / Preguntas y objetivos

| Control | Decisión | Comportamiento esperado |
|---|---|---|
| Nombre y descripción editables | MANTENER | Formulario de proyecto con dirty state y validaciones |
| Tipo de investigación editable | CORREGIR | Persistir realmente `research_type`; opcional y no condicionado a RSL |
| `Guardar Metadatos` | CORREGIR | «Guardar cambios»; deshabilitado sin cambios o durante request; mostrar conflicto revision |
| `Archivar Proyecto` | MOVER/CONDICIONAR | Menú `···` en encabezado; confirmar que queda solo lectura sin borrar bibliografía |
| `Desarchivar Proyecto` | MOVER | Menú `···` o banner en vista archivada; mostrar éxito al volver a editable |
| `Recargar desde Servidor` | MOVER | Acción discreta, solo ante errores/conflictos; proteger cambios locales |
| `×` de pregunta de investigación | CORREGIR | Icono eliminar con tooltip y foco; no perder evidencia enlazada; conflicto visible |
| `+ Añadir RQ` | MANTENER | Validar texto; actualizar borrador, indicar «sin guardar» |
| `×` de objetivo | CORREGIR | Misma política de eliminación, no confundir con cerrar ventana |
| `+ Añadir OBJ` | MANTENER | Añadir al borrador, foco y orden correcto |
| `Guardar Esquema Completo` | FUSIONAR VISUALMENTE | «Guardar preguntas y objetivos» contextual; deshabilitado si no hay cambios; compatibilidad con revisión |
| ID del proyecto / revisión | MOVER | Detalles técnicos desplegables; no principal encabezado de formulario |
| `Reintentar conexión` | MANTENER | Error con causa + reintento real, sin bloqueo del hilo UI |
| `Crear Primer Proyecto` | MANTENER | CTA único en empty state, no duplicado con otras acciones de la misma región |

No crear un guardado único silencioso de metadatos + outline sin servicio transaccional definido: visualmente pueden compartir diseño, pero cada persistencia conserva sus contratos y estados hasta poder unificarse correctamente.

### 8.3 Búsquedas y resultados

| Control | Decisión | Comportamiento esperado |
|---|---|---|
| `↻ Actualizar` resumen corpus `default_slr` | RETIRAR/CORREGIR | Sustituir por indicadores de proyecto activo refrescables sin bloquear UI |
| Selector IEEE/Springer/Scopus | CORREGIR | Dropdown o selector de fuente con icono/estado/capacidades reales; incluir WoS solo si soportado |
| Selector modo Avanzada/Normal | MANTENER | Segmented control con explicación «Palabras clave / Ecuación booleana» y validación específica |
| Rango de años | CORREGIR | Filtro de rango claro con validación inicio ≤ fin; máximo año configurable/actualizable |
| Checkboxes tipo documento | MOVER | Popover/panel de filtros por proveedor; valores no soportados ocultos o deshabilitados con motivo |
| Editor consulta multilinea | CORREGIR | Componente principal con contador, ejemplo contextual, teclado y errores subrayados cuando AST esté disponible |
| `Buscar en Base de Datos` | MANTENER COMO PRIMARIA | Renombrar «Buscar publicaciones»; impedir doble disparo, validar consulta y proyecto; mostrar run |
| Indicador spinner búsqueda | MANTENER/CORREGIR | Progreso auténtico, número de observaciones, estado y cancelación cuando API la soporte |
| Lote `bulk_ingest_records` | MOVER | Opciones avanzadas o «Límite de resultados» antes de iniciar; valores explicados |
| `Enriquecer DOI` checkbox | MOVER | Preferencia avanzada contextual con costo/efecto; preferiblemente por búsqueda |
| `Ingestar Streaming` | FUSIONAR | No duplicar búsqueda guardada. Si existe modo exploratorio separado, explicar «Guardar resultados» |
| `Desduplicar Corpus` | RETIRAR DEL FLUJO PRINCIPAL | Servicio de identidad automática segura y fusiones **manuales supervisadas** en mantenimiento de biblioteca |
| Botones `.BIB`, `.CSV`, `.RIS` | FUSIONAR/MOVER | «Exportar ▾» con formatos y scope; preferir menú en Biblioteca o Intercambio |
| `Copiar BibTeX` + `Cerrar` drawer | MANTENER CONTEXTUAL | Visor de exportación sólo tras export, sin ocupar pantalla de búsqueda permanentemente |
| `Ver en portal ›` | MANTENER | Abrir URL segura y real en navegador con nombre de fuente, no abrir en Burp |
| Selector cita IEEE/APA 7/LaTeX por paper | MOVER | Un selector global de estilo en menú `Copiar cita ▾` o preferencia; no repetir 3 toggles por registro |
| `Copiar (ESTILO)` | MANTENER | Solo si metadatos suficientes; citar como formato preliminar si no hay garantía de estilo completo |
| Lista de resultados en tarjetas grandes | CORREGIR | Tabla/lista compacta + detalle lateral y selección; procedencia y paginación reales |
| `Verificar ecuación` | AÑADIR SI IMPLEMENTADO | Mostrar reporte AST del Bloque 3; no ejecutar como traducción exacta si no hay equivalencia |
| `Cancelar ejecución` | AÑADIR SI IMPLEMENTADO | Se muestra solo RUNNING/QUEUED; cancelación por run_id real |
| `Reintentar ejecución` | AÑADIR SI IMPLEMENTADO | Nuevo run explícito; conservar original en historial |

**Criterio visual:** en búsqueda debe haber **una única acción primaria** y un camino visible hasta el artículo; nada de cinco botones equivalentes antes de ver resultados.

### 8.4 Biblioteca

| Control | Decisión | Comportamiento esperado |
|---|---|---|
| Campo `Buscar` | MANTENER | Debounce 250–400 ms o Enter; sin refresh sincrónico por tecla |
| `Filtrar` | RETIRAR SI DEBOUNCE | Si hay botón «Aplicar filtros», usarlo para todos los filtros; no mezcla de automático/manual |
| Filtros Todos/No leído/Leyendo/Leído | CORREGIR | Segmented o dropdown con contador; combinación AND y estado preservado |
| `Refrescar` | MOVER | Icono de toolbar con tooltip y estado loading; no competir con buscar |
| Tres botones por registro para lectura | FUSIONAR | Dropdown/selector de estado en fila o inspector; muestra opción actual sin tres CTA |
| `Leído` actual | **CORREGIR P0** | Enviar `READ`, no `READING` |
| `Ver/Añadir Notas y Evidencias` | FUSIONAR | Abrir pestaña «Notas» del inspector de ese paper; conservar ID/proyecto |
| `Ver Enlace` | MANTENER | En inspector; abrir URL comprobada con etiquetado correcto |
| Lista de tarjetas de publicación | CORREGIR | Compacta con filas seleccionables y detalles; nunca título en heading gigante por fila |
| Colecciones y etiquetas (prometidas) | AÑADIR SI IMPLEMENTADO | Mostrar filtros/acciones reales; no chips decorativos sin persistencia |
| Paginación | AÑADIR | Consultar `total`/`limit`/`offset`, no mostrar solo 100 y titularlos «todos» |
| Selección múltiple | AÑADIR CON PROPÓSITO | Exportar/organizar/estado masivo solo con operaciones seguras y autorizadas, sin automezclas |
| Fusión manual sugerida | AÑADIR SI IMPLEMENTADO | Vista previa de DOI/identidad/proyectos afectados y confirmación explícita |

En una lista de artículos, **el título es una fila clicable**, no un botón de acción científica. La interacción principal abre detalle; otras acciones viven en inspector/menú de fila.

### 8.5 Notas y evidencias

| Control | Decisión | Comportamiento esperado |
|---|---|---|
| ComboBox con «todas las publicaciones» | FUSIONAR | Selección desde Biblioteca + buscador opcional; si >100, no listar títulos interminables |
| `Refrescar Notas` | MOVER | Toolbar discreta, feedback de error |
| Tipo NOTA/CITA/PARÁFRASIS | MANTENER | Segmented con explicación corta y contenido dinámico |
| Origen ABSTRACT/FULLTEXT | MANTENER CONDICIONAL | Solo para evidencia textual; explicación de procedencia y capacidad |
| Campo Localizador | MANTENER CONDICIONAL | Solo FULLTEXT, obligatorio; ejemplos, validación y error inline |
| Selector RQ vinculada | MANTENER | Opcional, solo si hay preguntas y del proyecto; buscable si es largo |
| Campo Contenido | MANTENER | Editor cómodo, autoscroll, contador/límites y conservación de borrador |
| `Guardar Nota / Evidencia` | CORREGIR | Validar, respetar revisión/scope, deshabilitar mientras envía, responder solo al éxito |
| Lista de anotaciones | CORREGIR | Por publicación/selección, tipo y fecha; mostrar actor/provenance legibles |
| Editar nota existente | AÑADIR SI ENDPOINT FUNCIONA | Contrato Bloque 2 `research_update_annotation` con conflict handling; no inventar |
| Eliminar anotación | NO AÑADIR SIN CONTRATO | Bloque 2 no incluye eliminación permanente; no mostrar icono de papelera decorativo |

Notas y evidencia no deben indicar «FULLTEXT verificado» cuando el usuario solo ha pegado texto; mantener «fuente declarada por el autor» y locator.

### 8.6 Importación, exportación y restauración

| Control | Decisión | Comportamiento esperado |
|---|---|---|
| Selector BibTeX/RIS/CSV para importar | MANTENER | O autodeducir por extensión/archivo; permitir corregir |
| Pegar texto a importar | MANTENER COMO ALTERNATIVA | Entrada principal debería admitir selección real de archivo si se implementa |
| Etiqueta «arrastrar archivo» | CORREGIR | Habilitar DnD mediante API nativa o quitar la promesa |
| `Previsualizar Importación` | MANTENER COMO PRIMARIA DE PASO 1 | Validar, mostrar progreso, previsualización y errores por fila |
| `Limpiar` | MOVER | Acción terciaria junto a input; confirmar si destruye un borrador extenso |
| `Confirmar e Incorporar a la Biblioteca` | MANTENER COMO PRIMARIA DE PASO 2 | Solo preview válido/no caducado/proyecto editable; mostrar totales y errores |
| Scope «Proyecto Completo» único | RETIRAR CONTROL INÚTIL | Mostrar texto de ámbito; desplegar selector únicamente al soportar colecciones |
| Formatos BIB/RIS/CSV/JSON de exportación | MANTENER | Un control de formato claro y explicación de qué conserva cada uno |
| `Generar Exportación` | MANTENER | Distinguir generar vs guardar archivo en disco, manejar error y volumen |
| `Copiar al Portapapeles` | MANTENER CONTEXTUAL | Solo hay salida; feedback real |
| `Guardar archivo…` | AÑADIR SI IMPLEMENTADO | Diálogo nativo de archivo; sin ruta fija; función crítica para un producto desktop |
| Restaurar proyecto JSON | AÑADIR SI IMPLEMENTADO | Bloque 2 define backend; crear flujo preview/confirm en UI solo con contrato real |
| Historial del visor de exportaciones | FUSIONAR | Lista accesible en Intercambio; inspección, copiar, abrir carpeta si existe |
| `Refrescar Exportaciones` | MOVER | Solo en historial de archivos, no en pantalla principal de investigación |
| `Abrir Carpeta exports/` | CORREGIR | Ruta del SO y shell/open multiplataforma; comprobar existencia |
| `Copiar Contenido` | MANTENER | Dentro del visor, con error si no se pudo leer archivo |

### 8.7 Actividad e historial

| Control | Decisión | Comportamiento esperado |
|---|---|---|
| `Refrescar Eventos del Proyecto` | FUSIONAR | Toolbar «Actualizar» común al timeline |
| `Refrescar Consultas` | FUSIONAR | Mismo botón con filtros/tabs: Ejecuciones, Cambios, Agentes |
| `Refrescar Historial` en render_audit_tab | RETIRAR COMO DUPLICADO | Integrar lógica/campos útiles, eliminar función muerta tras tests |
| Filas de evento | CORREGIR | Item seleccionable con detalle de cambio, actor y fecha; no solo IDs gigantes |
| Filas de consulta | CORREGIR | Estado real `COMPLETED/PARTIAL/FAILED/CANCELLED`, fuente, conteos, filtro por proyecto |
| Conteo de hits global | CORREGIR | Distinguir total reportado, observado, único y cacheado |
| Exportar diagnóstico | AÑADIR SOLO SI REDACTADO | Opcional y seguro; requiere preview de datos a compartir |

### 8.8 Conexiones

| Control | Decisión | Comportamiento esperado |
|---|---|---|
| `Diagnosticar Salud de Conexiones & WAF` | RENOMBRAR | «Probar conexiones»; estado y capacidades reales de cada proveedor |
| `Extraer Automáticamente Sesiones desde Firefox (1-Clic)` | **RETIRAR** | Prohibido como experiencia normal: mecanismo inseguro/no portable |
| `Abrir en Burp` Scopus | **RETIRAR** | Reemplazar con «Abrir portal» en navegador del sistema |
| `Abrir en Burp` IEEE | **RETIRAR** | Igual |
| `Abrir en Burp` SpringerLink | **RETIRAR** | Igual |
| `Probar` Scopus | MANTENER | Acción en tarjeta de proveedor, prueba funcional y motivo de fallo |
| `Probar` IEEE | MANTENER | Igual |
| `Probar` SpringerLink | MANTENER | Igual, sin falso «SpringerLink» cuando se consultó Crossref |
| WoS: simple estado | CORREGIR | Dar acciones Conectar/Probar si la capacidad real existe; de lo contrario declarar limitación |
| Selector IEEE/Scopus/Springer/WoS para proxy | MOVER/CORREGIR | Opción avanzada de perfil; estado separado de la búsqueda |
| Campo URL base de proxy | CONDICIONAR | Solo modo experto autorizado, validación de dominios |
| `Guardar Proxy` | CONDICIONAR | No activo sin URL válida/autorización; error detallado sin secretos |
| `Conectar` / `Reconectar` | AÑADIR SI INTEGRACIÓN REAL | Flujo oficial soportado; no confundir abrir navegador con autenticar backend |
| `Desconectar` | AÑADIR SI INTEGRACIÓN REAL | Revocar/olvidar referencia a secreto con confirmación apropiada |
| `Ver limitaciones` | AÑADIR | Explica API pública, institucional, cuotas y restricciones, sin inventarlas |

### 8.9 Editor de consultas / Calibración

| Control | Decisión | Comportamiento esperado |
|---|---|---|
| `Cargar Ecuación RSL de Perturbación Proactiva (ESM_1.tex)` | MOVER | Menú «Ejemplos de consultas», nombrado como ejemplo específico; no precargar en proyectos ajenos |
| `Traducir y Validar` | MANTENER/CORREGIR | Reemplazar por pipeline AST; mostrar equivalencia/errores y query ejecutable por proveedor |
| Inputs P/I/C/O | MANTENER OPCIONAL | Panel «Construir con PICO» plegable; no exigir a usuarios fuera de RSL |
| Editor ecuación IEEE/Scopus/Springer sobre clones | **CORREGIR** | Mostrar read-only + Copiar o editores persistentes reales; jamás falso editing |
| Advertencia comodines IEEE | CORREGIR | Estado según parser/versión de reglas, no validez declarada por simple conteo |
| `Copiar ecuación` por proveedor | AÑADIR | Copia solo si existe salida; feedback y texto exacto |
| `Usar en búsqueda` por proveedor | AÑADIR | Llena editor de búsqueda, selecciona proveedor/mode y muestra transformación y warnings |
| Indicador de equivalencia | AÑADIR | `EQUIVALENT/APPROXIMATE/UNSUPPORTED` definido por Bloque 3; no icono decorativo |

---

## 9. Comportamiento dinámico: matriz de estados y políticas

### 9.1 Máquina de estados visual

Cada operación asíncrona usa `IDLE`, `VALIDATING`, `SUBMITTING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCEL_REQUESTED`, `CANCELLED` cuando corresponda. No todos los controles necesitan todos los estados; definir máquina específica por acción.

| Contexto | Primaria | Acciones secundarias | Mensaje |
|---|---|---|---|
| Sin proyecto activo | `Crear proyecto` | Explorar conexiones | «Crea o selecciona un proyecto para guardar investigaciones» |
| Proyecto archivado | Desarchivar (si permitido) | Ver biblioteca, exportar | «Proyecto en solo lectura» |
| Backend offline | `Reintentar conexión` | Ver datos caché rotulados, si existen | «No se pudieron confirmar los cambios» |
| Proveedor AUTH_REQUIRED | `Conectar` | Abrir portal | «Se requiere autorización institucional» |
| Proveedor PUBLIC_ACCESS | `Buscar`, si capacidad lo permite | Ver limitaciones | «Acceso público; algunas funciones no disponibles» |
| Consulta inválida | `Corregir ecuación` | Ver errores | «No se ejecutó la consulta» |
| Búsqueda RUNNING | `Cancelar` | Ver progreso | «N registros de M, si M es conocido» |
| Búsqueda PARTIAL | `Reintentar en nueva ejecución` | Abrir resultados guardados | «Resultados parciales por motivo…» |
| Biblioteca vacía | `Nueva búsqueda` | Importar referencias | «Este proyecto aún no tiene publicaciones» |
| Nota sin contenido | Guardar deshabilitado | Salir | «Escribe una nota» |
| Nota con cambios no guardados | `Guardar cambios` | `Descartar` | Dirty indicator visible |
| Exportación lista | `Guardar archivo` | Copiar contenido | «Generado: N registros y formato X» |
| Conflicto de revisión | `Recargar y comparar` | Copiar borrador | «El registro cambió desde otra sesión» |

### 9.2 Estado de búsqueda y selección

Evitar que el usuario seleccione Scopus en Conexiones y modifique sin darse cuenta la búsqueda IEEE en curso. Cada formulario tiene estado propio y scope. Si se cambia de fuente durante la edición de consulta, conservar el texto; reiniciar solo filtros incompatibles, previa notificación.

Si se inicia una búsqueda, capturar snapshot inmutable de `project_id`, `query`, `provider`, filtros y límites. Al completarse, asociar la respuesta al snapshot, no a valores actuales de widgets que podrían haber cambiado.

### 9.3 Feedback

- Success: un toast breve cuando operación simple confirma; para trabajos largos, un estado persistente y enlace a resultados.
- Error: mensaje inline con código/causa legible, botón «Reintentar» cuando proceda, sin exponer tracebacks.
- Warning: color+texto, no solo emoji.
- Disabled: tooltip o ayuda contextual que explique motivo; no bloquear silenciosamente.
- Destructivas: confirmación clara antes de persistir, nunca toast después de una acción irreversible no anunciada.

### 9.4 Atajos básicos

- `Ctrl/Cmd+K`: búsqueda de proyectos/secciones (solo si se implementa realmente).
- `Ctrl/Cmd+F`: foco en filtro del panel activo.
- `Ctrl/Cmd+Enter`: ejecutar búsqueda o guardar formulario según foco y contexto; advertir antes de mutación peligrosa.
- `Escape`: cerrar popup/modal sin borrar silenciosamente un borrador.
- `Tab/Shift+Tab`: navegación completa de controles.

No asignar shortcuts conflictivos sin revisar estándar de Windows/Linux/macOS, ni mostrar tooltips que prometen atajos no implementados.

---

## 10. Cambios de código de interfaz recomendados

### 10.1 Separar dominio, estado, vistas y componentes

```text
desktop_app/src/
  app.rs                      # composición / actualización, mucho más breve
  state.rs                    # active_project_id, navegación, solicitudes
  events.rs                   # eventos tipados y respuestas asíncronas
  theme.rs                    # tokens claro/oscuro + tamaños
  ui/
    mod.rs
    navigation.rs
    workspace_header.rs
    project_overview.rs
    search_workspace.rs
    library_table.rs
    paper_inspector.rs
    annotation_editor.rs
    connection_center.rs
    query_editor.rs
    interchange.rs
    activity.rs
    components/
      buttons.rs
      empty_state.rs
      filters.rs
      status.rs
      modal.rs
      pagination.rs
      toast.rs
```

Nombres propuestos: pueden ajustarse a estructura real, pero se exige separación de responsabilidades. La modularización no autoriza una reescritura total ni el reemplazo de `egui`.

### 10.2 Modelo de controles declarativo

En lugar de llamar `ui.button(...)` sin contexto en todas las vistas, incorporar helpers que reciban:
- estilo/tipo `Primary/Secondary/Tertiary/Destructive`;
- estado y permiso;
- etiqueta y tooltip;
- acción/evento;
- `request_id` y contexto.

Ejemplo conceptual, no API compilable:

```rust
let can_search = project.is_active()
    && provider.capabilities.search
    && query.is_valid()
    && !search_state.is_running();

primary_button(ui, "Buscar publicaciones", can_search, || {
    AppCommand::StartSearch(SearchRequestSnapshot::from_form(&form))
});
```

**Importante:** en egui Immediate Mode, preservar estado en structs estables y pasar comandos al dispatcher; nunca ejecutar operaciones bloqueantes en el closure de render.

### 10.3 Animaciones y rendimiento

Animaciones solo donde comunican progresos reales: spinner, skeleton, resalte de selección, transición de panel. Evitar animaciones continuas si no aportan valor. Reducir clones `papers.clone()` por frame cuando sea razonable. Virtualizar/paginar bibliotecas grandes. Lógica de acceso y llamadas REST fuera de dibujo.

---

## 11. Plan de implementación del rediseño

### Etapa UX-0 — Auditoría reproducible (previa al cambio visual)

1. Abrir la aplicación realmente y capturar las vistas actuales en modo oscuro y claro a 1280×720 y 1440×900.
2. Catalogar controles, handlers, endpoints, estados y bugs con esta matriz.
3. Clasificar: `KEEP`, `MOVE`, `MERGE`, `FIX`, `REMOVE`; anotar controles no integrados o decorativos.
4. Confirmar qué funciones de Bloque 3 técnico ya están implementadas antes de mostrar botones nuevos.
5. Guardar capturas del «antes» y test de regresión de navegación/acciones.

**Entregable:** inventario verificado con capturas y links a líneas actuales.

### Etapa UX-1 — Jerarquía, tema y componentes

1. Crear tokens y componentes globales, incluir estados de foco/hover/disabled.
2. Rehacer sidebar/header, mejorar escala, contraste y responsividad.
3. Reducir emojis decorativos y títulos repetidos.
4. Consolidar toasts/estado y empty/error states.
5. Mantener navegación funcional hacia todas las capacidades existentes.

**Entregable:** shell de diseño consistente con luz/oscuro, sin cambios de negocio.

### Etapa UX-2 — Flujo principal de investigación

1. Rediseñar búsqueda con editor visible, filtros plegables y CTA primario único.
2. Integrar `AcquisitionService` real y mostrar runs/estado del proyecto.
3. Rediseñar biblioteca como lista + inspector; reubicar notas/estados/citas.
4. Incorporar paginación, selección y detalle bibliográfico.
5. Tratar las fuentes verdaderas (Springer/Crossref) según Bloque 3 técnico.

**Entregable:** buscar -> visualizar -> guardar/organizar -> anotar sin confusión.

### Etapa UX-3 — Herramientas secundarias

1. Centro de conexiones sin Burp/cookies.
2. Editor booleano/AST con PICO opcional y «Usar en búsqueda».
3. Importar/exportar con historial integrado y selector de archivo real cuando se implemente.
4. Timeline de actividad consolidado.
5. Corregir rutas y estados de formularios existentes.

**Entregable:** cada sección tiene propósito y controles reales.

### Etapa UX-4 — Calidad visual y pruebas

1. Pruebas de layout, interacciones y accesibilidad en Windows/Linux/macOS soportados.
2. Pruebas de fallos del backend, sesiones expiradas y corpus grande.
3. Capturas «después» comparadas con criterios, sin suponer que el código compila porque se editó.
4. Ajustar espaciado, contraste, truncado y tooltips.
5. Actualizar documentación y registrar limitaciones no resueltas.

**Entregable:** evidencia visual y funcional, sin degradar A01–A20 ni B3-01–B3-36.

### Dependencias con Bloque 3

- UX-1 puede empezar antes de completar integraciones.
- UX-2 depende de 3.2/3.3 para AST y adquisiciones verdaderas.
- UX-3 Conexiones depende de 3.1; Importar/Exportar depende de los contratos existentes.
- UX-4 se realiza después de la corrección de 3.4 y debe coincidir con la validación 3.5.

**No bifurcar lógica entre «interfaz bonita» y «interfaz funcional»; mantener un solo proyecto/sistema de datos.**

---

## 12. Pruebas de aceptación UX/UI

| ID | Verificación verificable |
|---|---|
| UX-01 | Todas las secciones y acciones útiles son accesibles sin Burp; no aparece un chat ni modo web genérico |
| UX-02 | Las capturas reales claro/oscuro muestran contraste adecuado; ningún texto blanco ilegible en fondo claro |
| UX-03 | Navegación no desborda en 1280×720; sidebar/header/inspector son utilizables |
| UX-04 | Cambiar de proyecto mantiene scope correcto y no muestra datos viejos como si fueran del nuevo |
| UX-05 | Borrador de proyecto/nota/consulta advierte antes de descartarse accidentalmente |
| UX-06 | Formularios de crear/guardar tienen validación inline, loading, error y confirmación persistente |
| UX-07 | Archivar solo está disponible en proyecto editable y explica efecto antes de confirmar |
| UX-08 | `Leído` persiste exactamente `READ`; una respuesta HTTP fallida no se trata como éxito |
| UX-09 | `research_type` se conserva tras guardar y reiniciar |
| UX-10 | Buscar es una acción primaria única; no convive con segunda ingesta ambigua |
| UX-11 | No se crea run sin proyecto activo ni se escribe silenciosamente en `default_slr` |
| UX-12 | Fuentes y filtros muestran capacidades reales, no opciones no soportadas como activas |
| UX-13 | El parser informa errores/equivalencia y el resultado mostrado coincide con consulta realmente enviada |
| UX-14 | Resultados muestran proveedor real, fecha, conteos correctos y estado parcial si aplica |
| UX-15 | La biblioteca admite >100 registros, búsqueda/paginación y selección sin congelar UI |
| UX-16 | Estados de lectura se modifican con un control compacto, no con tres botones repetidos |
| UX-17 | Notas se crean desde el paper seleccionado, con scope, procedencia y pregunta opcional correctos |
| UX-18 | Una cita desde ABSTRACT se etiqueta como basada en resumen; FULLTEXT exige locator |
| UX-19 | Importación preview/commit muestra errores por registro; no se promete DnD no implementado |
| UX-20 | Exportar permite formatos correctos, copiar y guardar a archivo si esa acción aparece |
| UX-21 | «Abrir carpeta» usa ruta real y funciona en SO declarado o muestra error honesto |
| UX-22 | Actividad presenta búsquedas/cambios/agentes sin pantallas duplicadas ni función inaccesible |
| UX-23 | Conexiones prueban capacidad real y nunca muestran cookies ni tokens |
| UX-24 | Cambiar proveedor en Conexiones no modifica el proveedor elegido en Búsqueda |
| UX-25 | Editor de ecuaciones es read-only real o editable persistente; nunca modifica clones descartados |
| UX-26 | No hay botones decorativos, sin handler, «simulados», o con acciones distintas a la etiqueta |
| UX-27 | Controles async no bloquean render y permiten feedback/reintento |
| UX-28 | Navegación por teclado y tooltips de iconos funcionan en flujos esenciales |
| UX-29 | Capturas antes/después en claro/oscuro y varios tamaños están en informe de la entrega |
| UX-30 | `cargo check`, `cargo test`, suite Python y A01–A20/B3 relevantes no muestran regresión |
| UX-31 | Ninguna acción de UI viola permisos de proyecto archivado ni cambia datos durante error/offline |
| UX-32 | Controles de lectura, exportación y guardado muestran causa si están deshabilitados |

**Todos los UX-xx deben tener PASS/FAIL/BLOCKED con evidencia real**. Un botón visualmente nuevo no equivale a UX aprobada.

---

## 13. Prioridades y decisiones recomendadas

**P0 / antes de una demo confiable:**
- Corregir «Leído»/`READ`, research_type, scope de proyecto, acciones que aparentan éxito, duplicación de ingesta.
- Retirar Burp/Firefox del flujo productivo y corregir claims falsos de fuente.
- Corregir editor de ecuaciones aparentemente editable.
- No bloquear render durante llamadas REST; no perder borradores.

**P1 / rediseño de alto impacto:**
- Nueva jerarquía sidebar + cabecera.
- Búsqueda con CTA único y filtros secundarios.
- Biblioteca compacta e inspector de publicación.
- Notas integradas en contexto.
- Exportaciones e historial consolidados.
- Centro de conexiones y estados claros.
- Tema oscuro/claro realmente coherente.

**P2 / pulido:**
- Atajos, búsqueda de proyectos, animaciones mínimas, paneles redimensionables, tooltips avanzados, refinamiento de tablas y comandos de contexto.

### Decisiones estéticas concretas

1. **Un color de acción primario, no muchos**. Colores rojo/verde/amarillo reservados a estados, no a decorar cada botón.
2. **Un solo CTA principal por pantalla/paso**, resto de baja prioridad.
3. **No repetir título/encabezado de pantalla dentro de tres `ui.group` distintos**.
4. **No usar 9 pantallas cuando 6–8 secciones coherentes pueden cubrir el flujo**.
5. **No presentar ID/UUID/JSON técnico como información principal**: disponibles en detalles/copia.
6. **No dispersar un paper entre Biblioteca, Notas y Exportaciones**: su inspector reúne sus acciones.
7. **No usar «SLR/PICO» como requisito general**: PICO es una ayuda opcional.
8. **No usar los nombres de herramientas técnicas como acciones del investigador**: «Ingestar Streaming» se reemplaza por «Buscar»/«Guardar resultados» si corresponde.
9. **No prometer alcance institucional** mediante una etiqueta verde sin prueba funcional.
10. **No hacer «rediseño» cambiando solo CSS/colores**: egui requiere rehacer estructura, distribución, estados y operaciones.

---

## 14. Instrucciones para Antigravity o Codex

> Implementar esta especificación como **anexo UX/UI de Bloque 3**, no como un proyecto paralelo. Leer primero `docs/block2/README.md`, `docs/block3/README.md` y este documento. Comprobar el código actual antes de aplicar cada cambio porque el Bloque 3 técnico puede haber modificado handlers y pantallas.
>
> Crear inventario real de botones con `control_id`, etiqueta, handler, contexto, permisos, API, loading y resultado. Corregir problemas funcionales antes de mover controles. No usar mocks en producción ni prometer acciones no conectadas. No eliminar funciones útiles al fusionar secciones. No alterar datos persistidos ni esquema sin seguir migraciones del Bloque 3. Mantener egui/eframe.
>
> Trabajar por etapas UX-0 a UX-4. Después de cada una, entregar: archivos y commits, capturas reales claro/oscuro, resultado de tests/compilación, matriz UX-xx actualizada y fallos remanentes. Si no puede ejecutar escritorio o tomar capturas, marcar visual `BLOCKED`, nunca afirmar que se probó el diseño.
>
> Priorizar primero el flujo: **proyecto -> búsqueda -> resultado -> biblioteca -> publicación -> nota/cita -> exportación**. Todo elemento de UI debe soportar ese flujo o corresponder a una herramienta secundaria claramente separada.

**Definition of Done:** diseño visual más limpio y consistente **más** comportamiento correcto de controles en ejecución real, sin pérdida de funcionalidad, sin rutas personales fijas, sin resultados académicos mal atribuidos y sin operaciones engañosas.

---

## 15. Referencias de implementación

- [`desktop_app/src/app.rs`](../../desktop_app/src/app.rs)
- [`desktop_app/src/research_client.rs`](../../desktop_app/src/research_client.rs)
- [`desktop_app/src/main.rs`](../../desktop_app/src/main.rs)
- [`desktop_app/src/burp_launcher.rs`](../../desktop_app/src/burp_launcher.rs)
- [`desktop_app/src/firefox_extractor.rs`](../../desktop_app/src/firefox_extractor.rs)
- [`docs/block3/README.md`](README.md)
- [`docs/block2/README.md`](../block2/README.md)

**Nota de mantenimiento:** los rangos de líneas corresponden a la versión auditada en la elaboración de esta propuesta. Después de refactorizar, actualizar el inventario por `control_id` y vínculo al handler, sin depender de números de línea fijos.
