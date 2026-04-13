//! RadioMind Daemon — Rust storage core with Unix socket IPC.
//!
//! Listens on a Unix socket, handles JSON Lines requests from Python.
//! Provides: SQLite CRUD, FTS5 search, knowledge graph, HDC operations.

mod hdc;
mod ipc;
mod storage;

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixListener;
use std::path::PathBuf;

fn default_socket_path() -> PathBuf {
    let home = std::env::var("RADIOMIND_HOME")
        .unwrap_or_else(|_| {
            let h = std::env::var("HOME").unwrap_or_else(|_| "/tmp".into());
            format!("{h}/.radiomind")
        });
    PathBuf::from(home).join("radiomind.sock")
}

fn default_db_path() -> PathBuf {
    let home = std::env::var("RADIOMIND_HOME")
        .unwrap_or_else(|_| {
            let h = std::env::var("HOME").unwrap_or_else(|_| "/tmp".into());
            format!("{h}/.radiomind")
        });
    PathBuf::from(home).join("data").join("radiomind.db")
}

fn main() {
    env_logger::init();

    let socket_path = std::env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(default_socket_path);

    let db_path = default_db_path();

    if let Some(parent) = db_path.parent() {
        std::fs::create_dir_all(parent).ok();
    }

    let store = match storage::database::MemoryStore::open(&db_path) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("Failed to open database: {e}");
            std::process::exit(1);
        }
    };

    let mut codebook = hdc::Codebook::new(hdc::DEFAULT_DIM);

    if socket_path.exists() {
        std::fs::remove_file(&socket_path).ok();
    }
    if let Some(parent) = socket_path.parent() {
        std::fs::create_dir_all(parent).ok();
    }

    let listener = match UnixListener::bind(&socket_path) {
        Ok(l) => l,
        Err(e) => {
            eprintln!("Failed to bind socket {}: {e}", socket_path.display());
            std::process::exit(1);
        }
    };

    eprintln!("radiomind-daemon listening on {}", socket_path.display());
    eprintln!("database: {}", db_path.display());

    for stream in listener.incoming() {
        match stream {
            Ok(stream) => {
                let reader = BufReader::new(&stream);
                let mut writer = &stream;

                for line in reader.lines() {
                    let line = match line {
                        Ok(l) => l,
                        Err(_) => break,
                    };
                    if line.trim().is_empty() {
                        continue;
                    }

                    let response = match serde_json::from_str::<ipc::Request>(&line) {
                        Ok(req) => ipc::dispatch(&req, &store, &mut codebook),
                        Err(e) => ipc::Response::err(0, format!("parse error: {e}")),
                    };

                    let out = serde_json::to_string(&response).unwrap_or_default();
                    if writeln!(writer, "{out}").is_err() {
                        break;
                    }
                    if writer.flush().is_err() {
                        break;
                    }
                }
            }
            Err(e) => {
                eprintln!("Connection error: {e}");
            }
        }
    }

    std::fs::remove_file(&socket_path).ok();
}
