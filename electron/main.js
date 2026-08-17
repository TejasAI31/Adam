const { app, BrowserWindow, ipcMain, Tray, Menu, nativeImage, safeStorage } = require('electron');
let tray = null;
const path = require('path');
const child_process = require('child_process');
const fs = require('fs');
const http = require('http');
const net = require('net');

let pythonProcess = null;
let currentWindow = null;
let isAppQuitting = false;
let pythonRestartAttempts = 0;
let pythonRestartTimer = null;
let pythonSuccessTimeout = null;

// Determine paths
const workspaceRoot = path.join(__dirname, '..');
const backendDir = path.join(workspaceRoot, 'backend');

let pythonExec = path.join(backendDir, 'env', 'Scripts', 'python.exe');
let pythonArgs = ['-m', 'src.api_server'];

// Dynamic path overrides for packaged app
if (app.isPackaged) {
  const compiledExe = path.join(backendDir, 'dist', 'api_server', 'api_server.exe');
  const packagedExe = path.join(workspaceRoot, 'backend', 'api_server.exe');
  const standaloneExe = path.join(workspaceRoot, 'api_server.exe');

  if (fs.existsSync(compiledExe)) {
    pythonExec = compiledExe;
    pythonArgs = [];
  } else if (fs.existsSync(packagedExe)) {
    pythonExec = packagedExe;
    pythonArgs = [];
  } else if (fs.existsSync(standaloneExe)) {
    pythonExec = standaloneExe;
    pythonArgs = [];
  }
}

function killProcessOnPort(port) {
  try {
    const { execSync } = child_process;
    if (process.platform === 'win32') {
      const output = execSync(`netstat -ano | findstr :${port}`, { encoding: 'utf8' });
      const lines = output.split('\n');
      const pids = new Set();
      for (const line of lines) {
        const parts = line.trim().split(/\s+/);
        if (parts.length >= 5) {
          const localAddr = parts[1];
          const portMatch = localAddr.match(/:(\d+)$/);
          if (portMatch && parseInt(portMatch[1], 10) === port) {
            const pid = parseInt(parts[parts.length - 1], 10);
            if (pid > 0) {
              pids.add(pid);
            }
          }
        }
      }
      for (const pid of pids) {
        if (pid === process.pid) continue;
        console.log(`[Electron Main] Killing stale process ${pid} on port ${port}...`);
        try {
          execSync(`taskkill /F /PID ${pid}`);
        } catch (e) {
          console.warn(`[Electron Main] Failed to kill process ${pid}: ${e.message}`);
        }
      }
    } else {
      console.log(`[Electron Main] Killing process on port ${port} (Unix)...`);
      try {
        execSync(`lsof -t -i:${port} | xargs kill -9`);
      } catch (e) {
        // ignore
      }
    }
  } catch (err) {
    // netstat exits with 1 if no process found, which is normal
  }
}

function isValidPythonHome(dir) {
  if (!dir || !fs.existsSync(dir)) return false;
  if (dir.toLowerCase().includes('windowsapps')) return false;
  if (!fs.existsSync(path.join(dir, 'python.exe'))) return false;
  return true;
}

function findSystemPython() {
  if (process.platform === 'win32') {
    const pathEnv = process.env.PATH || '';
    const paths = pathEnv.split(path.delimiter);
    for (const p of paths) {
      const fullPath = path.join(p, 'python.exe');
      if (p.toLowerCase().includes('windowsapps')) continue;
      try {
        if (fs.existsSync(fullPath)) {
          return fullPath;
        }
      } catch (e) {}
    }
  }
  return '';
}

function fixPyvenvCfg() {
  const cfgPath = path.join(backendDir, 'env', 'pyvenv.cfg');
  if (!fs.existsSync(cfgPath)) return;

  try {
    let cfgContent = fs.readFileSync(cfgPath, 'utf8');
    let homeLine = cfgContent.split('\n').find(line => line.trim().startsWith('home ='));
    if (!homeLine) return;

    let homePath = homeLine.split('=')[1].trim();
    // If the configured home path is not a valid Python installation, we need to fix it
    if (!isValidPythonHome(homePath)) {
      console.log(`[Electron Main] Virtualenv home path "${homePath}" is invalid or missing python.exe. Attempting to fix...`);
      
      let systemPythonPath = findSystemPython();

      if (!systemPythonPath) {
        // Fallback checks for common python install paths
        const userProfile = process.env.USERPROFILE || '';
        const commonDirs = [
          path.join(userProfile, 'AppData', 'Local', 'Programs', 'Python'),
          'C:\\Program Files\\Python',
          'C:\\Program Files\\Python311',
          'C:\\Program Files\\Python312'
        ];
        for (const base of commonDirs) {
          if (fs.existsSync(base)) {
            if (base.endsWith('Python')) {
              try {
                const versions = fs.readdirSync(base);
                for (const ver of versions) {
                  const verDir = path.join(base, ver);
                  if (fs.existsSync(path.join(verDir, 'python.exe'))) {
                    systemPythonPath = path.join(verDir, 'python.exe');
                    break;
                  }
                }
              } catch (err) {}
            } else if (fs.existsSync(path.join(base, 'python.exe'))) {
              systemPythonPath = path.join(base, 'python.exe');
              break;
            }
          }
          if (systemPythonPath) break;
        }
      }

      if (systemPythonPath && fs.existsSync(systemPythonPath)) {
        const pythonHome = path.dirname(systemPythonPath);
        console.log(`[Electron Main] Found system Python home: ${pythonHome}`);

        let lines = cfgContent.split('\n');
        lines = lines.map(line => {
          if (line.trim().startsWith('home =')) {
            return `home = ${pythonHome}`;
          }
          if (line.trim().startsWith('executable =')) {
            return `executable = ${path.join(pythonHome, 'python.exe')}`;
          }
          if (line.trim().startsWith('command =')) {
            return `command = ${path.join(pythonHome, 'python.exe')} -m venv ${path.join(backendDir, 'env')}`;
          }
          return line;
        });

        fs.writeFileSync(cfgPath, lines.join('\n'), 'utf8');
        console.log(`[Electron Main] Successfully updated pyvenv.cfg with local Python paths.`);
      } else {
        console.warn(`[Electron Main] Could not find a valid system Python to patch pyvenv.cfg.`);
      }
    }
  } catch (err) {
    console.error(`[Electron Main] Error fixing pyvenv.cfg: ${err.message}`);
  }
}

function startPythonBackend() {
  killProcessOnPort(8000);
  
  let activePython = pythonExec;
  let activeArgs = [...pythonArgs];
  
  // If running in development (uncompiled script mode), dynamically find system Python
  // to bypass virtualenv C launcher version/DLL mismatch crashes
  if (pythonArgs.length > 0) {
    fixPyvenvCfg();
    let systemPython = '';
    
    if (process.platform === 'win32') {
      systemPython = findSystemPython();
      
      if (!systemPython) {
        const userProfile = process.env.USERPROFILE || '';
        const commonDirs = [
          path.join(userProfile, 'AppData', 'Local', 'Programs', 'Python'),
          'C:\\Program Files\\Python',
          'C:\\Program Files\\Python311',
          'C:\\Program Files\\Python312'
        ];
        for (const base of commonDirs) {
          if (fs.existsSync(base)) {
            if (base.endsWith('Python')) {
              try {
                const versions = fs.readdirSync(base);
                for (const ver of versions) {
                  const verDir = path.join(base, ver);
                  if (fs.existsSync(path.join(verDir, 'python.exe'))) {
                    systemPython = path.join(verDir, 'python.exe');
                    break;
                  }
                }
              } catch (err) {}
            } else if (fs.existsSync(path.join(base, 'python.exe'))) {
              systemPython = path.join(base, 'python.exe');
              break;
            }
          }
          if (systemPython) break;
        }
      }
    }
    
    if (systemPython && fs.existsSync(systemPython)) {
      console.log(`[Electron Main] Using system Python wrapper to launch backend: ${systemPython}`);
      activePython = systemPython;
    }
  }

  console.log(`[Electron Main] Spawning Python Backend at: ${activePython} with args:`, activeArgs);
  
  const sitePackages = path.join(backendDir, 'env', 'Lib', 'site-packages');
  const pythonPath = process.env.PYTHONPATH 
    ? `${backendDir};${sitePackages};${process.env.PYTHONPATH}`
    : `${backendDir};${sitePackages}`;

  pythonProcess = child_process.spawn(activePython, activeArgs, {
    cwd: backendDir,
    env: { ...process.env, PYTHONPATH: pythonPath, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' }
  });

  pythonProcess.stdout.on('data', (data) => {
    const chunk = data.toString();
    console.log(`[Python Stdout]: ${chunk.trim()}`);
    if (chunk.includes("Uvicorn running on http://127.0.0.1:8000")) {
      triggerPushbulletNotification("Adam Python API server is running on http://127.0.0.1:8000.");
    }
  });

  pythonProcess.stderr.on('data', (data) => {
    console.error(`[Python Stderr]: ${data.toString().trim()}`);
  });

  if (pythonSuccessTimeout) clearTimeout(pythonSuccessTimeout);
  pythonSuccessTimeout = setTimeout(() => {
    if (pythonProcess) {
      console.log('[Electron Main] Python backend running stably. Resetting restart attempts.');
      pythonRestartAttempts = 0;
    }
  }, 10000);

  pythonProcess.on('close', (code) => {
    console.log(`[Electron Main] Python process exited with code ${code}`);
    pythonProcess = null;
    
    if (pythonSuccessTimeout) {
      clearTimeout(pythonSuccessTimeout);
      pythonSuccessTimeout = null;
    }
    
    if (!isAppQuitting) {
      pythonRestartAttempts++;
      const delay = Math.min(2000 * Math.pow(2, pythonRestartAttempts - 1), 30000);
      console.log(`[Electron Main] Python backend exited unexpectedly. Restarting in ${delay}ms (attempt ${pythonRestartAttempts})...`);
      triggerPushbulletNotification(`Adam Python API server exited unexpectedly. Restarting in ${delay}ms (attempt ${pythonRestartAttempts})...`);
      
      if (pythonRestartTimer) clearTimeout(pythonRestartTimer);
      pythonRestartTimer = setTimeout(() => {
        if (!isAppQuitting) {
          startPythonBackend();
        }
      }, delay);
    }
  });
}

function stopPythonBackend() {
  isAppQuitting = true;
  if (pythonProcess) {
    console.log('[Electron Main] Terminating Python process...');
    pythonProcess.kill();
    pythonProcess = null;
  }
}

// Window creation helper (Single window reuse)
let mainWindow = null;

function getOrCreateWindow(width, height, resizable = true) {
  if (mainWindow) {
    mainWindow.setResizable(true); // Allow resizing programmatically
    mainWindow.setSize(width, height);
    mainWindow.setResizable(resizable);
    mainWindow.center();
    return mainWindow;
  }

  mainWindow = new BrowserWindow({
    width,
    height,
    resizable,
    frame: false,
    transparent: true,
    hasShadow: false,
    icon: path.join(__dirname, 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  return mainWindow;
}

function navigateToSelection() {
  const win = getOrCreateWindow(720, 880, true);
  win.setMinimumSize(600, 600);
  win.loadFile(path.join(__dirname, 'renderer', 'selection.html'));
}

function navigateToSetup() {
  const win = getOrCreateWindow(680, 680, true);
  win.setMinimumSize(550, 500);
  win.loadFile(path.join(__dirname, 'renderer', 'setup.html'));
}

function navigateToMain() {
  const win = getOrCreateWindow(1200, 800, true);
  win.setMinimumSize(1000, 700);
  win.loadFile(path.join(__dirname, 'renderer', 'main.html'));
}

// IPC Receivers for window routing
ipcMain.on('navigate-to-setup', (event, data) => {
  navigateToSetup();
});

ipcMain.on('navigate-to-main', (event, data) => {
  navigateToMain();
});

ipcMain.on('navigate-to-selection', (event, data) => {
  navigateToSelection();
});

ipcMain.on('window-control', (event, command) => {
  if (!mainWindow) return;
  if (command === 'minimize') {
    mainWindow.minimize();
  } else if (command === 'maximize') {
    if (mainWindow.isMaximized()) {
      mainWindow.unmaximize();
    } else {
      mainWindow.maximize();
    }
  } else if (command === 'close') {
    mainWindow.close();
  } else if (command === 'silent') {
    mainWindow.hide(); // Hide completely to place in tray
  }
});

// --- WEB SHARING / TUNNEL LOGIC ---
app.setName('Adam');
const settingsDir = app.getPath('userData');
const settingsPath = path.join(settingsDir, 'settings.json');

// Migrate settings from old 'adam-desktop' folder to aligned 'Adam' folder if needed
const oldSettingsPath = path.join(app.getPath('appData'), 'adam-desktop', 'settings.json');
if (!fs.existsSync(settingsPath) && fs.existsSync(oldSettingsPath)) {
  try {
    fs.mkdirSync(settingsDir, { recursive: true });
    fs.copyFileSync(oldSettingsPath, settingsPath);
    console.log('[Electron Main] Migrated settings from adam-desktop to Adam successfully.');
  } catch (err) {
    console.error('Failed to migrate settings:', err);
  }
}

// Ensure settings directory exists
if (!fs.existsSync(settingsDir)) {
  try {
    fs.mkdirSync(settingsDir, { recursive: true });
  } catch (err) {
    console.error('Failed to create settings directory:', err);
  }
}

// Seed default settings if missing (fresh installation)
if (!fs.existsSync(settingsPath)) {
  const defaultSettings = {
    "llama": {
        "SERVER_HOST": "127.0.0.1",
        "SERVER_PORT": 8080,
        "context_size": 30000,
        "ngl": 99,
        "flash_attn": "on",
        "SERVER_TIMEOUT": 60,
        "MAIN_MODEL_FILE": "",
        "DRAFT_MODEL_FILE": null,
        "MMPROJ_MODEL_FILE": null,
        "spec_draft_n_max": 16,
        "cache_type_k": "q4_0",
        "cache_type_v": "q4_0",
        "draft_ngl": 99,
        "main_device": "gpu",
        "draft_device": "gpu",
        "mmproj_device": "gpu"
    },
    "audio": {
        "sample_rate": 16000,
        "frame_duration_ms": 30,
        "vad_aggressiveness": 2,
        "min_speech_duration": 0.8,
        "max_speech_duration": 12
    },
    "model": {
        "stt_model_size": "medium",
        "stt_device": "cuda",
        "tts_repo_id": "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
        "tts_device": "cuda",
        "max_history_len": 4,
        "max_tool_output_len": 3000,
        "max_estimated_tokens": 15000,
        "max_output_tokens": 10000,
        "stt_compute_type": "int8",
        "stt_batch_size": 1,
        "align_words": false,
        "llm_model_name": "",
        "stt_enabled": false,
        "tts_enabled": false,
        "tts_speaker": "Aiden"
    },
    "enabled_tools": {
        "evaluate_expression": true,
        "solve_quadratic": true,
        "calculate_statistics": true,
        "web_search": true,
        "ytm_search_and_get": true,
        "ytm_get_browse_context": true,
        "open_browser_urls": true,
        "take_screenshot": true,
        "scan_screen_elements": true,
        "click_element_by_name": true
    },
    "sharing": {
        "enabled": false,
        "service": "localhostrun",
        "ngrok_token": "",
        "ngrok_domain": "",
        "autostart": false,
        "email_enabled": false,
        "email_provider": "gmail",
        "email_host": "smtp.gmail.com",
        "email_port": 587,
        "email_user": "",
        "email_pass": "",
        "email_recipient": "",
        "email_on_startup": false,
        "remote_control_enabled": false,
        "pushbullet": {
            "enabled": false,
            "token_encrypted": ""
        }
    }
  };
  try {
    fs.writeFileSync(settingsPath, JSON.stringify(defaultSettings, null, 4), 'utf8');
  } catch (err) {
    console.error('Failed to write default settings.json:', err);
  }
}
let activeTunnel = null; // localtunnel instance
let activeTunnelProc = null; // ngrok child process
let tunnelUrl = null;
let tunnelStatus = 'offline'; // 'offline', 'starting', 'online', 'error'
let tunnelError = null;
let sharingEnabled = false;
let reconnectTimer = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 15;
let tunnelLifetimeTimer = null;

function startTunnelLifetimeLimit() {
  if (tunnelLifetimeTimer) {
    clearTimeout(tunnelLifetimeTimer);
  }
  const TWELVE_HOURS_MS = 12 * 60 * 60 * 1000;
  console.log('[Tunnel] Starting 12-hour lifetime limit...');
  tunnelLifetimeTimer = setTimeout(() => {
    console.log('[Tunnel] 12-hour limit reached. Closing tunnel...');
    stopTunnel();
  }, TWELVE_HOURS_MS);
}

const https = require('https');

function resolveDomainIP(domain) {
  return new Promise((resolve) => {
    // Query Google DoH by raw IP 8.8.8.8 to bypass local DNS resolution for the DNS server itself
    const url = `https://8.8.8.8/resolve?name=${encodeURIComponent(domain)}&type=A`;
    https.get(url, { rejectUnauthorized: false, timeout: 5000 }, (res) => {
      let data = '';
      res.on('data', (chunk) => {
        data += chunk;
      });
      res.on('end', () => {
        try {
          const parsed = JSON.parse(data);
          if (parsed.Answer && parsed.Answer.length > 0) {
            const ips = parsed.Answer.filter(ans => ans.type === 1).map(ans => ans.data.trim());
            if (ips.length > 0) {
              resolve(ips);
              return;
            }
          }
        } catch (e) {
          console.error(`[DNS Resolving ${domain}] JSON parse error:`, e);
        }
        resolve(null);
      });
    }).on('error', (err) => {
      console.error(`[DNS Resolving ${domain}] DoH error:`, err);
      resolve(null);
    });
  });
}

async function getSshHostForDomain(domain) {
  try {
    const ips = await resolveDomainIP(domain);
    if (ips && ips.length > 0) {
      // Cycle through resolved IPs using reconnectAttempts to distribute load and try different IPs
      const index = reconnectAttempts % ips.length;
      const selectedIp = ips[index];
      console.log(`[Electron Main] Using resolved IP (cycle ${index}/${ips.length}) for ${domain}: ${selectedIp}`);
      return selectedIp;
    }
  } catch (err) {
    console.warn(`[Electron Main] DoH resolution failed for ${domain}:`, err);
  }
  
  console.log(`[Electron Main] DoH resolution failed or empty. Falling back to domain directly: ${domain}`);
  return domain;
}

function encryptToken(plainText) {
  if (!plainText) return '';
  try {
    if (safeStorage.isEncryptionAvailable()) {
      return safeStorage.encryptString(plainText).toString('base64');
    }
  } catch (e) {
    console.error("Encryption failed:", e);
  }
  return Buffer.from(plainText).toString('base64');
}

function decryptToken(cipherText) {
  if (!cipherText) return '';
  try {
    if (safeStorage.isEncryptionAvailable()) {
      const buffer = Buffer.from(cipherText, 'base64');
      return safeStorage.decryptString(buffer);
    }
  } catch (e) {
    console.error("Decryption failed:", e);
  }
  return Buffer.from(cipherText, 'base64').toString('utf8');
}

function triggerPushbulletNotification(message) {
  try {
    if (!fs.existsSync(settingsPath)) return;
    const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
    const pb = settings.sharing && settings.sharing.pushbullet;
    if (!pb || !pb.enabled || !pb.token_encrypted) return;

    const token = decryptToken(pb.token_encrypted);
    if (!token) return;

    console.log("[Pushbullet] Sending status notification...");

    const payload = JSON.stringify({
      type: 'note',
      title: 'Adam System Status',
      body: message
    });

    const options = {
      hostname: 'api.pushbullet.com',
      port: 443,
      path: '/v2/pushes',
      method: 'POST',
      headers: {
        'Access-Token': token,
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(payload)
      }
    };

    const req = https.request(options, (res) => {
      let responseBody = '';
      res.on('data', (chunk) => { responseBody += chunk; });
      res.on('end', () => {
        if (res.statusCode === 200) {
          console.log("[Pushbullet] Notification sent successfully.");
        } else {
          console.error(`[Pushbullet] Failed to send notification. HTTP Status: ${res.statusCode}. Response: ${responseBody}`);
        }
      });
    });

    req.on('error', (err) => {
      console.error("[Pushbullet] Notification connection error:", err);
    });

    req.write(payload);
    req.end();
  } catch (err) {
    console.error("[Pushbullet] Error triggering notification:", err);
  }
}

function ensureSshKeys() {
  return new Promise((resolve) => {
    const userHome = process.env.USERPROFILE || process.env.HOME || '';
    const sshDir = path.join(userHome, '.ssh');
    const keyPath = path.join(sshDir, 'id_ed25519');
    
    if (!fs.existsSync(sshDir)) {
      try {
        fs.mkdirSync(sshDir, { recursive: true });
      } catch (e) {
        console.error("Failed to create .ssh folder:", e);
      }
    }
    
    // Check if any common key exists
    const keys = ['id_rsa', 'id_ed25519', 'id_dsa', 'id_ecdsa'];
    const keyExists = keys.some(k => fs.existsSync(path.join(sshDir, k)));
    
    if (keyExists) {
      console.log("[SSH] Keys already exist.");
      resolve(true);
      return;
    }
    
    console.log("[SSH] No SSH keys found. Generating a new Ed25519 key...");
    const keygen = child_process.spawn("ssh-keygen", [
      "-t", "ed25519",
      "-N", "",
      "-f", keyPath
    ]);
    
    keygen.on('close', (code) => {
      if (code === 0) {
        console.log("[SSH] Successfully generated new Ed25519 key.");
        resolve(true);
      } else {
        console.error(`[SSH] ssh-keygen exited with code ${code}`);
        resolve(false);
      }
    });
    
    keygen.on('error', (err) => {
      console.error("[SSH] Failed to run ssh-keygen:", err);
      resolve(false);
    });
  });
}

function triggerEmailNotification(url) {
  try {
    if (fs.existsSync(settingsPath)) {
      const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
      const config = settings.sharing;
      if (config && config.email_enabled) {
        console.log("[Email] Preparing email notification...");
        
        const payload = JSON.stringify({
          smtp_host: config.email_host,
          smtp_port: parseInt(config.email_port) || 587,
          smtp_user: config.email_user,
          smtp_pass: config.email_pass,
          recipient: config.email_recipient,
          subject: "Adam Assistant - Remote Web Access Online",
          body: `
            <h3>Your Adam Assistant Web Interface is Online</h3>
            <p>You can access the assistant remotely on your mobile phone or other devices using this link:</p>
            <p><a href="${url}" target="_blank" style="font-size: 16px; font-weight: bold; color: #0088cc;">${url}</a></p>
            <p>This link was generated dynamically at: ${new Date().toLocaleString()}</p>
          `
        });
        
        const reqOpts = {
          hostname: '127.0.0.1',
          port: 8000,
          path: '/api/share/email',
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Content-Length': Buffer.byteLength(payload)
          }
        };
        
        const req = http.request(reqOpts, (res) => {
          let body = '';
          res.on('data', (chunk) => body += chunk);
          res.on('end', () => {
            console.log(`[Email] Notification status: ${res.statusCode} - ${body}`);
          });
        });
        
        req.on('error', (err) => {
          console.error('[Email] Failed to send notification request:', err);
        });
        
        req.write(payload);
        req.end();
      }
    }
  } catch (e) {
    console.error("[Email] Error processing notification trigger:", e);
  }
}

function checkPortOpen(port) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    const onError = () => {
      socket.destroy();
      resolve(false);
    };
    socket.setTimeout(1000);
    socket.once('error', onError);
    socket.once('timeout', onError);
    socket.connect(port, '127.0.0.1', () => {
      socket.end();
      resolve(true);
    });
  });
}

async function waitForBackend(port, timeoutMs = 60000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const isOpen = await checkPortOpen(port);
    if (isOpen) return true;
    await new Promise(r => setTimeout(r, 1000));
  }
  return false;
}

async function startTunnel(config) {
  stopTunnelInternal(); // Ensure any existing processes are completely killed first
  sharingEnabled = true;
  tunnelStatus = 'starting';
  tunnelError = null;
  sendSharingStatus("Waiting for API server to become ready...");
  
  // Wait up to 60 seconds for port 8000 to be active
  const backendReady = await waitForBackend(8000, 60000);
  if (!backendReady) {
    tunnelStatus = 'error';
    tunnelError = 'Python API server not responding on port 8000. Tunnel aborted.';
    sendSharingStatus();
    return;
  }
  
  sendSharingStatus("Initializing tunnel client...");
  
  try {
    const service = config.service || 'ngrok';
    
    if (service === 'localhostrun') {
      sendSharingStatus("Checking SSH credentials...");
      await ensureSshKeys();
      
      sendSharingStatus("Resolving tunnel endpoints...");
      const sshHost = await getSshHostForDomain("localhost.run");
      
      sendSharingStatus("Connecting via localhost.run... (may take up to 10s)");
      
      const args = [
        "-T",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=NUL",
        "-o", "ServerAliveInterval=60",
        "-o", "ServerAliveCountMax=720",
        "-o", "ConnectTimeout=10",
        "-o", "ExitOnForwardFailure=yes",
        "-R", "80:127.0.0.1:8000",
        `nokey@${sshHost}`
      ];
      
      activeTunnelProc = child_process.spawn("ssh", args);
      
      let isConnecting = true;
      const timeoutId = setTimeout(() => {
        if (isConnecting) {
          isConnecting = false;
          tunnelStatus = 'error';
          tunnelError = 'Connection to localhost.run timed out. Verify your internet connection or try Ngrok instead.';
          sendSharingStatus();
          if (activeTunnelProc) {
            try { activeTunnelProc.kill(); } catch(e){}
            activeTunnelProc = null;
          }
        }
      }, 30000);

      let stdoutAccumulator = "";
      activeTunnelProc.stdout.on('data', (data) => {
        const chunk = data.toString();
        stdoutAccumulator += chunk;
        console.log(`[localhost.run STDOUT]: ${chunk.trim()}`);
        
        const match = stdoutAccumulator.match(/https:\/\/[a-zA-Z0-9-]+\.lhr\.life/);
        if (match && isConnecting) {
          clearTimeout(timeoutId);
          isConnecting = false;
          tunnelUrl = match[0];
          tunnelStatus = 'online';
          reconnectAttempts = 0; // Reset on success
          sendSharingStatus();
          triggerEmailNotification(tunnelUrl);
          startTunnelLifetimeLimit();
          triggerPushbulletNotification(`Adam Web Sharing is ONLINE!\nTunnel URL: ${tunnelUrl}`);
        }
      });
      
      activeTunnelProc.stderr.on('data', (data) => {
        const line = data.toString();
        console.log(`[localhost.run STDERR]: ${line.trim()}`);
        if (line.includes("Could not resolve") || line.includes("Permission denied") || line.includes("Connection refused")) {
          if (isConnecting) {
            clearTimeout(timeoutId);
            isConnecting = false;
            tunnelStatus = 'error';
            tunnelError = line.trim();
            sendSharingStatus();
          }
        }
      });
      
      activeTunnelProc.on('close', (code) => {
        console.log(`[localhost.run] Process exited with code ${code}`);
        clearTimeout(timeoutId);
        isConnecting = false;
        activeTunnelProc = null;
        tunnelUrl = null;
        
        if (sharingEnabled) {
          tunnelStatus = 'starting';
          sendSharingStatus(`Tunnel disconnected. Reconnecting (attempt ${reconnectAttempts + 1})...`);
          triggerPushbulletNotification(`Adam Web Sharing tunnel disconnected. Attempting automatic reconnection (attempt ${reconnectAttempts + 1})...`);
          
          reconnectAttempts++;
          const backoffDelay = Math.min(5000 * Math.pow(2, reconnectAttempts - 1), 60000);
          reconnectTimer = setTimeout(() => {
            console.log(`[Tunnel] Attempting reconnect ${reconnectAttempts} after ${backoffDelay}ms...`);
            try {
              if (fs.existsSync(settingsPath)) {
                const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
                startTunnel(settings.sharing);
              } else {
                startTunnel(config);
              }
            } catch (err) {
              startTunnel(config);
            }
          }, backoffDelay);
        } else {
          if (tunnelStatus !== 'error') {
            tunnelStatus = 'offline';
          }
          sendSharingStatus();
        }
      });
      
      activeTunnelProc.on('error', (err) => {
        console.error('[localhost.run] Process error:', err);
        clearTimeout(timeoutId);
        isConnecting = false;
        activeTunnelProc = null;
        tunnelUrl = null;
        tunnelStatus = 'error';
        tunnelError = err.message || err.toString();
        sendSharingStatus();
      });
      
    } else if (service === 'ngrok') {
      if (!config.ngrok_token || !config.ngrok_token.trim()) {
        throw new Error("Ngrok Authtoken is required.");
      }
      if (!config.ngrok_domain || !config.ngrok_domain.trim()) {
        throw new Error("Ngrok Static Domain is required.");
      }
      
      sendSharingStatus("Starting Ngrok tunnel client...");
      
      const ngrokArgs = [
        "ngrok", "http", "8000",
        "--authtoken", config.ngrok_token.trim(),
        "--domain", config.ngrok_domain.trim()
      ];
      
      activeTunnelProc = child_process.spawn("npx", ngrokArgs, { shell: true });
      
      let isNgrokConnecting = true;
      
      const ngrokTimeout = setTimeout(() => {
        if (isNgrokConnecting) {
          isNgrokConnecting = false;
          tunnelUrl = `https://${config.ngrok_domain.trim()}`;
          tunnelStatus = 'online';
          reconnectAttempts = 0; // Reset on success
          sendSharingStatus();
          triggerEmailNotification(tunnelUrl);
          startTunnelLifetimeLimit();
          triggerPushbulletNotification(`Adam Web Sharing (Ngrok) is ONLINE!\nTunnel URL: ${tunnelUrl}`);
        }
      }, 3000);

      activeTunnelProc.stdout.on('data', (data) => {
        console.log(`[Ngrok STDOUT]: ${data.toString().trim()}`);
      });
      
      activeTunnelProc.stderr.on('data', (data) => {
        const line = data.toString();
        console.log(`[Ngrok STDERR]: ${line.trim()}`);
        if (line.includes("failed") || line.includes("Error") || line.includes("ERR_")) {
          clearTimeout(ngrokTimeout);
          isNgrokConnecting = false;
          tunnelStatus = 'error';
          tunnelError = line.trim();
          sendSharingStatus();
        }
      });
      
      activeTunnelProc.on('close', (code) => {
        console.log(`[Ngrok] Process exited with code ${code}`);
        clearTimeout(ngrokTimeout);
        activeTunnelProc = null;
        tunnelUrl = null;
        
        if (sharingEnabled) {
          tunnelStatus = 'starting';
          sendSharingStatus(`Tunnel disconnected. Reconnecting (attempt ${reconnectAttempts + 1})...`);
          triggerPushbulletNotification(`Adam Web Sharing (Ngrok) tunnel disconnected. Attempting automatic reconnection (attempt ${reconnectAttempts + 1})...`);
          
          reconnectAttempts++;
          const backoffDelay = Math.min(5000 * Math.pow(2, reconnectAttempts - 1), 60000);
          reconnectTimer = setTimeout(() => {
            console.log(`[Tunnel] Attempting reconnect ${reconnectAttempts} after ${backoffDelay}ms...`);
            try {
              if (fs.existsSync(settingsPath)) {
                const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
                startTunnel(settings.sharing);
              } else {
                startTunnel(config);
              }
            } catch (err) {
              startTunnel(config);
            }
          }, backoffDelay);
        } else {
          if (tunnelStatus !== 'error') {
            tunnelStatus = 'offline';
          }
          sendSharingStatus();
        }
      });
      
      activeTunnelProc.on('error', (err) => {
        console.error('[Ngrok] Process error:', err);
        clearTimeout(ngrokTimeout);
        activeTunnelProc = null;
        tunnelUrl = null;
        tunnelStatus = 'error';
        tunnelError = err.message || err.toString();
        sendSharingStatus();
      });
    }
  } catch (err) {
    console.error('[Tunnel] Failed to start:', err);
    activeTunnel = null;
    activeTunnelProc = null;
    tunnelUrl = null;
    tunnelStatus = 'error';
    tunnelError = err.message || err.toString();
    sendSharingStatus();
  }
}

function stopTunnelInternal() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (tunnelLifetimeTimer) {
    clearTimeout(tunnelLifetimeTimer);
    tunnelLifetimeTimer = null;
  }
  if (activeTunnel) {
    try { activeTunnel.close(); } catch(e){}
    activeTunnel = null;
  }
  if (activeTunnelProc) {
    try { activeTunnelProc.kill(); } catch(e){}
    activeTunnelProc = null;
  }
  tunnelUrl = null;
}

function stopTunnel() {
  sharingEnabled = false;
  reconnectAttempts = 0;
  stopTunnelInternal();
  tunnelStatus = 'offline';
  sendSharingStatus();
  triggerPushbulletNotification("Adam Web Sharing tunnel has been manually disabled.");
}

function sendSharingStatus(customProgressMsg = null) {
  if (mainWindow) {
    mainWindow.webContents.send('sharing-status-changed', {
      status: tunnelStatus,
      url: tunnelUrl,
      error: customProgressMsg || tunnelError
    });
  }
}

// IPC Invokes for Sharing Configuration
ipcMain.handle('get-sharing-config', async () => {
  try {
    if (fs.existsSync(settingsPath)) {
      const data = await fs.promises.readFile(settingsPath, 'utf8');
      const settings = JSON.parse(data);
      const sharing = settings.sharing || {};
      
      let pbToken = '';
      if (sharing.pushbullet && sharing.pushbullet.token_encrypted) {
        pbToken = '••••••••••••••••';
      }
      
      return {
        enabled: sharing.enabled || false,
        service: sharing.service || 'ngrok',
        cf_token: sharing.cf_token || '',
        ngrok_token: sharing.ngrok_token || '',
        ngrok_domain: sharing.ngrok_domain || '',
        autostart: sharing.autostart || false,
        email_enabled: sharing.email_enabled || false,
        email_provider: sharing.email_provider || 'gmail',
        email_host: sharing.email_host || '',
        email_port: sharing.email_port || 587,
        email_user: sharing.email_user || '',
        email_pass: sharing.email_pass || '',
        email_recipient: sharing.email_recipient || '',
        email_on_startup: sharing.email_on_startup || false,
        pushbullet_enabled: (sharing.pushbullet && sharing.pushbullet.enabled) || false,
        pushbullet_token: pbToken,
        remote_control_enabled: sharing.remote_control_enabled || false
      };
    }
  } catch (e) {
    console.error('Error reading sharing config:', e);
  }
  return { enabled: false, service: 'ngrok', cf_token: '', ngrok_token: '', ngrok_domain: '', autostart: false, email_enabled: false, email_provider: 'gmail', email_host: '', email_port: 587, email_user: '', email_pass: '', email_recipient: '', email_on_startup: false, pushbullet_enabled: false, pushbullet_token: '', remote_control_enabled: false };
});

ipcMain.handle('save-sharing-config', async (event, config) => {
  try {
    let settings = {};
    if (fs.existsSync(settingsPath)) {
      const data = await fs.promises.readFile(settingsPath, 'utf8');
      settings = JSON.parse(data);
    }
    
    const oldSharing = settings.sharing || {};
    const oldPb = oldSharing.pushbullet || {};
    let encryptedToken = oldPb.token_encrypted || '';
    
    if (config.pushbullet_token === '') {
      encryptedToken = '';
    } else if (config.pushbullet_token !== '••••••••••••••••') {
      encryptedToken = encryptToken(config.pushbullet_token);
    }
    
    const newSharing = {
      enabled: config.enabled,
      service: config.service,
      ngrok_token: config.ngrok_token,
      ngrok_domain: config.ngrok_domain,
      autostart: config.autostart,
      email_enabled: config.email_enabled,
      email_provider: config.email_provider,
      email_host: config.email_host,
      email_port: config.email_port,
      email_user: config.email_user,
      email_pass: config.email_pass,
      email_recipient: config.email_recipient,
      email_on_startup: config.email_on_startup,
      remote_control_enabled: config.remote_control_enabled || false,
      pushbullet: {
        enabled: config.pushbullet_enabled || false,
        token_encrypted: encryptedToken
      }
    };
    
    settings.sharing = newSharing;
    await fs.promises.writeFile(settingsPath, JSON.stringify(settings, null, 4), 'utf8');
    return { success: true };
  } catch (e) {
    console.error('Failed to save sharing config:', e);
    return { success: false, error: e.message };
  }
});

ipcMain.handle('toggle-sharing', async (event, enable, config = null) => {
  try {
    let tunnelConfig = config;
    if (fs.existsSync(settingsPath)) {
      const data = await fs.promises.readFile(settingsPath, 'utf8');
      const settings = JSON.parse(data);
      tunnelConfig = settings.sharing || {};
    }
    
    if (enable) {
      reconnectAttempts = 0;
      await startTunnel(tunnelConfig);
    } else {
      stopTunnel();
    }
    return { success: true };
  } catch (e) {
    console.error('Failed to toggle sharing:', e);
    return { success: false, error: e.message };
  }
});

ipcMain.handle('get-sharing-status', () => {
  return {
    status: tunnelStatus,
    url: tunnelUrl,
    error: tunnelError
  };
});

function createTray() {
  if (tray) return;
  // Load from the physical icon.png file we generated
  const iconPath = path.join(__dirname, 'icon.png');
  const icon = nativeImage.createFromPath(iconPath);
  tray = new Tray(icon);
  tray.setToolTip('Adam Assistant');
  
  const contextMenu = Menu.buildFromTemplate([
    { label: 'Active Mode', click: () => { if (mainWindow) { mainWindow.show(); mainWindow.focus(); } } },
    { label: 'Passive Mode', click: () => { if (mainWindow) { mainWindow.hide(); } } },
    { type: 'separator' },
    { label: 'Exit', click: () => { if (mainWindow) { mainWindow.close(); } } }
  ]);
  
  tray.setContextMenu(contextMenu);
  
  tray.on('click', () => {
    if (mainWindow) {
      if (mainWindow.isVisible()) {
        mainWindow.hide();
      } else {
        mainWindow.show();
        mainWindow.focus();
      }
    }
  });
}

// App lifecycle
app.whenReady().then(() => {
  startPythonBackend();
  createTray();
  navigateToSelection();

  // Autostart web sharing if enabled in configuration
  try {
    if (fs.existsSync(settingsPath)) {
      const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
      if (settings.sharing && ((settings.sharing.autostart && settings.sharing.enabled) || settings.sharing.email_on_startup)) {
        // Wait 5 seconds for backend to start, then start tunnel
        setTimeout(() => {
          reconnectAttempts = 0;
          startTunnel(settings.sharing);
        }, 5000);
      }
    }
  } catch (e) {
    console.error("Error auto-starting web sharing:", e);
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      navigateToSelection();
    }
  });
});

app.on('window-all-closed', () => {
  stopTunnel();
  stopPythonBackend();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('will-quit', () => {
  stopTunnel();
  stopPythonBackend();
});
