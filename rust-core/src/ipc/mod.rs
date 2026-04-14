use serde::{Deserialize, Serialize};
use crate::storage::database::{MemoryEntry, MemoryStore, SearchResult};
use crate::hdc;

#[derive(Debug, Deserialize)]
pub struct Request {
    pub id: u64,
    pub method: String,
    #[serde(default)]
    pub params: serde_json::Value,
}

#[derive(Debug, Serialize)]
pub struct Response {
    pub id: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

impl Response {
    pub fn ok(id: u64, result: serde_json::Value) -> Self {
        Self { id, result: Some(result), error: None }
    }
    pub fn err(id: u64, msg: String) -> Self {
        Self { id, result: None, error: Some(msg) }
    }
}

pub fn dispatch(
    req: &Request,
    store: &MemoryStore,
    codebook: &mut hdc::Codebook,
) -> Response {
    let r = match req.method.as_str() {
        "add" => do_add(req, store),
        "get" => do_get(req, store),
        "search" => do_search(req, store),
        "search_fts" => do_search_fts(req, store),
        "search_like" => do_search_like(req, store),
        "list_by_domain" => do_list_by_domain(req, store),
        "list_by_level" => do_list_by_level(req, store),
        "get_children" => do_get_children(req, store),
        "record_hit" => do_simple_id_op(req, store, |s, id| s.record_hit(id)),
        "increment_decay" => do_simple_id_op(req, store, |s, id| s.increment_decay(id)),
        "archive" => do_simple_id_op(req, store, |s, id| s.archive(id)),
        "add_triple" => do_add_triple(req, store),
        "query_entity" => do_query_entity(req, store),
        "stats" => Ok(serde_json::to_value(store.stats()).unwrap()),
        "hdc_similarity" => do_hdc_similarity(req, codebook),
        "ping" => Ok(serde_json::json!("pong")),
        _ => Err(format!("unknown method: {}", req.method)),
    };
    match r {
        Ok(val) => Response::ok(req.id, val),
        Err(msg) => Response::err(req.id, msg),
    }
}

type R = Result<serde_json::Value, String>;

fn p_str<'a>(params: &'a serde_json::Value, key: &str) -> &'a str {
    params.get(key).and_then(|v| v.as_str()).unwrap_or("")
}

fn p_i64(params: &serde_json::Value, key: &str) -> i64 {
    params.get(key).and_then(|v| v.as_i64()).unwrap_or(0)
}

fn p_usize(params: &serde_json::Value, key: &str, default: usize) -> usize {
    params.get(key).and_then(|v| v.as_u64()).unwrap_or(default as u64) as usize
}

fn do_add(req: &Request, store: &MemoryStore) -> R {
    let mut entry: MemoryEntry = serde_json::from_value(req.params.clone()).map_err(|e| e.to_string())?;
    let id = store.add(&mut entry).map_err(|e| e.to_string())?;
    Ok(serde_json::json!({"id": id}))
}

fn do_get(req: &Request, store: &MemoryStore) -> R {
    let id = p_i64(&req.params, "id");
    let entry = store.get(id).map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(entry).unwrap())
}

fn do_search(req: &Request, store: &MemoryStore) -> R {
    let query = p_str(&req.params, "query");
    let limit = p_usize(&req.params, "limit", 10);
    let domain = req.params.get("domain").and_then(|v| v.as_str());

    let mut results: Vec<SearchResult> = Vec::new();
    let mut seen = std::collections::HashSet::new();

    if let Ok(fts) = store.search_fts(query, limit * 2) {
        for r in fts {
            if let Some(id) = r.entry.id {
                let domain_match = domain.is_none() || r.entry.domain == domain.unwrap_or("");
                let privacy_ok = r.entry.privacy != "sealed" || domain.is_some();
                if domain_match && privacy_ok && seen.insert(id) {
                    results.push(r);
                }
            }
        }
    }
    if let Ok(like) = store.search_like(query, limit) {
        for r in like {
            if let Some(id) = r.entry.id {
                let domain_match = domain.is_none() || r.entry.domain == domain.unwrap_or("");
                let privacy_ok = r.entry.privacy != "sealed" || domain.is_some();
                if domain_match && privacy_ok && seen.insert(id) {
                    results.push(r);
                }
            }
        }
    }

    results.sort_by(|a, b| b.entry.level.cmp(&a.entry.level).then(b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal)));
    results.truncate(limit);

    for r in &results {
        if let Some(id) = r.entry.id {
            let _ = store.record_hit(id);
        }
    }

    Ok(serde_json::to_value(results).unwrap())
}

fn do_search_fts(req: &Request, store: &MemoryStore) -> R {
    let query = p_str(&req.params, "query");
    let limit = p_usize(&req.params, "limit", 10);
    let results = store.search_fts(query, limit).map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(results).unwrap())
}

fn do_search_like(req: &Request, store: &MemoryStore) -> R {
    let query = p_str(&req.params, "query");
    let limit = p_usize(&req.params, "limit", 10);
    let results = store.search_like(query, limit).map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(results).unwrap())
}

fn do_list_by_domain(req: &Request, store: &MemoryStore) -> R {
    let domain = p_str(&req.params, "domain");
    let level = req.params.get("level").and_then(|v| v.as_i64()).map(|l| l as i32);
    let limit = p_usize(&req.params, "limit", 50);
    let entries = store.list_by_domain(domain, level, limit).map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(entries).unwrap())
}

fn do_list_by_level(req: &Request, store: &MemoryStore) -> R {
    let level = p_i64(&req.params, "level") as i32;
    let limit = p_usize(&req.params, "limit", 50);
    let entries = store.list_by_level(level, limit).map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(entries).unwrap())
}

fn do_get_children(req: &Request, store: &MemoryStore) -> R {
    let parent_id = p_i64(&req.params, "parent_id");
    let entries = store.get_children(parent_id).map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(entries).unwrap())
}

fn do_simple_id_op(req: &Request, store: &MemoryStore, op: fn(&MemoryStore, i64) -> rusqlite::Result<()>) -> R {
    let id = p_i64(&req.params, "id");
    op(store, id).map_err(|e| e.to_string())?;
    Ok(serde_json::json!("ok"))
}

fn do_add_triple(req: &Request, store: &MemoryStore) -> R {
    let subject = p_str(&req.params, "subject");
    let relation = p_str(&req.params, "relation");
    let object = p_str(&req.params, "object");
    let id = store.add_triple(subject, relation, object, None).map_err(|e| e.to_string())?;
    Ok(serde_json::json!({"id": id}))
}

fn do_query_entity(req: &Request, store: &MemoryStore) -> R {
    let entity = p_str(&req.params, "entity");
    let triples = store.query_entity(entity).map_err(|e| e.to_string())?;
    Ok(serde_json::to_value(triples).unwrap())
}

fn do_hdc_similarity(req: &Request, codebook: &mut hdc::Codebook) -> R {
    let a = p_str(&req.params, "a");
    let b = p_str(&req.params, "b");
    let va = codebook.get(a).clone();
    let vb = codebook.get(b).clone();
    let sim = hdc::similarity(&va, &vb);
    Ok(serde_json::json!({"similarity": sim}))
}
