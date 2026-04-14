//! RadioMind Daemon — Rust storage core with Unix socket IPC.

mod hdc;
mod ipc;
mod storage;

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixListener;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

fn get_home() -> String {
    std::env::var("RADIOMIND_HOME").unwrap_or_else(|_| {
        let h = std::env::var("HOME").unwrap_or_else(|_| "/tmp".into());
        format!("{h}/.radiomind")
    })
}

fn main() {
    env_logger::init();

    let socket_path = std::env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(get_home()).join("radiomind.sock"));

    let db_path = PathBuf::from(get_home()).join("data").join("radiomind.db");

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

    // Signal handling: clean up socket on SIGTERM/SIGINT
    let running = Arc::new(AtomicBool::new(true));
    let r = running.clone();
    let sp = socket_path.clone();
    ctrlc::set_handler(move || {
        eprintln!("\nShutting down...");
        std::fs::remove_file(&sp).ok();
        r.store(false, Ordering::SeqCst);
        std::process::exit(0);
    })
    .expect("Failed to set signal handler");

    // Non-blocking listener so we can check the running flag
    listener
        .set_nonblocking(true)
        .expect("Failed to set non-blocking");

    eprintln!("radiomind-daemon listening on {}", socket_path.display());
    eprintln!("database: {}", db_path.display());

    while running.load(Ordering::SeqCst) {
        match listener.accept() {
            Ok((stream, _)) => {
                stream.set_nonblocking(false).ok();
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
            Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                std::thread::sleep(std::time::Duration::from_millis(50));
            }
            Err(e) => {
                eprintln!("Connection error: {e}");
            }
        }
    }

    std::fs::remove_file(&socket_path).ok();
}
