# MCPCONECCT — Bloque 2

Especificación de implementación v0.1, para revisión. Este documento define comportamiento futuro; no afirma que esté implementado. Destino sugerido en el repositorio: `docs/block2/README.md`. No sustituye el README público del producto.

## 1. Decisión de producto

MCPCONECCT es un espacio local de investigación bibliográfica. El usuario crea proyectos, busca o importa publicaciones, organiza referencias, escribe notas y registra evidencia. Una revisión sistemática es un uso especializado, no una condición para usar el producto.

El Bloque 1 aporta conectores, ingesta, enriquecimiento y exportadores. El Bloque 2 reutiliza esos servicios y corrige los contratos de persistencia que impidan aislar proyectos o preservar trabajo humano.

DEBE significa requisito de aceptación. NO DEBE significa comportamiento prohibido. Las decisiones técnicas de este documento son propuestas concretas para cerrar la ambigüedad del diseño anterior.

## 2. Alcance cerrado de esta entrega

Incluido: proyectos; preguntas y objetivos; biblioteca; colecciones; etiquetas; estado de lectura; notas; evidencia textual; historial de búsquedas; importación BibTeX/RIS/CSV; exportación bibliográfica; exportación y restauración JSON; acceso equivalente por REST, MCP y escritorio Rust.

Fuera de esta entrega: motor PICO nuevo, AST nuevo, Golden Dataset, cribado IC/EC, Cohen's kappa, PRISMA, sincronización con Parsifal, colaboración multiusuario, carga y extracción de PDF, embeddings, búsqueda semántica, redacción automática y análisis estadístico. Las herramientas existentes de traducción siguen disponibles; cualquier corrección debe conservar sus contratos públicos.

Los módulos metodológicos se especificarán en una entrega posterior. No crear botones vacíos, estados PRISMA nuevos ni tablas metodológicas ficticias para anticiparlos.

## 3. Glosario e identidad

- Publicación: una referencia bibliográfica. No equivale necesariamente a un estudio.
- Referencia del proyecto: pertenencia de una publicación a un proyecto, con estado de lectura propio.
- Observación: registro tal como llegó desde una búsqueda o importación.
- Nota: comentario libre vinculado a una referencia del proyecto.
- Evidencia: cita textual o paráfrasis vinculada a una referencia del proyecto, con procedencia declarada.
- Colección: agrupación manual dentro de un proyecto; sin jerarquía.
- Etiqueta: clasificación manual dentro de un proyecto.

Usar UUID v4 para nuevas identidades. El DOI normalizado y el hash bibliográfico son claves de comparación, nunca la clave primaria nueva. Añadir un DOI no cambia el `publication_id`.

## 4. Modelo persistente obligatorio

SQLite sigue siendo el almacén. Activar claves foráneas en cada conexión y conservar WAL y busy_timeout. Todas las fechas nuevas: ISO 8601 UTC con sufijo Z. Todas las entidades editables tienen `revision INTEGER NOT NULL DEFAULT 1`.

| Tabla nueva | Campos de negocio y restricciones |
|---|---|
| research_projects | project_id PK, name obligatorio 1–120 caracteres, description hasta 10000, research_type etiqueta libre hasta 80, archived boolean, created_at, updated_at, revision |
| research_questions | question_id PK, project_id FK, text obligatorio hasta 5000, position entero >=0, revision |
| research_objectives | objective_id PK, project_id FK, text obligatorio hasta 5000, position entero >=0, revision |
| publications | publication_id PK; metadatos bibliográficos del contrato CanonicalPaper; doi nullable UNIQUE; created_at, updated_at, revision |
| project_publications | project_id FK, publication_id FK, reading_status, added_at, revision; PK(project_id, publication_id) |
| collections | collection_id PK, project_id FK, name, name_key, revision; UNIQUE(project_id,name_key) |
| collection_members | collection_id FK, project_id, publication_id; PK(collection_id,publication_id); FK compuesta a project_publications |
| tags | tag_id PK, project_id FK, name, name_key, revision; UNIQUE(project_id,name_key) |
| publication_tags | tag_id FK, project_id, publication_id; PK(tag_id,publication_id); FK compuesta a project_publications |
| annotations | annotation_id PK, project_id, publication_id, kind, body, source_kind, source_url nullable, locator nullable, question_id nullable, actor_type, actor_label, created_at, updated_at, revision |
| acquisition_runs | run_id PK, project_id FK, kind SEARCH o IMPORT, status, request_json, started_at, finished_at nullable, reported_total nullable, observed_count, unique_count, stop_reason nullable |
| source_observations | observation_id PK, run_id FK, publication_id FK, source_record_key, raw_json, received_at; UNIQUE(run_id,source_record_key) |
| research_events | event_id PK, project_id FK, entity_type, entity_id, action, actor_type, actor_label, before_json, after_json, created_at |
| mutation_receipts | project_scope, operation, idempotency_key, request_hash, response_json; PK(project_scope,operation,idempotency_key) |
| publication_aliases | old_id PK, publication_id FK, alias_type LEGACY o MERGED |

`name_key` = Unicode NFKC + trim + casefold. Nombres de etiquetas/colecciones: 1–80 caracteres después de trim. No normalizar el texto visible a minúsculas.

Validar que colección, etiqueta, pregunta y referencia pertenecen al mismo proyecto antes de escribir. Un fallo cancela toda la transacción. Mantener estas validaciones en servicios compartidos, además de las restricciones SQL posibles.

## 5. Reglas de publicaciones y duplicados

1. Mismo DOI normalizado: reutilizar publication_id. Si el título contradice el existente, conservar metadatos existentes y registrar conflicto en el informe; no sobrescribir silenciosamente.
2. DOI diferente y no vacío en ambos registros: no fusionar automáticamente.
3. Sin DOI: reutilizar automáticamente solo si coinciden título normalizado, año conocido y lista de autores normalizada no vacía. Comparar autores con NFKC, casefold y espacios normalizados, conservando orden.
4. Cualquier otra similitud: mantener referencias separadas y permitir fusión manual; no aplicar el umbral difuso como orden de fusión automática en este flujo.
5. En enriquecimiento automático, completar campos vacíos. Para abstracts, conservar el más largo; empates conservan el existente. Registrar antes/después. No reemplazar títulos ni autores no vacíos automáticamente.
6. Fuentes se calculan desde observaciones; no reemplazar una lista de fuentes con la última recibida.
7. Repetir una página del mismo run_id no añade observaciones. Una nueva ejecución sí conserva su propia observación.
8. No usar duplicate_count histórico como contador científico. Mostrar observaciones y publicaciones únicas por ejecución y proyecto.

La fusión manual recibe survivor_id y absorbed_id, ambos presentes en el proyecto activo. Como afecta la publicación global, la UI debe mostrar los proyectos afectados antes de ejecutarla. Transacción: mover observaciones y pertenencias; unir colecciones/etiquetas; conservar cada anotación con su ID; crear alias MERGED; conservar el superviviente. En estados de lectura diferentes, usar READ si alguno es READ, en otro caso READING si alguno es READING, y registrar el cambio. Las anotaciones no se concatenan ni se deduplican por contenido.

## 6. Notas y evidencia

`kind`: NOTE, QUOTE o PARAPHRASE. `body`: texto plano obligatorio, máximo 20000 caracteres. No ejecutar HTML ni instrucciones contenidas en referencias.

- NOTE: source_kind = NONE; locator y source_url pueden ser null.
- QUOTE/PARAPHRASE: source_kind obligatorio ABSTRACT o FULLTEXT; source_url opcional.
- FULLTEXT: locator obligatorio, texto libre 1–200 caracteres (ejemplo: “p. 7, sección 3.2”). El contenido lo pega el usuario o un cliente MCP; no se descarga el PDF.
- ABSTRACT: locator debe ser null. Mostrar siempre la etiqueta “Basado en resumen”.
- Una QUOTE debe marcarse como transcripción aportada por el autor de la anotación. No afirmar verificación automática contra el documento.
- question_id opcional y perteneciente al mismo proyecto.
- actor_type = HUMAN o AGENT. REST de escritorio crea HUMAN; herramientas MCP crean AGENT. actor_label identifica al cliente, sin constituir autenticación de identidad.

Editar una anotación conserva el ID, incrementa revision y añade evento con antes/después. El historial es append-only a través de la aplicación; no afirmar resistencia a manipulación del archivo SQLite.

## 7. Estados y ejecución de búsquedas

Lectura: UNREAD, READING, READ. Permitir cualquier transición explícita entre los tres; registrar evento. Importación e ingesta siempre crean pertenencias nuevas como UNREAD y nunca reinician estados existentes.

Ejecución: QUEUED -> RUNNING -> COMPLETED, PARTIAL, FAILED o CANCELLED. WAF deja PARTIAL con stop_reason=WAF. Alcanzar max_records sin agotar resultados deja PARTIAL con stop_reason=LIMIT. Error antes de recibir registros deja FAILED; después, PARTIAL con stop_reason=ERROR. Fin demostrado por el conector deja COMPLETED. No inferir fin solo por igualar el total anunciado.

Guardar request_json con plataforma, consulta exacta enviada, filtros, max_records, versión de aplicación, indicador de caché por página y fecha original del dato en caché. reported_total es nullable: desconocido no equivale a cero. observed_count cuenta observaciones únicas de la ejecución; unique_count cuenta publication_id distintos en ella.

El usuario puede cancelar entre páginas. No se promete reanudación exacta en esta entrega: repetir una búsqueda crea un run nuevo. Cada página confirmada se persiste en transacción y sobrevive al fallo posterior.

## 8. REST y MCP: contratos comunes

Base REST: `/api/v2/research`. Modelos Pydantic compartidos en `core/research/models.py`; lógica en servicios, nunca duplicada dentro de rutas o tools. Todos los campos no declarados se rechazan.

| Operación | REST | MCP |
|---|---|---|
| Crear/listar proyecto | POST/GET /projects | research_create_project / research_list_projects |
| Leer/editar proyecto | GET/PATCH /projects/{project_id} | research_get_project / research_update_project |
| Preguntas y objetivos | PUT /projects/{project_id}/outline | research_set_outline |
| Biblioteca | GET /projects/{project_id}/publications | research_list_publications |
| Cambiar lectura | PATCH /projects/{project_id}/publications/{publication_id} | research_update_reading_status |
| Colecciones y etiquetas | PUT /projects/{project_id}/organization | research_set_organization |
| Crear/listar anotaciones | POST/GET /projects/{project_id}/annotations | research_create_annotation / research_list_annotations |
| Editar anotación | PATCH /projects/{project_id}/annotations/{annotation_id} | research_update_annotation |
| Iniciar búsqueda | POST /projects/{project_id}/searches | research_start_search |
| Consultar/cancelar ejecución | GET /projects/{project_id}/runs/{run_id}; POST .../cancel | research_get_run / research_cancel_run |
| Historial | GET /projects/{project_id}/events | research_list_events |
| Previsualizar/confirmar importación | POST /projects/{project_id}/imports/preview; POST .../commit | research_preview_import / research_commit_import |
| Exportar | POST /projects/{project_id}/exports | research_export_project |
| Restaurar JSON | POST /restores/preview; POST /restores/commit | research_preview_restore / research_commit_restore |
| Fusionar publicaciones | POST /projects/{project_id}/merges | research_merge_publications |

Todas las listas: limit 1–100 (25 por defecto), offset >=0, orden created_at ascendente e ID como desempate; entidades sin created_at usan ID. Respuesta: `{items,total,limit,offset}`. Biblioteca admite q (substring casefold de título), reading_status, collection_id, tag_id; filtros combinados con AND.

Todas las mutaciones reciben `idempotency_key` UUID. Repetición de misma clave y cuerpo devuelve respuesta guardada; cuerpo diferente devuelve 409 IDEMPOTENCY_CONFLICT. Scope de creación/restauración = GLOBAL; resto project_id. Mutaciones de entidades existentes reciben expected_revision; conflicto devuelve 409 REVISION_CONFLICT sin cambios.

`set_outline` reemplaza preguntas/objetivos en una transacción usando expected_revision del proyecto. Elementos existentes conservan ID; nuevos reciben UUID. No eliminar preguntas con evidencia enlazada: 409 QUESTION_IN_USE.

`set_organization` recibe colecciones, etiquetas y asignaciones completas con IDs existentes o IDs nuevos UUID; usa expected_revision del proyecto. Eliminar una colección/etiqueta elimina solo sus asignaciones. No elimina publicaciones. Devuelve el nuevo revision del proyecto.

Errores uniformes: `{error:{code,message,details}}`. 404 NOT_FOUND para proyecto o entidad fuera de su ámbito; 422 VALIDATION_ERROR para datos inválidos; 409 para conflicto. MCP devuelve el mismo objeto y señal de error del protocolo. Trabajo largo responde con run_id, estado y status_url; nunca bloquear una llamada hasta descargar todo el corpus.

No incluir eliminación permanente de proyectos/publicaciones en esta entrega. Archivar proyectos mediante PATCH; proyectos archivados son de solo lectura salvo desarchivar. Exportar sigue permitido.

## 9. Importación y exportación

Archivos UTF-8, máximo 20 MiB y 10000 registros por importación; rechazar excedentes antes del commit. BibTeX y RIS se leen con parser, no regex aisladas. CSV RFC4180 con encabezados y delimitador coma; aceptar BOM UTF-8. CSV recibe mapping explícito de columnas a campos canónicos; title obligatorio. Autores y keywords en CSV se representan como arrays JSON dentro de la celda.

Preview no modifica el corpus: devuelve preview_id, hash del archivo, conteos y errores por número de registro. Commit recibe preview_id, hash e idempotency_key. Preview caduca a los 30 minutos; cambiado/caducado devuelve 409 PREVIEW_EXPIRED_OR_CHANGED. Commit incorpora solo registros válidos, conserva los rechazados en informe y usa las reglas de identidad del apartado 5. Ninguna fila inválida se descarta sin aparecer en el informe.

Exportación selecciona scope ALL o COLLECTION (collection_id obligatorio), format BIB, RIS, CSV o PROJECT_JSON. BIB/RIS/CSV exportan bibliografía y un informe de campos no representados; notas y evidencia no se prometen transferibles a gestores externos. PROJECT_JSON exige scope ALL.

PROJECT_JSON: schema_version=1, project, questions, objectives, publications, memberships, collections, tags, assignments, annotations, runs, observations, events. Mantener IDs originales en el archivo. Excluir cookies, tokens, headers de autorización, rutas locales privadas y cuerpos de petición que contengan credenciales. Los raw_json se reducen a metadatos bibliográficos permitidos; no exportar respuestas HTTP completas.

Restaurar siempre crea un proyecto nuevo y devuelve mapa de IDs; no reemplaza un proyecto existente. Reutilizar publicaciones por DOI compatible y remapear relaciones. Preservar fechas/autoría de anotaciones; añadir evento RESTORED. Validar schema_version y todas las referencias antes del commit; cualquier referencia rota cancela la restauración completa.

Parsifal es una referencia de producto, no una integración implementada. No usar “sincronizado”, logos de compatibilidad ni claims de soporte sin una prueba documentada con la herramienta destino.

## 10. Escritorio Rust

Implementar sobre la aplicación actual; no cambiar de framework. Selector de proyecto persistente; al iniciar, reabrir el último proyecto existente, o mostrar lista vacía con “Crear proyecto”.

Vistas: Proyecto (nombre, preguntas, objetivos); Búsqueda (servicios existentes + destino visible); Biblioteca (tabla, filtros, colecciones, etiquetas, estado); Notas y evidencia (detalle de referencia); Historial (runs y eventos); Intercambio (preview, commit, descarga).

Estados obligatorios en cada vista: vacío, cargando, error con reintento, datos disponibles. Ninguna escritura optimista se considera confirmada antes de respuesta exitosa. En conflicto de revisión, conservar borrador local y ofrecer recargar; no sobrescribir automáticamente.

Rust no escribe las tablas nuevas directamente. Lecturas nuevas y escrituras pasan por FastAPI. Si el backend no está disponible, mostrar “Servicio local no disponible” con reintento; no simular guardado. Mantener las pestañas existentes de conexión y exportación funcionales.

## 11. Migración desde Bloque 1

Crear `schema_migrations(version PRIMARY KEY, applied_at)`. Migración transaccional y repetible; backup SQLite consistente mediante API backup, no copia aislada del archivo WAL.

Crear un proyecto por cada project_id legado distinto. Conservar IDs de proyecto legado, incluido default_slr. Crear UUID de publicación y alias LEGACY para cada record_id; construir pertenencias. Si datos históricos ya fueron sobrescritos entre proyectos, registrar limitación: no reconstruir pertenencias inexistentes.

No inventar source_observations para representar búsquedas que no se conservaron. Registrar importación LEGACY en el historial con procedencia desconocida cuando corresponda. Conservar las tablas antiguas hasta completar validación; adaptar las funciones públicas de core/db.py a los servicios nuevos. Los endpoints MCP/REST del Bloque 1 mantienen sus nombres y formas de respuesta; agregar pruebas de compatibilidad.

## 12. Archivos y orden de trabajo

Crear: core/research/models.py, repository.py, projects.py, library.py, annotations.py, acquisitions.py, interchange.py; core/migrations/; dashboard/routes/research_api.py; mcp_server/tools/research_tools.py; tests/test_research_*.py.

Modificar: core/db.py, core/stream_fetcher.py, core/deduplicator.py, registro de rutas y herramientas, desktop_app/src/app.rs y cliente HTTP de Rust. Reutilizar exportadores existentes mediante adaptadores. No añadir archivos vacíos como supuesto trabajo completado.

Orden: migración e identidad -> proyectos/biblioteca -> notas/organización -> adquisición/trazabilidad -> intercambio/restauración -> UI/MCP. Cada etapa termina con sus pruebas antes de iniciar la siguiente.

## 13. Pruebas de aceptación obligatorias

| ID | Escenario y resultado verificable |
|---|---|
| A01 | Crear proyecto solo con nombre: funciona sin PICO, criterios o PRISMA. |
| A02 | Mismo DOI en proyectos A/B: una publicación, dos pertenencias; cambiar lectura/nota en A no cambia B. |
| A03 | Repetir una página con mismo run: conteos y anotaciones permanecen iguales. |
| A04 | Nueva búsqueda del mismo DOI: nueva observación, ninguna publicación duplicada. |
| A05 | Títulos similares y DOI distintos: permanecen separados. |
| A06 | Añadir DOI a referencia: conserva publication_id y anotaciones. |
| A07 | Fusión manual con notas/colecciones en ambos lados: todas las relaciones sobreviven y alias resuelve al superviviente. |
| A08 | Abstact usado como evidencia: etiqueta ABSTRACT en UI y exportación; no FULLTEXT. |
| A09 | Asignar etiqueta/pregunta de otro proyecto: error, cero escrituras parciales. |
| A10 | Misma mutación/clave dos veces: un evento y respuesta idéntica; distinto cuerpo: 409. |
| A11 | Dos ediciones con misma revisión inicial: primera funciona, segunda devuelve conflicto. |
| A12 | Conector anuncia 1000 y límite descarga 100: reported_total=1000, observed_count=100, status=PARTIAL. |
| A13 | WAF después de una página: página conservada y run PARTIAL/WAF. |
| A14 | CSV con coma, comillas, tildes y autores múltiples: ida/vuelta conserva los campos soportados. |
| A15 | Importación con registros inválidos: preview e informe identifican cada rechazo; commit conserva válidos. |
| A16 | JSON exportado/restaurado: preguntas, notas, evidencia y relaciones equivalentes tras remapear IDs; sin credenciales. |
| A17 | Restauración con referencia rota: no crea proyecto ni filas parciales. |
| A18 | Migración ejecutada dos veces: no duplica proyectos/publicaciones; backup restaurable. |
| A19 | REST y MCP para la misma operación producen el mismo estado persistente. |
| A20 | Rust muestra vacío/cargando/error; caída del backend no muestra un falso guardado. |

Ejecutar suite Python completa y cargo check/cargo test. Probar adquisición con fixtures deterministas; pruebas en vivo separadas y optativas por requerir credenciales. Verificar visualmente el flujo crear proyecto -> importar -> organizar -> anotar -> exportar. Registrar comandos, resultados y limitaciones reales; no declarar éxito por cantidad de archivos creados.

## 14. Criterio de terminado

Esta entrega está terminada solo si A01–A20 pasan, el Bloque 1 conserva compatibilidad y el flujo completo funciona desde Rust y MCP. No declarar implementados los módulos metodológicos fuera de alcance. Si el código real impide cumplir un contrato, documentar la discrepancia y proponer un cambio explícito a esta especificación; no sustituirlo silenciosamente.
