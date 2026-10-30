"""
Pydantic Models and Data Contracts for Block 2 Research System.
Shared between REST API and MCP Tools.
Rejects undeclared fields (extra="forbid").
"""
from typing import List, Optional, Dict, Any, Literal
from enum import Enum
import unicodedata
from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator


def normalize_name_key(name: str) -> str:
    """Unicode NFKC + trim + casefold normalization for unique collection/tag indexing."""
    if not name:
        return ""
    normalized = unicodedata.normalize("NFKC", name).strip()
    return normalized.casefold()


# --- Enums ---

class ReadingStatus(str, Enum):
    UNREAD = "UNREAD"
    READING = "READING"
    READ = "READ"


class AnnotationKind(str, Enum):
    NOTE = "NOTE"
    QUOTE = "QUOTE"
    PARAPHRASE = "PARAPHRASE"


class SourceKind(str, Enum):
    NONE = "NONE"
    ABSTRACT = "ABSTRACT"
    FULLTEXT = "FULLTEXT"


class ActorType(str, Enum):
    HUMAN = "HUMAN"
    AGENT = "AGENT"


class RunKind(str, Enum):
    SEARCH = "SEARCH"
    IMPORT = "IMPORT"


class RunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ExportScope(str, Enum):
    ALL = "ALL"
    COLLECTION = "COLLECTION"


class ExportFormat(str, Enum):
    BIB = "BIB"
    RIS = "RIS"
    CSV = "CSV"
    PROJECT_JSON = "PROJECT_JSON"


class AliasType(str, Enum):
    LEGACY = "LEGACY"
    MERGED = "MERGED"


# --- Error Model ---

class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)


class UniformErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error: ErrorDetail


# --- Project Models ---

class ResearchProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=10000)
    research_type: str = Field(default="", max_length=80)
    idempotency_key: Optional[str] = None

    @field_validator("name")
    def validate_name(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Project name cannot be empty or whitespace only")
        return s


class ResearchProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=10000)
    research_type: Optional[str] = Field(default=None, max_length=80)
    archived: Optional[bool] = None
    expected_revision: Optional[int] = None
    idempotency_key: Optional[str] = None

    @field_validator("name")
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            s = v.strip()
            if not s:
                raise ValueError("Project name cannot be empty")
            return s
        return v


class ResearchProjectResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    name: str
    description: str
    research_type: str
    archived: bool
    created_at: str
    updated_at: str
    revision: int


# --- Outline (Questions & Objectives) ---

class QuestionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: Optional[str] = None
    text: str = Field(min_length=1, max_length=5000)
    position: int = Field(default=0, ge=0)


class ObjectiveItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective_id: Optional[str] = None
    text: str = Field(min_length=1, max_length=5000)
    position: int = Field(default=0, ge=0)


class SetOutlineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int
    questions: List[QuestionItem] = Field(default_factory=list)
    objectives: List[ObjectiveItem] = Field(default_factory=list)
    idempotency_key: Optional[str] = None


class OutlineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    revision: int
    questions: List[Dict[str, Any]]
    objectives: List[Dict[str, Any]]


# --- Organization (Collections & Tags) ---

class CollectionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collection_id: Optional[str] = None
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    def check_name(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Collection name cannot be empty")
        return s


class TagDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag_id: Optional[str] = None
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    def check_name(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Tag name cannot be empty")
        return s


class CollectionAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collection_id: str
    publication_id: str


class TagAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag_id: str
    publication_id: str


class SetOrganizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int
    collections: List[CollectionDefinition] = Field(default_factory=list)
    tags: List[TagDefinition] = Field(default_factory=list)
    collection_members: List[CollectionAssignment] = Field(default_factory=list)
    publication_tags: List[TagAssignment] = Field(default_factory=list)
    idempotency_key: Optional[str] = None


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    revision: int
    collections: List[Dict[str, Any]]
    tags: List[Dict[str, Any]]
    collection_members: List[Dict[str, Any]]
    publication_tags: List[Dict[str, Any]]


# --- Publications & Library ---

class PublicationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    publication_id: str
    doi: Optional[str]
    title: str
    normalized_title: str
    authors: List[str]
    year: Optional[int]
    venue: Optional[str]
    doc_type: str
    abstract: str
    keywords: List[str]
    url: str
    raw_bibtex_key: str
    citation_count: int
    created_at: str
    updated_at: str
    revision: int
    reading_status: ReadingStatus
    added_at: str
    collections: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)


class UpdateReadingStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reading_status: ReadingStatus
    expected_revision: Optional[int] = None
    idempotency_key: Optional[str] = None


# --- Annotations (Notes & Evidence) ---

class AnnotationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    publication_id: str
    kind: AnnotationKind
    body: str = Field(min_length=1, max_length=20000)
    source_kind: SourceKind
    source_url: Optional[str] = None
    locator: Optional[str] = None
    question_id: Optional[str] = None
    actor_label: str = Field(default="")
    idempotency_key: Optional[str] = None

    @model_validator(mode="after")
    def validate_rules(self) -> "AnnotationCreate":
        # NOTE: source_kind = NONE; locator and source_url may be null
        if self.kind == AnnotationKind.NOTE:
            if self.source_kind != SourceKind.NONE:
                raise ValueError("NOTE annotation must have source_kind = 'NONE'")
        elif self.kind in (AnnotationKind.QUOTE, AnnotationKind.PARAPHRASE):
            # QUOTE/PARAPHRASE: source_kind must be ABSTRACT or FULLTEXT
            if self.source_kind not in (SourceKind.ABSTRACT, SourceKind.FULLTEXT):
                raise ValueError(f"{self.kind.value} annotation must have source_kind 'ABSTRACT' or 'FULLTEXT'")
            if self.source_kind == SourceKind.FULLTEXT:
                if not self.locator or not self.locator.strip():
                    raise ValueError("FULLTEXT evidence requires a non-empty locator (1-200 chars)")
                if len(self.locator.strip()) > 200:
                    raise ValueError("FULLTEXT locator exceeds 200 characters")
            elif self.source_kind == SourceKind.ABSTRACT:
                if self.locator is not None:
                    raise ValueError("ABSTRACT evidence cannot have a locator (must be null)")
        return self


class AnnotationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: Optional[str] = Field(default=None, min_length=1, max_length=20000)
    source_url: Optional[str] = None
    locator: Optional[str] = None
    question_id: Optional[str] = None
    expected_revision: int
    actor_label: str = Field(default="")
    idempotency_key: Optional[str] = None


class AnnotationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    annotation_id: str
    project_id: str
    publication_id: str
    kind: AnnotationKind
    body: str
    source_kind: SourceKind
    source_url: Optional[str]
    locator: Optional[str]
    question_id: Optional[str]
    actor_type: ActorType
    actor_label: str
    created_at: str
    updated_at: str
    revision: int
    provenance_badge: str


# --- Manual Merge ---

class MergePublicationsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    survivor_id: str
    absorbed_id: str
    idempotency_key: Optional[str] = None

    @model_validator(mode="after")
    def validate_different(self) -> "MergePublicationsRequest":
        if self.survivor_id == self.absorbed_id:
            raise ValueError("survivor_id and absorbed_id must be different publications")
        return self


class MergePublicationsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    survivor_id: str
    absorbed_id: str
    affected_projects: List[str]
    final_reading_status: ReadingStatus
    merged_at: str


# --- Search & Acquisition Runs ---

class StartSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database: str
    query: str
    search_mode: Optional[str] = "advanced"
    year_start: Optional[int] = None
    year_end: Optional[int] = None
    doc_types: Optional[List[str]] = None
    max_records: int = Field(default=50, ge=1, le=500)
    enrich_doi: bool = True
    idempotency_key: Optional[str] = None


class RunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    project_id: str
    kind: RunKind
    status: RunStatus
    request_json: Dict[str, Any]
    started_at: str
    finished_at: Optional[str]
    reported_total: Optional[int]
    observed_count: int
    unique_count: int
    stop_reason: Optional[str]


# --- Import Preview & Commit ---

class ImportPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_content: str  # text or base64 encoded text
    file_format: Literal["bib", "ris", "csv"]
    csv_mapping: Optional[Dict[str, str]] = None  # Column mapping if CSV
    idempotency_key: Optional[str] = None


class RowErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_index: int
    error_message: str
    raw_snippet: Optional[str] = None


class ImportPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: str
    file_hash: str
    total_parsed: int
    valid_count: int
    invalid_count: int
    row_errors: List[RowErrorDetail]
    preview_items: List[Dict[str, Any]]
    expires_at: str


class ImportCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: str
    file_hash: str
    idempotency_key: str


class ImportCommitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    imported_count: int
    rejected_count: int
    rejected_report: List[RowErrorDetail]


# --- Export ---

class ExportProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: ExportScope = ExportScope.ALL
    collection_id: Optional[str] = None
    format: ExportFormat
    idempotency_key: Optional[str] = None

    @model_validator(mode="after")
    def validate_export(self) -> "ExportProjectRequest":
        if self.format == ExportFormat.PROJECT_JSON and self.scope != ExportScope.ALL:
            raise ValueError("PROJECT_JSON export requires scope = 'ALL'")
        if self.scope == ExportScope.COLLECTION and not self.collection_id:
            raise ValueError("COLLECTION export scope requires collection_id")
        return self


# --- Restore ---

class RestorePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_json_content: str
    idempotency_key: Optional[str] = None


class RestorePreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: str
    file_hash: str
    schema_version: int
    project_name: str
    counts: Dict[str, int]
    expires_at: str


class RestoreCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: str
    file_hash: str
    idempotency_key: str


class RestoreCommitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_project_id: str
    id_mapping: Dict[str, Dict[str, str]]  # entity_type -> {old_id: new_id}
    restored_at: str


# --- Events ---

class ResearchEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str
    project_id: str
    entity_type: str
    entity_id: str
    action: str
    actor_type: str
    actor_label: str
    before_json: Optional[Dict[str, Any]]
    after_json: Optional[Dict[str, Any]]
    created_at: str
