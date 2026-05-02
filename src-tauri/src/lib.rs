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
      start_sidecar(app.handle())?;
      Ok(())
    })
    .invoke_handler(tauri::generate_handler![get_api_base_url])
    .build(tauri::generate_context!())
    .expect("error while building tauri application")
    .run(|app_handle, event| {
      if let RunEvent::Exit = event {
        if let Ok(mut guard) = app_handle.state::<SidecarChild>().0.lock() {
          if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
          }
        }
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

fn start_sidecar(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
  let port = std::env::var("SHADOW_API_PORT").unwrap_or_else(|_| "8742".to_string());
  let root = project_root();
  let python = resolve_python(app);
  let mut cmd = std::process::Command::new(&python);
  cmd.arg("-m")
    .arg("uvicorn")
    .arg("backend.main:app")
    .arg("--host")
    .arg("127.0.0.1")
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

  log::info!("spawning sidecar: {:?} (cwd={:?})", python, root);
  let child = cmd.spawn()?;
  if let Some(state) = app.try_state::<SidecarChild>() {
    if let Ok(mut g) = state.0.lock() {
      *g = Some(child);
    }
  }

  let addr = format!("127.0.0.1:{}", port);
  for _ in 0..80 {
    if std::net::TcpStream::connect(&addr).is_ok() {
      log::info!("sidecar accepting TCP on {}", addr);
      return Ok(());
    }
    std::thread::sleep(Duration::from_millis(200));
  }
  log::warn!("sidecar TCP probe timed out");
  Ok(())
}

#[tauri::command]
fn get_api_base_url() -> String {
  let port = sidecar_api_port();
  format!("http://127.0.0.1:{}", port)
}
