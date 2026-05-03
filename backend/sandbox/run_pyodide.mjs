import { loadPyodide } from 'pyodide'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

async function main() {
  const args = process.argv.slice(2)
  if (args.length < 2) {
    console.error('Usage: node run_pyodide.mjs <script_path> <dataset_path>')
    process.exit(1)
  }

  const scriptPath = args[0]
  const datasetPath = args[1]

  try {
    const pyodide = await loadPyodide()
    
    // Load packages we might need
    await pyodide.loadPackage('micropip')
    
    // Mount the dataset directory so Pyodide can read it
    if (datasetPath && datasetPath !== 'None' && datasetPath !== '') {
      const datasetDir = path.dirname(datasetPath)
      const mountDir = '/workspace_data'
      pyodide.FS.mkdirTree(mountDir)
      pyodide.FS.mount(pyodide.FS.filesystems.NODEFS, { root: datasetDir }, mountDir)
      
      // Tell Python where the dataset is in the virtual FS
      const filename = path.basename(datasetPath)
      pyodide.runPython(`
import os
os.environ['FRAUD_DATASET_PATH'] = '${mountDir}/${filename}'
      `)
    }

    const scriptBody = fs.readFileSync(scriptPath, 'utf-8')
    
    // Redirect stdout/stderr
    pyodide.setStdout({ batched: (msg) => console.log(msg) })
    pyodide.setStderr({ batched: (msg) => console.error(msg) })

    await pyodide.runPythonAsync(scriptBody)
    
    process.exit(0)
  } catch (e) {
    console.error(e)
    process.exit(1)
  }
}

main()
