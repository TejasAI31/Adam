const BACKEND_URL = (window.location.protocol === 'file:' || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') 
  ? 'http://127.0.0.1:8000' 
  : window.location.origin;

document.addEventListener('DOMContentLoaded', () => {
  if (typeof window.api === 'undefined') {
    document.body.classList.add('not-electron');
  }
  const backendLoader = document.getElementById('backend-loader');
  const mainContent = document.getElementById('main-content');
  
  const mainList = document.getElementById('main-located-list');
  const draftList = document.getElementById('draft-located-list');
  const mmprojList = document.getElementById('mmproj-located-list');
  
  const sttCard = document.getElementById('stt-service-card');
  const ttsCard = document.getElementById('tts-service-card');
  const sttEnabledCheckbox = document.getElementById('stt-enabled-checkbox');
  const ttsEnabledCheckbox = document.getElementById('tts-enabled-checkbox');
  const sttModelSizeSelect = document.getElementById('stt-model-size-select');
  
  const sttDeviceSwitch = document.getElementById('stt-device-switch');
  const ttsDeviceSwitch = document.getElementById('tts-device-switch');
  const sttDeviceLabel = document.getElementById('stt-device-label');
  const ttsDeviceLabel = document.getElementById('tts-device-label');
  
  const kvQuantSelect = document.getElementById('kv-quant-select');
  
  const ramBar = document.getElementById('ram-planner-bar');
  const vramBar = document.getElementById('vram-planner-bar');
  const ramUsageText = document.getElementById('ram-usage-text');
  const vramUsageText = document.getElementById('vram-usage-text');
  
  const btnProceed = document.getElementById('btn-proceed');

  // Memory states
  let systemResources = { ram: { total: 16.0, used: 4.0 }, vram: { total: 8.0, used: 0.0 } };
  let modelDatabase = { main: [], drafters: [], mmproj: [] };
  let sttDatabase = [];
  let ttsDatabase = [];
  let selectedConfig = {
    main_model: '',
    draft_model: null,
    mmproj_model: null,
    main_device: 'gpu',
    draft_device: 'gpu',
    mmproj_device: 'gpu',
    stt_device: 'gpu',
    tts_device: 'gpu',
    stt_enabled: true,
    tts_enabled: true,
    stt_model_size: 'medium',
    cache_type: 'q4_0'
  };

  // Poll server health until ready
  async function checkBackendOnline() {
    try {
      const response = await fetch(`${BACKEND_URL}/api/models`);
      if (response.ok) {
        const resStats = await fetch(`${BACKEND_URL}/api/resources`);
        if (resStats.ok) {
          const stats = await resStats.json();
          if (stats.models_loaded) {
            if (typeof window.api !== 'undefined' && window.api.navigateToMain) {
              window.api.navigateToMain();
            } else {
              window.location.href = 'main.html';
            }
            return;
          }
        }
        const data = await response.json();
        await fetchSystemResources();
        setupInterface(data);
      } else {
        setTimeout(checkBackendOnline, 200);
      }
    } catch (e) {
      setTimeout(checkBackendOnline, 200);
    }
  }

  async function fetchSystemResources() {
    try {
      const res = await fetch(`${BACKEND_URL}/api/resources`);
      if (res.ok) {
        const data = await res.json();
        systemResources.ram.total = data.ram.total || 16.0;
        systemResources.ram.used = data.ram.used || 4.0;
        systemResources.vram.total = data.vram.total || 0.0;
        systemResources.vram.used = data.vram.used || 0.0;
        
        // If system has no discrete GPU, force CPU routing
        if (systemResources.vram.total === 0) {
          selectedConfig.main_device = 'cpu';
          selectedConfig.draft_device = 'cpu';
          selectedConfig.mmproj_device = 'cpu';
          selectedConfig.stt_device = 'cpu';
          selectedConfig.tts_device = 'cpu';
        }
      }
    } catch (e) {
      console.warn("Could not load hardware statistics:", e);
    }
  }

  function getModelFamily(filename) {
    const name = filename.toLowerCase();
    if (name.includes('qwen3vl') || name.includes('qwen3-vl')) return 'qwen3vl';
    if (name.includes('qwen3.5')) return 'qwen3.5';
    if (name.includes('qwen')) return 'qwen';
    if (name.includes('llama')) return 'llama';
    if (name.includes('gemma')) return 'gemma';
    if (name.includes('phi')) return 'phi';
    if (name.includes('mistral')) return 'mistral';
    const match = filename.match(/^([a-zA-Z0-9]+)/);
    return match ? match[1].toLowerCase() : 'unknown';
  }

  function getModelFriendlyDescription(modelName) {
    const nameLower = modelName.toLowerCase();
    if (nameLower.includes('qwen3.5-4b')) {
      return "Highly intelligent assistant with deep general knowledge. Recommended for most systems.";
    }
    if (nameLower.includes('qwen3vl-2b')) {
      return "Lightweight vision assistant capable of reading and understanding uploaded images.";
    }
    if (nameLower.includes('qwen3.5-0.8b')) {
      return "Draft model. Enables speculative decoding to write text up to 2x faster.";
    }
    if (nameLower.includes('mmproj-qwen3.5-4b')) {
      return "Image vision processor required for the 4B main model to see images.";
    }
    if (nameLower.includes('mmproj-qwen3vl-2b')) {
      return "Image vision processor required for the 2B main model to see images.";
    }
    return "Custom supplementary pipeline model.";
  }

  function getModelSpecs(filename) {
    let quant = '';
    const qMatch = filename.match(/(q[0-9]_[a-zA-Z0-9_]+|f16|f32|q[0-9]_k_m|q[0-9]_k_s|q[0-9]_0|q[0-9]_1)/i);
    if (qMatch) {
      quant = qMatch[1].toUpperCase();
    } else if (filename.toLowerCase().includes('gguf')) {
      const parts = filename.split(/[-_]/);
      const qPart = parts.find(p => p.toLowerCase().startsWith('q') && p.length <= 6 && /\d/.test(p));
      if (qPart) quant = qPart.toUpperCase();
    }
    
    let arch = 'GGUF';
    const nameLower = filename.toLowerCase();
    if (nameLower.includes('qwen')) arch = 'Qwen';
    else if (nameLower.includes('llama')) arch = 'Llama';
    else if (nameLower.includes('gemma')) arch = 'Gemma';
    else if (nameLower.includes('phi')) arch = 'Phi';
    else if (nameLower.includes('mistral')) arch = 'Mistral';
    
    let cleanName = filename.replace(/\.gguf$/i, '')
                            .replace(new RegExp(`[-_]${quant}`, 'i'), '');
    
    return {
      quant: quant || 'Q4_0',
      arch: arch,
      cleanName: cleanName,
      description: getModelFriendlyDescription(filename)
    };
  }

  function setupInterface(data) {
    backendLoader.classList.add('hidden');
    mainContent.classList.remove('hidden');

    modelDatabase.main = data.models.main || [];
    modelDatabase.drafters = data.models.drafters || [];
    modelDatabase.mmproj = data.models.mmproj || [];

    sttDatabase = data.models.stt || [];
    ttsDatabase = data.models.tts || [];

    // Pre-populate selections from active model settings
    const active = data.selected;
    selectedConfig.main_model = active.main_model || '';
    selectedConfig.draft_model = active.draft_model || null;
    selectedConfig.mmproj_model = active.mmproj_model || null;

    // Render lists
    renderMainModels();
    renderDraftModels();
    renderVisionAdapters();
    renderSttTtsStatus();

    // Bind VRAM presets
    const presetCpu = document.getElementById('preset-cpu');
    const presetLow = document.getElementById('preset-low');
    const presetMedium = document.getElementById('preset-medium');
    const presetHigh = document.getElementById('preset-high');
    const suboptContainer = document.getElementById('vram-suboption-container');
    const btnPerf = document.getElementById('subopt-performance');
    const btnVers = document.getElementById('subopt-versatility');

    let activePreset = 'high';
    let activeSuboption = 'performance';

    const updatePresetButtonsUI = (selected) => {
      [presetCpu, presetLow, presetMedium, presetHigh].forEach(btn => {
        if (!btn) return;
        btn.style.borderColor = 'var(--border-translucent)';
        btn.style.background = 'rgba(0,0,0,0.3)';
        btn.style.boxShadow = 'none';
      });
      
      let activeBtn = null;
      if (selected === 'cpu') activeBtn = presetCpu;
      else if (selected === 'low') activeBtn = presetLow;
      else if (selected === 'medium') activeBtn = presetMedium;
      else if (selected === 'high') activeBtn = presetHigh;
      
      if (activeBtn) {
        activeBtn.style.borderColor = 'var(--accent-sky)';
        activeBtn.style.background = 'rgba(56, 189, 248, 0.1)';
        activeBtn.style.boxShadow = '0 0 10px rgba(56, 189, 248, 0.2)';
      }
      
      if (suboptContainer) {
        if (selected === 'medium' || selected === 'high') {
          suboptContainer.style.display = 'flex';
        } else {
          suboptContainer.style.display = 'none';
        }
      }
    };

    const updateVramSuboptionUI = (activeSub) => {
      if (btnPerf && btnVers) {
        if (activeSub === 'performance') {
          btnPerf.style.borderColor = 'var(--accent-sky)';
          btnPerf.style.background = 'rgba(56, 189, 248, 0.1)';
          btnPerf.style.color = 'var(--text-main)';
          btnPerf.style.fontWeight = '700';
          
          btnVers.style.borderColor = 'var(--border-translucent)';
          btnVers.style.background = 'rgba(0,0,0,0.3)';
          btnVers.style.color = 'var(--text-dim)';
          btnVers.style.fontWeight = '400';
        } else {
          btnVers.style.borderColor = 'var(--accent-sky)';
          btnVers.style.background = 'rgba(56, 189, 248, 0.1)';
          btnVers.style.color = 'var(--text-main)';
          btnVers.style.fontWeight = '700';
          
          btnPerf.style.borderColor = 'var(--border-translucent)';
          btnPerf.style.background = 'rgba(0,0,0,0.3)';
          btnPerf.style.color = 'var(--text-dim)';
          btnPerf.style.fontWeight = '400';
        }
      }
    };

    const applyPresetCombination = (preset, suboption) => {
      const hasGPU = systemResources.vram.total > 0;
      
      if (preset === 'cpu') {
        // CPU Only Performance Mode
        selectedConfig.main_model = "Qwen3VL-2B-Instruct-Q4_K_M.gguf";
        selectedConfig.draft_model = null;
        selectedConfig.mmproj_model = "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf";
        
        selectedConfig.main_device = "cpu";
        selectedConfig.draft_device = "cpu";
        selectedConfig.mmproj_device = "cpu";
        selectedConfig.stt_device = "cpu";
        selectedConfig.tts_device = "gpu"; // Qwen TTS has no CPU version, but it is disabled here
        
        selectedConfig.stt_enabled = true;
        selectedConfig.tts_enabled = false;
        selectedConfig.stt_model_size = "base";
        
        sttModelSizeSelect.value = "base";
        sttEnabledCheckbox.checked = true;
        ttsEnabledCheckbox.checked = false;
        
        toggleServiceCardState('stt', true);
        toggleServiceCardState('tts', false);
      }
      else if (preset === 'low') {
        // Low VRAM (4GB) Performance Mode
        selectedConfig.main_model = "Qwen3.5-4B-Q4_K_M.gguf";
        selectedConfig.draft_model = null;
        selectedConfig.mmproj_model = "mmproj-Qwen3.5-4B-BF16.gguf";
        
        selectedConfig.main_device = hasGPU ? "gpu" : "cpu";
        selectedConfig.draft_device = "cpu";
        selectedConfig.mmproj_device = hasGPU ? "gpu" : "cpu";
        selectedConfig.stt_device = "cpu"; // WhisperX Small -> CPU
        selectedConfig.tts_device = "gpu";
        
        selectedConfig.stt_enabled = true;
        selectedConfig.tts_enabled = false;
        selectedConfig.stt_model_size = "small";
        
        sttModelSizeSelect.value = "small";
        sttEnabledCheckbox.checked = true;
        ttsEnabledCheckbox.checked = false;
        
        toggleServiceCardState('stt', true);
        toggleServiceCardState('tts', false);
      }
      else if (preset === 'medium') {
        // Medium VRAM (6GB)
        selectedConfig.main_model = "Qwen3.5-4B-Q4_K_M.gguf";
        selectedConfig.mmproj_model = "mmproj-Qwen3.5-4B-BF16.gguf";
        
        selectedConfig.main_device = hasGPU ? "gpu" : "cpu";
        selectedConfig.mmproj_device = hasGPU ? "gpu" : "cpu";
        selectedConfig.stt_device = "cpu"; // WhisperX Small -> CPU
        selectedConfig.tts_device = "gpu";
        
        selectedConfig.stt_enabled = true;
        selectedConfig.stt_model_size = "small";
        sttModelSizeSelect.value = "small";
        sttEnabledCheckbox.checked = true;
        toggleServiceCardState('stt', true);
        
        if (suboption === 'performance') {
          selectedConfig.draft_model = "Qwen3.5-0.8B-Q4_K_M.gguf";
          selectedConfig.draft_device = hasGPU ? "gpu" : "cpu";
          selectedConfig.tts_enabled = false;
          ttsEnabledCheckbox.checked = false;
          toggleServiceCardState('tts', false);
        } else {
          // Versatility Mode
          selectedConfig.draft_model = null;
          selectedConfig.draft_device = "cpu";
          selectedConfig.tts_enabled = true;
          ttsEnabledCheckbox.checked = true;
          toggleServiceCardState('tts', true);
        }
      }
      else if (preset === 'high') {
        // High VRAM (8GB+)
        selectedConfig.main_model = "Qwen3.5-4B-Q4_K_M.gguf";
        selectedConfig.draft_model = "Qwen3.5-0.8B-Q4_K_M.gguf";
        selectedConfig.mmproj_model = "mmproj-Qwen3.5-4B-BF16.gguf";
        
        selectedConfig.main_device = hasGPU ? "gpu" : "cpu";
        selectedConfig.draft_device = hasGPU ? "gpu" : "cpu";
        selectedConfig.mmproj_device = hasGPU ? "gpu" : "cpu";
        selectedConfig.stt_device = hasGPU ? "gpu" : "cpu";
        selectedConfig.tts_device = "gpu";
        
        selectedConfig.stt_enabled = true;
        toggleServiceCardState('stt', true);
        sttEnabledCheckbox.checked = true;
        
        if (suboption === 'performance') {
          selectedConfig.stt_model_size = "medium";
          sttModelSizeSelect.value = "medium";
          selectedConfig.tts_enabled = false;
          ttsEnabledCheckbox.checked = false;
          toggleServiceCardState('tts', false);
        } else {
          // Versatility Mode
          selectedConfig.stt_model_size = "small";
          sttModelSizeSelect.value = "small";
          selectedConfig.tts_enabled = true;
          ttsEnabledCheckbox.checked = true;
          toggleServiceCardState('tts', true);
        }
      }
      
      // Update UI components
      renderMainModels();
      renderDraftModels();
      renderVisionAdapters();
      renderSttTtsStatus();
      updateServiceLabels();
      updateResourceMeters();
    };

    if (presetCpu) {
      presetCpu.addEventListener('click', () => {
        activePreset = 'cpu';
        updatePresetButtonsUI('cpu');
        applyPresetCombination(activePreset, activeSuboption);
      });
    }
    if (presetLow) {
      presetLow.addEventListener('click', () => {
        activePreset = 'low';
        updatePresetButtonsUI('low');
        applyPresetCombination(activePreset, activeSuboption);
      });
    }
    if (presetMedium) {
      presetMedium.addEventListener('click', () => {
        activePreset = 'medium';
        updatePresetButtonsUI('medium');
        applyPresetCombination(activePreset, activeSuboption);
      });
    }
    if (presetHigh) {
      presetHigh.addEventListener('click', () => {
        activePreset = 'high';
        updatePresetButtonsUI('high');
        applyPresetCombination(activePreset, activeSuboption);
      });
    }
    
    if (btnPerf) {
      btnPerf.addEventListener('click', () => {
        activeSuboption = 'performance';
        updateVramSuboptionUI('performance');
        applyPresetCombination(activePreset, activeSuboption);
      });
    }
    if (btnVers) {
      btnVers.addEventListener('click', () => {
        activeSuboption = 'versatility';
        updateVramSuboptionUI('versatility');
        applyPresetCombination(activePreset, activeSuboption);
      });
    }

    // Set initial active state visual styles
    updatePresetButtonsUI(activePreset);
    updateVramSuboptionUI(activeSuboption);
    applyPresetCombination(activePreset, activeSuboption);
    
    // Bind service pipelines (Whisper and TTS)
    sttEnabledCheckbox.addEventListener('change', () => {
      selectedConfig.stt_enabled = sttEnabledCheckbox.checked;
      toggleServiceCardState('stt', sttEnabledCheckbox.checked);
      updateResourceMeters();
    });

    ttsEnabledCheckbox.addEventListener('change', () => {
      selectedConfig.tts_enabled = ttsEnabledCheckbox.checked;
      toggleServiceCardState('tts', ttsEnabledCheckbox.checked);
      updateResourceMeters();
    });

    sttModelSizeSelect.addEventListener('change', () => {
      selectedConfig.stt_model_size = sttModelSizeSelect.value;
      renderSttTtsStatus();
      updateResourceMeters();
    });

    sttDeviceSwitch.addEventListener('change', () => {
      updateServiceLabels();
      updateResourceMeters();
    });
    
    ttsDeviceSwitch.addEventListener('change', () => {
      updateServiceLabels();
      updateResourceMeters();
    });

    kvQuantSelect.addEventListener('change', () => {
      selectedConfig.cache_type = kvQuantSelect.value;
    });

    // Load initial enable classes
    toggleServiceCardState('stt', sttEnabledCheckbox.checked);
    toggleServiceCardState('tts', ttsEnabledCheckbox.checked);
    updateServiceLabels();
    renderSttTtsStatus();
    updateResourceMeters();
  }

  function toggleServiceCardState(service, enabled) {
    const card = document.getElementById(`${service}-service-card`);
    const devSwitch = document.getElementById(`${service}-device-switch`);
    const sizeSelect = document.getElementById('stt-model-size-select');
    
    if (enabled) {
      if (card) card.classList.add('selected');
      if (devSwitch) devSwitch.disabled = (systemResources.vram.total === 0);
      if (service === 'stt' && sizeSelect) sizeSelect.disabled = false;
    } else {
      if (card) card.classList.remove('selected');
      if (devSwitch) devSwitch.disabled = true;
      if (service === 'stt' && sizeSelect) sizeSelect.disabled = true;
    }
  }

  function updateServiceLabels() {
    const sttSw = document.getElementById('stt-device-switch');
    const sttLbl = document.getElementById('stt-device-label');
    const ttsSw = document.getElementById('tts-device-switch');
    const ttsLbl = document.getElementById('tts-device-label');

    if (systemResources.vram.total === 0) {
      if (sttSw) { sttSw.checked = false; sttSw.disabled = true; }
      if (ttsSw) { ttsSw.checked = false; ttsSw.disabled = true; }
      selectedConfig.stt_device = 'cpu';
      selectedConfig.tts_device = 'cpu';
    }
    
    if (sttSw && sttLbl) {
      sttLbl.textContent = sttSw.checked ? 'GPU' : 'CPU';
      selectedConfig.stt_device = sttSw.checked ? 'gpu' : 'cpu';
    }
    if (ttsSw && ttsLbl) {
      ttsLbl.textContent = ttsSw.checked ? 'GPU' : 'CPU';
      selectedConfig.tts_device = ttsSw.checked ? 'gpu' : 'cpu';
    }
  }

  function renderSttTtsStatus() {
    // 1. STT Card Status
    const sttDownloadRight = document.getElementById('stt-download-right');
    if (sttDownloadRight) {
      const size = sttModelSizeSelect.value;
      const sttModel = sttDatabase.find(m => m.name === `whisperx:${size}`);
      if (sttModel && !sttModel.downloaded) {
        const safeId = `whisperx_${size}`;
        if (sttModel.partial === true) {
          sttDownloadRight.innerHTML = `
            <div id="download-container-${safeId}" style="display: flex; gap: 6px; align-items: center;">
              <button class="glow-btn download-btn resume-btn" data-model="whisperx:${size}" style="padding: 4px 8px; font-size: 11px; cursor: pointer; border-radius: 6px; display: inline-flex; align-items: center; gap: 4px; background: rgba(56, 189, 248, 0.15); border-color: rgba(56, 189, 248, 0.4); color: var(--accent-sky);">Resume</button>
              <button class="glow-btn restart-btn" data-model="whisperx:${size}" style="padding: 4px 8px; font-size: 11px; cursor: pointer; border-radius: 6px; display: inline-flex; align-items: center; gap: 4px; background: rgba(239, 68, 68, 0.1); border-color: rgba(239, 68, 68, 0.3); color: var(--accent-red, #ef4444);">Restart</button>
            </div>
          `;
          sttDownloadRight.querySelector('.restart-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            startDownload(`whisperx:${size}`, true);
          });
        } else {
          sttDownloadRight.innerHTML = `
            <div id="download-container-${safeId}">
              <button class="glow-btn download-btn" data-model="whisperx:${size}" style="padding: 4px 8px; font-size: 11px; cursor: pointer; border-radius: 4px;">Download</button>
            </div>
          `;
        }
        sttDownloadRight.querySelector('.download-btn').addEventListener('click', (e) => {
          e.stopPropagation();
          startDownload(`whisperx:${size}`, false);
        });
      } else {
        const hasGPU = systemResources.vram.total > 0;
        const deviceChecked = selectedConfig.stt_device === 'gpu' && hasGPU;
        sttDownloadRight.innerHTML = `
          <span class="device-toggle-label" id="stt-device-label">${deviceChecked ? 'GPU' : 'CPU'}</span>
          <label class="switch">
            <input type="checkbox" id="stt-device-switch" ${deviceChecked ? 'checked' : ''} ${(!hasGPU || !selectedConfig.stt_enabled) ? 'disabled' : ''} class="device-switch">
            <span class="slider"></span>
          </label>
        `;
        const sw = document.getElementById('stt-device-switch');
        const lbl = document.getElementById('stt-device-label');
        if (sw) {
          sw.addEventListener('change', () => {
            lbl.textContent = sw.checked ? 'GPU' : 'CPU';
            selectedConfig.stt_device = sw.checked ? 'gpu' : 'cpu';
            updateResourceMeters();
          });
        }
      }
    }

    // 2. TTS Card Status
    const ttsDownloadRight = document.getElementById('tts-download-right');
    if (ttsDownloadRight) {
      const ttsModel = ttsDatabase.find(m => m.name === `tts:qwen`);
      if (ttsModel && !ttsModel.downloaded) {
        const safeId = `tts_qwen`;
        if (ttsModel.partial === true) {
          ttsDownloadRight.innerHTML = `
            <div id="download-container-${safeId}" style="display: flex; gap: 6px; align-items: center;">
              <button class="glow-btn download-btn resume-btn" data-model="tts:qwen" style="padding: 4px 8px; font-size: 11px; cursor: pointer; border-radius: 6px; display: inline-flex; align-items: center; gap: 4px; background: rgba(56, 189, 248, 0.15); border-color: rgba(56, 189, 248, 0.4); color: var(--accent-sky);">Resume</button>
              <button class="glow-btn restart-btn" data-model="tts:qwen" style="padding: 4px 8px; font-size: 11px; cursor: pointer; border-radius: 6px; display: inline-flex; align-items: center; gap: 4px; background: rgba(239, 68, 68, 0.1); border-color: rgba(239, 68, 68, 0.3); color: var(--accent-red, #ef4444);">Restart</button>
            </div>
          `;
          ttsDownloadRight.querySelector('.restart-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            startDownload(`tts:qwen`, true);
          });
        } else {
          ttsDownloadRight.innerHTML = `
            <div id="download-container-${safeId}">
              <button class="glow-btn download-btn" data-model="tts:qwen" style="padding: 4px 8px; font-size: 11px; cursor: pointer; border-radius: 4px;">Download</button>
            </div>
          `;
        }
        ttsDownloadRight.querySelector('.download-btn').addEventListener('click', (e) => {
          e.stopPropagation();
          startDownload(`tts:qwen`, false);
        });
      } else {
        selectedConfig.tts_device = 'gpu';
        ttsDownloadRight.innerHTML = `
          <span class="badge badge-quant" style="background: rgba(56, 189, 248, 0.15); color: var(--accent-sky); font-weight: bold; border: 1px solid rgba(56, 189, 248, 0.3); padding: 4px 8px; border-radius: 4px;">GPU Only</span>
        `;
      }
    }
    restoreActiveDownloadsUI();
  }


  // CPU/GPU switches should only be available for selected models
  function updateDeviceSwitchStates() {
    // 1. Main Models
    document.querySelectorAll('#main-located-list .model-card').forEach(card => {
      const isSelected = card.classList.contains('selected');
      const devSwitch = card.querySelector('.device-switch');
      if (devSwitch) {
        devSwitch.disabled = !isSelected || (systemResources.vram.total === 0);
      }
    });

    // 2. Draft Models
    document.querySelectorAll('#draft-located-list .model-card').forEach(card => {
      const isSelected = card.classList.contains('selected');
      const devSwitch = card.querySelector('.device-switch');
      if (devSwitch) {
        devSwitch.disabled = !isSelected || (systemResources.vram.total === 0);
      }
    });

    // 3. Vision Adapters
    document.querySelectorAll('#mmproj-located-list .model-card').forEach(card => {
      const isSelected = card.classList.contains('selected');
      const devSwitch = card.querySelector('.device-switch');
      if (devSwitch) {
        devSwitch.disabled = !isSelected || (systemResources.vram.total === 0);
      }
    });
  }

  function renderMainModels() {
    mainList.innerHTML = '';
    if (modelDatabase.main.length === 0) {
      mainList.innerHTML = `<div style="color: var(--text-dim); font-size: 12px; font-style: italic;">No model files found in models/</div>`;
      return;
    }

    modelDatabase.main.forEach(model => {
      const card = document.createElement('div');
      const isSelected = model.name === selectedConfig.main_model;
      card.className = `model-card ${isSelected ? 'selected' : ''}`;
      card.id = `card-main-${model.name.replace(/\./g, '_')}`;
      
      const specs = getModelSpecs(model.name);
      const hasGPU = systemResources.vram.total > 0;
      const deviceChecked = isSelected ? (selectedConfig.main_device === 'gpu' && hasGPU) : hasGPU;
      
      let rightContent = '';
      if (model.downloaded === false) {
        const safeId = model.name.replace(/\./g, '_').replace(/:/g, '_');
        if (model.partial === true) {
          rightContent = `
            <div class="card-right" id="download-container-${safeId}" style="display: flex; gap: 6px; align-items: center;">
              <button class="glow-btn download-btn resume-btn" style="padding: 4px 8px; font-size: 11px; cursor: pointer; border-radius: 6px; display: inline-flex; align-items: center; gap: 4px; background: rgba(56, 189, 248, 0.15); border-color: rgba(56, 189, 248, 0.4); color: var(--accent-sky);">
                Resume
              </button>
              <button class="glow-btn restart-btn" style="padding: 4px 8px; font-size: 11px; cursor: pointer; border-radius: 6px; display: inline-flex; align-items: center; gap: 4px; background: rgba(239, 68, 68, 0.1); border-color: rgba(239, 68, 68, 0.3); color: var(--accent-red, #ef4444);">
                Restart
              </button>
            </div>
          `;
        } else {
          rightContent = `
            <div class="card-right" id="download-container-${safeId}">
              <button class="glow-btn download-btn" style="padding: 4px 10px; font-size: 11px; cursor: pointer; border-radius: 6px; display: inline-flex; align-items: center; gap: 4px;">
                <svg style="width: 11px; height: 11px;" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"></path>
                </svg>
                Download
              </button>
            </div>
          `;
        }
      } else {
        rightContent = `
          <div class="card-right">
            <span class="device-toggle-label">${deviceChecked ? 'GPU' : 'CPU'}</span>
            <label class="switch">
              <input type="checkbox" class="device-switch" ${deviceChecked ? 'checked' : ''} ${(!hasGPU || !isSelected) ? 'disabled' : ''}>
              <span class="slider"></span>
            </label>
          </div>
        `;
      }

      card.innerHTML = `
        <div class="card-left">
          <input type="radio" name="main-model-radio" class="card-checkbox" ${isSelected ? 'checked' : ''}>
          <div style="display: flex; flex-direction: column; gap: 2px;">
            <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
              <span class="card-name" title="${model.name}">${specs.cleanName}</span>
              <span class="badge badge-arch">${specs.arch}</span>
              <span class="badge badge-quant">${specs.quant}</span>
              <span class="badge badge-size">${model.size_gb.toFixed(2)} GB</span>
            </div>
            <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px; line-height: 1.3;">${specs.description}</div>
          </div>
        </div>
        ${rightContent}
      `;

      const radio = card.querySelector('.card-checkbox');
      const selectAction = () => {
        selectedConfig.main_model = model.name;
        document.querySelectorAll('#main-located-list .model-card').forEach(c => c.classList.remove('selected'));
        card.classList.add('selected');
        radio.checked = true;
        
        const devSwitch = card.querySelector('.device-switch');
        if (devSwitch) {
          selectedConfig.main_device = devSwitch.checked ? 'gpu' : 'cpu';
        }

        validateFamilyCompatibilities();
        updateDeviceSwitchStates();
        updateResourceMeters();
      };
      
      card.addEventListener('click', (e) => {
        if (e.target.closest('.switch') || e.target.closest('.device-switch') || e.target.closest('.download-btn') || e.target.closest('.restart-btn')) return;
        selectAction();
      });

      radio.addEventListener('click', (e) => {
        e.stopPropagation();
        selectAction();
      });

      const devSwitch = card.querySelector('.device-switch');
      const devLabel = card.querySelector('.device-toggle-label');
      if (devSwitch) {
        devSwitch.addEventListener('change', () => {
          devLabel.textContent = devSwitch.checked ? 'GPU' : 'CPU';
          if (card.classList.contains('selected')) {
            selectedConfig.main_device = devSwitch.checked ? 'gpu' : 'cpu';
          }
          updateResourceMeters();
        });
      }

      const downloadBtn = card.querySelector('.download-btn');
      if (downloadBtn) {
        downloadBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          startDownload(model.name, false);
        });
      }

      const restartBtn = card.querySelector('.restart-btn');
      if (restartBtn) {
        restartBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          startDownload(model.name, true);
        });
      }

      mainList.appendChild(card);
    });
    
    updateDeviceSwitchStates();
    restoreActiveDownloadsUI();
  }

  function renderDraftModels() {
    draftList.innerHTML = '';
    if (modelDatabase.drafters.length === 0) {
      draftList.innerHTML = `<div style="color: var(--text-dim); font-size: 12px; font-style: italic;">No draft model files found in models/drafters/</div>`;
      return;
    }

    modelDatabase.drafters.forEach(model => {
      const card = document.createElement('div');
      const isSelected = model.name === selectedConfig.draft_model;
      card.className = `model-card ${isSelected ? 'selected' : ''}`;
      card.id = `card-draft-${model.name.replace(/\./g, '_')}`;
      
      const specs = getModelSpecs(model.name);
      const hasGPU = systemResources.vram.total > 0;
      const deviceChecked = isSelected ? (selectedConfig.draft_device === 'gpu' && hasGPU) : hasGPU;
      
      let rightContent = '';
      if (model.downloaded === false) {
        const safeId = model.name.replace(/\./g, '_').replace(/:/g, '_');
        if (model.partial === true) {
          rightContent = `
            <div class="card-right" id="download-container-${safeId}" style="display: flex; gap: 6px; align-items: center;">
              <button class="glow-btn download-btn resume-btn" style="padding: 4px 8px; font-size: 11px; cursor: pointer; border-radius: 6px; display: inline-flex; align-items: center; gap: 4px; background: rgba(56, 189, 248, 0.15); border-color: rgba(56, 189, 248, 0.4); color: var(--accent-sky);">
                Resume
              </button>
              <button class="glow-btn restart-btn" style="padding: 4px 8px; font-size: 11px; cursor: pointer; border-radius: 6px; display: inline-flex; align-items: center; gap: 4px; background: rgba(239, 68, 68, 0.1); border-color: rgba(239, 68, 68, 0.3); color: var(--accent-red, #ef4444);">
                Restart
              </button>
            </div>
          `;
        } else {
          rightContent = `
            <div class="card-right" id="download-container-${safeId}">
              <button class="glow-btn download-btn" style="padding: 4px 10px; font-size: 11px; cursor: pointer; border-radius: 6px; display: inline-flex; align-items: center; gap: 4px;">
                <svg style="width: 11px; height: 11px;" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"></path>
                </svg>
                Download
              </button>
            </div>
          `;
        }
      } else {
        rightContent = `
          <div class="card-right">
            <span class="device-toggle-label">${deviceChecked ? 'GPU' : 'CPU'}</span>
            <label class="switch">
              <input type="checkbox" class="device-switch" ${deviceChecked ? 'checked' : ''} ${(!hasGPU || !isSelected) ? 'disabled' : ''}>
              <span class="slider"></span>
            </label>
          </div>
        `;
      }

      card.innerHTML = `
        <div class="card-left">
          <input type="checkbox" class="card-checkbox" ${isSelected ? 'checked' : ''}>
          <div style="display: flex; flex-direction: column; gap: 2px;">
            <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
              <span class="card-name" title="${model.name}">${specs.cleanName}</span>
              <span class="badge badge-arch">${specs.arch}</span>
              <span class="badge badge-quant">${specs.quant}</span>
              <span class="badge badge-size">${model.size_gb.toFixed(2)} GB</span>
            </div>
            <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px; line-height: 1.3;">${specs.description}</div>
            <span class="family-warning" style="display: none;"></span>
          </div>
        </div>
        ${rightContent}
      `;

      const checkbox = card.querySelector('.card-checkbox');
      
      const toggleAction = () => {
        if (card.classList.contains('disabled')) return;
        
        if (selectedConfig.draft_model === model.name) {
          // Deselect
          selectedConfig.draft_model = null;
          card.classList.remove('selected');
          checkbox.checked = false;
        } else {
          // Select
          // Uncheck all other draft models
          document.querySelectorAll('#draft-located-list .card-checkbox').forEach(cb => {
            if (cb !== checkbox) cb.checked = false;
          });
          document.querySelectorAll('#draft-located-list .model-card').forEach(c => {
            if (c !== card) c.classList.remove('selected');
          });
          
          selectedConfig.draft_model = model.name;
          card.classList.add('selected');
          checkbox.checked = true;
          
          const devSwitch = card.querySelector('.device-switch');
          if (devSwitch) {
            selectedConfig.draft_device = devSwitch.checked ? 'gpu' : 'cpu';
          }
        }
        
        updateDeviceSwitchStates();
        updateResourceMeters();
      };

      card.addEventListener('click', (e) => {
        if (e.target.closest('.switch') || e.target.closest('.device-switch') || e.target.closest('.download-btn') || e.target.closest('.restart-btn')) return;
        toggleAction();
      });

      checkbox.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleAction();
      });

      const devSwitch = card.querySelector('.device-switch');
      const devLabel = card.querySelector('.device-toggle-label');
      if (devSwitch) {
        devSwitch.addEventListener('change', () => {
          devLabel.textContent = devSwitch.checked ? 'GPU' : 'CPU';
          if (card.classList.contains('selected')) {
            selectedConfig.draft_device = devSwitch.checked ? 'gpu' : 'cpu';
          }
          updateResourceMeters();
        });
      }

      const downloadBtn = card.querySelector('.download-btn');
      if (downloadBtn) {
        downloadBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          startDownload(model.name, false);
        });
      }

      const restartBtn = card.querySelector('.restart-btn');
      if (restartBtn) {
        restartBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          startDownload(model.name, true);
        });
      }

      draftList.appendChild(card);
    });
    
    updateDeviceSwitchStates();
    restoreActiveDownloadsUI();
  }

  function renderVisionAdapters() {
    mmprojList.innerHTML = '';
    if (modelDatabase.mmproj.length === 0) {
      mmprojList.innerHTML = `<div style="color: var(--text-dim); font-size: 12px; font-style: italic;">No vision adapter files found in models/mmproj/</div>`;
      return;
    }

    modelDatabase.mmproj.forEach(model => {
      const card = document.createElement('div');
      const isSelected = model.name === selectedConfig.mmproj_model;
      card.className = `model-card ${isSelected ? 'selected' : ''}`;
      card.id = `card-mmproj-${model.name.replace(/\./g, '_')}`;
      
      const specs = getModelSpecs(model.name);
      const hasGPU = systemResources.vram.total > 0;
      const deviceChecked = isSelected ? (selectedConfig.mmproj_device === 'gpu' && hasGPU) : hasGPU;
      
      let rightContent = '';
      if (model.downloaded === false) {
        const safeId = model.name.replace(/\./g, '_').replace(/:/g, '_');
        if (model.partial === true) {
          rightContent = `
            <div class="card-right" id="download-container-${safeId}" style="display: flex; gap: 6px; align-items: center;">
              <button class="glow-btn download-btn resume-btn" style="padding: 4px 8px; font-size: 11px; cursor: pointer; border-radius: 6px; display: inline-flex; align-items: center; gap: 4px; background: rgba(56, 189, 248, 0.15); border-color: rgba(56, 189, 248, 0.4); color: var(--accent-sky);">
                Resume
              </button>
              <button class="glow-btn restart-btn" style="padding: 4px 8px; font-size: 11px; cursor: pointer; border-radius: 6px; display: inline-flex; align-items: center; gap: 4px; background: rgba(239, 68, 68, 0.1); border-color: rgba(239, 68, 68, 0.3); color: var(--accent-red, #ef4444);">
                Restart
              </button>
            </div>
          `;
        } else {
          rightContent = `
            <div class="card-right" id="download-container-${safeId}">
              <button class="glow-btn download-btn" style="padding: 4px 10px; font-size: 11px; cursor: pointer; border-radius: 6px; display: inline-flex; align-items: center; gap: 4px;">
                <svg style="width: 11px; height: 11px;" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"></path>
                </svg>
                Download
              </button>
            </div>
          `;
        }
      } else {
        rightContent = `
          <div class="card-right">
            <span class="device-toggle-label">${deviceChecked ? 'GPU' : 'CPU'}</span>
            <label class="switch">
              <input type="checkbox" class="device-switch" ${deviceChecked ? 'checked' : ''} ${(!hasGPU || !isSelected) ? 'disabled' : ''}>
              <span class="slider"></span>
            </label>
          </div>
        `;
      }

      card.innerHTML = `
        <div class="card-left">
          <input type="checkbox" class="card-checkbox" ${isSelected ? 'checked' : ''}>
          <div style="display: flex; flex-direction: column; gap: 2px;">
            <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
              <span class="card-name" title="${model.name}">${specs.cleanName}</span>
              <span class="badge badge-arch">${specs.arch}</span>
              <span class="badge badge-quant">${specs.quant}</span>
              <span class="badge badge-size">${model.size_gb.toFixed(2)} GB</span>
            </div>
            <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px; line-height: 1.3;">${specs.description}</div>
            <span class="family-warning" style="display: none;"></span>
          </div>
        </div>
        ${rightContent}
      `;

      const checkbox = card.querySelector('.card-checkbox');
      
      const toggleAction = () => {
        if (card.classList.contains('disabled')) return;
        
        if (selectedConfig.mmproj_model === model.name) {
          // Deselect
          selectedConfig.mmproj_model = null;
          card.classList.remove('selected');
          checkbox.checked = false;
        } else {
          // Select
          // Uncheck all other vision models
          document.querySelectorAll('#mmproj-located-list .card-checkbox').forEach(cb => {
            if (cb !== checkbox) cb.checked = false;
          });
          document.querySelectorAll('#mmproj-located-list .model-card').forEach(c => {
            if (c !== card) c.classList.remove('selected');
          });
          
          selectedConfig.mmproj_model = model.name;
          card.classList.add('selected');
          checkbox.checked = true;
          
          const devSwitch = card.querySelector('.device-switch');
          if (devSwitch) {
            selectedConfig.mmproj_device = devSwitch.checked ? 'gpu' : 'cpu';
          }
        }
        
        updateDeviceSwitchStates();
        updateResourceMeters();
      };

      card.addEventListener('click', (e) => {
        if (e.target.closest('.switch') || e.target.closest('.device-switch') || e.target.closest('.download-btn') || e.target.closest('.restart-btn')) return;
        toggleAction();
      });

      checkbox.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleAction();
      });

      const devSwitch = card.querySelector('.device-switch');
      const devLabel = card.querySelector('.device-toggle-label');
      if (devSwitch) {
        devSwitch.addEventListener('change', () => {
          devLabel.textContent = devSwitch.checked ? 'GPU' : 'CPU';
          if (card.classList.contains('selected')) {
            selectedConfig.mmproj_device = devSwitch.checked ? 'gpu' : 'cpu';
          }
          updateResourceMeters();
        });
      }

      const downloadBtn = card.querySelector('.download-btn');
      if (downloadBtn) {
        downloadBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          startDownload(model.name, false);
        });
      }

      const restartBtn = card.querySelector('.restart-btn');
      if (restartBtn) {
        restartBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          startDownload(model.name, true);
        });
      }

      mmprojList.appendChild(card);
    });
    
    updateDeviceSwitchStates();
    restoreActiveDownloadsUI();
  }

  function validateFamilyCompatibilities() {
    if (!selectedConfig.main_model) return;
    
    const mainFamily = getModelFamily(selectedConfig.main_model);

    // 1. Validate Draft Models
    modelDatabase.drafters.forEach(model => {
      const card = document.getElementById(`card-draft-${model.name.replace(/\./g, '_')}`);
      if (!card) return;

      const draftFamily = getModelFamily(model.name);
      const isCompat = (draftFamily === mainFamily);
      const warningSpan = card.querySelector('.family-warning');

      if (!isCompat) {
        card.classList.add('disabled');
        warningSpan.textContent = `(Incompatible family: requires ${mainFamily.toUpperCase()})`;
        warningSpan.style.display = 'inline';
        
        if (selectedConfig.draft_model === model.name) {
          selectedConfig.draft_model = null;
          card.classList.remove('selected');
          card.querySelector('.card-checkbox').checked = false;
        }
      } else {
        card.classList.remove('disabled');
        warningSpan.style.display = 'none';
      }
    });

    // 2. Validate Vision Adapters
    modelDatabase.mmproj.forEach(model => {
      const card = document.getElementById(`card-mmproj-${model.name.replace(/\./g, '_')}`);
      if (!card) return;

      const visionFamily = getModelFamily(model.name);
      const isCompat = (visionFamily === mainFamily);
      const warningSpan = card.querySelector('.family-warning');

      if (!isCompat) {
        card.classList.add('disabled');
        warningSpan.textContent = `(Incompatible family: requires ${mainFamily.toUpperCase()})`;
        warningSpan.style.display = 'inline';
        
        if (selectedConfig.mmproj_model === model.name) {
          selectedConfig.mmproj_model = null;
          card.classList.remove('selected');
          card.querySelector('.card-checkbox').checked = false;
        }
      } else {
        card.classList.remove('disabled');
        warningSpan.style.display = 'none';
      }
    });
  }

  function updateResourceMeters() {
    let estRam = 0.0;
    let estVram = 0.0;

    let missingModels = false;

    // 1. Main model sizing
    if (selectedConfig.main_model) {
      const model = modelDatabase.main.find(m => m.name === selectedConfig.main_model);
      if (model) {
        if (!model.downloaded) missingModels = true;
        if (selectedConfig.main_device === 'gpu') estVram += model.size_gb;
        else estRam += model.size_gb;
      }
      btnProceed.disabled = missingModels;
    } else {
      btnProceed.disabled = true;
    }

    // 2. Draft model sizing
    if (selectedConfig.draft_model) {
      const model = modelDatabase.drafters.find(m => m.name === selectedConfig.draft_model);
      if (model) {
        if (!model.downloaded) missingModels = true;
        if (selectedConfig.draft_device === 'gpu') estVram += model.size_gb;
        else estRam += model.size_gb;
      }
    }

    // 3. Vision adapter sizing
    if (selectedConfig.mmproj_model) {
      const model = modelDatabase.mmproj.find(m => m.name === selectedConfig.mmproj_model);
      if (model) {
        if (!model.downloaded) missingModels = true;
        if (selectedConfig.mmproj_device === 'gpu') estVram += model.size_gb;
        else estRam += model.size_gb;
      }
    }

    // 4. Whisper STT sizing
    if (selectedConfig.stt_enabled) {
      let sttSize = 1.5; // Medium
      const sizeVal = selectedConfig.stt_model_size;
      const sttModel = sttDatabase.find(m => m.name === `whisperx:${sizeVal}`);
      if (sttModel && !sttModel.downloaded) {
        missingModels = true;
      }
      if (sizeVal === 'tiny') sttSize = 0.1;
      else if (sizeVal === 'base') sttSize = 0.25;
      else if (sizeVal === 'small') sttSize = 0.50;
      else if (sizeVal === 'medium') sttSize = 1.5;
      else if (sizeVal === 'large-v3') sttSize = 3.0;

      if (selectedConfig.stt_device === 'gpu') estVram += sttSize;
      else estRam += sttSize;
    }

    // 5. TTS sizing
    if (selectedConfig.tts_enabled) {
      const ttsModel = ttsDatabase.find(m => m.name === "tts:qwen");
      if (ttsModel && !ttsModel.downloaded) {
        missingModels = true;
      }
      if (selectedConfig.tts_device === 'gpu') estVram += 1.2;
      else estRam += 1.2;
    }

    // Re-verify main proceed button activation status
    btnProceed.disabled = missingModels || !selectedConfig.main_model;

    // Render bars
    const totalRam = systemResources.ram.total;
    const totalVram = systemResources.vram.total;

    const ramPercent = Math.min((estRam / totalRam) * 100, 100);
    ramBar.style.width = `${ramPercent}%`;
    ramUsageText.textContent = `${estRam.toFixed(2)} GB / ${totalRam.toFixed(1)} GB`;

    if (totalVram > 0) {
      const vramPercent = Math.min((estVram / totalVram) * 100, 100);
      vramBar.style.width = `${vramPercent}%`;
      vramUsageText.textContent = `${estVram.toFixed(2)} GB / ${totalVram.toFixed(1)} GB`;
      
      if (vramPercent > 100) {
        vramBar.className = 'meter-bar-fill overflow';
      } else if (vramPercent > 85) {
        vramBar.className = 'meter-bar-fill warning';
      } else {
        vramBar.className = 'meter-bar-fill';
      }
    } else {
      vramBar.style.width = '0%';
      vramUsageText.textContent = `N/A (No GPU)`;
      vramBar.className = 'meter-bar-fill';
    }

    if (ramPercent > 100) {
      ramBar.className = 'meter-bar-fill overflow';
    } else if (ramPercent > 85) {
      ramBar.className = 'meter-bar-fill warning';
    } else {
      ramBar.className = 'meter-bar-fill';
    }
  }

  btnProceed.addEventListener('click', async () => {
    btnProceed.disabled = true;
    
    const payload = {
      main_model: selectedConfig.main_model,
      draft_model: selectedConfig.draft_model,
      mmproj_model: selectedConfig.mmproj_model,
      main_device: selectedConfig.main_device,
      draft_device: selectedConfig.draft_device,
      mmproj_device: selectedConfig.mmproj_device,
      stt_device: selectedConfig.stt_device,
      tts_device: selectedConfig.tts_device,
      stt_enabled: selectedConfig.stt_enabled,
      tts_enabled: selectedConfig.tts_enabled,
      stt_model_size: selectedConfig.stt_model_size,
      cache_type_k: selectedConfig.cache_type,
      cache_type_v: selectedConfig.cache_type
    };

    try {
      const res = await fetch(`${BACKEND_URL}/api/setup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      
      if (res.ok) {
        if (typeof window.api !== 'undefined' && window.api.navigateToSetup) {
          window.api.navigateToSetup();
        } else {
          window.location.href = 'setup.html';
        }
      } else {
        alert("Failed to start setup service.");
        btnProceed.disabled = false;
      }
    } catch (e) {
      alert("Error contacting API server: " + e.message);
      btnProceed.disabled = false;
    }
  });

  const btnSkipModels = document.getElementById('btn-skip-models');
  if (btnSkipModels) {
    btnSkipModels.addEventListener('click', async () => {
      btnSkipModels.disabled = true;
      btnProceed.disabled = true;
      
      const payload = {
        main_model: "",
        draft_model: null,
        mmproj_model: null,
        main_device: 'cpu',
        draft_device: 'cpu',
        mmproj_device: 'cpu',
        stt_device: 'cpu',
        tts_device: 'cpu',
        stt_enabled: false,
        tts_enabled: false,
        stt_model_size: '',
        cache_type_k: 'q4_0',
        cache_type_v: 'q4_0'
      };

      try {
        const res = await fetch(`${BACKEND_URL}/api/setup`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        
        if (res.ok) {
          if (typeof window.api !== 'undefined' && window.api.navigateToSetup) {
            window.api.navigateToSetup();
          } else {
            window.location.href = 'setup.html';
          }
        } else {
          alert("Failed to start setup service.");
          btnSkipModels.disabled = false;
          btnProceed.disabled = false;
        }
      } catch (e) {
        alert("Error contacting API server: " + e.message);
        btnSkipModels.disabled = false;
        btnProceed.disabled = false;
      }
    });
  }

  let setupPollInterval = null;
  async function pollSetupStatus() {
    try {
      const response = await fetch(`${BACKEND_URL}/api/setup/status`);
      if (response.ok) {
        const data = await response.json();
        if (data.error) {
          clearInterval(setupPollInterval);
          if (typeof window.api !== 'undefined' && window.api.navigateToSetup) {
            window.api.navigateToSetup();
          } else {
            window.location.href = 'setup.html';
          }
        } else if (data.progress > 0 && data.progress < 100) {
          clearInterval(setupPollInterval);
          if (typeof window.api !== 'undefined' && window.api.navigateToSetup) {
            window.api.navigateToSetup();
          } else {
            window.location.href = 'setup.html';
          }
        } else if (data.progress === 100) {
          clearInterval(setupPollInterval);
          if (typeof window.api !== 'undefined' && window.api.navigateToMain) {
            window.api.navigateToMain();
          } else {
            window.location.href = 'main.html';
          }
        }
      }
    } catch(e) {}
  }
  setupPollInterval = setInterval(pollSetupStatus, 1000);

  let activeDownloadInterval = null;
  const activeDownloads = {};
  const notifiedDownloads = new Set();
  
  function startDownload(modelName, restart = false) {
    const safeId = modelName.replace(/\./g, '_').replace(/:/g, '_');
    const container = document.getElementById(`download-container-${safeId}`);
    if (container) {
      const btn = container.querySelector('.download-btn');
      if (btn) btn.disabled = true;
      const restartBtn = container.querySelector('.restart-btn');
      if (restartBtn) restartBtn.disabled = true;
    }
    notifiedDownloads.delete(modelName);
    
    fetch(`${BACKEND_URL}/api/models/download`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ model_name: modelName, restart: restart })
    })
    .then(res => {
      if (res.ok) {
        if (!activeDownloadInterval) {
          activeDownloadInterval = setInterval(checkDownloadProgress, 1000);
        }
      } else {
        res.json().then(data => {
          alert(`Failed to start download: ${data.detail || 'Unknown error'}`);
          if (container) {
            const btn = container.querySelector('.download-btn');
            if (btn) btn.disabled = false;
            const restartBtn = container.querySelector('.restart-btn');
            if (restartBtn) restartBtn.disabled = false;
          }
        });
      }
    })
    .catch(err => {
      console.error("Failed to start model download:", err);
      if (container) {
        const btn = container.querySelector('.download-btn');
        if (btn) btn.disabled = false;
      }
    });
  }

  function cancelDownload(modelName) {
    const safeId = modelName.replace(/\./g, '_').replace(/:/g, '_');
    const container = document.getElementById(`download-container-${safeId}`);
    if (container) {
      const cancelBtn = container.querySelector('.cancel-download-btn');
      if (cancelBtn) {
        cancelBtn.disabled = true;
        cancelBtn.textContent = 'Cancelling...';
      }
    }
    
    fetch(`${BACKEND_URL}/api/models/download/cancel`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ model_name: modelName })
    })
    .then(res => {
      if (!res.ok) {
        console.error(`Failed to cancel download for ${modelName}`);
        if (container) {
          const cancelBtn = container.querySelector('.cancel-download-btn');
          if (cancelBtn) {
            cancelBtn.disabled = false;
            cancelBtn.textContent = 'Cancel';
          }
        }
      }
    })
    .catch(err => {
      console.error(`Error requesting cancel for ${modelName}:`, err);
      if (container) {
        const cancelBtn = container.querySelector('.cancel-download-btn');
        if (cancelBtn) {
          cancelBtn.disabled = false;
          cancelBtn.textContent = 'Cancel';
        }
      }
    });
  }

  function checkDownloadProgress() {
    fetch(`${BACKEND_URL}/api/models/download/status`)
      .then(res => res.json())
      .then(data => {
        let hasActive = false;
        let anyCompletedOrError = false;
        
        for (const modelName in data) {
          const info = data[modelName];
          if (!info) continue;
          
          activeDownloads[modelName] = info;
          
          if (info.status === 'downloading') {
            hasActive = true;
            updateDownloadUI(modelName, info.progress, info.speed_mbps);
          } else if (info.status === 'completed') {
            if (!notifiedDownloads.has(modelName)) {
              notifiedDownloads.add(modelName);
              anyCompletedOrError = true;
            }
          } else if (info.status === 'cancelled') {
            if (!notifiedDownloads.has(modelName)) {
              notifiedDownloads.add(modelName);
              anyCompletedOrError = true;
            }
          } else if (info.status === 'error') {
            if (!notifiedDownloads.has(modelName)) {
              notifiedDownloads.add(modelName);
              alert(`Download failed for ${modelName}: ${info.error}`);
              anyCompletedOrError = true;
            }
          }
        }
        
        if (anyCompletedOrError) {
          fetch(`${BACKEND_URL}/api/models`)
            .then(res => res.json())
            .then(configData => {
              modelDatabase.main = configData.models.main || [];
              modelDatabase.drafters = configData.models.drafters || [];
              modelDatabase.mmproj = configData.models.mmproj || [];
              sttDatabase = configData.models.stt || [];
              ttsDatabase = configData.models.tts || [];
              renderMainModels();
              renderDraftModels();
              renderVisionAdapters();
              renderSttTtsStatus();
              updateResourceMeters();
            });
        }
        
        if (!hasActive) {
          clearInterval(activeDownloadInterval);
          activeDownloadInterval = null;
        }
      })
      .catch(err => {
        console.error("Error checking download progress:", err);
      });
  }

  function restoreActiveDownloadsUI() {
    for (const modelName in activeDownloads) {
      const info = activeDownloads[modelName];
      if (info && info.status === 'downloading') {
        updateDownloadUI(modelName, info.progress, info.speed_mbps);
      }
    }
  }

  function updateDownloadUI(modelName, progress, speedMbps) {
    const safeId = modelName.replace(/\./g, '_').replace(/:/g, '_');
    const container = document.getElementById(`download-container-${safeId}`);
    if (container) {
      container.innerHTML = `
        <div style="display: flex; flex-direction: column; align-items: flex-end; width: 100%; max-width: 140px; gap: 4px;">
          <div style="font-size: 10px; color: var(--text-dim); font-family: var(--font-mono); display: flex; justify-content: space-between; width: 100%;">
            <span>${progress.toFixed(1)}%</span>
            <span>${speedMbps.toFixed(1)} Mbps</span>
          </div>
          <div style="width: 100%; height: 4px; background: rgba(255,255,255,0.1); border-radius: 2px; overflow: hidden;">
            <div style="width: ${progress}%; height: 100%; background: var(--text-main); transition: width 0.3s ease;"></div>
          </div>
          <button class="cancel-download-btn" data-model="${modelName}" style="background: none; border: none; color: var(--accent-red, #ef4444); font-size: 10px; cursor: pointer; padding: 2px 4px; margin-top: 2px; text-decoration: underline;">Cancel</button>
        </div>
      `;
      
      const cancelBtn = container.querySelector('.cancel-download-btn');
      if (cancelBtn) {
        cancelBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          cancelDownload(modelName);
        });
      }
    }
  }

  function checkActiveDownloadOnStartup() {
    fetch(`${BACKEND_URL}/api/models/download/status`)
      .then(res => res.json())
      .then(data => {
        let hasActive = false;
        for (const modelName in data) {
          const info = data[modelName];
          if (!info) continue;
          
          activeDownloads[modelName] = info;
          
          if (info.status === 'downloading') {
            hasActive = true;
            const safeId = modelName.replace(/\./g, '_').replace(/:/g, '_');
            const container = document.getElementById(`download-container-${safeId}`);
            if (container) {
              const btn = container.querySelector('.download-btn');
              if (btn) btn.disabled = true;
            }
          } else if (info.status === 'completed' || info.status === 'error' || info.status === 'cancelled') {
            notifiedDownloads.add(modelName);
          }
        }
        if (hasActive) {
          if (!activeDownloadInterval) {
            activeDownloadInterval = setInterval(checkDownloadProgress, 1000);
          }
        }
      })
      .catch(err => console.warn("Failed to check active download on startup:", err));
  }

  // Poll server health until ready
  async function checkBackendOnline() {
    try {
      const response = await fetch(`${BACKEND_URL}/api/models`);
      if (response.ok) {
        const resStats = await fetch(`${BACKEND_URL}/api/resources`);
        if (resStats.ok) {
          const stats = await resStats.json();
          if (stats.models_loaded) {
            if (typeof window.api !== 'undefined' && window.api.navigateToMain) {
              window.api.navigateToMain();
            } else {
              window.location.href = 'main.html';
            }
            return;
          }
        }
        const data = await response.json();
        await fetchSystemResources();
        setupInterface(data);
        checkActiveDownloadOnStartup();
      } else {
        setTimeout(checkBackendOnline, 200);
      }
    } catch (e) {
      setTimeout(checkBackendOnline, 200);
    }
  }

  checkBackendOnline();
});
