use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Manager, RunEvent};

pub struct SidecarChild(pub Mutex<Option<std::process::Child>>);

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .manage(SidecarChild(Mutex::new(None)))
    .setup(|app| {
      if cfg!(debug_assertions) {
        let _ = app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        );
      }
      start_sidecar(app.handle()).map_err(|e| {
        log::error!("{e}");
        e
      })?;
      Ok(())
    })
    .invoke_handler(tauri::generate_handler![get_api_base_url, restart_sidecar])
    .build(tauri::generate_context!())
    .expect("error while building tauri application")
    .run(|app_handle, event| {
      if let RunEvent::Exit = event {
        let _ = stop_tracked_sidecar(app_handle);
      }
    });
}

fn project_root() -> std::path::PathBuf {
  std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
    .parent()
    .expect("invalid CARGO_MANIFEST_DIR")
    .to_path_buf()
}

fn sidecar_api_port() -> String {
  std::env::var("SHADOW_API_PORT")
    .or_else(|_| std::env::var("FRAUD_COPILOT_API_PORT"))
    .unwrap_or_else(|_| "8742".to_string())
}

fn resolve_python(app: &AppHandle) -> std::path::PathBuf {
  if let Ok(explicit) = std::env::var("SHADOW_DEV_PYTHON") {
    return std::path::PathBuf::from(explicit);
  }
  if let Ok(legacy) = std::env::var("FRAUD_COPILOT_DEV_PYTHON") {
    return std::path::PathBuf::from(legacy);
  }
  let root = project_root();
  let venv_py = root.join(".venv").join("bin").join("python3");
  if cfg!(debug_assertions) && venv_py.exists() {
    return venv_py;
  }
  if cfg!(debug_assertions) {
    return std::path::PathBuf::from("python3");
  }
  if let Ok(dir) = app.path().resource_dir() {
    let candidates = [
      dir.join("python").join("bin").join("python3"),
      dir.join("python").join("install").join("bin").join("python3"),
      dir.join("python").join("python.exe"),
    ];
    for c in candidates {
      if c.exists() {
        return c;
      }
    }
  }
  std::path::PathBuf::from("python3")
}

/// Dev builds listen on all interfaces so both `localhost` and `127.0.0.1` reach the API; release stays loopback-only.
fn uvicorn_bind_host() -> &'static str {
  if cfg!(debug_assertions) {
    "0.0.0.0"
  } else {
    "127.0.0.1"
  }
}

fn build_uvicorn_command(app: &AppHandle) -> std::process::Command {
  let port = std::env::var("SHADOW_API_PORT").unwrap_or_else(|_| "8742".to_string());
  let root = project_root();
  let python = resolve_python(app);
  let mut cmd = std::process::Command::new(&python);
  cmd.arg("-m")
    .arg("uvicorn")
    .arg("backend.main:app")
    .arg("--host")
    .arg(uvicorn_bind_host())
    .arg("--port")
    .arg(&port)
    .current_dir(&root);
  let mut path_var = std::env::var("PYTHONPATH").unwrap_or_default();
  if !path_var.is_empty() {
    path_var.push(std::path::MAIN_SEPARATOR);
  }
  path_var.push_str(root.to_string_lossy().as_ref());
  cmd.env("PYTHONPATH", path_var);
  cmd.env("SHADOW_API_PORT", &port);
  cmd
}

fn spawn_and_track_sidecar(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
  let mut cmd = build_uvicorn_command(app);
  let root = project_root();
  let python = resolve_python(app);
  log::info!(
    "spawning sidecar: {:?} (cwd={:?}) host={}",
    python,
    root,
    uvicorn_bind_host()
  );
  let mut child = cmd.spawn()?;
  std::thread::sleep(Duration::from_millis(450));
  if let Ok(Some(status)) = child.try_wait() {
    return Err(
      format!(
        "Python sidecar exited immediately (status: {status}). Confirm `.venv` exists and `PYTHONPATH` includes the repo root; from the repo run: `.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port {}`",
        sidecar_api_port()
      )
      .into(),
    );
  }
  if let Some(state) = app.try_state::<SidecarChild>() {
    if let Ok(mut g) = state.0.lock() {
      *g = Some(child);
    }
  }
  Ok(())
}

fn stop_tracked_sidecar(app: &AppHandle) -> Result<(), String> {
  let Some(state) = app.try_state::<SidecarChild>() else {
    return Err("Sidecar state not initialized.".into());
  };
  let mut g = state.0.lock().map_err(|_| "Sidecar mutex poisoned.".to_string())?;
  if let Some(mut child) = g.take() {
    let _ = child.kill();
    let _ = child.wait();
  }
  Ok(())
}

fn wait_sidecar_tcp(port: &str) -> bool {
  let addr = format!("127.0.0.1:{}", port);
  for _ in 0..80 {
    if std::net::TcpStream::connect(&addr).is_ok() {
      log::info!("sidecar accepting TCP on {}", addr);
      return true;
    }
    std::thread::sleep(Duration::from_millis(200));
  }
  log::warn!("sidecar TCP probe timed out");
  false
}

fn start_sidecar(app: &AppHandle) -> Result<(), String> {
  spawn_and_track_sidecar(app).map_err(|e| e.to_string())?;
  let port = sidecar_api_port();
  if !wait_sidecar_tcp(&port) {
    let _ = stop_tracked_sidecar(app);
    return Err(format!(
      "Python API did not become reachable on 127.0.0.1:{} within ~16s. \
Ensure port is free, `.venv` exists, and from the repo root: \
export PYTHONPATH=\"$(pwd)\" && .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port {}",
      port, port
    ));
  }
  Ok(())
}

/// Stop the tracked uvicorn child (if any), spawn a fresh one, and wait until TCP accepts on the API port.
#[tauri::command]
fn restart_sidecar(app: AppHandle) -> Result<String, String> {
  stop_tracked_sidecar(&app)?;
  std::thread::sleep(Duration::from_millis(500));
  spawn_and_track_sidecar(&app).map_err(|e| format!("Failed to spawn sidecar: {e}"))?;
  let port = sidecar_api_port();
  if !wait_sidecar_tcp(&port) {
    return Err(format!(
      "Python API did not become reachable on 127.0.0.1:{} within ~16s. Another process may be holding the port—quit it or change SHADOW_API_PORT.",
      port
    ));
  }
  Ok(format!("Python API restarted on 127.0.0.1:{}.", port))
}

#[tauri::command]
fn get_api_base_url() -> String {
  let port = sidecar_api_port();
  format!("http://127.0.0.1:{}", port)
}
