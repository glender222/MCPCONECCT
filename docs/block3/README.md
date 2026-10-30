# MCPCONECCT — Bloque 3: Consolidación, seguridad, fidelidad científica y preparación para distribución

> **Especificación técnica de implementación v0.1 — propuesta para ejecución y revisión.**
>
> **Fecha de referencia:** 29 de octubre de 2026. **Repositorio:** [glender222/MCPCONECCT](https://github.com/glender222/MCPCONECCT). **Línea base auditada:** `98e51ce7681fc3db048ebfb532a0b21356834822` (rama `main`).
>
> Este README describe requisitos **por implementar, corregir y verificar**. La presencia de una sección aquí **no afirma** que ya se haya realizado. Se apoya en la auditoría estática del Bloque 1 y Bloque 2; los tests, la compilación, las pruebas visuales y la conectividad real aún deben ejecutarse y documentarse durante el Bloque 3.
>
> **Ubicación:** `docs/block3/README.md`. Complementa `docs/block2/README.md` y no reemplaza el README público.
>
> **Lenguaje normativo:** **DEBE** = obligatorio para considerar terminada esta entrega; **NO DEBE** = prohibición; **DEBERÍA** = recomendación que requiere justificar cualquier excepción; **PUEDE** = opcional. **P0** = seguridad/integridad, **P1** = confiabilidad/funcionalidad, **P2** = mantenimiento/distribución.

---

## 1. Decisión de producto y objetivo

MCPCONECCT debe ser un **espacio local de investigación bibliográfica orientado a proyectos**, interoperable con clientes MCP (Codex, Claude Code, Antigravity y otros clientes compatibles) y accesible desde la aplicación nativa Rust. La experiencia principal es **buscar, recopilar, verificar metadatos, organizar, anotar y exportar fuentes académicas**. No es un chat y no debe restaurarse un «modo web» de búsqueda genérica.

El **Bloque 1** entregó conectores académicos, traducción de ecuaciones, ingesta, deduplicación, exportadores y auditoría básica. El **Bloque 2** agregó proyectos, biblioteca, anotaciones, identificadores persistentes, migraciones, importación/restauración y contratos REST/MCP. El **Bloque 3** debe **unificar estos caminos**, corregir los problemas detectados, asegurar los datos y hacer que el comportamiento de la aplicación sea científicamente reproducible.

**Principio rector:** un artículo recuperado, un total presentado o una ecuación traducida jamás deben atribuirse a una base distinta de la consultada ni considerarse verificados cuando no lo están. Un error explícito es preferible a un resultado aparentemente válido pero incorrecto.

### 1.1 Resultados obligatorios

1. El escritorio, REST y MCP inician búsquedas del **proyecto realmente seleccionado**, usando un servicio único de adquisición y persistencia.
2. Los secretos de autenticación no son expuestos por REST, MCP, logs, exports ni UI; el acceso de usuario al portal se realiza por flujos autorizados y sin Burp Suite como requisito.
3. Las fuentes y los conteos se identifican por su **proveedor real**, con información completa para reproducir cada consulta.
4. El motor booleano preserva semántica mediante análisis estructurado; cuando no puede traducir de forma exacta, advierte o rechaza en lugar de inventar equivalencias.
5. Los trabajos limitan estrictamente los registros solicitados, permiten cancelación confiable y registran estados comprobables.
6. La aplicación Rust tiene operaciones asíncronas donde corresponda, errores visibles, estados de lectura correctos y ninguna promesa falsa de guardado.
7. Instalación, pruebas, versiones y documentación son verificables mediante integración continua.

### 1.2 Fuera del alcance deliberadamente

NO implementar en esta entrega: descarga o extracción masiva de PDF/full text; scraping de contenido protegido sin autorización; automatización del login institucional mediante capturas ocultas; evasión de CAPTCHAs/WAF; módulos de cribado IC/EC y Cohen's kappa; diagrama PRISMA automático; recomendaciones con IA, embeddings o RAG; editor de artículos; colaboración multiusuario; sincronización declarada con Parsifal/Zotero/Mendeley sin pruebas de integración; ni interfaces vacías de próximas fases.

El AST y el conjunto de pruebas de consultas sí entran ahora al Bloque 3 porque se requieren para corregir problemas reales de exactitud, aunque estuvieran fuera del alcance original del Bloque 2.

---

## 2. Evidencia de la auditoría y lista de deuda técnica

Estos hallazgos provienen de una revisión del código, no de una ejecución. Antes de modificar, confirmar que siguen presentes en el commit de trabajo y registrar cualquier desviación.

| ID | Severidad | Hallazgo observado | Fuente actual | Corrección exigida |
|---|---|---|---|---|
| H01 | **P0** | `GET /api/connections` devuelve el almacén de sesiones completo, potencialmente con cookies, headers y API keys | `dashboard/routes/api.py` | Respuesta pública solo con estado saneado y control de acceso |
| H02 | **P0** | `POST /api/connections/update` devuelve la sesión actualizada, incluidos secretos | `dashboard/routes/api.py` | Respuesta sin valores sensibles |
| H03 | **P0** | Sesiones persistidas como JSON sin cifrado ni permisos estrictos garantizados | `core/http_client.py` | Secret store del SO o almacenamiento protegido, permisos y migración segura |
| H04 | **P0** | Firefox: ruta absoluta de un desarrollador y archivos de cookies copiados a `/tmp` | `desktop_app/src/firefox_extractor.rs` | Retirar la extracción general predeterminada; conexión explícita/segura y rutas portables |
| H05 | **P0** | Burp y navegador con opciones para ignorar certificados | `desktop_app/src/burp_launcher.rs`, `core/http_client.py`, `.env.example` | TLS verificado por defecto; depuración aislada y opt-in |
| H06 | **P0** | «SpringerLink público» busca realmente en Crossref con `prefix:10.1007` | `platforms/springer.py` | Identificar fuente real o usar conector verificado de Springer |
| H07 | **P0** | El año desconocido puede transformarse en un año supuesto durante la conversión Crossref | `platforms/springer.py` | Fecha desconocida = `null`; nunca completar con año ficticio |
| H08 | **P1** | Algunas comprobaciones de conexión pueden declarar éxito sin verificar búsqueda/autorización | `platforms/springer.py`, `platforms/scopus.py`, `platforms/wos.py` | Health check por capacidades, sin falsos positivos |
| H09 | **P0** | La ingesta del escritorio apunta a `default_slr` y endpoint del Bloque 1 aunque otro proyecto esté activo | `desktop_app/src/app.rs` | Toda ingesta nueva dirigida al proyecto seleccionado |
| H10 | **P0** | Conviven corpus legado y biblioteca del Bloque 2 con rutas y semánticas distintas | `core/db.py`, `core/stream_fetcher.py`, `core/research/*` | Servicio único de adquisición; ruta antigua como adaptador seguro |
| H11 | **P0** | `to_scopus` puede convertir `AND NOT` en `AND AND NOT` | `core/query_translator.py` | AST, serialización y tests de equivalencia |
| H12 | **P0** | Traductor IEEE puede perder negación/anidamiento y cambiar comodines silenciosamente | `core/query_translator.py`, `core/query_parser.py` | Rechazo explícito ante traducción no equivalente |
| H13 | **P1** | `max_records` puede superarse porque las páginas son de 25 y se ingieren completas | `core/research/acquisitions.py` | Límite estricto, incluso en última página |
| H14 | **P1** | Riesgo de ausencia de progreso en paginación repetida y estados ambiguos | `core/research/acquisitions.py` | Detectar repetición, total y agotamiento reales |
| H15 | **P1** | Cancelación en memoria/hilos daemon; puede perderse al reiniciar | `core/research/acquisitions.py` | Estados durables, recuperación y cancelación verificable |
| H16 | **P1** | El botón «Leído» envía `READING` | `desktop_app/src/app.rs` | Enviar `READ` |
| H17 | **P1** | Se edita `research_type` en UI pero no se envía al backend | `desktop_app/src/app.rs`, `desktop_app/src/research_client.rs` | Persistir el valor y probar recarga |
| H18 | **P1** | Lecturas HTTP síncronas en funciones de refresco del escritorio | `desktop_app/src/research_client.rs`, `desktop_app/src/app.rs` | Eventos asíncronos, timeout y estado de carga |
| H19 | **P1** | Vistas Rust limitan listas a 100 sin paginación completa | `desktop_app/src/research_client.rs` | Paginación incremental con total correcto |
| H20 | **P1** | `app.rs` concentra miles de líneas de estado, acciones y vistas | `desktop_app/src/app.rs` | Modularizar sin cambiar framework |
| H21 | **P1** | Script de escritorio asume rutas Linux, DISPLAY y binario precompilado | `run_desktop.sh`, `desktop_app/src/main.rs` | Bootstrap y rutas portables por SO |
| H22 | **P1** | API key IEEE existe en configuración pero `search` usa endpoint web | `platforms/ieee.py` | Implementar rama API real o declarar capacidad no soportada |
| H23 | **P1** | Previews de importación/restauración residen en RAM y no sobreviven reinicios | `core/research/interchange.py` | Almacenamiento temporal durable, con caducidad y límites |
| H24 | **P1** | Actor HUMAN/AGENT inferido de una etiqueta textual, no de identidad autenticada | `core/research/repository.py` | Separar provenance declarada de identidad verificada |
| H25 | **P1** | Dependencias de FastAPI/Uvicorn/Jinja2 no explícitas; compatibilidad Python desalineada con SDK MCP v2 | `pyproject.toml` | Dependencias declaradas, lock y matriz de versiones probada |
| H26 | **P2** | README anuncia cantidad de tools/tests y versión anteriores | `README.md`, `mcp_server/tools/*` | Documentación y badges derivados de resultados reales |
| H27 | **P2** | No hay workflows CI visibles en el árbol auditado | `.github/workflows/` ausente | Integración continua Python + Rust + seguridad |
| H28 | **P1** | Proxy institucional y URL base configurable sin política de destinos suficientemente restringida | `config/settings.py`, `core/http_client.py` | Allowlist por proveedor, redirecciones seguras y protección SSRF |

**Excepción de compatibilidad:** conservar interfaces antiguas **NO** autoriza mantener respuestas que filtran secretos. H01/H02 se corrigen aunque clientes antiguos tengan que actualizarse; documentar el cambio de seguridad.

---

## 3. Arquitectura objetivo y decisiones innegociables

```text
Usuario / Rust (egui)                 Agentes MCP / herramientas
       |                                         |
       +---------> API local FastAPI <-----------+
                          |
              Servicios compartidos v2
       +------------------+----------------------+
       |                  |                      |
  SearchOrchestrator   ResearchService    ConnectionManager
       |                  |                      |
  Query AST          Proyectos/biblioteca   Secret store SO
       |                  |                + autorizaciones
  Provider Adapters  AcquisitionService          |
       |                  |                      |
  APIs/portales     SQLite transaccional <-------+
  autorizados      runs + páginas + eventos
       |
  Normalización + provenance + observaciones
       |
  Exportadores auditables (BibTeX, RIS, CSV, JSON)
```

### 3.1 Responsabilidades obligatorias

- **`ConnectionManager`** administra perfiles y capacidades por proveedor, autorización explícita, diagnóstico y revocación. Nunca entrega secretos a UI/agentes.
- **`QueryEngine`** tokeniza, construye AST, valida operadores/campos, compila consultas por proveedor y devuelve advertencias estructuradas.
- **`ProviderAdapter`** ejecuta consultas admitidas sin inventar soporte, normaliza registros y declara origen, fechas, conteos y condiciones de acceso.
- **`SearchOrchestrator`** decide qué proveedor(es) utilizar, valida disponibilidad y prepara la solicitud reproducible sin escribir directamente en tablas de UI.
- **`AcquisitionService`** es la única vía normal para iniciar, paginar, almacenar, cancelar y finalizar una ejecución de búsqueda vinculada a proyecto.
- **`ResearchRepository`** hace transacciones y valida ámbito de proyecto, idempotencia, claves foráneas y concurrencia.
- **`ExportService`** exporta desde pertenencias/observaciones reales, sin reinterpretar proveedores ni filtrar secretos.
- **`API REST y MCP`** son adaptadores finos sobre los mismos servicios; sus salidas no deberían divergir.
- **`Rust Desktop`** consume servicios; no introduce reglas de negocio independientes ni escribe las nuevas tablas directamente.

No reemplazar Rust/egui, Python/FastAPI ni SQLite por otro stack. No introducir microservicios, Redis, Kafka o base de datos remota para un problema que se puede resolver localmente.

### 3.2 Invariantes

1. Cada nueva búsqueda pertenece a exactamente un `project_id` válido y activo.
2. Una publicación global tiene `publication_id` estable; cada proyecto mantiene pertenencia, lectura y notas propias.
3. El proveedor **consultado** se almacena separado del editor de la publicación y de la procedencia del enriquecimiento.
4. No almacenar ni exportar credenciales en `research_events`, `source_observations`, `request_json` o resultados MCP.
5. Las páginas confirmadas sobreviven a un fallo posterior; una operación abortada no deja referencias colgantes.
6. Conteos desconocidos se representan como `null` y nunca como cero salvo que una fuente confirme cero.
7. Ningún cambio de semántica de consulta se aplica silenciosamente.
8. Ninguna acción visual se presenta como completada hasta recibir confirmación persistida.

---

## 4. Seguridad: modelo de amenazas y requisitos P0

### 4.1 Activos protegidos

Cookies autenticadas, API keys, tokens SSO/OAuth, headers de autorización, cuentas institucionales, datos locales de investigación, notas y evidencias, rutas privadas, resultados inéditos, base SQLite y exportaciones.

### 4.2 Adversarios/escenarios

- Página web externa intentando alcanzar puertos locales o provocar mutaciones desde un navegador.
- Otro proceso local leyendo endpoints inseguros o archivos de sesión.
- Cliente MCP o agente que solicita accidental o maliciosamente tokens.
- Redirección desde dominio autorizado hacia un destino distinto mientras se conservan credenciales.
- Proxy no confiable o TLS sin verificación.
- Parámetros `base_url_override` usados para dirigir peticiones internas o reenvío indebido de cookies.
- Archivo importado malicioso, datos HTML en abstracts y prompt injection dentro de metadatos.
- Errores/salidas de depuración que contienen secretos.

### 4.3 Políticas obligatorias

- **TLS verificado por defecto**; configurar `DISABLE_SSL_VERIFY=false` en ejemplos y código. Prohibido `--ignore-certificate-errors` en uso normal.
- **No secretos en respuestas**. `GET /api/connections` y nuevas rutas entregan estados, número de credenciales existentes o capacidades, jamás valores.
- **No secretos en eventos/logs**. Redactar `Cookie`, `Authorization`, `X-ELS-APIKey`, `X-ApiKey` y equivalentes; sanitizar URL/query params sensibles y errores HTTP.
- **Protección local**. Escuchar en loopback por defecto; modo red no puede activarse sin autenticación, autorización, política de origen y TLS donde aplique. Considerar Host/Origin, DNS rebinding y CSRF en dashboard. CORS no sustituye autenticación.
- **Privilegios mínimos**. Herramientas MCP con facultades de cambiar conexiones, iniciar ingesta o alterar documentos requerirán políticas de aprobación del host y un ámbito explícito; no se concede acceso a todos los proyectos por defecto cuando exista identidad de cliente.
- **Destinos permitidos**. URLs institucionales y overrides deben validarse por esquema HTTPS, host, puerto y asociación con proveedor. Impedir destinos de red privada/loopback o hosts arbitrarios, salvo modos técnicos explícitamente restringidos. Validar cada redirección y no reutilizar credenciales entre dominios.
- **Almacenamiento**. Preferir keyring del SO: Secret Service/KWallet/GNOME en Linux, Credential Manager/DPAPI en Windows, Keychain en macOS. SQLite solo almacena referencia a secreto y metadatos. Si no existe almacén seguro, informar limitación y utilizar modo memoria; NO degradar silenciosamente a JSON en texto plano.
- **Migración de secretos**. Al detectar `config/auth_store.json`, solicitar consentimiento antes de migrar; no imprimir valores, hacer lectura local, persistir en almacén seguro y borrar copia obsoleta solo tras verificación y autorización. No incluirlo en backups/exportaciones.
- **Archivos temporales**. Directorios exclusivos con permisos privados, borrado seguro a nivel lógico y expiración; nunca copiar la base general de cookies de Firefox a un directorio global predecible.
- **Datos no confiables**. No renderizar abstracts, títulos, notas o citas como HTML ejecutable. No tratar instrucciones de documentos como instrucciones del agente. Validar importaciones y límites de tamaño.
- **Auditoría**. Registrar acciones autorizadas y errores saneados, indicando si la identidad es verificada o solo declarada.

### 4.4 Política de herramientas privilegiadas

Separar herramientas MCP de **lectura/búsqueda** y herramientas de **mutación/configuración**. Crear lista de permisos por cliente: `search:read`, `project:read`, `project:write`, `connection:manage` y `export:create`, como capacidades locales propuestas. La implementación concreta puede usar permisos del host y un control local adicional. No afirmar autenticación real por el simple `actor_label`.

---

## 5. Conexión a bases académicas sin Burp Suite y sin copiar cookies manualmente

### 5.1 Experiencia esperada

1. El usuario selecciona Scopus, IEEE, SpringerLink, Web of Science u otra fuente compatible.
2. Pulsa **Conectar**. La app indica el mecanismo disponible (API oficial, acceso público o sesión de navegador autorizada).
3. Cuando haga falta autenticación institucional, se abre el navegador del sistema o un flujo soportado por el proveedor. El usuario inicia sesión por su institución.
4. La app verifica **capacidades reales**: acceso público, metadatos, búsqueda avanzada, paginación, filtros y exportación, sin confundir HTTP 200 con acceso institucional.
5. En adelante el usuario ve `Conectado`, `Acceso público`, `Acceso limitado`, `Requiere autenticación`, `Sesión caducada` o `Error`, con motivo y fecha.
6. El usuario puede **Reconectar**, **Desconectar**, **Probar** y **Abrir portal**. La interfaz nunca pide ni muestra contenido de cookies, aunque un mecanismo autorizado pueda administrar internamente un token de sesión.

**Límite fundamental:** abrir el portal en el navegador **no** autoriza ni permite automáticamente que `httpx` reutilice sus cookies. No afirmar «1 clic y se comparte la sesión» sin una integración real y consentida. Si un proveedor carece de API/OAuth/flujo seguro soportado, mostrar **Conexión automatizada no disponible** y permitir importación bibliográfica o búsqueda manual; jamás simular autenticación.

### 5.2 Orden de preferencia por proveedor

1. API oficial documentada con credenciales del usuario/institución, sujeta a licencia y cuotas.
2. Búsqueda pública legítima del proveedor, si expone resultados verificables.
3. Flujo de autenticación oficial en navegador (OAuth/OIDC/SSO o mecanismo equivalente), solo cuando existe forma documentada y autorizada de conectar la sesión a la aplicación.
4. Integración mediante sesión aislada de navegador controlada por el usuario, **si y solo si** respeta términos de uso, consentimiento y protecciones de la plataforma. Nunca leer perfiles genéricos de Firefox/Chrome de forma silenciosa.
5. Modo manual de importación BibTeX/RIS/CSV como alternativa honesta.

`Burp Suite` queda fuera del flujo de usuario. Si se conserva, únicamente como herramienta opcional de diagnóstico para desarrolladores, detrás de `DEV_DIAGNOSTICS=true`, sin botones visibles en producción, sin desactivar TLS en automático y sin dependencia funcional.

### 5.3 Estados tipados

`UNCONFIGURED`, `AUTH_REQUIRED`, `PUBLIC_ACCESS`, `INSTITUTIONAL_ACCESS`, `LIMITED_ACCESS`, `EXPIRED`, `CHALLENGED`, `NETWORK_ERROR`, `UNSUPPORTED`.

El resultado de diagnóstico DEBE incluir al menos `provider`, `status`, `checked_at`, `capabilities`, `auth_method`, `evidence` (sin secretos), `requires_user_action` y `next_action`. No confundir «portal alcanzable» con «búsqueda autenticada funcional».

### 5.4 Compatibilidad y retiro de módulos heredados

- Deshabilitar desde la UI de producción `Extraer Automáticamente Sesiones desde Firefox` y `Abrir en Burp`; retirar progresivamente `burp_launcher.rs` y `firefox_extractor.rs` tras confirmar que no quedan dependencias.
- Mantener importación manual de cURL **solo en modo experto/developer**, con advertencia, consentimiento, filtrado de dominios, redacción de salida y almacenamiento seguro; eliminarla de experiencias por defecto.
- Mantener `configure_auth` de MCP como compatibilidad solo si existe un sistema seguro de almacenamiento, con autorización explícita y sin devolver valores. Marcar deprecación del manejo de cookies literales.
- Eliminar rutas absolutas del desarrollador y utilizar configuración de directorios por plataforma (`platformdirs`/rutas nativas equivalentes).

---

## 6. Conectores académicos y fidelidad de la fuente

### 6.1 Contrato uniforme de proveedor

Cada adaptador DEBE declarar: `provider_id`, `provider_display_name`, `source_kind` (`OFFICIAL_API`, `OFFICIAL_WEB`, `PUBLIC_METADATA_AGGREGATOR`, `MANUAL_IMPORT`), `supports_advanced_boolean`, `supports_filters`, `supports_pagination`, `supports_total_count`, `requires_auth`, `rate_limit_policy` y `limitations`.

La respuesta normalizada de `search` incluye:

- `request`: consulta **exacta enviada**, idioma/sintaxis, filtros efectivos, tamaño de página, offset, mecanismo de acceso.
- `source`: proveedor real, endpoint lógico/versión, método `API/WEB/AGGREGATOR`; no exponer secretos.
- `result`: registros, `reported_total` nullable, `returned_count`, `has_more` nullable, `next_cursor`/offset si aplica.
- `provenance`: fecha/hora UTC de ejecución, caché sí/no, fecha de la respuesta original si procede, identificador de ejecución/página, warnings y límites relevantes.
- `capability_report`: qué filtros/operadores fueron aplicados en servidor, localmente o no están admitidos.

**Terminología obligatoria:** `source_provider` indica la fuente donde se realizó la búsqueda; `publisher` se refiere al editor bibliográfico; `enrichment_provider` indica quién completó metadatos. Nunca derivar `source_provider` de un prefijo DOI.

### 6.2 Scopus

- Separar explícitamente el adaptador de API Elsevier del adaptador de portal web. No suponer que una cookie es válida por el simple acceso a una URL.
- Usar solo endpoints permitidos por el proveedor y comprobar respuestas funcionales con fixtures y pruebas opt-in.
- Controlar cuota, errores 401/403/429, sesiones caducadas y paginación documentada.
- Verificar que `DOCTYPE`, años y campos de consulta se serializan correctamente; si un filtro no es soportado, reportarlo.
- No intentar eludir bloqueos ni desafíos automatizados.

### 6.3 IEEE Xplore

- Si se configuró una API key IEEE, debe existir un camino de búsqueda que use la **API oficial** correctamente, o declararse la credencial como no utilizable por esta versión.
- La ruta web `/rest/search` no debe considerarse una API pública estable ni equivalente a la oficial sin validación.
- Verificar límites de comodines, sintaxis Command Search, tipos y años con datos/documentación vigentes. Un linter no es prueba de ejecución válida.
- Probar que cada registro extraído tiene DOI/ID, título y año sin inventar valores.

### 6.4 SpringerLink versus Crossref

- `Crossref` **NO** es `SpringerLink`. Si se consulta `api.crossref.org/works`, guardar `source_provider=crossref` y presentarlo bajo Crossref, no como resultados directos de SpringerLink.
- `prefix:10.1007` no prueba que el resultado abarque todo Springer Nature/SpringerLink; el prefijo es criterio de metadatos, no índice editorial equivalente.
- No afirmar que `total-results` de Crossref corresponde a los resultados de SpringerLink.
- El adaptador Springer debe utilizar API/búsqueda oficial verificada o señalar `UNSUPPORTED` para la funcionalidad exacta; la alternativa Crossref debe ser una **fuente distinta y elegible**.
- Eliminar todo año sustituto: ausencia de `published` implica `year=null`.
- El test de conexión debe devolver fracaso si fallan la petición, el estado HTTP o el parseo requerido. Nunca `connected=true` como fallback genérico.
- Validar el efecto real de filtros múltiples; no aplicar solo el primero sin advertencia.

### 6.5 Web of Science

- Distinguir API Starter/otros niveles de acceso y portal web; nunca inferir credenciales válidas de un HTTP 200 a la página de inicio.
- Separar «portal alcanzable» de «permiso de búsqueda».
- Verificar que nombres de campos, filtros y paginación sean compatibles con el producto contratado.
- Mostrar las limitaciones de búsqueda/abstract si la API no los provee.

### 6.6 OpenAlex y Crossref para enriquecimiento

- Usarlos como proveedores de **enriquecimiento** o búsqueda **independiente** cuando corresponda; conservar siempre la procedencia.
- No reemplazar título/autores existentes sin revisión, acorde con Bloque 2. Para abstracts, aplicar política conservadora y registrar cambios.
- No aumentar un conteo de resultados de Scopus/IEEE/Springer por registros obtenidos mediante enriquecimiento.
- Deduplicar identidad de publicaciones sin destruir observaciones por fuente.

---

## 7. Motor de consultas: parser, AST, linters y traducción segura

### 7.1 Problema a resolver

`core/query_parser.py` separa cláusulas con reglas textuales y `core/query_translator.py` reescribe cadenas. Esto puede alterar `AND NOT`, anidamiento, operadores, campos y comodines. Para una revisión académica, estos cambios no son aceptables sin conocimiento del usuario.

### 7.2 Modelo de AST mínimo obligatorio

Definir nodos tipados para `Term`, `Phrase`, `Field`, `And`, `Or`, `Not`, `Group` y `Proximity` cuando un proveedor soporte proximidad. Cada nodo conserva `source_span` y la expresión original para mensajes precisos. El parser DEBE reconocer comillas escapadas, paréntesis anidados, precedencia, negación, operadores completos, comodines y field tags relevantes.

Precedencia y semántica estarán definidas por la sintaxis canónica; no asumir que todas las plataformas comparten precedencia. La salida debe ser un `CompilationReport`:

```json
{
  "target_provider": "ieee",
  "compiled_query": null,
  "status": "UNSUPPORTED_SEMANTICS",
  "errors": [
    {
      "code": "UNSUPPORTED_OPERATOR",
      "message": "La plataforma no admite una traducción equivalente",
      "span": [12, 19]
    }
  ],
  "warnings": [],
  "transformations": [],
  "is_semantically_equivalent": false
}
```

**Contrato:** si `is_semantically_equivalent=false`, no ejecutar automáticamente bajo la etiqueta de traducción exacta. Ofrecer edición manual, consulta propia de plataforma o consentimiento explícito para una **aproximación identificada como tal**. El sistema guarda ambas versiones y la razón del cambio.

### 7.3 Reglas de compilación

- No reemplazar `NOT` con `AND NOT` mediante sustitución textual.
- No dividir `OR` dentro de frases entre comillas.
- No convertir grupos anidados en un AND plano.
- Comodines: validar presupuesto sobre la consulta **final**; si es necesario expandir, usar diccionario versionado y mostrar términos introducidos; ante palabra desconocida, rechazar o pedir decisión, jamás quitar `*` en silencio.
- Field scopes: respetar `TITLE`, `ABSTRACT`, `KEYWORDS` y equivalentes únicamente cuando el proveedor ofrece correspondencia demostrable.
- Proximidad (`NEAR`, `W/n` y equivalentes): mapear solo si la distancia y el orden son equivalentes. De lo contrario devolver `UNSUPPORTED_SEMANTICS`.
- En consultas básicas por palabras clave, crear un tipo de consulta distinto de una ecuación avanzada; no enviar palabras libres como booleano validado.
- Limitar longitud y profundidad del AST para evitar consumo abusivo de memoria/CPU.
- Validación separada de compilación: `valid_syntax` no implica `supported_by_provider`.

### 7.4 Golden Dataset del Bloque 3 (sin módulos metodológicos)

Construir fixtures con entradas, AST esperado, salida por proveedor, errores previstos y versión de reglas. Mínimo:
- `("graph neural network" OR GNN) AND (anomaly OR intrusion)`;
- `A AND NOT B` y `A AND (NOT B)`;
- `A AND (B OR (C AND NOT D))`;
- frases que contengan literalmente “and”/“or”;
- comillas escapadas y paréntesis dentro de frases;
- consultas con exactamente 10 y 11 comodines cuando corresponda;
- varios comodines en un mismo término;
- operadores de proximidad;
- campos no soportados;
- guiones, Unicode, términos largos y expresiones vacías.

El conjunto DEBE incluir casos negativos y comparación de semántica, no limitarse a comprobar que aparece `TITLE-ABS-KEY` o que una cadena contiene `All Metadata`.

---

## 8. Adquisición única: búsqueda, paginación y proyecto

### 8.1 Flujo funcional

```text
Proyecto activo
  -> consulta (canónica o nativa)
  -> compilación y validación por proveedor
  -> preflight de conexión/capacidades
  -> creación de acquisition_run
  -> obtención de páginas
  -> transacción por página: raw metadata saneada + publicación + pertenencia + observación
  -> actualización de progreso
  -> finalización/cancelación/error
  -> biblioteca, historial, exportación
```

`AcquisitionService` del Bloque 2 es el destino canónico. No deben existir dos sistemas nuevos de ingesta con diferentes reglas de idempotencia, deduplicación y estado. El Bloque 1 puede permanecer mediante wrappers que deleguen en servicios nuevos, con una migración explícita del corpus heredado.

### 8.2 Límite estricto `max_records`

En cada iteración calcular `remaining=max_records-observed_count`; solicitar como máximo `min(provider_max_page_size, remaining)` si el proveedor lo permite. Aunque el proveedor devuelva más registros de los solicitados, **recortar antes de persistir** y registrar la anomalía. No alcanzar el límite por accidente. Ninguna página puede superar el máximo en la base.

`max_records` cuenta **observaciones nuevas de esa ejecución**, no publicaciones únicas globales. `reported_total` es un dato reportado por proveedor, posiblemente ausente o inconsistente. `unique_count` cuenta IDs distintos entre observaciones de la ejecución.

### 8.3 Terminación y ausencia de progreso

- Detectar páginas repetidas por cursor/identificador y firma de registros.
- No continuar indefinidamente si se reciben páginas con cero observaciones nuevas.
- Usar `has_more` o cursor del proveedor cuando está disponible; no deducir agotamiento solo de la longitud de una página sin contrato documentado.
- Soportar total desconocido (`null`).
- Distinguir error de proveedor de resultados genuinamente vacíos.
- Mantener orden estable y deduplicación por `(run_id, source_record_key)`.
- Aplicar límites de tiempo, páginas, reintentos y tamaño de respuesta, con retroceso exponencial y atención a `Retry-After`; no repetir automáticamente errores de autenticación.
- No intentar saltar protecciones antibot; detener y pedir intervención del usuario.

### 8.4 Máquina de estados

`QUEUED -> RUNNING -> COMPLETED|PARTIAL|FAILED|CANCELLED`. Definir transiciones atómicas y un campo de `cancel_requested` persistido. Una cancelación debe ser idempotente, comprobada entre páginas y no quedar sobrescrita por un worker tardío.

Al reiniciar el backend:
1. detectar jobs pendientes o abandonados;
2. conciliar estados de forma determinista;
3. marcar `PARTIAL` con `INTERRUPTED` si existen observaciones previas y no hay recuperación exacta;
4. marcar `FAILED` con `INTERRUPTED` si aún no hay observaciones;
5. permitir reintentar como ejecución nueva, sin duplicar el historial de la ejecución original.

No prometer reanudación exacta donde no existe cursor/estrategia persistida del proveedor. Evitar depender únicamente de hilos daemon y diccionarios en memoria; una cola SQLite local con worker controlado es suficiente. No lanzar trabajos ilimitados.

### 8.5 Razones de detención

Normalizar `END_OF_RESULTS`, `LIMIT`, `USER_CANCELLED`, `ERROR`, `AUTH_EXPIRED`, `WAF`, `RATE_LIMIT`, `REPEATED_PAGE`, `INTERRUPTED`, `UNSUPPORTED_QUERY`. Los detalles sensibles se redactan.

### 8.6 Caché

Clave completa: proveedor efectivo + ruta de acceso + hash de consulta compilada + filtros + versión de reglas + página/cursor + tamaño de página + ámbito de acceso. No compartir una respuesta institucional privada con otra identidad o conexión. Conservar `fetched_at`, TTL, proveedor y origen. Permitir refresco explícito. El reporte distingue «consulta realizada ahora» de «resultado leído de caché».

---

## 9. Identidad bibliográfica, deduplicación y proveniencia

Se mantienen las reglas del Bloque 2: DOI normalizado comparable pero `publication_id` estable; DOI distintos nunca se fusionan automáticamente; sin DOI, comparación estricta de título normalizado, año conocido y autores normalizados no vacíos; similitud difusa solo como **sugerencia**.

El motor heredado de deduplicación difusa NO DEBE fusionar automáticamente publicaciones del sistema nuevo ni alterar notas, relaciones o eventos. Si se conserva, confinarlo a datos legacy y ofrecer revisión manual con vista previa de proyectos afectados.

Cada observación conserva fuente consultada, registro/ID de origen, momento, consulta, versión del adaptador y advertencias. Una misma publicación puede tener observaciones de IEEE, Scopus, Crossref y un archivo RIS importado, pero **no** significa que se haya encontrado en SpringerLink por tener DOI `10.1007/*`.

Enriquecimiento con OpenAlex/Crossref: registrar antes/después, completar campos vacíos, conservar la procedencia y no reescribir el historial de resultados reportados por el proveedor. Toda exportación distingue bibliografía de observaciones brutas y ofrece información para reconciliar conteos.

---

## 10. Persistencia y migraciones sin pérdida de información

### 10.1 Mantener entidades del Bloque 2

Conservar `research_projects`, `research_questions`, `research_objectives`, `publications`, `project_publications`, `collections`, `tags`, `annotations`, `acquisition_runs`, `source_observations`, `research_events`, `mutation_receipts` y `publication_aliases`. No resetear IDs, estados de lectura, anotaciones, notas, fechas ni historial existente.

### 10.2 Cambios aditivos propuestos

La implementación puede resolverlos con tablas nuevas o columnas compatibles, siempre que conserve las invariantes:

| Entidad | Campos mínimos / finalidad |
|---|---|
| `connection_profiles` | `profile_id`, `provider_id`, `auth_mode`, `status`, `capabilities_json`, `secret_ref` nullable, `created_at`, `checked_at`; SIN credenciales crudas |
| `query_compilations` | `compilation_id`, `original_query`, `canonical_ast_json`, `target_provider`, `compiled_query`, `compiler_version`, `warnings_json`, `is_equivalent` |
| `research_search_pages` | `run_id`, `page_key`/cursor, `provider_id`, `request_hash`, `response_metadata_json`, `fetched_at`, `cache_origin`, `record_count`; UNIQUE por run y página |
| `acquisition_runs` extensiones | `cancel_requested`, `heartbeat_at`, `worker_lease_until`, `connection_profile_id` nullable, `query_compilation_id` nullable; estado y razón de detención estables |
| `source_observations` extensiones | `source_provider`, `source_kind`, `source_record_id`, `page_key`, `observed_at`, `enrichment_provider` nullable |

No es obligatorio almacenar el AST completo si existe serialización determinista y versionada, pero sí conservar material suficiente para reproducir la consulta. Los metadatos sin procedencia se marcan `LEGACY_UNKNOWN`, nunca se inventan.

### 10.3 Reglas de migración

1. Snapshot SQLite consistente por `sqlite3.Connection.backup`; no copiar solo `.db` ignorando WAL.
2. Schema version incremental en `schema_migrations`. Ejecutar una sola vez, con transacciones y rollback.
3. Migración idempotente con repetición verificable.
4. Conservar tablas antiguas durante una ventana de compatibilidad; no borrarlas sin comprobaciones y backup recuperable.
5. Preservar vínculos de proyectos y aliases creados por Bloque 2. No volver a importar la misma referencia si ya tiene alias.
6. Distinguir bibliotecas nuevas de `corpus_papers` heredado; migrar de forma explícita, con reporte de omisiones/colisiones.
7. Nunca inferir observaciones históricas ausentes ni reconstruir conteos que no fueron conservados.
8. Documentar estrategia de downgrade: restaurar backup completo, no intentar revertir parcialmente migraciones peligrosas.
9. Guardar todo timestamp nuevo en UTC ISO 8601 con `Z`; `PRAGMA foreign_keys=ON`, WAL y `busy_timeout` en cada conexión.
10. Separar transacciones de datos de operaciones de almacenamiento de secretos, con manejo explícito de fallas parciales.

### 10.4 Temporales de importación

El dict `_previews` de `InterchangeService` se sustituye por previsualizaciones acotadas y persistentes (tablas temporales o archivos privados con hash, TTL de 30 minutos, límite agregado y limpieza). `preview` no escribe biblioteca; `commit` verifica hash, ámbito de proyecto, idempotencia y caducidad. Reiniciar el backend no debe eliminar arbitrariamente previews aún válidas.

---

## 11. Contratos REST y MCP, autorización y compatibilidad

### 11.1 Conservar contratos del Bloque 2

Mantener `/api/v2/research` y herramientas `research_*`, pero enrutar toda búsqueda y mutación a servicios compartidos. Añadir campos opcionales compatibles y ofrecer migración documentada cuando algún cambio exija nueva versión.

La ruta canónica de búsqueda seguirá siendo:

`POST /api/v2/research/projects/{project_id}/searches`.

La respuesta debe contener `run_id`, `status`, `status_url` y `project_id`. Las páginas se consultan a través del estado de ejecución y la biblioteca, no mediante un timeout largo que bloquee al escritorio.

Ejemplo conceptual de solicitud (ajustar modelo existente preservando contratos):

```json
{
  "database": "scopus",
  "query": "(GNN OR \"graph neural network\") AND anomaly",
  "query_input_kind": "CANONICAL",
  "year_start": 2020,
  "year_end": 2026,
  "doc_types": ["Article", "Conference Paper"],
  "max_records": 100,
  "enrich_doi": true,
  "idempotency_key": "UUID"
}
```

`query_input_kind` toma `CANONICAL`, `PROVIDER_NATIVE` o `KEYWORDS`. Para clientes legacy que envían `query` sin ese campo, conservar interpretación existente hasta migración explícita; no traducir automáticamente cadenas que antes se enviaban directamente al proveedor.

### 11.2 Gestión de conexiones: nueva API saneada

Implementar bajo `/api/v2/connections`, o servicio equivalente acordado, operaciones:
- `GET /`: estados/metadatos saneados de conexiones.
- `POST /{provider}/connect`: inicia flujo permitido, devuelve acción y estado; no tokens.
- `POST /{provider}/test`: verifica capacidad funcional.
- `POST /{provider}/disconnect`: revoca/borra credencial local, cuando sea compatible con el proveedor.
- `GET /{provider}/capabilities`: capacidades y limitaciones.

Todas las respuestas prohíben campos `cookies`, `api_key`, `authorization`, `token` y headers crudos. Diferenciar administradores de conexiones de consumidores de búsquedas. Las operaciones de secretos requieren autorización, y el dashboard no utiliza métodos GET para acciones mutables.

**Rutas legacy:** mantener compatibilidad de nombres cuando sea seguro, pero reemplazar inmediatamente cualquier respuesta secreta por estructura redactada. No guardar un `api_key` en JSON sin protección por conservar un contrato antiguo.

### 11.3 MCP

- Mantener `stdio` para clientes locales y comprobar negociación con el SDK elegido.
- Evaluar `Streamable HTTP` para exposición HTTP autenticada; conservar `sse` únicamente como compatibilidad documentada, si SDK y clientes lo soportan.
- No habilitar MCP remoto sin controles de autorización y transporte adecuados.
- Herramientas privilegiadas de configuración requieren permiso/consentimiento y no pueden revelar secretos.
- Los errores MCP deben preservar código de negocio estructurado y no incluir credenciales.
- Identidad del actor: `actor_type` y `actor_label` son metadatos de procedencia; cuando se requiera autorización, agregar `principal_id` autenticado separadamente. No derivar seguridad de una palabra como «Codex».

### 11.4 Errores comunes

Adoptar `{error:{code,message,details}, request_id}` en REST con códigos HTTP coherentes. Códigos mínimos: `NOT_FOUND`, `VALIDATION_ERROR`, `REVISION_CONFLICT`, `IDEMPOTENCY_CONFLICT`, `AUTH_REQUIRED`, `AUTH_EXPIRED`, `FORBIDDEN`, `UNSUPPORTED_QUERY`, `PROVIDER_UNAVAILABLE`, `RATE_LIMITED`, `WAF_CHALLENGE`, `CANCELLED`, `MIGRATION_FAILED`, `INTERNAL_ERROR`.

No devolver texto HTML de un proveedor ni tracebacks a la UI. El log técnico de diagnóstico debe estar saneado y enlazado por `request_id`.

---

## 12. Aplicación Rust: UX, bugs concretos y modularización

### 12.1 Navegación objetivo

Barra lateral persistente similar a un workspace:
- **Proyectos**: crear, cambiar, archivar, renombrar, historial; reabrir último proyecto válido.
- **Búsquedas del proyecto**: lista de búsquedas guardadas/ejecuciones con estado, proveedor y fecha; seleccionar una abre resultados, filtros y procedencia. No mostrar un chat ni habilitar un modo de búsqueda web genérica.
- **Biblioteca**: publicaciones del proyecto, filtros combinados, lecturas, colecciones, etiquetas, orden y paginación.
- **Notas y evidencias**: vínculo a publicación/proyecto/pregunta; distinguir ABSTRACT de FULLTEXT aportado manualmente.
- **Importar/Exportar**: BibTeX/RIS/CSV y JSON; contenido completo no se descarga en esta fase.
- **Conexiones**: conectar, probar y reconectar sin Burp y sin campos de cookies.
- **Calibrador**: AST + reportes visibles, consulta por plataforma editable y validación.
- **Historial/Auditoría**: runs y acciones realizadas, diferenciando actor declarado de identidad comprobada.

### 12.2 Errores que deben corregirse explícitamente

- En botón «Leído», enviar `READ` en lugar de `READING`.
- En guardado de proyecto, transmitir y persistir `research_type`; tras recargar debe conservarse.
- Toda ingesta desde la búsqueda utiliza `get_active_project_id()`, no `"default_slr"` hardcodeado.
- No ofrecer «guardar» ni «ingestar» sin proyecto válido seleccionado; enseñar cómo crearlo.
- Eliminar el conteo central global `default_slr` como resumen de un proyecto distinto. Cada tarjeta usa `project_id` correcto y muestra la fuente del conteo.
- Evitar llamadas HTTP de red en el hilo de render/`Default`. Despachar a trabajadores y devolver mensajes al hilo UI con canales; mostrar `loading` y timeout.
- Manejar estados de backend: `OFFLINE`, `CONNECTING`, `ONLINE`, `ERROR` con reintento; no fijar `backend_online=true` por omisión ni simular éxito.
- Usar paginación (preferible incremento de 25–100) con total y filtros reales, no truncar silenciosamente a 100 elementos.
- Validar respuestas HTTP antes de parsearlas. En ingesta y deduplicación legacy, no interpretar cualquier JSON de error como resultado exitoso con ceros.
- Mantener borradores locales en conflictos de revisión, ofrecer recargar/comparar, nunca descartar silenciosamente.
- Etiquetas y botones reflejan acciones efectivas: si se anuncia arrastrar archivo o descargar, implementar esa acción o eliminar la promesa.
- Debounce al filtrar bibliotecas y evitar refrescar toda la vista en cada tecla.

### 12.3 Propuesta de módulos (sin reescritura total)

```text
desktop_app/src/
  main.rs
  app.rs                  # estado raíz, enrutamiento de eventos, composición
  state.rs                # estado tipado de aplicación
  events.rs               # mensajes de fondo y acciones
  api/
    mod.rs
    research.rs
    connections.rs
    search.rs
  views/
    sidebar.rs
    projects.rs
    search.rs
    library.rs
    annotations.rs
    interchange.rs
    connections.rs
    calibration.rs
    history.rs
  components/
    statuses.rs
    pagination.rs
    notifications.rs
```

Esta estructura es una propuesta, no una obligación de nombres exactos. Mantener `egui`/`eframe`, minimizar churn, escribir pruebas a medida que se extraigan módulos y conservar los comportamientos ya útiles.

### 12.4 Rendimiento y accesibilidad

No bloquear el hilo UI; usar timeouts, cancelación y estados vacíos/reintento; conservar foco al cambiar de vistas; admitir tamaños de ventana razonables, textos largos, selección/copia de DOI/citas, contraste consistente claro/oscuro, atajos básicos de búsqueda y mensajes comprensibles en español.

---

## 13. Instalación reproducible y soporte multiplataforma

### 13.1 Python y dependencias

El SDK MCP v2 publicado documenta **Python 3.11+**; contrastar requisitos al fijar la versión exacta antes de declarar soporte. Cambiar `requires-python` o el rango de SDK tras probar la matriz elegida. No asumir Python 3.10 válido con MCP v2 por compatibilidad histórica del resto del código.

Declarar directamente dependencias runtime utilizadas: `fastapi`, `uvicorn`, `jinja2`, `httpx`, `mcp`, `pydantic`, bibliografía, `python-dotenv` si se usa, y librería de keyring seleccionada. Definir extras para desarrollo/tests y crear lock de dependencias reproducible; no depender de instalaciones transitivas accidentales.

### 13.2 Rust

Mantener `Cargo.lock`, compilar con `cargo check --locked` y `cargo test --locked`; definir versiones Rust mínimas que realmente compilan con `eframe 0.37`. Revisar compatibilidad de backends por OS; no suponer rutas Linux para fuentes ni navegadores. Los instaladores no deben incluir credenciales ni bases personales.

### 13.3 Bootstrap

- Linux: script que detecta entorno/puerto, crea venv o usa entorno existente, valida dependencias, inicia backend y construye/abre escritorio; muestra errores.
- Windows: PowerShell o ejecutable lanzador compatible con Windows 11; rutas correctas para Python/venv, almacenamiento de configuración en AppData y sin `bash` obligatorio.
- macOS: scripts o empaquetado compatibles; Keychain y rutas de Application Support.
- No fijar `DISPLAY=:1` ni `/usr/share/fonts/...` como requisito. Utilizar fuentes del sistema con fallback.
- El backend debe poder arrancarse desde el escritorio, detectarse y cerrarse de forma controlada cuando sea administrado por el proceso; si es externo, no matarlo indebidamente.
- Usar rutas configurables y resolver conflictos del puerto `8765` con mensaje claro.
- Preparar diagnóstico de inicio seguro, sin imprimir secretos.

### 13.4 Versionado/documentación

Una sola fuente de versión de producto para UI, `pyproject.toml`, `Cargo.toml` y API; fijar versión de esquema por separado. No etiquetar «3.0» por redactar el Bloque 3. Actualizar README público al finalizar y obtener badges de CI, no de texto estático desactualizado. Documentar limitaciones por plataforma y permisos institucionales necesarios.

---

## 14. Pruebas automatizadas y validación científica

### 14.1 Capas obligatorias

1. **Unitarias**: AST, serializadores, validadores, normalización DOI/título, estados de lectura, límites.
2. **Contratos**: REST y MCP producen estructuras coherentes y mismas mutaciones por `project_id`.
3. **Integración SQLite**: migraciones, transacciones por página, concurrencia, idempotencia, cancelación y restart simulado.
4. **Fixtures de conectores**: respuestas válidas, vacías, malformadas, 401/403/429, timeout, redirección, proveedor no soportado, totales desconocidos.
5. **Seguridad**: no secretos en todas las respuestas, archivos, logs, eventos, exports; CSRF/origen, protección de destinos, TLS y permisos.
6. **Rust**: compilación, deserialización, eventos de estado y cambios de lectura; smoke tests de arranque.
7. **End-to-end local**: crear proyecto -> conectar por modo disponible -> buscar -> almacenar -> anotar -> importar -> exportar -> restaurar.
8. **Pruebas reales opt-in**: cada proveedor con credenciales autorizadas, entorno aislado y cuotas limitadas; no ejecutarlas por defecto en CI.

### 14.2 Matriz de errores

Comprobar para cada proveedor: `OK_PUBLIC`, `OK_AUTH`, `UNAUTHORIZED`, `FORBIDDEN`, `EXPIRED`, `RATE_LIMIT`, `WAF`, `TIMEOUT`, `BAD_JSON`, `EMPTY_RESULTS`, `UNKNOWN_TOTAL`, `REDIRECT_EXTERNAL`, `PAGE_REPEAT` y `UNSUPPORTED_FILTER`. En todos debe existir una respuesta coherente y ningún secreto filtrado.

### 14.3 CI mínima

Crear GitHub Actions que ejecuten Python 3.11+ seleccionado, lint/format (`ruff` o equivalente), `pytest`, `cargo fmt --check`, `cargo check --locked`, `cargo test --locked`, auditoría de dependencias y un escaneo básico de secretos. Ejecutar en PR y push. Publicar artefactos de test únicamente si no contienen datos privados.

**Importante:** ningún test que dependa de cuentas Scopus/IEEE/WoS debe bloquear CI pública. Los tests locales con mocks y fixtures deben demostrar las invariantes; un pequeño conjunto de pruebas live se ejecuta manualmente con opt-in y resultados registrados.

### 14.4 Calidad del método

Evaluar la fidelidad de consultas con un golden dataset y, donde haya acceso autorizado, comparar manualmente un conjunto pequeño y documentado de búsquedas contra la UI oficial de la plataforma: consulta exacta, conteos, fechas, tipos y muestra de DOIs. Registrar diferencias, metodología, hora y limitaciones. No afirmar equivalencia universal solo por coincidencia de un conteo.

---

## 15. Observabilidad, privacidad y métricas

Registrar en ejecuciones/diagnóstico: `request_id`, `run_id`, `project_id`, proveedor, duración, estado HTTP normalizado, número de registros recibidos/persistidos, caché, reintentos y reason code. No registrar respuesta HTTP completa ni headers sensibles.

Métricas funcionales:
- búsquedas que terminan con estado válido;
- porcentaje de jobs correctamente asociados al proyecto;
- discrepancias de `reported_total`/`observed_count` justificadas;
- errores de compilación semántica;
- tiempo de respuesta UI y bloqueos;
- fallos de conexión por proveedor/capacidad;
- diferencias reproducibles entre export e import;
- porcentaje de tests/escenarios P0 aprobados.

Sin telemetría externa por defecto. Exportaciones de diagnóstico requieren vista previa y redacción de datos sensibles. El historial de auditoría es append-only a través de la aplicación, no inmutable frente a manipulación física del SQLite.

---

## 16. Plan de trabajo por fases y puertas de calidad

**No implementar todo a la vez.** Crear cambios pequeños, con pruebas y commits temáticos. Ejecutar el orden indicado, evitando rediseñar interfaces antes de estabilizar los servicios.

### Fase 3.0 — Inventario y pruebas de regresión (P0)

- Congelar commit de trabajo y estado de tests/compilación actuales.
- Registrar todas las rutas REST, tools MCP y contratos consumidos por Rust.
- Reproducir con tests aislados H01, H02, H06, H09, H11, H13, H16 y H17.
- Elaborar mapa de tablas legacy y v2; confirmar backups.

**Salida:** matriz base de pruebas, fallos conocidos y restricciones; ningún dato borrado.

### Fase 3.1 — Seguridad de secretos y conexiones (P0)

- Quitar exposición de secretos en REST; sanear MCP/logs.
- Crear `ConnectionManager` y almacén seguro; migración opt-in.
- Validar destinos, redirecciones, TLS y acceso local.
- Aislar o retirar extracción Firefox y Burp del flujo productivo.
- Definir capability checks reales y estados tipados.

**Salida:** no exposición de credenciales; acceso público/institucional distinguible; sin Burp requerido.

### Fase 3.2 — Fidelidad de conectores y AST (P0)

- Separar Crossref de SpringerLink; eliminar año supuesto.
- Separar API oficial/endpoint web por plataforma.
- Implementar parser/AST, compiladores y golden dataset.
- Mostrar errores y aproximaciones antes de ejecutar.
- Añadir provenance completa por resultado.

**Salida:** consultas reproducibles y proveedor correcto en cada registro/conteo.

### Fase 3.3 — Consolidación de ingesta y datos (P0/P1)

- Introducir servicio único de búsqueda/inserción por proyecto.
- Migración aditiva, backup y reconciliación de legacy.
- `max_records` estricto, detectores de páginas repetidas y errores.
- Cancelación persistente, reconciliación al reiniciar, TTL/caché por scope.
- No automezclar con fuzzy los registros del sistema nuevo.

**Salida:** búsqueda desde Rust/MCP/REST termina en mismo proyecto y modelo de datos.

### Fase 3.4 — Escritorio y UX (P1)

- Corregir READ, research_type, contexto de proyecto y estados.
- Eliminar HTTP bloqueante del render; modularizar `app.rs`.
- Historial de búsquedas por proyecto, paginación y errores visibles.
- Pantalla de conexiones sin Burp/cookies manuales.
- Mantener notas, import/export y calibrador funcionando.

**Salida:** recorrido completo del usuario sin falsos guardados ni corpus paralelo.

### Fase 3.5 — Distribución, documentación y CI (P1/P2)

- Corregir dependencias, versiones, lock y scripts por SO.
- Agregar acciones CI y tests de seguridad/regresión.
- Sincronizar README principal, ayudas y versión del producto.
- Documentar casos reales de plataforma y límites conocidos.
- Realizar pruebas manuales visuales y smoke tests de release.

**Salida:** build y uso reproducible; evidencia de criterios de aceptación.

### 16.1 Archivos prioritarios

| Prioridad | Archivos del repositorio |
|---|---|
| P0 | `dashboard/routes/api.py`, `core/http_client.py`, `config/settings.py`, `mcp_server/tools/auth_tools.py` |
| P0 | `platforms/scopus.py`, `platforms/ieee.py`, `platforms/springer.py`, `platforms/wos.py`, `platforms/base.py` |
| P0 | `core/query_parser.py`, `core/query_translator.py`, `core/query_validator.py` |
| P0 | `core/research/acquisitions.py`, `core/research/repository.py`, `core/migrations/runner.py`, `core/db.py`, `core/stream_fetcher.py` |
| P1 | `dashboard/routes/research_api.py`, `mcp_server/tools/research_tools.py`, `core/research/interchange.py` |
| P1 | `desktop_app/src/app.rs`, `desktop_app/src/research_client.rs`, `desktop_app/src/main.rs`, `desktop_app/src/burp_launcher.rs`, `desktop_app/src/firefox_extractor.rs` |
| P1/P2 | `run_desktop.sh`, `run_dashboard.py`, `run_mcp.py`, `pyproject.toml`, `desktop_app/Cargo.toml`, `README.md`, `tests/`, `.github/workflows/` |

Crear módulos nuevos únicamente cuando reduzcan duplicación o hagan explícita una responsabilidad; no añadir archivos vacíos o código sin uso. Reusar lo válido del Bloque 2.

---

## 17. Pruebas de aceptación del Bloque 3

**Regla:** los criterios `B3-01` a `B3-36` son verificables con tests automatizados o instrucciones manuales repetibles. Cada uno debe registrar estado `PASS/FAIL/BLOCKED`, comando o procedimiento, evidencia y commit. `BLOCKED` no equivale a `PASS`.

| ID | Prioridad | Escenario y resultado obligatorio |
|---|---|---|
| B3-01 | P0 | `GET /api/connections` no devuelve cookies, tokens, headers ni claves incluso con store poblado. |
| B3-02 | P0 | Actualización/autenticación de conexión no refleja secretos en respuestas, eventos, errores ni logs. |
| B3-03 | P0 | Guardado de credenciales usa almacén protegido o memoria con aviso; no archivo plano silencioso. |
| B3-04 | P0 | Backend solo loopback por defecto; exposición en red sin auth es rechazada o bloqueada. |
| B3-05 | P0 | TLS verificado por defecto; sin proxy/Burp requerido para búsqueda normal. |
| B3-06 | P0 | Redirección hacia host no autorizado no reenvía cookies ni headers privados. |
| B3-07 | P0 | Firefox no se extrae de forma silenciosa y no se copia su cookie DB a `/tmp` global. |
| B3-08 | P0 | Conectar/verificar proveedor muestra capacidades correctas, no falso acceso institucional por HTTP 200. |
| B3-09 | P0 | Sin mecanismo institucional soportado, sistema devuelve `UNSUPPORTED/AUTH_REQUIRED`, nunca sesión fingida. |
| B3-10 | P0 | Respuesta Crossref indica `source_provider=crossref` y no se presenta como total SpringerLink. |
| B3-11 | P0 | Registro con año ausente conserva `null`, incluso tras enriquecimiento/export. |
| B3-12 | P0 | IEEE con API key usa ruta API implementada o informa explícitamente que no está disponible. |
| B3-13 | P0 | Consulta `A AND NOT B` se compila sin duplicar `AND` ni alterar negación. |
| B3-14 | P0 | Consulta anidada con OR/AND/NOT conserva semántica o rechaza traducción; nunca aplana grupos. |
| B3-15 | P0 | Once comodines o un término con varios comodines producen rechazo/expansión explícita y presupuesto correcto. |
| B3-16 | P0 | Campos y operadores de proximidad no soportados generan error tipado, sin transformación oculta. |
| B3-17 | P0 | Se guarda consulta canónica, consulta ejecutada, reglas, filtros, proveedor real y momento. |
| B3-18 | P0 | Buscar con proyecto A activo crea run, observaciones y biblioteca en A, nunca en `default_slr` ni B. |
| B3-19 | P0 | La misma búsqueda desde REST y MCP usa reglas de ingesta equivalentes y mismo aislamiento de proyecto. |
| B3-20 | P0 | `max_records=10` no almacena 25 observaciones aunque el proveedor devuelva página de 25. |
| B3-21 | P1 | Página repetida o sin progreso no produce bucle infinito ni duplica observaciones. |
| B3-22 | P1 | Total desconocido sigue siendo `null`, no cero; agotamiento y límite se distinguen. |
| B3-23 | P1 | Cancelar entre páginas deja estado final coherente e idempotente y conserva páginas anteriores. |
| B3-24 | P1 | Reiniciar backend reconcilia runs huérfanos y no simula `COMPLETED`. |
| B3-25 | P0 | DOI distinto y título similar no se automezclan; notas, aliases y membresías sobreviven. |
| B3-26 | P1 | Preview de importación válida persiste al reinicio dentro del TTL y no duplica commit. |
| B3-27 | P1 | Botón «Leído» produce `READ` en SQLite y se refleja tras recargar UI. |
| B3-28 | P1 | Editar `research_type` en Rust persiste y sobrevive al reinicio. |
| B3-29 | P1 | Biblioteca/listado de proyectos con más de 100 ítems permite acceder a todos mediante paginación. |
| B3-30 | P1 | Backend caído o lento no bloquea dibujo UI ni muestra guardado o ingesta falsamente exitosos. |
| B3-31 | P1 | Exportaciones BibTeX/RIS/CSV/JSON contienen datos correctos y ninguna credencial. |
| B3-32 | P1 | Migración ejecutada dos veces no duplica ni pierde proyectos, notas, fuentes y estados. |
| B3-33 | P1 | Snapshot SQLite previo es restaurable, incluso en modo WAL. |
| B3-34 | P1 | Configuración y arranque documentados funcionan en matriz declarada de SO; sin rutas personales. |
| B3-35 | P1 | CI ejecuta pytest, validación de contratos, tests Rust, lint y escaneo básico de secretos. |
| B3-36 | P2 | README público coincide con versión, herramientas implementadas, modos de acceso y tests realmente observados. |

### 17.1 Pruebas de regresión del Bloque 2

Re-ejecutar **A01–A20**, especialmente A02 (aislamiento), A03–A05 (observaciones/identidad), A07 (fusiones), A09–A11 (scopes/idempotencia/revisiones), A12–A13 (runs), A14–A17 (import/export/restore), A18 (migración), A19 (REST/MCP) y A20 (errores de UI). Los contratos nuevos no deben degradar estas garantías.

### 17.2 Pruebas manuales obligatorias de producto

1. Iniciar aplicación limpia, crear proyecto «Investigación GNN» y seleccionarlo.
2. Conectar fuente pública o institucional permitida; observar método/capacidades sin ver cookies.
3. Buscar una ecuación avanzada; revisar el reporte de compilación y proveedor.
4. Guardar 10 registros y comprobar que solo esos 10 se añadieron a proyecto activo.
5. Cambiar estado a READ, añadir nota y cambiar entre dos proyectos; comprobar aislamiento.
6. Importar RIS/BibTeX, identificar un duplicado y generar export compatible.
7. Interrumpir backend durante una búsqueda y recuperar una ejecución PARTIAL/FAILED correctamente.
8. Reiniciar escritorio, comprobar proyectos/biblioteca/historial y verificar que no aparece un chat ni modo web genérico.

Guardar capturas de estados (sin información privada), resultados y limitaciones. No usar imágenes como sustituto de pruebas de persistencia.

---

## 18. Criterio de terminado / Definition of Done

La entrega se considera terminada solo cuando:

- Todos los **P0** están corregidos y todos los criterios correspondientes pasan.
- `B3-01` a `B3-36` tienen evidencia `PASS` o excepciones explícitas aprobadas, no supuestos.
- A01–A20 del Bloque 2 siguen pasando; se corrigen los tests que reflejen contratos inseguros sin conservar vulnerabilidades.
- Los distintos clientes usan el mismo servicio de adquisición y los mismos IDs de proyecto/publicación.
- Un test demuestra que ningún token/cookie llega a REST/MCP/logs/exports ni a un dominio no autorizado.
- Los resultados SpringerLink/Crossref y el AST de consultas no tienen sustituciones semánticas silenciosas.
- Los fallos del escritorio sobre lectura, research_type, bloqueo y paginación están solucionados.
- Existe un procedimiento reproducible de instalación, migración, backup y recuperación.
- CI compila y ejecuta pruebas de Python y Rust en versiones publicadas de dependencias.
- README público y documentación reflejan exactamente lo realmente implementado, no metas.
- Se ha registrado una evaluación final con fallos remanentes, cobertura, plataformas validadas y limitaciones verificables.

**No aceptar como «Bloque 3 terminado»** una interfaz nueva con botones decorativos, un puñado de tests verdes, conteos procedentes de un proveedor incorrecto, supresión de errores o una autenticación que requiere intervención de Burp sin declararlo.

---

## 19. Instrucciones operativas para Antigravity, Codex u otro agente implementador

1. **Leer primero** `README.md`, `docs/block2/README.md`, este README, `pyproject.toml` y los servicios/contratos existentes. Crear un mapa de funciones usadas desde Rust, REST y MCP.
2. **No reescribir en bloque.** Desarrollar Fases 3.0–3.5 por PR/commit separado; priorizar cambios P0 y conservar la funcionalidad del Bloque 2.
3. **Antes de corregir**, añadir tests que capturen el bug. Un test rojo reproducible + corrección + test verde es preferible a afirmar una mejora a ojo.
4. **No inventar respuestas de proveedores**. Usar fixtures identificadas como simuladas. Las pruebas live requieren permisos, credenciales del usuario y reporte explícito.
5. **No ejecutar comandos destructivos** ni purgar el archivo `auth_store.json` o bases de usuario sin backup, consentimiento y ruta de recuperación.
6. **No desactivar TLS, eludir WAF/CAPTCHA ni extraer credenciales ocultas** como atajo técnico.
7. **No cambiar nombres públicos ni esquemas silenciosamente**. Si un contrato anterior es inseguro, documentar la excepción y crear migración segura para clientes.
8. **Mantener código sencillo y reutilizable**; evitar nuevas dependencias salvo beneficio comprobable.
9. **Al cerrar cada fase**, entregar: archivos cambiados, decisión técnica, comandos ejecutados, tests y resultados, migraciones, capturas pertinentes, riesgos y tareas pendientes.
10. **Si una restricción de plataforma impide una característica**, marcar `BLOCKED/UNSUPPORTED` con evidencia; no sustituir esa fuente por otra sin mostrarlo al usuario.

### Formato mínimo del informe de implementación

```markdown
## Fase 3.x — Resultado
- Commit y archivos:
- Requisitos Hxx resueltos:
- Criterios B3-xx: PASS / FAIL / BLOCKED
- Comandos ejecutados y salida resumida:
- Compatibilidad con A01–A20:
- Pruebas en vivo (si se autorizaron):
- Datos migrados y backup comprobado:
- Riesgos, limitaciones y siguientes acciones:
```

---

## 20. Referencias y decisiones que deben revalidarse

**Código y diseño propios**
- [Repositorio MCPCONECCT](https://github.com/glender222/MCPCONECCT)
- [Bloque 2](../block2/README.md)
- [API legacy](../../dashboard/routes/api.py)
- [API de investigación](../../dashboard/routes/research_api.py)
- [Adquisición v2](../../core/research/acquisitions.py)
- [Motor de consultas](../../core/query_translator.py)
- [Cliente de sesiones](../../core/http_client.py)
- [Escritorio Rust](../../desktop_app/src/app.rs)
- [Conector Springer/Crossref](../../platforms/springer.py)

**Estándares y proveedores**
- [MCP — documentación oficial](https://modelcontextprotocol.io/)
- [MCP Python SDK v2 — documentación](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/index.md)
- [MCP Python SDK — guía de migración v2](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/migration.md)
- [FastAPI — seguridad](https://fastapi.tiangolo.com/tutorial/security/)
- [SQLite — Online Backup API](https://www.sqlite.org/backup.html)
- [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)
- [Springer Nature API](https://dev.springernature.com/)
- [Elsevier Developer Portal](https://dev.elsevier.com/)
- [IEEE Xplore API](https://developer.ieee.org/)
- [Web of Science API](https://developer.clarivate.com/)

Los endpoints, reglas de búsqueda, requisitos de licencia, versiones SDK y comportamientos del proveedor pueden cambiar. Confirmar contra documentación vigente y pruebas reales autorizadas durante la implementación; nunca convertir una hipótesis o fixture en afirmación de producción.

---

## 21. Resumen ejecutivo de prioridades

1. **Primero seguridad y verdad de los datos:** secretos, TLS, conexión autorizada, fuentes reales y consultas exactas.
2. **Después integración:** eliminar el corpus paralelo, hacer persistencia estrictamente por proyecto y corregir paginación/cancelación.
3. **Luego experiencia:** arreglar Rust, mantener sidebar/búsquedas por proyecto, flujo sin Burp y sin modo web genérico.
4. **Por último distribución:** pruebas CI, soporte multiplataforma, documentación real, instalación y criterios de release.

**Resultado esperado del Bloque 3:** MCPCONECCT deja de ser un conjunto de módulos potentes pero parcialmente desacoplados para convertirse en una herramienta bibliográfica local **coherente, verificable, segura y lista para futuras funciones metodológicas**, sin prometer capacidades científicas, institucionales o de autenticación que no hayan sido comprobadas.
