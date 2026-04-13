use rusqlite::{params, Connection, Result as SqlResult};
use serde::{Deserialize, Serialize};
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

const SCHEMA_VERSION: i32 = 2;

const SCHEMA_SQL: &str = "
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT '',
    timestamp REAL NOT NULL,
    level INTEGER NOT NULL DEFAULT 0,
    parent_id INTEGER REFERENCES memories(id),
    status TEXT NOT NULL DEFAULT 'active',
    privacy TEXT NOT NULL DEFAULT 'open',
    embedding BLOB,
    hit_count INTEGER NOT NULL DEFAULT 0,
    last_hit_at REAL NOT NULL DEFAULT 0,
    decay_count INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_3d ON memories(domain, level, timestamp);
CREATE INDEX IF NOT EXISTS idx_parent ON memories(parent_id);
CREATE INDEX IF NOT EXISTS idx_status ON memories(status);
CREATE INDEX IF NOT EXISTS idx_domain_level ON memories(domain, level);

CREATE TABLE IF NOT EXISTS domains (
    name TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    memory_count INTEGER NOT NULL DEFAULT 0
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(content, tokenize='unicode61');

CREATE TABLE IF NOT EXISTS triples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    relation TEXT NOT NULL,
    object TEXT NOT NULL,
    valid_from REAL,
    valid_until REAL,
    source_id INTEGER,
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_subject ON triples(subject);
CREATE INDEX IF NOT EXISTS idx_relation ON triples(relation);
CREATE INDEX IF NOT EXISTS idx_valid ON triples(valid_from, valid_until);
";

fn now() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs_f64()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryEntry {
    pub id: Option<i64>,
    pub content: String,
    pub domain: String,
    pub level: i32,
    pub parent_id: Option<i64>,
    pub status: String,
    pub privacy: String,
    pub embedding: Option<Vec<u8>>,
    pub hit_count: i32,
    pub last_hit_at: f64,
    pub decay_count: i32,
    pub created_at: f64,
    pub metadata: String,
}

impl Default for MemoryEntry {
    fn default() -> Self {
        Self {
            id: None,
            content: String::new(),
            domain: String::new(),
            level: 0,
            parent_id: None,
            status: "active".into(),
            privacy: "open".into(),
            embedding: None,
            hit_count: 0,
            last_hit_at: 0.0,
            decay_count: 0,
            created_at: now(),
            metadata: "{}".into(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchResult {
    pub entry: MemoryEntry,
    pub score: f64,
    pub method: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Triple {
    pub id: Option<i64>,
    pub subject: String,
    pub relation: String,
    pub object: String,
    pub valid_from: Option<f64>,
    pub valid_until: Option<f64>,
    pub source_id: Option<i64>,
    pub confidence: f64,
    pub created_at: f64,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Stats {
    pub total_active: i64,
    pub by_level: LevelCounts,
    pub archived: i64,
    pub domain_count: usize,
    pub triples: i64,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct LevelCounts {
    pub fact: i64,
    pub pattern: i64,
    pub principle: i64,
}

pub struct MemoryStore {
    conn: Connection,
}

impl MemoryStore {
    pub fn open(path: &Path) -> SqlResult<Self> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).ok();
        }
        let conn = Connection::open(path)?;
        conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;")?;
        conn.execute_batch(SCHEMA_SQL)?;

        let version: i32 = conn
            .query_row(
                "SELECT COALESCE(MAX(version), 0) FROM schema_version",
                [],
                |r| r.get(0),
            )
            .unwrap_or(0);

        if version == 0 {
            conn.execute("INSERT INTO schema_version VALUES (?1)", params![SCHEMA_VERSION])?;
        } else if version < SCHEMA_VERSION {
            conn.execute(
                "UPDATE schema_version SET version = ?1",
                params![SCHEMA_VERSION],
            )?;
        }

        Ok(Self { conn })
    }

    // --- CRUD ---

    pub fn exists(&self, content: &str, domain: &str) -> bool {
        self.conn
            .query_row(
                "SELECT 1 FROM memories WHERE content = ?1 AND domain = ?2 AND status = 'active' LIMIT 1",
                params![content, domain],
                |_| Ok(()),
            )
            .is_ok()
    }

    pub fn add(&self, entry: &mut MemoryEntry) -> SqlResult<i64> {
        if self.exists(&entry.content, &entry.domain) {
            return Ok(-1);
        }

        self.conn.execute(
            "INSERT INTO memories (content, domain, timestamp, level, parent_id, status, privacy, embedding, hit_count, last_hit_at, decay_count, created_at, metadata) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13)",
            params![
                entry.content, entry.domain, entry.created_at, entry.level,
                entry.parent_id, entry.status, entry.privacy, entry.embedding,
                entry.hit_count, entry.last_hit_at, entry.decay_count,
                entry.created_at, entry.metadata,
            ],
        )?;

        let row_id = self.conn.last_insert_rowid();
        self.conn.execute(
            "INSERT INTO memories_fts(rowid, content) VALUES (?1, ?2)",
            params![row_id, entry.content],
        )?;

        entry.id = Some(row_id);
        self.ensure_domain(&entry.domain)?;
        Ok(row_id)
    }

    pub fn get(&self, id: i64) -> SqlResult<Option<MemoryEntry>> {
        let mut stmt = self
            .conn
            .prepare("SELECT * FROM memories WHERE id = ?1")?;
        let mut rows = stmt.query_map(params![id], |r| self.row_to_entry(r))?;
        Ok(rows.next().transpose()?)
    }

    pub fn record_hit(&self, id: i64) -> SqlResult<()> {
        self.conn.execute(
            "UPDATE memories SET hit_count = hit_count + 1, last_hit_at = ?1 WHERE id = ?2",
            params![now(), id],
        )?;
        Ok(())
    }

    pub fn increment_decay(&self, id: i64) -> SqlResult<()> {
        self.conn.execute(
            "UPDATE memories SET decay_count = decay_count + 1 WHERE id = ?1",
            params![id],
        )?;
        Ok(())
    }

    pub fn archive(&self, id: i64) -> SqlResult<()> {
        self.conn.execute(
            "UPDATE memories SET status = 'archived' WHERE id = ?1",
            params![id],
        )?;
        Ok(())
    }

    // --- Search ---

    pub fn search_fts(&self, query: &str, limit: usize) -> SqlResult<Vec<SearchResult>> {
        let safe = sanitize_fts_query(query);
        if safe.is_empty() {
            return Ok(vec![]);
        }

        let mut stmt = self.conn.prepare(
            "SELECT m.*, rank FROM memories_fts JOIN memories m ON memories_fts.rowid = m.id WHERE memories_fts MATCH ?1 AND m.status = 'active' ORDER BY rank LIMIT ?2",
        )?;

        let results = stmt
            .query_map(params![safe, limit as i64], |r| {
                let entry = self.row_to_entry(r)?;
                let rank: f64 = r.get("rank")?;
                Ok(SearchResult {
                    entry,
                    score: -rank,
                    method: "fts".into(),
                })
            })?
            .filter_map(|r| r.ok())
            .collect();

        Ok(results)
    }

    pub fn search_like(&self, query: &str, limit: usize) -> SqlResult<Vec<SearchResult>> {
        let pattern = format!("%{query}%");
        let mut stmt = self.conn.prepare(
            "SELECT * FROM memories WHERE content LIKE ?1 AND status = 'active' ORDER BY timestamp DESC LIMIT ?2",
        )?;

        let results = stmt
            .query_map(params![pattern, limit as i64], |r| {
                let entry = self.row_to_entry(r)?;
                Ok(SearchResult {
                    entry,
                    score: 1.0,
                    method: "like".into(),
                })
            })?
            .filter_map(|r| r.ok())
            .collect();

        Ok(results)
    }

    pub fn list_by_domain(&self, domain: &str, level: Option<i32>, limit: usize) -> SqlResult<Vec<MemoryEntry>> {
        let entries = if let Some(lvl) = level {
            let mut stmt = self.conn.prepare(
                "SELECT * FROM memories WHERE domain=?1 AND level=?2 AND status='active' ORDER BY timestamp DESC LIMIT ?3",
            )?;
            stmt.query_map(params![domain, lvl, limit as i64], |r| self.row_to_entry(r))?
                .filter_map(|r| r.ok())
                .collect()
        } else {
            let mut stmt = self.conn.prepare(
                "SELECT * FROM memories WHERE domain=?1 AND status='active' ORDER BY level DESC, timestamp DESC LIMIT ?2",
            )?;
            stmt.query_map(params![domain, limit as i64], |r| self.row_to_entry(r))?
                .filter_map(|r| r.ok())
                .collect()
        };
        Ok(entries)
    }

    pub fn list_by_level(&self, level: i32, limit: usize) -> SqlResult<Vec<MemoryEntry>> {
        let mut stmt = self.conn.prepare(
            "SELECT * FROM memories WHERE level=?1 AND status='active' ORDER BY hit_count DESC, timestamp DESC LIMIT ?2",
        )?;
        let entries = stmt
            .query_map(params![level, limit as i64], |r| self.row_to_entry(r))?
            .filter_map(|r| r.ok())
            .collect();
        Ok(entries)
    }

    pub fn get_children(&self, parent_id: i64) -> SqlResult<Vec<MemoryEntry>> {
        let mut stmt = self.conn.prepare(
            "SELECT * FROM memories WHERE parent_id=?1 AND status='active' ORDER BY timestamp DESC",
        )?;
        let entries = stmt
            .query_map(params![parent_id], |r| self.row_to_entry(r))?
            .filter_map(|r| r.ok())
            .collect();
        Ok(entries)
    }

    pub fn count_by_domain_level(&self, domain: &str, level: i32) -> i64 {
        self.conn
            .query_row(
                "SELECT COUNT(*) FROM memories WHERE domain=?1 AND level=?2 AND status='active'",
                params![domain, level],
                |r| r.get(0),
            )
            .unwrap_or(0)
    }

    // --- Knowledge Graph ---

    pub fn add_triple(&self, subject: &str, relation: &str, object: &str, valid_from: Option<f64>) -> SqlResult<i64> {
        let t = now();
        let vf = valid_from.unwrap_or(t);

        let unique_relations = ["name_is", "works_at", "located_in", "currently_doing"];
        if unique_relations.contains(&relation) {
            self.conn.execute(
                "UPDATE triples SET valid_until = ?1 WHERE subject = ?2 AND relation = ?3 AND valid_until IS NULL",
                params![t, subject, relation],
            )?;
        }

        self.conn.execute(
            "INSERT INTO triples (subject, relation, object, valid_from, source_id, confidence, created_at) VALUES (?1,?2,?3,?4,NULL,1.0,?5)",
            params![subject, relation, object, vf, t],
        )?;
        Ok(self.conn.last_insert_rowid())
    }

    pub fn query_entity(&self, entity: &str) -> SqlResult<Vec<Triple>> {
        let mut stmt = self.conn.prepare(
            "SELECT * FROM triples WHERE subject = ?1 AND valid_until IS NULL ORDER BY created_at DESC",
        )?;
        let triples = stmt
            .query_map(params![entity], |r| row_to_triple(r))?
            .filter_map(|r| r.ok())
            .collect();
        Ok(triples)
    }

    pub fn triple_count(&self) -> i64 {
        self.conn
            .query_row("SELECT COUNT(*) FROM triples WHERE valid_until IS NULL", [], |r| r.get(0))
            .unwrap_or(0)
    }

    // --- Stats ---

    pub fn stats(&self) -> Stats {
        let total_active: i64 = self.conn
            .query_row("SELECT COUNT(*) FROM memories WHERE status='active'", [], |r| r.get(0))
            .unwrap_or(0);

        let count = |lvl: i32| -> i64 {
            self.conn
                .query_row("SELECT COUNT(*) FROM memories WHERE level=?1 AND status='active'", params![lvl], |r| r.get(0))
                .unwrap_or(0)
        };

        let archived: i64 = self.conn
            .query_row("SELECT COUNT(*) FROM memories WHERE status='archived'", [], |r| r.get(0))
            .unwrap_or(0);

        let domains: Vec<String> = {
            let mut stmt = self.conn.prepare("SELECT name FROM domains").unwrap();
            stmt.query_map([], |r| r.get(0)).unwrap().filter_map(|r| r.ok()).collect()
        };

        Stats {
            total_active,
            by_level: LevelCounts { fact: count(0), pattern: count(1), principle: count(2) },
            archived,
            domain_count: domains.len(),
            triples: self.triple_count(),
        }
    }

    // --- Domain ---

    fn ensure_domain(&self, domain: &str) -> SqlResult<()> {
        if domain.is_empty() { return Ok(()); }
        let exists: bool = self.conn
            .query_row("SELECT 1 FROM domains WHERE name = ?1", params![domain], |_| Ok(()))
            .is_ok();
        if !exists {
            self.conn.execute(
                "INSERT INTO domains (name, created_at, memory_count) VALUES (?1, ?2, 1)",
                params![domain, now()],
            )?;
        } else {
            self.conn.execute(
                "UPDATE domains SET memory_count = memory_count + 1 WHERE name = ?1",
                params![domain],
            )?;
        }
        Ok(())
    }

    // --- Internal ---

    fn row_to_entry(&self, r: &rusqlite::Row) -> SqlResult<MemoryEntry> {
        Ok(MemoryEntry {
            id: Some(r.get("id")?),
            content: r.get("content")?,
            domain: r.get("domain")?,
            level: r.get("level")?,
            parent_id: r.get("parent_id")?,
            status: r.get("status")?,
            privacy: r.get::<_, String>("privacy").unwrap_or_else(|_| "open".into()),
            embedding: r.get("embedding")?,
            hit_count: r.get("hit_count")?,
            last_hit_at: r.get("last_hit_at")?,
            decay_count: r.get("decay_count")?,
            created_at: r.get("created_at")?,
            metadata: r.get("metadata")?,
        })
    }
}

fn row_to_triple(r: &rusqlite::Row) -> SqlResult<Triple> {
    Ok(Triple {
        id: Some(r.get("id")?),
        subject: r.get("subject")?,
        relation: r.get("relation")?,
        object: r.get("object")?,
        valid_from: r.get("valid_from")?,
        valid_until: r.get("valid_until")?,
        source_id: r.get("source_id")?,
        confidence: r.get("confidence")?,
        created_at: r.get("created_at")?,
    })
}

fn sanitize_fts_query(query: &str) -> String {
    query
        .split_whitespace()
        .map(|token| {
            let cleaned: String = token.chars().filter(|c| c.is_alphanumeric() || *c > '\u{4e00}').collect();
            if cleaned.is_empty() { String::new() } else if cleaned.contains(' ') { format!("\"{}\"", cleaned) } else { cleaned }
        })
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}
