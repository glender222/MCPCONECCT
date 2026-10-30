//! HTTP Client for Block 2 Research REST API (/api/v2/research).
//! Provides thread-safe access with comprehensive error and connection handling.

use serde::{Deserialize, Serialize};

pub const BACKEND_URL: &str = "http://127.0.0.1:8765/api/v2/research";

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ProjectItem {
    #[serde(default)]
    pub project_id: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub research_type: String,
    #[serde(default)]
    pub archived: bool,
    #[serde(default)]
    pub revision: i64,
    #[serde(default)]
    pub created_at: String,
    #[serde(default)]
    pub updated_at: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct QuestionItem {
    pub question_id: Option<String>,
    pub text: String,
    #[serde(default)]
    pub position: i64,
    #[serde(default)]
    pub revision: i64,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ObjectiveItem {
    pub objective_id: Option<String>,
    pub text: String,
    #[serde(default)]
    pub position: i64,
    #[serde(default)]
    pub revision: i64,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct OutlineData {
    pub project_id: String,
    pub revision: i64,
    #[serde(default)]
    pub questions: Vec<QuestionItem>,
    #[serde(default)]
    pub objectives: Vec<ObjectiveItem>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct PublicationDetail {
    pub publication_id: String,
    pub doi: Option<String>,
    pub title: String,
    #[serde(default)]
    pub authors: Vec<String>,
    pub year: Option<i64>,
    pub venue: Option<String>,
    #[serde(default)]
    pub doc_type: String,
    #[serde(default)]
    pub abstract_text: String,
    #[serde(alias = "abstract", default)]
    pub abstract_alias: String,
    #[serde(default)]
    pub url: String,
    #[serde(default)]
    pub reading_status: String,
    #[serde(default)]
    pub added_at: String,
    #[serde(default)]
    pub collections: Vec<String>,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub sources: Vec<String>,
}

impl PublicationDetail {
    pub fn get_abstract(&self) -> &str {
        if !self.abstract_text.is_empty() {
            &self.abstract_text
        } else {
            &self.abstract_alias
        }
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct AnnotationItem {
    pub annotation_id: String,
    pub project_id: String,
    pub publication_id: String,
    pub kind: String,
    pub body: String,
    pub source_kind: String,
    pub source_url: Option<String>,
    pub locator: Option<String>,
    pub question_id: Option<String>,
    pub actor_type: String,
    pub actor_label: String,
    pub created_at: String,
    pub revision: i64,
    pub provenance_badge: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct EventItem {
    pub event_id: String,
    pub project_id: String,
    pub entity_type: String,
    pub entity_id: String,
    pub action: String,
    pub actor_type: String,
    pub actor_label: String,
    pub created_at: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ImportPreviewData {
    pub preview_id: String,
    pub file_hash: String,
    pub total_parsed: i64,
    pub valid_count: i64,
    pub invalid_count: i64,
    pub expires_at: String,
}

pub struct ResearchClient;

impl ResearchClient {
    fn client() -> reqwest::blocking::Client {
        reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(15))
            .build()
            .unwrap_or_default()
    }

    pub fn list_projects() -> Result<Vec<ProjectItem>, String> {
        let url = format!("{}/projects?limit=100", BACKEND_URL);
        let resp = Self::client().get(&url).send().map_err(|e| format!("Servicio local no disponible: {}", e))?;
        if !resp.status().is_success() {
            return Err(format!("Error HTTP {}: {}", resp.status(), resp.text().unwrap_or_default()));
        }
        let data: serde_json::Value = resp.json().map_err(|e| format!("Error parseando proyectos: {}", e))?;
        let items: Vec<ProjectItem> = serde_json::from_value(data.get("items").cloned().unwrap_or_default())
            .map_err(|e| format!("Error deserializando: {}", e))?;
        Ok(items)
    }

    pub fn create_project(name: &str, description: &str, research_type: &str) -> Result<ProjectItem, String> {
        let url = format!("{}/projects", BACKEND_URL);
        let payload = serde_json::json!({
            "name": name,
            "description": description,
            "research_type": research_type,
            "idempotency_key": uuid::Uuid::new_v4().to_string(),
        });
        let resp = Self::client().post(&url).json(&payload).send().map_err(|e| format!("Servicio local no disponible: {}", e))?;
        if !resp.status().is_success() {
            return Err(format!("Error HTTP {}: {}", resp.status(), resp.text().unwrap_or_default()));
        }
        resp.json::<ProjectItem>().map_err(|e| format!("Error deserializando proyecto: {}", e))
    }

    pub fn update_project(project_id: &str, name: &str, description: &str, archived: Option<bool>, expected_rev: i64) -> Result<ProjectItem, String> {
        let url = format!("{}/projects/{}", BACKEND_URL, project_id);
        let mut map = serde_json::Map::new();
        map.insert("name".to_string(), serde_json::Value::String(name.to_string()));
        map.insert("description".to_string(), serde_json::Value::String(description.to_string()));
        map.insert("expected_revision".to_string(), serde_json::Value::Number(expected_rev.into()));
        map.insert("idempotency_key".to_string(), serde_json::Value::String(uuid::Uuid::new_v4().to_string()));
        if let Some(arch) = archived {
            map.insert("archived".to_string(), serde_json::Value::Bool(arch));
        }
        let payload = serde_json::Value::Object(map);
        let resp = Self::client().patch(&url).json(&payload).send().map_err(|e| format!("Servicio local no disponible: {}", e))?;
        if !resp.status().is_success() {
            return Err(format!("Error HTTP {}: {}", resp.status(), resp.text().unwrap_or_default()));
        }
        resp.json::<ProjectItem>().map_err(|e| format!("Error deserializando proyecto: {}", e))
    }

    pub fn get_outline(project_id: &str) -> Result<OutlineData, String> {
        let url = format!("{}/projects/{}/outline", BACKEND_URL, project_id);
        let resp = Self::client().get(&url).send().map_err(|e| format!("Servicio local no disponible: {}", e))?;
        if !resp.status().is_success() {
            return Err(format!("Error HTTP {}: {}", resp.status(), resp.text().unwrap_or_default()));
        }
        resp.json::<OutlineData>().map_err(|e| format!("Error deserializando esquema: {}", e))
    }

    pub fn set_outline(project_id: &str, expected_rev: i64, questions: Vec<QuestionItem>, objectives: Vec<ObjectiveItem>) -> Result<OutlineData, String> {
        let url = format!("{}/projects/{}/outline", BACKEND_URL, project_id);
        let payload = serde_json::json!({
            "expected_revision": expected_rev,
            "questions": questions,
            "objectives": objectives,
            "idempotency_key": uuid::Uuid::new_v4().to_string(),
        });
        let resp = Self::client().put(&url).json(&payload).send().map_err(|e| format!("Servicio local no disponible: {}", e))?;
        if !resp.status().is_success() {
            return Err(format!("Error HTTP {}: {}", resp.status(), resp.text().unwrap_or_default()));
        }
        resp.json::<OutlineData>().map_err(|e| format!("Error deserializando esquema: {}", e))
    }

    pub fn list_publications(project_id: &str, q: &str, reading_status: Option<&str>) -> Result<Vec<PublicationDetail>, String> {
        let mut url = format!("{}/projects/{}/publications?limit=100", BACKEND_URL, project_id);
        if !q.is_empty() {
            url.push_str(&format!("&q={}", urlencoding::encode(q)));
        }
        if let Some(rs) = reading_status {
            if !rs.is_empty() {
                url.push_str(&format!("&reading_status={}", rs));
            }
        }
        let resp = Self::client().get(&url).send().map_err(|e| format!("Servicio local no disponible: {}", e))?;
        if !resp.status().is_success() {
            return Err(format!("Error HTTP {}: {}", resp.status(), resp.text().unwrap_or_default()));
        }
        let data: serde_json::Value = resp.json().map_err(|e| format!("Error parseando publicaciones: {}", e))?;
        let items: Vec<PublicationDetail> = serde_json::from_value(data.get("items").cloned().unwrap_or_default())
            .map_err(|e| format!("Error deserializando publicaciones: {}", e))?;
        Ok(items)
    }

    pub fn update_reading_status(project_id: &str, publication_id: &str, new_status: &str) -> Result<(), String> {
        let url = format!("{}/projects/{}/publications/{}", BACKEND_URL, project_id, publication_id);
        let payload = serde_json::json!({
            "reading_status": new_status,
            "idempotency_key": uuid::Uuid::new_v4().to_string(),
        });
        let resp = Self::client().patch(&url).json(&payload).send().map_err(|e| format!("Servicio local no disponible: {}", e))?;
        if !resp.status().is_success() {
            return Err(format!("Error HTTP {}: {}", resp.status(), resp.text().unwrap_or_default()));
        }
        Ok(())
    }

    pub fn list_annotations(project_id: &str, publication_id: Option<&str>) -> Result<Vec<AnnotationItem>, String> {
        let mut url = format!("{}/projects/{}/annotations?limit=100", BACKEND_URL, project_id);
        if let Some(pid) = publication_id {
            if !pid.is_empty() {
                url.push_str(&format!("&publication_id={}", pid));
            }
        }
        let resp = Self::client().get(&url).send().map_err(|e| format!("Servicio local no disponible: {}", e))?;
        if !resp.status().is_success() {
            return Err(format!("Error HTTP {}: {}", resp.status(), resp.text().unwrap_or_default()));
        }
        let data: serde_json::Value = resp.json().map_err(|e| format!("Error parseando notas: {}", e))?;
        let items: Vec<AnnotationItem> = serde_json::from_value(data.get("items").cloned().unwrap_or_default())
            .map_err(|e| format!("Error deserializando notas: {}", e))?;
        Ok(items)
    }

    pub fn create_annotation(
        project_id: &str,
        publication_id: &str,
        kind: &str,
        body: &str,
        source_kind: &str,
        locator: Option<&str>,
        question_id: Option<&str>,
    ) -> Result<AnnotationItem, String> {
        let url = format!("{}/projects/{}/annotations", BACKEND_URL, project_id);
        let mut map = serde_json::Map::new();
        map.insert("publication_id".to_string(), serde_json::Value::String(publication_id.to_string()));
        map.insert("kind".to_string(), serde_json::Value::String(kind.to_string()));
        map.insert("body".to_string(), serde_json::Value::String(body.to_string()));
        map.insert("source_kind".to_string(), serde_json::Value::String(source_kind.to_string()));
        map.insert("idempotency_key".to_string(), serde_json::Value::String(uuid::Uuid::new_v4().to_string()));
        if let Some(loc) = locator {
            map.insert("locator".to_string(), serde_json::Value::String(loc.to_string()));
        }
        if let Some(qid) = question_id {
            map.insert("question_id".to_string(), serde_json::Value::String(qid.to_string()));
        }
        let payload = serde_json::Value::Object(map);
        let resp = Self::client().post(&url).json(&payload).send().map_err(|e| format!("Servicio local no disponible: {}", e))?;
        if !resp.status().is_success() {
            return Err(format!("Error HTTP {}: {}", resp.status(), resp.text().unwrap_or_default()));
        }
        resp.json::<AnnotationItem>().map_err(|e| format!("Error deserializando nota: {}", e))
    }

    pub fn list_events(project_id: &str) -> Result<Vec<EventItem>, String> {
        let url = format!("{}/projects/{}/events?limit=50", BACKEND_URL, project_id);
        let resp = Self::client().get(&url).send().map_err(|e| format!("Servicio local no disponible: {}", e))?;
        if !resp.status().is_success() {
            return Err(format!("Error HTTP {}: {}", resp.status(), resp.text().unwrap_or_default()));
        }
        let data: serde_json::Value = resp.json().map_err(|e| format!("Error parseando eventos: {}", e))?;
        let items: Vec<EventItem> = serde_json::from_value(data.get("items").cloned().unwrap_or_default())
            .map_err(|e| format!("Error deserializando eventos: {}", e))?;
        Ok(items)
    }

    pub fn preview_import(content: &str, format: &str) -> Result<ImportPreviewData, String> {
        let url = format!("{}/projects/any/imports/preview", BACKEND_URL);
        let payload = serde_json::json!({
            "file_content": content,
            "file_format": format,
        });
        let resp = Self::client().post(&url).json(&payload).send().map_err(|e| format!("Servicio local no disponible: {}", e))?;
        if !resp.status().is_success() {
            return Err(format!("Error HTTP {}: {}", resp.status(), resp.text().unwrap_or_default()));
        }
        resp.json::<ImportPreviewData>().map_err(|e| format!("Error parseando previsualización: {}", e))
    }

    pub fn commit_import(project_id: &str, preview_id: &str, file_hash: &str) -> Result<(), String> {
        let url = format!("{}/projects/{}/imports/commit", BACKEND_URL, project_id);
        let payload = serde_json::json!({
            "preview_id": preview_id,
            "file_hash": file_hash,
            "idempotency_key": uuid::Uuid::new_v4().to_string(),
        });
        let resp = Self::client().post(&url).json(&payload).send().map_err(|e| format!("Servicio local no disponible: {}", e))?;
        if !resp.status().is_success() {
            return Err(format!("Error HTTP {}: {}", resp.status(), resp.text().unwrap_or_default()));
        }
        Ok(())
    }

    pub fn export_project(project_id: &str, scope: &str, format: &str) -> Result<String, String> {
        let url = format!("{}/projects/{}/exports", BACKEND_URL, project_id);
        let payload = serde_json::json!({
            "scope": scope,
            "format": format,
        });
        let resp = Self::client().post(&url).json(&payload).send().map_err(|e| format!("Servicio local no disponible: {}", e))?;
        if !resp.status().is_success() {
            return Err(format!("Error HTTP {}: {}", resp.status(), resp.text().unwrap_or_default()));
        }
        let data: serde_json::Value = resp.json().map_err(|e| format!("Error: {}", e))?;
        Ok(data.get("content").and_then(|v| v.as_str()).unwrap_or("").to_string())
    }
}
