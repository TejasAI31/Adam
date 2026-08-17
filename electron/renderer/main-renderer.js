const BACKEND_URL = (window.location.protocol === 'file:' || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') 
  ? 'http://127.0.0.1:8000' 
  : window.location.origin;

document.addEventListener('DOMContentLoaded', () => {
  // Identify if running outside Electron (i.e. web browser)
  if (typeof window.api === 'undefined') {
    document.body.classList.add('not-electron');
  }

  // Navigation elements
  const tabs = document.querySelectorAll('.nav-tab');
  const panels = document.querySelectorAll('.tab-panel');
  
  // Mobile Top Navigation elements
  const mobileHamburgerBtn = document.getElementById('mobile-hamburger-btn');
  const mobileChatsBtn = document.getElementById('mobile-chats-btn');
  const mobileSidebarOverlay = document.getElementById('mobile-sidebar-overlay');
  const appSidebar = document.querySelector('.app-sidebar');
  const chatSessionsSidebar = document.querySelector('.chat-sessions-sidebar');
  const mobileActiveTitle = document.getElementById('mobile-active-session-title');

  function closeMobileMenus() {
    if (appSidebar) appSidebar.classList.remove('show');
    if (chatSessionsSidebar) chatSessionsSidebar.classList.remove('show');
    if (mobileSidebarOverlay) mobileSidebarOverlay.classList.remove('show');
  }

  if (mobileHamburgerBtn && appSidebar && mobileSidebarOverlay) {
    mobileHamburgerBtn.addEventListener('click', () => {
      appSidebar.classList.toggle('show');
      if (chatSessionsSidebar) chatSessionsSidebar.classList.remove('show');
      mobileSidebarOverlay.classList.toggle('show', appSidebar.classList.contains('show'));
    });
  }

  if (mobileChatsBtn && chatSessionsSidebar && mobileSidebarOverlay) {
    mobileChatsBtn.addEventListener('click', () => {
      chatSessionsSidebar.classList.toggle('show');
      if (appSidebar) appSidebar.classList.remove('show');
      mobileSidebarOverlay.classList.toggle('show', chatSessionsSidebar.classList.contains('show'));
    });
  }

  if (mobileSidebarOverlay) {
    mobileSidebarOverlay.addEventListener('click', closeMobileMenus);
  }

  // Resource Monitor elements
  const cpuVal = document.getElementById('cpu-val');
  const cpuBar = document.getElementById('cpu-bar');
  const gpuVal = document.getElementById('gpu-val');
  const gpuBar = document.getElementById('gpu-bar');
  const vramVal = document.getElementById('vram-val');
  const vramBar = document.getElementById('vram-bar');
  const contextTurnsVal = document.getElementById('context-turns-val');

  // Chat sessions elements
  const btnNewSession = document.getElementById('btn-new-session');
  const sessionList = document.getElementById('session-list');
  const activeSessionTitle = document.getElementById('active-session-title');
  const messageList = document.getElementById('message-list');
  
  // Input elements
  const chatTextarea = document.getElementById('chat-textarea');
  const btnSendMessage = document.getElementById('btn-send-message');
  const btnAttachFile = document.getElementById('btn-attach-file');
  const fileInputAttachments = document.getElementById('file-input-attachments');
  const filePreviewTray = document.getElementById('file-preview-tray');
  
  // Voice & interrupt elements
  const btnToggleMic = document.getElementById('btn-toggle-mic');
  const btnTogglePlaybackSpeak = document.getElementById('btn-toggle-playback-speak');
  const btnInterrupt = document.getElementById('btn-interrupt');
  const voiceDot = document.getElementById('voice-dot');
  const voiceStatusText = document.getElementById('voice-status-text');

  // Logs Elements
  const consoleLogs = document.getElementById('console-logs');
  const btnClearLogs = document.getElementById('btn-clear-logs');
  const btnCopyLogs = document.getElementById('btn-copy-logs');

  // Config Elements
  const btnSaveConfig = document.getElementById('btn-save-config');
  const reloadModal = document.getElementById('reload-modal');
  const reloadReasonsText = document.getElementById('reload-reasons-text');
  const btnModalCancel = document.getElementById('btn-modal-cancel');
  const btnModalConfirm = document.getElementById('btn-modal-confirm');

  // State Management
  let sessions = JSON.parse(localStorage.getItem('adam_sessions')) || [];
  let currentSessionId = localStorage.getItem('adam_active_session_id') || null;
  let attachedFiles = [];
  let eventSource = null;
  let isInterruptBtnVisible = false;
  let activeLlamaModels = {}; // Cached from backend for reloading config references

  // Initial Config state
  let configData = {};

  // --- TABS NAVIGATION ---
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      panels.forEach(p => p.classList.remove('active'));
      
      tab.classList.add('active');
      const targetPanel = document.getElementById(`panel-${tab.dataset.tab}`);
      if (targetPanel) targetPanel.classList.add('active');
      
      closeMobileMenus();
      
      if (tab.dataset.tab === 'config') {
        loadConfiguration();
        if (window.stopSharingPolling) window.stopSharingPolling();
      } else if (tab.dataset.tab === 'sharing') {
        loadSharingConfig();
        if (window.startSharingPolling) window.startSharingPolling();
      } else if (tab.dataset.tab === 'remote') {
        initRemoteControl();
        if (window.stopSharingPolling) window.stopSharingPolling();
      } else {
        if (window.stopSharingPolling) window.stopSharingPolling();
      }
    });
  });

  // --- RESOURCE MONITOR ---
  let lastAutoCompressTime = 0;
  async function autoCompressContext() {
    const now = Date.now();
    if (now - lastAutoCompressTime < 30000) return; // Limit to once per 30s
    lastAutoCompressTime = now;
    
    try {
      const res = await fetch(`${BACKEND_URL}/api/chat/compress`, { method: 'POST' });
      if (res.ok) {
        appendLogConsole("[SYSTEM] Automatic context compression triggered due to VRAM usage exceeding 95%.");
      }
    } catch (e) {
      console.warn("Auto context compression failed:", e);
    }
  }

  async function updateResourceStats() {
    try {
      const response = await fetch(`${BACKEND_URL}/api/resources`);
      if (!response.ok) return;
      const data = await response.json();
      
      if (data.models_loaded === false) {
        if (typeof window.api !== 'undefined' && window.api.navigateToSelection) {
          window.api.navigateToSelection();
        } else {
          window.location.href = 'selection.html';
        }
        return;
      }
      
      cpuVal.textContent = `${data.cpu}%`;
      cpuBar.style.width = `${data.cpu}%`;
      
      gpuVal.textContent = `${data.gpu}%`;
      gpuBar.style.width = `${data.gpu}%`;
      
      vramVal.textContent = `${data.vram.used} GB / ${data.vram.total} GB`;
      vramBar.style.width = `${data.vram.percent}%`;

      contextTurnsVal.textContent = `${data.context_turns} turns`;

      // STT capability block off
      const tabVoice = document.getElementById('tab-voice');
      if (data.stt_loaded === false) {
        btnToggleMic.style.opacity = '0.25';
        btnToggleMic.style.pointerEvents = 'none';
        btnToggleMic.title = 'Speech-to-text model not loaded';
      } else {
        btnToggleMic.style.opacity = '1.0';
        btnToggleMic.style.pointerEvents = 'auto';
        btnToggleMic.title = 'Toggle voice pipeline';
      }
      
      // Show Voice selection tab if either STT or TTS is loaded
      if (tabVoice) {
        if (data.stt_loaded || data.tts_loaded) {
          tabVoice.style.display = 'flex';
        } else {
          tabVoice.style.display = 'none';
        }
      }

      // TTS capability block off
      if (data.tts_loaded === false) {
        btnTogglePlaybackSpeak.style.opacity = '0.25';
        btnTogglePlaybackSpeak.style.pointerEvents = 'none';
        btnTogglePlaybackSpeak.title = 'Text-to-speech model not loaded';
      } else {
        btnTogglePlaybackSpeak.style.opacity = '1.0';
        btnTogglePlaybackSpeak.style.pointerEvents = 'auto';
        btnTogglePlaybackSpeak.title = 'Speech synthesis output';
      }

      // Check if both STT and TTS are loaded to show/hide the Passive button
      const btnPassiveMode = document.getElementById('btn-passive-mode');
      if (btnPassiveMode) {
        btnPassiveMode.style.display = 'flex';
      }

      // Auto context compression after vram hits >95%
      if (data.vram.percent > 95) {
        autoCompressContext();
      }
    } catch (e) {
      console.warn("Failed to fetch resource stats:", e);
    }
  }
  setInterval(updateResourceStats, 2000);
  updateResourceStats();

  // --- CHAT SESSION MANAGEMENT ---
  let isSyncing = false;
  async function syncSessions(forceRender = false) {
    if (isSyncing) return;
    isSyncing = true;
    try {
      const clientType = (typeof window.api !== 'undefined') ? 'desktop' : 'remote';
      const response = await fetch(`${BACKEND_URL}/api/sessions?client=${clientType}`);
      if (response.ok) {
        const fetched = await response.json();
        const fetchedStr = JSON.stringify(fetched);
        const localStr = JSON.stringify(sessions);
        
        if (fetched.length === 0 && sessions.length > 0) {
          await fetch(`${BACKEND_URL}/api/sessions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(sessions)
          });
        } else if (fetched.length > 0 && (fetchedStr !== localStr || forceRender)) {
          sessions = fetched;
          localStorage.setItem('adam_sessions', fetchedStr);
          
          if (!currentSessionId || !sessions.some(s => s.id === currentSessionId)) {
            currentSessionId = sessions[0].id;
            localStorage.setItem('adam_active_session_id', currentSessionId);
          }
          
          renderSessions();
          selectSession(currentSessionId, false);
        }
      }
    } catch (e) {
      console.warn("Error syncing sessions from backend:", e);
    } finally {
      isSyncing = false;
    }
  }

  async function saveSessions() {
    localStorage.setItem('adam_sessions', JSON.stringify(sessions));
    if (currentSessionId) {
      localStorage.setItem('adam_active_session_id', currentSessionId);
    } else {
      localStorage.removeItem('adam_active_session_id');
    }
    
    try {
      await fetch(`${BACKEND_URL}/api/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sessions)
      });
    } catch (e) {
      console.warn("Failed to save sessions to backend:", e);
    }
  }

  function renderSessions() {
    sessionList.innerHTML = '';
    if (sessions.length === 0) {
      createNewSession("Default Session");
      return;
    }

    sessions.forEach(session => {
      const item = document.createElement('div');
      item.className = `session-item ${session.id === currentSessionId ? 'active' : ''}`;
      item.innerHTML = `
        <span class="session-name" title="Double click to rename">${session.name}</span>
        <button class="delete-session" title="Delete session">
          <svg style="width: 14px; height: 14px" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
          </svg>
        </button>
      `;
      
      item.addEventListener('click', (e) => {
        if (e.target.closest('.delete-session')) return;
        selectSession(session.id);
      });

      const nameSpan = item.querySelector('.session-name');
      nameSpan.addEventListener('dblclick', () => {
        const input = document.createElement('input');
        input.type = 'text';
        input.value = session.name;
        input.style.width = '100%';
        input.style.background = 'rgba(0,0,0,0.6)';
        input.style.border = '1px solid var(--accent-cyan)';
        input.style.color = 'var(--text-main)';
        input.style.padding = '2px 4px';
        input.style.borderRadius = '4px';
        
        input.addEventListener('blur', () => {
          if (input.value.trim()) {
            session.name = input.value.trim();
            saveSessions();
            renderSessions();
            if (session.id === currentSessionId) {
              activeSessionTitle.textContent = session.name;
              if (mobileActiveTitle) mobileActiveTitle.textContent = session.name;
            }
          }
        });

        input.addEventListener('keydown', (ke) => {
          if (ke.key === 'Enter') input.blur();
        });

        nameSpan.replaceWith(input);
        input.focus();
        input.select();
      });

      item.querySelector('.delete-session').addEventListener('click', () => {
        deleteSession(session.id);
      });

      sessionList.appendChild(item);
    });
  }

  function createNewSession(name = null) {
    const id = `session_${Date.now()}`;
    const newName = name || `Session ${sessions.length + 1}`;
    const origin = (typeof window.api !== 'undefined') ? 'desktop' : 'remote';
    const newSession = {
      id,
      name: newName,
      messages: [],
      origin: origin
    };
    sessions.unshift(newSession);
    currentSessionId = id;
    saveSessions();
    renderSessions();
    selectSession(id);
  }

  function selectSession(id, notifyBackend = true) {
    currentSessionId = id;
    localStorage.setItem('adam_active_session_id', id);
    renderSessions();
    
    const session = sessions.find(s => s.id === id);
    if (session) {
      activeSessionTitle.textContent = session.name;
      if (mobileActiveTitle) mobileActiveTitle.textContent = session.name;
      closeMobileMenus();
      messageList.innerHTML = '';
      session.messages.forEach(msg => appendMessageUI(msg));
      scrollToBottom();
      
      if (notifyBackend) {
        saveSessions();
        fetch(`${BACKEND_URL}/api/session/switch`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: id })
        }).catch(err => console.warn("Failed to switch session context in backend:", err));
      }
    }
  }

  function deleteSession(id) {
    const index = sessions.findIndex(s => s.id === id);
    if (index > -1) {
      sessions.splice(index, 1);
      if (currentSessionId === id) {
        currentSessionId = sessions.length > 0 ? sessions[0].id : null;
      }
      saveSessions();
      renderSessions();
      if (currentSessionId) {
        selectSession(currentSessionId);
      } else {
        messageList.innerHTML = '';
        activeSessionTitle.textContent = 'No session selected';
      }
    }
  }

  btnNewSession.addEventListener('click', () => createNewSession());

  // --- MESSAGE RENDERING ---
  function appendMessageUI(msg) {
    const container = document.createElement('div');
    container.className = `message-container ${msg.sender}`;
    container.id = msg.id || `msg_${Date.now()}`;

    const senderSpan = document.createElement('div');
    senderSpan.className = `message-sender ${msg.sender}`;
    senderSpan.textContent = msg.sender === 'user' ? 'User' : 'Adam';

    // Header wrapper to hold sender and copy/download buttons inline
    const headerRow = document.createElement('div');
    headerRow.style.display = 'flex';
    headerRow.style.alignItems = 'center';
    headerRow.style.justifyContent = 'space-between';
    headerRow.style.width = '100%';
    headerRow.style.marginBottom = '6px';

    const copyBtn = document.createElement('button');
    copyBtn.className = 'copy-msg-btn';
    copyBtn.title = 'Copy to clipboard';
    copyBtn.innerHTML = `
      <svg style="width: 12px; height: 12px;" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3"></path>
      </svg>
    `;
    copyBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      navigator.clipboard.writeText(msg.text).then(() => {
        copyBtn.innerHTML = `
          <svg style="width: 12px; height: 12px; color: var(--accent-cyan);" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
          </svg>
        `;
        setTimeout(() => {
          copyBtn.innerHTML = `
            <svg style="width: 12px; height: 12px;" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3"></path>
            </svg>
          `;
        }, 1500);
      });
    });

    const actionsWrapper = document.createElement('div');
    actionsWrapper.style.display = 'flex';
    actionsWrapper.style.alignItems = 'center';
    actionsWrapper.style.gap = '6px';
    actionsWrapper.appendChild(copyBtn);

    // If it's an assistant response, add download button next to it
    if (msg.sender === 'assistant') {
      const downloadBtn = document.createElement('button');
      downloadBtn.className = 'copy-msg-btn';
      downloadBtn.title = 'Download as Markdown (.md)';
      downloadBtn.innerHTML = `
        <svg style="width: 12px; height: 12px;" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path>
        </svg>
      `;
      downloadBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const blob = new Blob([msg.text || ''], { type: 'text/markdown' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `adam_response_${Date.now()}.md`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      });
      actionsWrapper.appendChild(downloadBtn);
    }

    headerRow.appendChild(senderSpan);
    headerRow.appendChild(actionsWrapper);
    container.appendChild(headerRow);

    const textDiv = document.createElement('div');
    textDiv.className = 'message-text';
    
    // Render text block in markdown
    if (typeof marked !== 'undefined') {
      textDiv.innerHTML = marked.parse(msg.text || '');
    } else {
      textDiv.textContent = msg.text;
    }

    if (msg.attachments && msg.attachments.length > 0) {
      msg.attachments.forEach(file => {
        if (file.type === 'image') {
          const img = document.createElement('img');
          img.src = file.data || msg.image;
          img.className = 'message-image';
          container.appendChild(img);
        } else if (file.type === 'pdf') {
          const pdfBox = document.createElement('div');
          pdfBox.style.display = 'flex';
          pdfBox.style.alignItems = 'center';
          pdfBox.style.gap = '8px';
          pdfBox.style.background = 'rgba(255, 255, 255, 0.04)';
          pdfBox.style.border = '1px solid rgba(255, 255, 255, 0.1)';
          pdfBox.style.borderRadius = '6px';
          pdfBox.style.padding = '6px 12px';
          pdfBox.style.marginTop = '8px';
          pdfBox.style.alignSelf = 'flex-start';
          pdfBox.innerHTML = `
            <svg style="width: 20px; height: 20px; color: var(--danger); flex-shrink: 0;" fill="currentColor" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
              <path fill-rule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4zm2 2a1 1 0 011-1h3v3a1 1 0 001 1h3v7H7a1 1 0 01-1-1V6z" clip-rule="evenodd"></path>
            </svg>
            <span style="font-size: 12px; font-weight: 500; color: var(--text-main); max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${file.name}</span>
          `;
          container.appendChild(pdfBox);
        }
      });
    } else if (msg.image) {
      const img = document.createElement('img');
      img.src = msg.image;
      img.className = 'message-image';
      container.appendChild(img);
    }
    
    container.appendChild(textDiv);
    messageList.appendChild(container);
    scrollToBottom();
  }

  function appendStreamPlaceholder(msgId) {
    // Delete any existing placeholders for safety
    const existing = document.getElementById(msgId);
    if (existing) existing.remove();

    const container = document.createElement('div');
    container.className = 'message-container assistant';
    container.id = msgId;

    const senderSpan = document.createElement('div');
    senderSpan.className = 'message-sender assistant';
    senderSpan.textContent = 'Adam';

    const textDiv = document.createElement('div');
    textDiv.className = 'message-text typing';
    textDiv.id = `${msgId}_text`;

    container.appendChild(senderSpan);
    container.appendChild(textDiv);
    messageList.appendChild(container);
    scrollToBottom();
    
    // Show interrupt button
    showInterruptBtn(true);
  }

  function updateStreamText(msgId, chunk) {
    const textDiv = document.getElementById(`${msgId}_text`);
    if (textDiv) {
      textDiv.classList.remove('typing');
      
      // Store raw accumulated text in a dataset attribute to prevent parsing HTML nodes back as source Markdown
      if (!textDiv.dataset.rawText) {
        textDiv.dataset.rawText = textDiv.textContent || '';
      }
      textDiv.dataset.rawText += chunk;
      
      if (typeof marked !== 'undefined') {
        textDiv.innerHTML = marked.parse(textDiv.dataset.rawText);
      } else {
        textDiv.textContent = textDiv.dataset.rawText;
      }
      scrollToBottom();
    }
  }

  function appendToolCard(msgId, toolData) {
    const container = document.getElementById(msgId);
    if (!container) return;
    
    const cardId = `tool_${msgId}_${toolData.name}`;
    let card = document.getElementById(cardId);
    if (!card) {
      card = document.createElement('div');
      card.className = 'tool-execution-card';
      card.id = cardId;
      card.innerHTML = `
        <div class="tool-icon-spin"></div>
        <span>Running tool: ${toolData.name}...</span>
      `;
      // Append before the main text block
      container.appendChild(card);
    }
  }

  function resolveToolCard(msgId, toolData) {
    const cardId = `tool_${msgId}_${toolData.name}`;
    const card = document.getElementById(cardId);
    if (card) {
      card.innerHTML = `
        <span style="color: var(--success); font-weight: bold; font-size: 14px">✓</span>
        <span>Executed tool: ${toolData.name}</span>
      `;
      // Remove spinner, show completion green check
      setTimeout(() => {
        card.style.opacity = '0.7';
      }, 1000);
    }
  }

  function showInterruptBtn(show) {
    isInterruptBtnVisible = show;
    btnInterrupt.style.display = show ? 'block' : 'none';
  }

  function scrollToBottom() {
    messageList.scrollTop = messageList.scrollHeight;
  }

  // --- CONNECT SYSTEM EVENTS (SSE) ---
  function connectEventSource() {
    if (eventSource) eventSource.close();

    console.log("[SSE] Opening connection...");
    eventSource = new EventSource(`${BACKEND_URL}/api/events`);

    eventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.type === 'ping') return;
        
        handleSystemEvent(data.type, data.data);
      } catch (err) {
        console.error("SSE parse error:", err);
      }
    };

    eventSource.onerror = (err) => {
      console.warn("SSE connection lost. Reconnecting in 3s...", err);
      eventSource.close();
      setTimeout(connectEventSource, 3000);
    };
  }

  function handleSystemEvent(type, data) {
    // 1. Logs Streaming
    if (type === 'log') {
      appendLogConsole(data.line);
    }
    
    // 2. Setup progress (in case settings changed or reload was triggered from config)
    if (type === 'setup_progress') {
      console.log("[Setup Update]", data);
    }
    
    // 3. User Voice input transcription detection
    if (type === 'chat_message' && data.sender === 'user') {
      // Avoid duplicating if we typed it
      const existing = document.getElementById(data.id);
      if (!existing) {
        const msg = {
          sender: 'user',
          text: data.text,
          image: data.image || null,
          attachments: data.attachments || [],
          id: data.id
        };
        const targetSessionId = data.session_id || currentSessionId;
        const session = sessions.find(s => s.id === targetSessionId);
        if (session) {
          session.messages.push(msg);
          localStorage.setItem('adam_sessions', JSON.stringify(sessions));
          if (targetSessionId === currentSessionId) {
            appendMessageUI(msg);
          }
        }
      }
    }

    // 4. Chat states typing indicator
    if (type === 'chat_status' && data.status === 'typing') {
      const targetSessionId = data.session_id || currentSessionId;
      if (targetSessionId === currentSessionId) {
        appendStreamPlaceholder(data.msg_id);
      }
    }

    // 5. Chat chunks streaming tokens
    if (type === 'chat_chunk') {
      const targetSessionId = data.session_id || currentSessionId;
      if (targetSessionId === currentSessionId) {
        updateStreamText(data.msg_id, data.text);
      }
    }

    // 6. Tools calls streaming updates
    if (type === 'chat_tool') {
      const targetSessionId = data.session_id || currentSessionId;
      if (targetSessionId === currentSessionId) {
        if (data.status === 'start') {
          appendToolCard(data.msg_id, data.tool);
        } else if (data.status === 'end') {
          resolveToolCard(data.msg_id, data.tool);
        }
      }
    }

    // 7. Full completed assistant message
    if (type === 'chat_message' && data.sender === 'assistant') {
      const targetSessionId = data.session_id || currentSessionId;
      const session = sessions.find(s => s.id === targetSessionId);
      if (session) {
        // Remove stream placeholder container and replace with saved DB structure
        const placeholder = document.getElementById(data.id);
        if (placeholder) placeholder.remove();
        
        const msg = {
          sender: 'assistant',
          text: data.text,
          id: data.id
        };
        session.messages.push(msg);
        localStorage.setItem('adam_sessions', JSON.stringify(sessions));
        if (targetSessionId === currentSessionId) {
          appendMessageUI(msg);
        }
      }
      showInterruptBtn(false);
    }

    // 8. Voice loop states
    if (type === 'voice_status') {
      if (data.status === 'transcribing') {
        voiceDot.className = 'status-dot typing';
        voiceStatusText.textContent = 'Transcribing voice...';
      } else if (data.status === 'idle') {
        voiceDot.className = 'status-dot active';
        voiceStatusText.textContent = 'Listening (Voice active)';
      }
    }

    // 9. Playback interrupt
    if (type === 'playback_interrupted') {
      showInterruptBtn(false);
      clearAllTypingPlaceholders();
    }

    // 10. Chat errors
    if (type === 'chat_error') {
      clearAllTypingPlaceholders();
      console.error("[Chat Error]", data);
    }

    // 11. Sessions and remote control updates
    if (type === 'sessions_updated') {
      syncSessions();
    }
    if (type === 'session_switch') {
      const targetSessionId = data.session_id;
      if (targetSessionId !== currentSessionId) {
        selectSession(targetSessionId, false);
      }
    }
    if (type === 'session_clear') {
      const targetSessionId = data.session_id;
      const session = sessions.find(s => s.id === targetSessionId);
      if (session) {
        session.messages = [];
        if (targetSessionId === currentSessionId) {
          messageList.innerHTML = '';
        }
      }
    }
  }

  // --- SEND MESSAGES ---
  async function sendMessage() {
    const text = chatTextarea.value.trim();
    if (!text && attachedFiles.length === 0) return;

    chatTextarea.value = '';
    chatTextarea.style.height = 'auto'; // Reset height
    chatTextarea.disabled = true;
    btnSendMessage.disabled = true;

    const msgId = `msg_${Date.now()}`;
    const userMsg = {
      sender: 'user',
      text: text,
      image: attachedFiles.length > 0 ? attachedFiles[0].data : null,
      attachments: [...attachedFiles],
      id: msgId
    };

    // Save and render User UI message
    const session = sessions.find(s => s.id === currentSessionId);
    if (session) {
      session.messages.push(userMsg);
      saveSessions();
    }
    appendMessageUI(userMsg);

    // Call API
    const isSpeechOutput = btnTogglePlaybackSpeak.classList.contains('active');
    const payload = {
      message: text,
      image: attachedFiles.length > 0 ? attachedFiles[0].data : null,
      attachments: attachedFiles,
      speech_enabled: isSpeechOutput,
      msg_id: msgId,
      session_id: currentSessionId
    };

    // Reset attachment preview
    clearAllAttachments();

    try {
      const res = await fetch(`${BACKEND_URL}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        let errMsg = "Unknown error";
        try {
          const errData = await res.json();
          errMsg = errData.detail || JSON.stringify(errData);
        } catch(jsonErr) {
          try {
            const rawText = await res.text();
            if (rawText.includes("<!DOCTYPE") || rawText.includes("<html")) {
              errMsg = `HTTP ${res.status}: Request rejected by tunnel proxy. (Check payload size limits)`;
            } else {
              errMsg = rawText.substring(0, 200);
            }
          } catch(txtErr) {
            errMsg = `HTTP status code: ${res.status}`;
          }
        }
        alert(`API Error: ${errMsg}`);
      }
    } catch (e) {
      console.error("Message deliver failure:", e);
      alert("Failed to send message: " + e.message);
    } finally {
      chatTextarea.disabled = false;
      btnSendMessage.disabled = false;
      chatTextarea.focus();
    }
  }

  btnSendMessage.addEventListener('click', sendMessage);
  chatTextarea.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Autosize textarea
  chatTextarea.addEventListener('input', () => {
    chatTextarea.style.height = 'auto';
    chatTextarea.style.height = `${chatTextarea.scrollHeight}px`;
  });

  function clearAllTypingPlaceholders() {
    const typingIndicators = document.querySelectorAll('.message-text.typing');
    typingIndicators.forEach(el => {
      const container = el.closest('.message-container');
      if (container) container.remove();
    });
    showInterruptBtn(false);
  }

  // --- INTERRUPT BUTTON LOGIC ---
  btnInterrupt.addEventListener('click', async () => {
    try {
      clearAllTypingPlaceholders();
      await fetch(`${BACKEND_URL}/api/chat/interrupt`, { method: 'POST' });
    } catch (e) {
      console.warn("Interrupt failed", e);
    }
  });

  // --- VOICE AND AUDIO OPTIONS ---
  let isVoiceInputEnabled = false;

  btnToggleMic.addEventListener('click', () => {
    isVoiceInputEnabled = !isVoiceInputEnabled;
    btnToggleMic.classList.toggle('active', isVoiceInputEnabled);
    if (isVoiceInputEnabled) {
      voiceDot.className = 'status-dot active';
      voiceStatusText.textContent = 'Listening (Voice active)';
      console.log("[Mic] Voice loop activated.");
    } else {
      voiceDot.className = 'status-dot';
      voiceStatusText.textContent = 'Voice loop muted';
    }
  });

  let isSpeechSynthesisEnabled = (typeof window.api !== 'undefined');
  btnTogglePlaybackSpeak.addEventListener('click', async () => {
    isSpeechSynthesisEnabled = !isSpeechSynthesisEnabled;
    btnTogglePlaybackSpeak.classList.toggle('active', isSpeechSynthesisEnabled);
    
    // Style toggle
    if (isSpeechSynthesisEnabled) {
      btnTogglePlaybackSpeak.style.color = 'var(--accent-cyan)';
    } else {
      btnTogglePlaybackSpeak.style.color = 'var(--text-muted)';
      // Muted mid-speaking: call interrupt to stop audio synthesis instantly
      try {
        await fetch(`${BACKEND_URL}/api/chat/interrupt`, { method: 'POST' });
      } catch (e) {
        console.warn("Mute interrupt failed", e);
      }
    }
  });

  // Default button highlights
  if (isSpeechSynthesisEnabled) {
    btnTogglePlaybackSpeak.classList.add('active');
    btnTogglePlaybackSpeak.style.color = 'var(--accent-cyan)';
  } else {
    btnTogglePlaybackSpeak.style.color = 'var(--text-muted)';
  }

  // --- MULTIPLE FILES ATTACHMENT PIPELINE (IMAGES & PDFS) ---
  function compressImage(base64Data, maxWidth = 800, maxHeight = 800, quality = 0.7) {
    return new Promise((resolve) => {
      const img = new Image();
      img.src = base64Data;
      img.onload = () => {
        let width = img.width;
        let height = img.height;
        
        if (width > maxWidth || height > maxHeight) {
          if (width > height) {
            height = Math.round((height * maxWidth) / width);
            width = maxWidth;
          } else {
            width = Math.round((width * maxHeight) / height);
            height = maxHeight;
          }
        }
        
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, width, height);
        resolve(canvas.toDataURL('image/jpeg', quality));
      };
      img.onerror = () => {
        resolve(base64Data);
      };
    });
  }

  btnAttachFile.addEventListener('click', () => {
    fileInputAttachments.click();
  });

  fileInputAttachments.addEventListener('change', () => {
    const files = Array.from(fileInputAttachments.files);
    files.forEach(file => {
      const reader = new FileReader();
      reader.onload = async (e) => {
        const fileType = file.type || (file.name.toLowerCase().endsWith('.pdf') ? 'application/pdf' : 'image/png');
        let data = e.target.result;
        
        if (fileType.includes('image')) {
          try {
            data = await compressImage(data);
          } catch(err) {
            console.warn("Image compression failed, using original:", err);
          }
        }
        
        attachedFiles.push({
          name: file.name,
          type: fileType.includes('pdf') ? 'pdf' : 'image',
          data: data
        });
        renderFilePreviews();
      };
      reader.readAsDataURL(file);
    });
    fileInputAttachments.value = '';
  });

  function renderFilePreviews() {
    filePreviewTray.innerHTML = '';
    if (attachedFiles.length === 0) {
      filePreviewTray.style.display = 'none';
      return;
    }
    filePreviewTray.style.display = 'flex';
    
    attachedFiles.forEach((file, index) => {
      const item = document.createElement('div');
      item.style.position = 'relative';
      item.style.display = 'flex';
      item.style.flexDirection = 'column';
      item.style.alignItems = 'center';
      item.style.background = 'rgba(10, 18, 42, 0.85)';
      item.style.border = '1px solid var(--border-color)';
      item.style.borderRadius = '6px';
      item.style.padding = '8px';
      item.style.width = '80px';
      item.style.boxShadow = 'var(--shadow-glow)';

      if (file.type === 'image') {
        const img = document.createElement('img');
        img.src = file.data;
        img.style.width = '64px';
        img.style.height = '64px';
        img.style.objectFit = 'cover';
        img.style.borderRadius = '4px';
        item.appendChild(img);
      } else {
        const pdfIcon = document.createElement('div');
        pdfIcon.innerHTML = `
          <svg style="width: 32px; height: 32px; color: var(--danger);" fill="currentColor" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
            <path fill-rule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4zm2 2a1 1 0 011-1h3v3a1 1 0 001 1h3v7H7a1 1 0 01-1-1V6z" clip-rule="evenodd"></path>
          </svg>
        `;
        const nameLabel = document.createElement('span');
        nameLabel.textContent = file.name;
        nameLabel.style.fontSize = '9px';
        nameLabel.style.color = 'var(--text-muted)';
        nameLabel.style.width = '64px';
        nameLabel.style.whiteSpace = 'nowrap';
        nameLabel.style.overflow = 'hidden';
        nameLabel.style.textOverflow = 'ellipsis';
        nameLabel.style.textAlign = 'center';
        nameLabel.style.marginTop = '4px';
        
        item.appendChild(pdfIcon);
        item.appendChild(nameLabel);
      }

      const removeBtn = document.createElement('button');
      removeBtn.textContent = '×';
      removeBtn.style.position = 'absolute';
      removeBtn.style.top = '-6px';
      removeBtn.style.right = '-6px';
      removeBtn.style.background = 'var(--danger)';
      removeBtn.style.color = 'white';
      removeBtn.style.border = 'none';
      removeBtn.style.borderRadius = '50%';
      removeBtn.style.width = '16px';
      removeBtn.style.height = '16px';
      removeBtn.style.fontSize = '10px';
      removeBtn.style.fontWeight = 'bold';
      removeBtn.style.cursor = 'pointer';
      removeBtn.style.display = 'flex';
      removeBtn.style.alignItems = 'center';
      removeBtn.style.justifyContent = 'center';
      removeBtn.style.boxShadow = '0 2px 4px rgba(0,0,0,0.5)';
      
      removeBtn.addEventListener('click', () => {
        attachedFiles.splice(index, 1);
        renderFilePreviews();
      });
      item.appendChild(removeBtn);

      filePreviewTray.appendChild(item);
    });
  }

  function clearAllAttachments() {
    attachedFiles = [];
    renderFilePreviews();
  }

  // --- SYSTEM LOGS LOGIC ---
  const logVerbosity = document.getElementById('log-verbosity');
  let allLogs = [];

  function shouldShowLog(line, level) {
    const lowerLine = line.toLowerCase();
    if (level === 'errors') {
      return lowerLine.includes('[error]') || lowerLine.includes('error') || lowerLine.includes('exception') || lowerLine.includes('fail') || lowerLine.includes('crash') || lowerLine.includes('critical');
    } else if (level === 'warnings') {
      return lowerLine.includes('[error]') || lowerLine.includes('error') || lowerLine.includes('exception') || lowerLine.includes('fail') || lowerLine.includes('crash') || lowerLine.includes('critical') || lowerLine.includes('[warning]') || lowerLine.includes('warning') || lowerLine.includes('warn');
    }
    return true; // 'all'
  }

  function filterAndRenderLogs() {
    const level = logVerbosity.value;
    consoleLogs.textContent = '';
    
    const filtered = allLogs.filter(line => shouldShowLog(line, level));
    consoleLogs.textContent = filtered.join('\n') + (filtered.length > 0 ? '\n' : '');
    consoleLogs.scrollTop = consoleLogs.scrollHeight;
  }

  logVerbosity.addEventListener('change', filterAndRenderLogs);

  function appendLogConsole(line) {
    allLogs.push(line);
    
    const level = logVerbosity.value;
    if (shouldShowLog(line, level)) {
      const shouldScroll = consoleLogs.scrollTop + consoleLogs.clientHeight >= consoleLogs.scrollHeight - 20;
      consoleLogs.textContent += line + '\n';
      
      if (shouldScroll) {
        consoleLogs.scrollTop = consoleLogs.scrollHeight;
      }
    }
  }

  btnClearLogs.addEventListener('click', () => {
    allLogs = [];
    consoleLogs.textContent = '';
  });

  btnCopyLogs.addEventListener('click', () => {
    const level = logVerbosity.value;
    const filtered = allLogs.filter(line => shouldShowLog(line, level));
    navigator.clipboard.writeText(filtered.join('\n'));
    alert("Filtered logs copied to clipboard!");
  });

  // --- CONFIG CONFIGURATION LOGIC ---
  async function loadConfiguration() {
    try {
      const response = await fetch(`${BACKEND_URL}/api/config`);
      if (!response.ok) return;
      configData = await response.json();

      // Cache current models selection for reload comparison
      const modelsRes = await fetch(`${BACKEND_URL}/api/models`);
      if (modelsRes.ok) {
        const mdata = await modelsRes.json();
        activeLlamaModels = mdata.selected;
      }

      // Populate Inputs
      document.getElementById('cfg-llama-host').value = configData.llama.SERVER_HOST;
      document.getElementById('cfg-llama-port').value = configData.llama.SERVER_PORT;
      document.getElementById('cfg-llama-ctx').value = configData.llama.context_size;
      document.getElementById('cfg-llama-ngl').value = configData.llama.ngl;
      document.getElementById('cfg-llama-flash').value = configData.llama.flash_attn;

      document.getElementById('cfg-audio-rate').value = configData.audio.sample_rate;
      document.getElementById('cfg-audio-frame').value = configData.audio.frame_duration_ms;
      document.getElementById('cfg-audio-vad').value = configData.audio.vad_aggressiveness;
      document.getElementById('cfg-audio-min-dur').value = configData.audio.min_speech_duration;
      document.getElementById('cfg-audio-max-dur').value = configData.audio.max_speech_duration;

      document.getElementById('cfg-model-stt-size').value = configData.model.stt_model_size;
      document.getElementById('cfg-model-stt-device').value = configData.model.stt_device;
      document.getElementById('cfg-model-tts-repo').value = configData.model.tts_repo_id;
      document.getElementById('cfg-model-tts-device').value = configData.model.tts_device;

      document.getElementById('cfg-model-hist-turns').value = configData.model.max_history_len;
      document.getElementById('cfg-model-tool-len').value = configData.model.max_tool_output_len;
      document.getElementById('cfg-model-compression').value = configData.model.max_estimated_tokens;
      document.getElementById('cfg-model-max-output').value = configData.model.max_output_tokens;
    } catch (e) {
      console.error("Failed to load configs:", e);
    }
  }

  btnSaveConfig.addEventListener('click', async () => {
    // Pack values
    const newConfig = {
      llama: {
        SERVER_HOST: document.getElementById('cfg-llama-host').value,
        SERVER_PORT: parseInt(document.getElementById('cfg-llama-port').value),
        context_size: parseInt(document.getElementById('cfg-llama-ctx').value),
        ngl: parseInt(document.getElementById('cfg-llama-ngl').value),
        flash_attn: document.getElementById('cfg-llama-flash').value,
        SERVER_TIMEOUT: configData.llama.SERVER_TIMEOUT,
        MAIN_MODEL_FILE: activeLlamaModels.main_model,
        DRAFT_MODEL_FILE: activeLlamaModels.draft_model,
        MMPROJ_MODEL_FILE: activeLlamaModels.mmproj_model,
        spec_draft_n_max: configData.llama.spec_draft_n_max,
        cache_type_k: configData.llama.cache_type_k,
        cache_type_v: configData.llama.cache_type_v,
      },
      audio: {
        sample_rate: parseInt(document.getElementById('cfg-audio-rate').value),
        frame_duration_ms: parseInt(document.getElementById('cfg-audio-frame').value),
        vad_aggressiveness: parseInt(document.getElementById('cfg-audio-vad').value),
        min_speech_duration: parseFloat(document.getElementById('cfg-audio-min-dur').value),
        max_speech_duration: parseFloat(document.getElementById('cfg-audio-max-dur').value),
      },
      model: {
        stt_model_size: document.getElementById('cfg-model-stt-size').value,
        stt_device: document.getElementById('cfg-model-stt-device').value,
        tts_repo_id: document.getElementById('cfg-model-tts-repo').value,
        tts_device: document.getElementById('cfg-model-tts-device').value,
        max_history_len: parseInt(document.getElementById('cfg-model-hist-turns').value),
        max_tool_output_len: parseInt(document.getElementById('cfg-model-tool-len').value),
        max_estimated_tokens: parseInt(document.getElementById('cfg-model-compression').value),
        max_output_tokens: parseInt(document.getElementById('cfg-model-max-output').value),
        stt_compute_type: configData.model.stt_compute_type,
        stt_batch_size: configData.model.stt_batch_size,
        align_words: configData.model.align_words,
      }
    };

    try {
      const res = await fetch(`${BACKEND_URL}/api/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig)
      });
      if (res.ok) {
        // Mandatory reload modal prompt
        reloadReasonsText.innerHTML = `
          Configuration saved successfully. Reloading the neural engine pipelines is required to apply the updated configuration parameters.<br><br>
          Do you want to reload the engines now?
        `;
        reloadModal.style.display = 'flex';
      }
    } catch (e) {
      alert("Failed to save config: " + e.message);
    }
  });

  btnModalCancel.addEventListener('click', () => {
    reloadModal.style.display = 'none';
  });

  btnModalConfirm.addEventListener('click', async () => {
    reloadModal.style.display = 'none';
    
    // Call API setup to reload using current models configuration
    const payload = {
      main_model: activeLlamaModels.main_model,
      draft_model: activeLlamaModels.draft_model,
      mmproj_model: activeLlamaModels.mmproj_model
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
      }
    } catch (e) {
      alert("Failed to trigger reload: " + e.message);
    }
  });

  // --- CONFIGURE MODELS BACK TO SELECTION ---
  const btnUnloadModels = document.getElementById('btn-unload-models');
  if (btnUnloadModels) {
    btnUnloadModels.addEventListener('click', async () => {
      const confirmUnload = confirm("Are you sure you want to unload current models and return to configuration?");
      if (!confirmUnload) return;
      try {
        const res = await fetch(`${BACKEND_URL}/api/unload`, { method: 'POST' });
        if (res.ok) {
          if (typeof window.api !== 'undefined' && window.api.navigateToSelection) {
            window.api.navigateToSelection();
          } else {
            window.location.href = 'selection.html';
          }
        } else {
          alert("Failed to unload models.");
        }
      } catch (e) {
        alert("Error unloading models: " + e.message);
      }
    });
  }

  // --- PASSIVE MODE & EXIT APP ---
  const btnPassiveModeClick = document.getElementById('btn-passive-mode');
  if (btnPassiveModeClick) {
    btnPassiveModeClick.addEventListener('click', () => {
      if (typeof window.api !== 'undefined') {
        window.api.windowControl('silent'); // Minimize to tray
      }
    });
  }

  const btnExitApp = document.getElementById('btn-exit-app');
  if (btnExitApp) {
    btnExitApp.addEventListener('click', () => {
      if (typeof window.api !== 'undefined') {
        window.api.windowControl('close'); // Quit app
      }
    });
  }

  // --- COMPRESS CONTEXT ---
  const btnCompressContext = document.getElementById('btn-compress-context');
  if (btnCompressContext) {
    btnCompressContext.addEventListener('click', async () => {
      try {
        const res = await fetch(`${BACKEND_URL}/api/chat/compress`, { method: 'POST' });
        if (res.ok) {
          const rdata = await res.json();
          alert(`Context compressed successfully. Current context length: ${rdata.context_turns} turns.`);
          appendLogConsole(`[SYSTEM] Manual context compression executed. New size: ${rdata.context_turns} turns.`);
        }
      } catch (e) {
        alert("Failed to compress context: " + e.message);
      } finally {
        setTimeout(() => {
          chatTextarea.disabled = false;
          chatTextarea.focus();
        }, 100);
      }
    });
  }

  // --- CLEAR CHAT ---
  const btnClearChat = document.getElementById('btn-clear-chat');
  if (btnClearChat) {
    btnClearChat.addEventListener('click', async () => {
      try {
        const confirmClear = confirm("Are you sure you want to clear all messages in this session?");
        if (!confirmClear) return;
        
        const session = sessions.find(s => s.id === currentSessionId);
        if (session) {
          session.messages = [];
          saveSessions();
          messageList.innerHTML = '';
          appendLogConsole(`[SYSTEM] Cleared chat messages for session: ${session.name}`);
          
          // Notify backend to clear history of this session
          await fetch(`${BACKEND_URL}/api/session/clear`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: currentSessionId })
          });
        }
      } catch (e) {
        console.warn("Failed to clear session history on backend:", e);
      } finally {
        setTimeout(() => {
          chatTextarea.disabled = false;
          chatTextarea.focus();
        }, 100);
      }
    });
  }

  // --- AGENT CAPABILITIES TOOLS TAB ---
  const toolsContainer = document.getElementById('tools-container');
  const toolDefinitions = [
    // Math Tools
    { id: 'evaluate_expression', name: 'Expression Evaluator', desc: 'Evaluate advanced mathematical and scientific expressions.', category: 'Mathematical Capabilities' },
    { id: 'solve_quadratic', name: 'Quadratic Equation Solver', desc: 'Solve quadratic equations of the form ax^2 + bx + c = 0.', category: 'Mathematical Capabilities' },
    { id: 'calculate_statistics', name: 'Descriptive Statistics', desc: 'Compute mean, median, mode, variance, and standard deviation for a set of numbers.', category: 'Mathematical Capabilities' },
    
    // Web Search Tools
    { id: 'web_search', name: 'Web Search', desc: 'Query the web to retrieve up-to-date information, facts, or answers.', category: 'Information & Search' },
    
    // Media & Playback Tools
    { id: 'ytm_search_and_get', name: 'YouTube Music Search', desc: 'Search YouTube Music and get direct URLs for songs, albums, artists, or playlists.', category: 'Media & Playback' },
    { id: 'ytm_get_browse_context', name: 'YouTube Music Browser', desc: 'Fetch recommendations, charts, related tracks, or song lyrics on YouTube Music.', category: 'Media & Playback' },
    
    // Browser Interaction Tools
    { id: 'open_browser_urls', name: 'Default Browser Opener', desc: 'Opens one or more web URLs in the default system browser.', category: 'Web Browser Interaction' },
    
    // System Tools
    { id: 'take_screenshot', name: 'Screen Capture (Grid Overlay)', desc: 'Capture a screenshot with a spatial coordinate grid overlay for precision visual analysis.', category: 'System Administration' },
    { id: 'scan_screen_elements', name: 'UI Accessibility Scanner', desc: 'Scan active window or Taskbar UI controls for visual grounding.', category: 'System Administration' },
    { id: 'click_element_by_name', name: 'UI Element Clicker', desc: 'Search visible UI controls or Taskbar icons by name and click them directly.', category: 'System Administration' }
  ];

  async function initToolsTab() {
    if (!toolsContainer) return;
    try {
      const response = await fetch(`${BACKEND_URL}/api/tools`);
      let enabledTools = {};
      if (response.ok) {
        const data = await response.json();
        enabledTools = data.enabled_tools || {};
      }

      // Group tools by category
      const categories = {};
      toolDefinitions.forEach(t => {
        if (!categories[t.category]) categories[t.category] = [];
        categories[t.category].push(t);
      });

      toolsContainer.innerHTML = '';
      
      Object.keys(categories).forEach(cat => {
        const catSection = document.createElement('div');
        catSection.style.background = 'rgba(255,255,255,0.01)';
        catSection.style.border = '1px solid var(--border-color)';
        catSection.style.borderRadius = '8px';
        catSection.style.padding = '14px';
        catSection.style.marginBottom = '12px';

        catSection.innerHTML = `
          <div style="font-size: 11px; font-weight: 600; color: var(--accent-cyan); text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 10px;">${cat}</div>
          <div class="category-grid" style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px;"></div>
        `;

        const grid = catSection.querySelector('.category-grid');
        categories[cat].forEach(tool => {
          const isChecked = enabledTools[tool.id] !== false; // Default to true if not specified
          const card = document.createElement('div');
          card.style.background = 'rgba(255,255,255,0.02)';
          card.style.border = '1px solid rgba(255,255,255,0.04)';
          card.style.borderRadius = '6px';
          card.style.padding = '8px 12px';
          card.style.display = 'flex';
          card.style.alignItems = 'flex-start';
          card.style.gap = '10px';

          card.innerHTML = `
            <input type="checkbox" class="tool-checkbox" data-tool-id="${tool.id}" ${isChecked ? 'checked' : ''} style="margin-top: 3px; accent-color: var(--accent-cyan); width: 16px; height: 16px; cursor: pointer;">
            <div style="display: flex; flex-direction: column; gap: 2px;">
              <span style="font-size: 12px; font-weight: 600; color: var(--text-main);">${tool.name}</span>
              <span style="font-size: 10px; color: var(--text-dim); line-height: 1.3;">${tool.desc}</span>
            </div>
          `;

          const cb = card.querySelector('.tool-checkbox');
          cb.addEventListener('change', () => saveToolsState());
          
          grid.appendChild(card);
        });

        toolsContainer.appendChild(catSection);
      });
    } catch (e) {
      console.error("Failed to load tools config:", e);
    }
  }

  async function saveToolsState() {
    const checkboxes = document.querySelectorAll('.tool-checkbox');
    const enabled_tools = {};
    checkboxes.forEach(cb => {
      enabled_tools[cb.dataset.toolId] = cb.checked;
    });

    try {
      await fetch(`${BACKEND_URL}/api/tools`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled_tools })
      });
    } catch (e) {
      console.warn("Failed to save tools state:", e);
    }
  }

  // --- VOICE SELECTION TAB ---
  const voiceGrid = document.getElementById('voice-grid');
  const voiceDefinitions = [
    { id: 'Vivian', name: 'Vivian', desc: 'Bright female voice', lang: 'Chinese' },
    { id: 'Serena', name: 'Serena', desc: 'Warm young female voice', lang: 'Chinese' },
    { id: 'Uncle_Fu', name: 'Uncle Fu', desc: 'Seasoned male voice', lang: 'Chinese' },
    { id: 'Dylan', name: 'Dylan', desc: 'Beijing male voice', lang: 'Chinese (Beijing)' },
    { id: 'Eric', name: 'Eric', desc: 'Chengdu male voice', lang: 'Chinese (Sichuan)' },
    { id: 'Ryan', name: 'Ryan', desc: 'Dynamic male voice', lang: 'English' },
    { id: 'Aiden', name: 'Aiden', desc: 'Sunny American voice', lang: 'English' },
    { id: 'Ono_Anna', name: 'Ono Anna', desc: 'Japanese female voice', lang: 'Japanese' },
    { id: 'Sohee', name: 'Sohee', desc: 'Warm Korean female voice', lang: 'Korean' }
  ];

  async function initVoiceTab() {
    if (!voiceGrid) return;
    try {
      const response = await fetch(`${BACKEND_URL}/api/config`);
      let currentSpeaker = 'Aiden';
      if (response.ok) {
        const data = await response.json();
        currentSpeaker = data.model.tts_speaker || 'Aiden';
      }

      voiceGrid.innerHTML = '';
      voiceDefinitions.forEach(voice => {
        const isActive = voice.id === currentSpeaker;
        const card = document.createElement('div');
        card.className = `voice-card ${isActive ? 'selected' : ''}`;
        card.dataset.voiceId = voice.id;
        
        card.style.background = 'rgba(255,255,255,0.02)';
        card.style.border = '1px solid rgba(255,255,255,0.05)';
        card.style.padding = '12px';
        card.style.borderRadius = '8px';
        card.style.cursor = 'pointer';
        card.style.transition = 'all 0.2s ease';
        
        if (isActive) {
          card.style.borderColor = 'var(--accent-cyan)';
          card.style.background = 'rgba(0, 195, 255, 0.08)';
          card.style.boxShadow = '0 0 10px rgba(0, 195, 255, 0.15)';
        }

        card.innerHTML = `
          <h3 style="font-size: 13px; font-weight: 600; margin-bottom: 2px; color: var(--text-main);">${voice.name}</h3>
          <p style="font-size: 11px; color: var(--text-muted); margin-bottom: 6px;">${voice.desc}</p>
          <span style="font-size: 9px; padding: 2px 6px; background: rgba(0,195,255,0.1); color: var(--accent-cyan); border-radius: 4px; font-weight: 600; text-transform: uppercase;">${voice.lang}</span>
        `;

        card.addEventListener('click', () => selectVoicePreset(voice.id));
        voiceGrid.appendChild(card);
      });
    } catch (e) {
      console.error("Failed to load voice presets:", e);
    }
  }

  async function selectVoicePreset(speakerId) {
    document.querySelectorAll('.voice-card').forEach(card => {
      if (card.dataset.voiceId === speakerId) {
        card.style.borderColor = 'var(--accent-cyan)';
        card.style.background = 'rgba(0, 195, 255, 0.08)';
        card.style.boxShadow = '0 0 10px rgba(0, 195, 255, 0.15)';
      } else {
        card.style.borderColor = 'rgba(255,255,255,0.05)';
        card.style.background = 'rgba(255,255,255,0.02)';
        card.style.boxShadow = 'none';
      }
    });

    try {
      await fetch(`${BACKEND_URL}/api/voice`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ speaker: speakerId })
      });
    } catch (e) {
      console.warn("Failed to set speaker voice:", e);
    }
  }

  // --- WEB SHARING / PORT TUNNELING ---
  const shareService = document.getElementById('share-service');
  const shareNgrokToken = document.getElementById('share-ngrok-token');
  const shareNgrokDomain = document.getElementById('share-ngrok-domain');
  const shareAutostart = document.getElementById('share-autostart');
  const shareRemoteControl = document.getElementById('share-remote-control');
  const btnSaveSharing = document.getElementById('btn-save-sharing');
  const btnToggleSharing = document.getElementById('btn-toggle-sharing');
  const shareStatusDot = document.getElementById('share-status-dot');
  const shareStatusText = document.getElementById('share-status-text');
  const shareUrlContainer = document.getElementById('share-url-container');
  const shareUrlInput = document.getElementById('share-url-input');
  const btnCopyShareUrl = document.getElementById('btn-copy-share-url');
  const shareQrImage = document.getElementById('share-qr-image');
  const shareQrLoading = document.getElementById('share-qr-loading');
  const shareErrorMessage = document.getElementById('share-error-message');

  const ngrokTokenGroup = document.getElementById('ngrok-token-group');
  const ngrokDomainGroup = document.getElementById('ngrok-domain-group');
  
  // Email Integration Elements
  const shareEmailEnabled = document.getElementById('share-email-enabled');
  const shareEmailProvider = document.getElementById('share-email-provider');
  const shareEmailHost = document.getElementById('share-email-host');
  const shareEmailPort = document.getElementById('share-email-port');
  const shareEmailUser = document.getElementById('share-email-user');
  const shareEmailPass = document.getElementById('share-email-pass');
  const shareEmailRecipient = document.getElementById('share-email-recipient');
  const shareEmailOnStartup = document.getElementById('share-email-on-startup');
  const emailSettingsGroup = document.getElementById('email-settings-group');

  // Pushbullet Notification Elements
  const sharePushbulletEnabled = document.getElementById('share-pushbullet-enabled');
  const sharePushbulletToken = document.getElementById('share-pushbullet-token');
  const pushbulletSettingsGroup = document.getElementById('pushbullet-settings-group');

  function toggleEmailFieldsVisibility() {
    if (!shareEmailEnabled || !emailSettingsGroup) return;
    emailSettingsGroup.style.display = shareEmailEnabled.checked ? 'flex' : 'none';
  }

  function togglePushbulletFieldsVisibility() {
    if (!sharePushbulletEnabled || !pushbulletSettingsGroup) return;
    pushbulletSettingsGroup.style.display = sharePushbulletEnabled.checked ? 'flex' : 'none';
  }

  if (shareEmailEnabled) {
    shareEmailEnabled.addEventListener('change', toggleEmailFieldsVisibility);
  }

  if (sharePushbulletEnabled) {
    sharePushbulletEnabled.addEventListener('change', togglePushbulletFieldsVisibility);
  }

  if (shareEmailProvider) {
    shareEmailProvider.addEventListener('change', () => {
      const val = shareEmailProvider.value;
      if (val === 'gmail') {
        if (shareEmailHost) shareEmailHost.value = 'smtp.gmail.com';
        if (shareEmailPort) shareEmailPort.value = '587';
      } else if (val === 'outlook') {
        if (shareEmailHost) shareEmailHost.value = 'smtp.office365.com';
        if (shareEmailPort) shareEmailPort.value = '587';
      } else if (val === 'yahoo') {
        if (shareEmailHost) shareEmailHost.value = 'smtp.mail.yahoo.com';
        if (shareEmailPort) shareEmailPort.value = '587';
      } else if (val === 'custom') {
        if (shareEmailHost) shareEmailHost.value = '';
        if (shareEmailPort) shareEmailPort.value = '587';
      }
    });
  }

  // Hide sharing tab and TTS button in remote browser
  const isElectron = typeof window.api !== 'undefined';
  if (!isElectron) {
    const sharingTab = document.querySelector('.nav-tab[data-tab="sharing"]');
    if (sharingTab) sharingTab.style.display = 'none';
    if (btnTogglePlaybackSpeak) btnTogglePlaybackSpeak.style.display = 'none';
  }

  function handleServiceFieldsVisibility() {
    if (!shareService) return;
    const service = shareService.value;
    
    if (service === 'localhostrun') {
      if (ngrokTokenGroup) ngrokTokenGroup.style.display = 'none';
      if (ngrokDomainGroup) ngrokDomainGroup.style.display = 'none';
    } else if (service === 'ngrok') {
      if (ngrokTokenGroup) ngrokTokenGroup.style.display = 'flex';
      if (ngrokDomainGroup) ngrokDomainGroup.style.display = 'flex';
    }
  }

  if (shareService) {
    shareService.addEventListener('change', handleServiceFieldsVisibility);
  }

  async function loadSharingConfig() {
    if (!isElectron) return;
    try {
      const config = await window.api.getSharingConfig();
      if (shareService) shareService.value = config.service || 'ngrok';
      if (shareNgrokToken) shareNgrokToken.value = config.ngrok_token || '';
      if (shareNgrokDomain) shareNgrokDomain.value = config.ngrok_domain || '';
      if (shareAutostart) shareAutostart.checked = config.autostart || false;
      if (shareRemoteControl) shareRemoteControl.checked = config.remote_control_enabled || false;
      
      // Load email fields
      if (shareEmailEnabled) shareEmailEnabled.checked = config.email_enabled || false;
      if (shareEmailProvider) shareEmailProvider.value = config.email_provider || 'gmail';
      if (shareEmailHost) shareEmailHost.value = config.email_host || '';
      if (shareEmailPort) shareEmailPort.value = config.email_port || '587';
      if (shareEmailUser) shareEmailUser.value = config.email_user || '';
      if (shareEmailPass) shareEmailPass.value = config.email_pass || '';
      if (shareEmailRecipient) shareEmailRecipient.value = config.email_recipient || '';
      if (shareEmailOnStartup) shareEmailOnStartup.checked = config.email_on_startup || false;
      
      // Load pushbullet fields
      if (sharePushbulletEnabled) sharePushbulletEnabled.checked = config.pushbullet_enabled || false;
      if (sharePushbulletToken) sharePushbulletToken.value = config.pushbullet_token || '';
      
      toggleEmailFieldsVisibility();
      togglePushbulletFieldsVisibility();
      handleServiceFieldsVisibility();
      
      const status = await window.api.getSharingStatus();
      updateSharingUI(status);
    } catch (e) {
      console.error("Failed to load sharing config:", e);
    }
  }

  function updateSharingUI(statusInfo) {
    if (!shareStatusDot || !shareStatusText) return;
    const { status, url, error } = statusInfo;
    
    if (status === 'online') {
      shareStatusDot.className = 'status-dot active';
      shareStatusDot.style.background = '#10b981'; // Green
      shareStatusText.textContent = 'Online';
      if (btnToggleSharing) {
        btnToggleSharing.textContent = 'Disable Web Sharing';
        btnToggleSharing.style.background = 'rgba(239, 68, 68, 0.15)';
        btnToggleSharing.style.borderColor = 'rgba(239, 68, 68, 0.3)';
      }
      
      if (shareUrlContainer) shareUrlContainer.style.display = 'flex';
      if (shareUrlInput) shareUrlInput.value = url;
      if (shareErrorMessage) shareErrorMessage.style.display = 'none';
      
      // Load QR Code
      if (shareQrImage && shareQrLoading) {
        shareQrImage.style.display = 'none';
        shareQrLoading.style.display = 'block';
        shareQrImage.src = `https://api.qrserver.com/v1/create-qr-code/?size=150x150&data=${encodeURIComponent(url)}`;
        shareQrImage.onload = () => {
          shareQrLoading.style.display = 'none';
          shareQrImage.style.display = 'block';
        };
      }
    } else if (status === 'starting') {
      shareStatusDot.className = 'status-dot typing';
      shareStatusDot.style.background = '#f59e0b'; // Amber
      shareStatusText.textContent = error || 'Starting Tunnel...';
      if (btnToggleSharing) {
        btnToggleSharing.textContent = 'Disable Web Sharing';
        btnToggleSharing.style.background = 'rgba(239, 68, 68, 0.15)';
        btnToggleSharing.style.borderColor = 'rgba(239, 68, 68, 0.3)';
      }
      if (shareUrlContainer) shareUrlContainer.style.display = 'none';
      if (shareErrorMessage) shareErrorMessage.style.display = 'none';
    } else if (status === 'error') {
      shareStatusDot.className = 'status-dot';
      shareStatusDot.style.background = '#ef4444'; // Red
      shareStatusText.textContent = 'Error';
      if (btnToggleSharing) {
        btnToggleSharing.textContent = 'Enable Web Sharing';
        btnToggleSharing.style.background = 'rgba(0, 102, 255, 0.15)';
        btnToggleSharing.style.borderColor = 'rgba(0, 102, 255, 0.3)';
      }
      if (shareUrlContainer) shareUrlContainer.style.display = 'none';
      if (shareErrorMessage) {
        shareErrorMessage.style.display = 'block';
        shareErrorMessage.textContent = error || 'Tunnel connection failed.';
      }
    } else {
      // offline
      shareStatusDot.className = 'status-dot';
      shareStatusDot.style.background = 'var(--text-dim)';
      shareStatusText.textContent = 'Offline';
      if (btnToggleSharing) {
        btnToggleSharing.textContent = 'Enable Web Sharing';
        btnToggleSharing.style.background = 'rgba(0, 102, 255, 0.15)';
        btnToggleSharing.style.borderColor = 'rgba(0, 102, 255, 0.3)';
      }
      if (shareUrlContainer) shareUrlContainer.style.display = 'none';
      if (shareErrorMessage) shareErrorMessage.style.display = 'none';
    }
  }

  if (isElectron) {
    if (btnSaveSharing) {
      btnSaveSharing.addEventListener('click', async () => {
        const config = {
          enabled: false,
          service: shareService.value,
          ngrok_token: shareNgrokToken.value.trim(),
          ngrok_domain: shareNgrokDomain.value.trim(),
          autostart: shareAutostart.checked,
          email_enabled: shareEmailEnabled ? shareEmailEnabled.checked : false,
          email_provider: shareEmailProvider ? shareEmailProvider.value : 'gmail',
          email_host: shareEmailHost ? shareEmailHost.value.trim() : '',
          email_port: shareEmailPort ? parseInt(shareEmailPort.value) : 587,
          email_user: shareEmailUser ? shareEmailUser.value.trim() : '',
          email_pass: shareEmailPass ? shareEmailPass.value.trim() : '',
          email_recipient: shareEmailRecipient ? shareEmailRecipient.value.trim() : '',
          email_on_startup: shareEmailOnStartup ? shareEmailOnStartup.checked : false,
          remote_control_enabled: shareRemoteControl ? shareRemoteControl.checked : false,
          pushbullet_enabled: sharePushbulletEnabled ? sharePushbulletEnabled.checked : false,
          pushbullet_token: sharePushbulletToken ? sharePushbulletToken.value.trim() : ''
        };
        
        try {
          const oldConfig = await window.api.getSharingConfig();
          config.enabled = oldConfig.enabled;
          
          const result = await window.api.saveSharingConfig(config);
          if (result.success) {
            alert("Sharing configuration saved successfully.");
          } else {
            alert("Failed to save sharing configuration: " + result.error);
          }
        } catch (e) {
          console.error("Save config error:", e);
        }
      });
    }

    if (btnToggleSharing) {
      btnToggleSharing.addEventListener('click', async () => {
        if (btnToggleSharing.disabled) return;
        btnToggleSharing.disabled = true;
        const originalText = btnToggleSharing.textContent;
        btnToggleSharing.textContent = "Processing...";
        
        try {
          const statusInfo = await window.api.getSharingStatus();
          const shouldEnable = statusInfo.status === 'offline' || statusInfo.status === 'error';
          
          const config = {
            enabled: shouldEnable,
            service: shareService.value,
            ngrok_token: shareNgrokToken.value.trim(),
            ngrok_domain: shareNgrokDomain.value.trim(),
            autostart: shareAutostart.checked,
            email_enabled: shareEmailEnabled ? shareEmailEnabled.checked : false,
            email_provider: shareEmailProvider ? shareEmailProvider.value : 'gmail',
            email_host: shareEmailHost ? shareEmailHost.value.trim() : '',
            email_port: shareEmailPort ? parseInt(shareEmailPort.value) : 587,
            email_user: shareEmailUser ? shareEmailUser.value.trim() : '',
            email_pass: shareEmailPass ? shareEmailPass.value.trim() : '',
            email_recipient: shareEmailRecipient ? shareEmailRecipient.value.trim() : '',
            email_on_startup: shareEmailOnStartup ? shareEmailOnStartup.checked : false,
            remote_control_enabled: shareRemoteControl ? shareRemoteControl.checked : false,
            pushbullet_enabled: sharePushbulletEnabled ? sharePushbulletEnabled.checked : false,
            pushbullet_token: sharePushbulletToken ? sharePushbulletToken.value.trim() : ''
          };
          await window.api.saveSharingConfig(config);
          await window.api.toggleSharing(shouldEnable, config);
        } catch (e) {
          console.error("Toggle sharing error:", e);
        } finally {
          setTimeout(() => {
            if (btnToggleSharing) {
              btnToggleSharing.disabled = false;
            }
          }, 2000);
        }
      });
    }

    if (btnCopyShareUrl && shareUrlInput) {
      btnCopyShareUrl.addEventListener('click', () => {
        navigator.clipboard.writeText(shareUrlInput.value).then(() => {
          btnCopyShareUrl.textContent = "Copied!";
          setTimeout(() => {
            btnCopyShareUrl.textContent = "Copy";
          }, 1500);
        });
      });
    }

    let sharingPollInterval = null;
    function startSharingPolling() {
      if (sharingPollInterval) clearInterval(sharingPollInterval);
      sharingPollInterval = setInterval(async () => {
        if (typeof window.api !== 'undefined') {
          try {
            const status = await window.api.getSharingStatus();
            updateSharingUI(status);
          } catch (e) {
            console.error("Error polling sharing status:", e);
          }
        }
      }, 2000);
    }
    window.startSharingPolling = startSharingPolling; // Export to tab switch handler

    function stopSharingPolling() {
      if (sharingPollInterval) {
        clearInterval(sharingPollInterval);
        sharingPollInterval = null;
      }
    }
    window.stopSharingPolling = stopSharingPolling; // Export to tab switch handler

    if (typeof window.api !== 'undefined' && window.api.onSharingStatusChanged) {
      window.api.onSharingStatusChanged((statusInfo) => {
        updateSharingUI(statusInfo);
      });
    }
    
    setTimeout(() => {
      loadSharingConfig();
      const activeTab = document.querySelector('.nav-tab.active');
      if (activeTab && activeTab.dataset.tab === 'sharing') {
        startSharingPolling();
      }
    }, 1000);
  }

  // --- REMOTE CONTROL TAB FUNCTIONALITY ---
  let isRemoteInitialized = false;
  let remoteSelectedPaths = new Set();
  let remoteCurrentPath = '';
  let dragStartCoords = null;
  let dragEndCoords = null;
  let clickCoords = null;

  function initRemoteControl() {
    if (isRemoteInitialized) {
      loadRemoteScreenshot();
      return;
    }
    
    isRemoteInitialized = true;
    
    const actionSelect = document.getElementById('action-select');
    const actionTypeContainer = document.getElementById('action-type-container');
    const actionKeyContainer = document.getElementById('action-key-container');
    const actionDragHelp = document.getElementById('action-drag-help');
    
    actionSelect.addEventListener('change', () => {
      const act = actionSelect.value;
      actionTypeContainer.style.display = act === 'type' ? 'block' : 'none';
      actionKeyContainer.style.display = act === 'press_key' ? 'block' : 'none';
      actionDragHelp.style.display = act === 'drag' ? 'block' : 'none';
      
      clearScreenMarkers();
    });
    
    const screenImg = document.getElementById('screen-img');
    screenImg.addEventListener('click', (e) => {
      const rect = screenImg.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width;
      const y = (e.clientY - rect.top) / rect.height;
      
      const act = actionSelect.value;
      if (act === 'drag') {
        if (!dragStartCoords) {
          dragStartCoords = { x, y };
          placeMarkerOnScreen('screen-marker', x, y);
          hideDragLine();
        } else if (!dragEndCoords) {
          dragEndCoords = { x, y };
          placeMarkerOnScreen('screen-drag-marker', x, y);
          drawDragLineOnScreen();
        } else {
          dragStartCoords = { x, y };
          dragEndCoords = null;
          placeMarkerOnScreen('screen-marker', x, y);
          document.getElementById('screen-drag-marker').style.display = 'none';
          hideDragLine();
        }
      } else {
        clickCoords = { x, y };
        placeMarkerOnScreen('screen-marker', x, y);
        dragStartCoords = null;
        dragEndCoords = null;
        document.getElementById('screen-drag-marker').style.display = 'none';
        hideDragLine();
      }
    });
    
    window.addEventListener('resize', () => {
      const panel = document.getElementById('panel-remote');
      if (panel && panel.classList.contains('active')) {
        repositionMarkers();
      }
    });
    
    document.getElementById('btn-refresh-screen').addEventListener('click', loadRemoteScreenshot);
    document.getElementById('btn-execute-action').addEventListener('click', executeRemoteAction);
    document.getElementById('btn-file-up').addEventListener('click', navigateExplorerUp);
    
    const btnFileRoot = document.getElementById('btn-file-root');
    if (btnFileRoot) {
      btnFileRoot.addEventListener('click', () => {
        document.getElementById('explorer-path-input').value = '';
        remoteCurrentPath = '';
        loadExplorerRoot();
      });
    }
    
    document.getElementById('btn-clear-selection').addEventListener('click', clearExplorerSelection);
    document.getElementById('btn-download-selected').addEventListener('click', downloadSelectedFiles);
    
    loadRemoteScreenshot();
    loadExplorerDesktop(); // Open on desktop by default
  }

  function placeMarkerOnScreen(markerId, x, y) {
    const marker = document.getElementById(markerId);
    const img = document.getElementById('screen-img');
    const container = document.getElementById('screen-container');
    if (!marker || !img || !container) return;
    
    const imgRect = img.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();
    
    const left = (imgRect.left - containerRect.left) + x * imgRect.width;
    const top = (imgRect.top - containerRect.top) + y * imgRect.height;
    
    marker.style.left = `${left}px`;
    marker.style.top = `${top}px`;
    marker.style.display = 'block';
  }

  function repositionMarkers() {
    const actionSelect = document.getElementById('action-select');
    if (!actionSelect) return;
    const act = actionSelect.value;
    if (act === 'drag') {
      if (dragStartCoords) placeMarkerOnScreen('screen-marker', dragStartCoords.x, dragStartCoords.y);
      if (dragEndCoords) {
        placeMarkerOnScreen('screen-drag-marker', dragEndCoords.x, dragEndCoords.y);
        drawDragLineOnScreen();
      }
    } else {
      if (clickCoords) placeMarkerOnScreen('screen-marker', clickCoords.x, clickCoords.y);
    }
  }

  function clearScreenMarkers() {
    dragStartCoords = null;
    dragEndCoords = null;
    clickCoords = null;
    const marker1 = document.getElementById('screen-marker');
    const marker2 = document.getElementById('screen-drag-marker');
    if (marker1) marker1.style.display = 'none';
    if (marker2) marker2.style.display = 'none';
    hideDragLine();
  }

  function drawDragLineOnScreen() {
    if (!dragStartCoords || !dragEndCoords) return;
    const img = document.getElementById('screen-img');
    const container = document.getElementById('screen-container');
    const svg = document.getElementById('screen-drag-line');
    const line = svg ? svg.querySelector('line') : null;
    if (!img || !container || !svg || !line) return;
    
    const imgRect = img.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();
    
    const startX = (imgRect.left - containerRect.left) + dragStartCoords.x * imgRect.width;
    const startY = (imgRect.top - containerRect.top) + dragStartCoords.y * imgRect.height;
    const endX = (imgRect.left - containerRect.left) + dragEndCoords.x * imgRect.width;
    const endY = (imgRect.top - containerRect.top) + dragEndCoords.y * imgRect.height;
    
    line.setAttribute('x1', startX);
    line.setAttribute('y1', startY);
    line.setAttribute('x2', endX);
    line.setAttribute('y2', endY);
    
    svg.style.display = 'block';
  }
  
  function hideDragLine() {
    const svg = document.getElementById('screen-drag-line');
    if (svg) svg.style.display = 'none';
  }

  function loadRemoteScreenshot() {
    const img = document.getElementById('screen-img');
    const loading = document.getElementById('screen-loading');
    if (!img || !loading) return;
    
    loading.style.display = 'flex';
    img.classList.add('loading');
    
    img.onload = () => {
      loading.style.display = 'none';
      img.classList.remove('loading');
      repositionMarkers();
    };
    
    img.onerror = () => {
      loading.style.display = 'none';
      img.classList.remove('loading');
      console.error("Failed to load remote screenshot.");
    };
    
    img.src = `${BACKEND_URL}/api/remote-control/screen/screenshot?t=${Date.now()}`;
  }

  async function executeRemoteAction() {
    const actionSelect = document.getElementById('action-select');
    const act = actionSelect ? actionSelect.value : 'click';
    const btn = document.getElementById('btn-execute-action');
    
    let payload = { action: act };
    
    if (act === 'drag') {
      if (!dragStartCoords || !dragEndCoords) {
        alert("Please set both start and end drag points by clicking on the screen image.");
        return;
      }
      payload.x = dragStartCoords.x;
      payload.y = dragStartCoords.y;
      payload.drag_to_x = dragEndCoords.x;
      payload.drag_to_y = dragEndCoords.y;
    } else if (act === 'type') {
      const textVal = document.getElementById('action-text-input').value;
      if (!textVal) {
        alert("Please enter the text to type.");
        return;
      }
      if (!clickCoords) {
        alert("Please click on the screen image first to set the spot where you want to type.");
        return;
      }
      payload.text = textVal;
      payload.x = clickCoords.x;
      payload.y = clickCoords.y;
    } else if (act === 'press_key') {
      payload.key = document.getElementById('action-key-select').value;
    } else {
      if (!clickCoords) {
        alert("Please click on the screen image first to set coordinates.");
        return;
      }
      payload.x = clickCoords.x;
      payload.y = clickCoords.y;
    }
    
    btn.disabled = true;
    btn.textContent = "Executing...";
    
    try {
      const res = await fetch(`${BACKEND_URL}/api/remote-control/screen/action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.status === 'success') {
        if (act === 'type') {
          document.getElementById('action-text-input').value = '';
        }
        
        appendLogConsole(`[SYSTEM] Executed remote action '${act}' successfully.`);
        clearScreenMarkers();
        loadRemoteScreenshot();
      } else {
        alert("Action execution failed: " + (data.message || "Unknown error"));
      }
    } catch (err) {
      console.error(err);
      alert("Error executing action: " + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "Execute";
    }
  }

  async function loadExplorerDesktop() {
    const tree = document.getElementById('explorer-tree');
    if (!tree) return;
    tree.innerHTML = '<div style="padding: 10px; color: var(--text-muted);">Loading Desktop...</div>';
    
    try {
      const pathRes = await fetch(`${BACKEND_URL}/api/remote-control/files/desktop`);
      const pathData = await pathRes.json();
      const desktopPath = pathData.desktop_path;
      
      document.getElementById('explorer-path-input').value = desktopPath;
      remoteCurrentPath = desktopPath;
      
      const res = await fetch(`${BACKEND_URL}/api/remote-control/files/list?path=${encodeURIComponent(desktopPath)}`);
      const data = await res.json();
      tree.innerHTML = '';
      
      if (data.items && data.items.length > 0) {
        data.items.forEach(item => {
          const node = createTreeNode(item.name, item.path, item.is_dir, item.size);
          tree.appendChild(node);
        });
      } else {
        tree.innerHTML = '<div style="padding: 10px; color: var(--text-muted);">Desktop is empty.</div>';
      }
    } catch (e) {
      tree.innerHTML = `<div style="padding: 10px; color: var(--danger);">Failed to load Desktop: ${e.message}</div>`;
    }
  }

  async function loadExplorerPath(path) {
    const tree = document.getElementById('explorer-tree');
    if (!tree) return;
    tree.innerHTML = '<div style="padding: 10px; color: var(--text-muted);">Loading folder...</div>';
    
    try {
      const res = await fetch(`${BACKEND_URL}/api/remote-control/files/list?path=${encodeURIComponent(path)}`);
      if (!res.ok) {
        throw new Error("Unable to list directory");
      }
      const data = await res.json();
      tree.innerHTML = '';
      
      document.getElementById('explorer-path-input').value = path;
      remoteCurrentPath = path;
      
      if (data.items && data.items.length > 0) {
        data.items.forEach(item => {
          const node = createTreeNode(item.name, item.path, item.is_dir, item.size);
          tree.appendChild(node);
        });
      } else {
        tree.innerHTML = '<div style="padding: 10px; color: var(--text-muted);">Folder is empty.</div>';
      }
    } catch (e) {
      tree.innerHTML = `<div style="padding: 10px; color: var(--danger);">Failed to load folder: ${e.message}</div>`;
    }
  }

  async function loadExplorerRoot() {
    const tree = document.getElementById('explorer-tree');
    if (!tree) return;
    tree.innerHTML = '<div style="padding: 10px; color: var(--text-muted);">Loading drives...</div>';
    
    try {
      const res = await fetch(`${BACKEND_URL}/api/remote-control/files/list`);
      const data = await res.json();
      tree.innerHTML = '';
      
      if (data.drives && data.drives.length > 0) {
        data.drives.forEach(drive => {
          const node = createTreeNode(drive, drive, true);
          tree.appendChild(node);
        });
      } else {
        tree.innerHTML = '<div style="padding: 10px; color: var(--text-muted);">No drives detected.</div>';
      }
    } catch (e) {
      tree.innerHTML = `<div style="padding: 10px; color: var(--danger);">Failed to load drives: ${e.message}</div>`;
    }
  }

  function createTreeNode(name, path, isDir, sizeBytes = 0) {
    const node = document.createElement('div');
    node.className = 'tree-node';
    if (isDir) node.classList.add('folder-node');
    else node.classList.add('file-node');
    node.dataset.path = path;
    node.dataset.loaded = 'false';
    
    const header = document.createElement('div');
    header.className = 'tree-node-header';
    header.style.display = 'flex';
    header.style.alignItems = 'center';
    
    const toggle = document.createElement('span');
    toggle.className = 'tree-toggle';
    if (isDir) {
      toggle.textContent = '▶';
    } else {
      toggle.style.opacity = '0';
      toggle.textContent = '';
    }
    header.appendChild(toggle);
    
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'tree-checkbox';
    checkbox.dataset.path = path;
    
    checkbox.addEventListener('change', (e) => {
      if (isDir) {
        const childrenContainer = node.querySelector('.tree-node-children');
        if (childrenContainer) {
          const childCheckboxes = childrenContainer.querySelectorAll('.tree-checkbox');
          childCheckboxes.forEach(cb => {
            cb.checked = checkbox.checked;
            if (checkbox.checked) {
              remoteSelectedPaths.add(cb.dataset.path);
            } else {
              remoteSelectedPaths.delete(cb.dataset.path);
            }
          });
        }
      }
      
      if (checkbox.checked) {
        remoteSelectedPaths.add(path);
      } else {
        remoteSelectedPaths.delete(path);
      }
      updateSelectionActionBar();
      e.stopPropagation();
    });
    header.appendChild(checkbox);
    
    const icon = document.createElement('span');
    icon.className = 'tree-icon';
    icon.textContent = isDir ? '📁' : '📄';
    header.appendChild(icon);
    
    const label = document.createElement('span');
    label.className = 'tree-label';
    label.textContent = name;
    header.appendChild(label);
    
    if (!isDir) {
      const sizeSpan = document.createElement('span');
      sizeSpan.className = 'tree-size';
      sizeSpan.textContent = formatBytes(sizeBytes);
      header.appendChild(sizeSpan);
    }
    
    node.appendChild(header);
    
    if (isDir) {
      const children = document.createElement('div');
      children.className = 'tree-node-children';
      children.style.display = 'none';
      node.appendChild(children);
      
      header.addEventListener('click', (e) => {
        if (e.target === checkbox) return;
        toggleFolderNode(node);
      });

      header.addEventListener('dblclick', (e) => {
        if (e.target === checkbox) return;
        e.stopPropagation();
        loadExplorerPath(path);
      });
    }
    
    return node;
  }

  function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }

  function toggleFolderNode(nodeEl) {
    const path = nodeEl.dataset.path;
    const childrenContainer = nodeEl.querySelector('.tree-node-children');
    const toggle = nodeEl.querySelector('.tree-toggle');
    const isExpanded = childrenContainer.style.display === 'block';
    
    document.getElementById('explorer-path-input').value = path;
    remoteCurrentPath = path;
    
    document.querySelectorAll('.tree-node').forEach(n => n.classList.remove('active'));
    nodeEl.classList.add('active');
    
    if (isExpanded) {
      childrenContainer.style.display = 'none';
      toggle.classList.remove('expanded');
    } else {
      childrenContainer.style.display = 'block';
      toggle.classList.add('expanded');
      
      if (nodeEl.dataset.loaded === 'false') {
        loadFolderChildren(nodeEl, childrenContainer, path);
      }
    }
  }

  async function loadFolderChildren(nodeEl, childrenContainer, path) {
    childrenContainer.innerHTML = '<div style="padding: 6px; color: var(--text-dim); font-size: 11px;">Loading...</div>';
    
    try {
      const res = await fetch(`${BACKEND_URL}/api/remote-control/files/list?path=${encodeURIComponent(path)}`);
      if (!res.ok) {
        throw new Error("Unable to list directory");
      }
      const data = await res.json();
      childrenContainer.innerHTML = '';
      nodeEl.dataset.loaded = 'true';
      
      const parentCheckbox = nodeEl.querySelector('.tree-checkbox');
      const isParentChecked = parentCheckbox ? parentCheckbox.checked : false;
      
      if (data.items && data.items.length > 0) {
        data.items.forEach(item => {
          const childNode = createTreeNode(item.name, item.path, item.is_dir, item.size);
          
          if (isParentChecked) {
            const childCheckbox = childNode.querySelector('.tree-checkbox');
            if (childCheckbox) {
              childCheckbox.checked = true;
            }
            remoteSelectedPaths.add(item.path);
          }
          
          childrenContainer.appendChild(childNode);
        });
      } else {
        childrenContainer.innerHTML = '<div style="padding: 6px; color: var(--text-dim); font-size: 11px;">Empty Folder</div>';
      }
      
      updateSelectionActionBar();
    } catch (err) {
      childrenContainer.innerHTML = `<div style="padding: 6px; color: var(--danger); font-size: 11px;">Error: ${err.message}</div>`;
      nodeEl.dataset.loaded = 'false';
    }
  }

  function navigateExplorerUp() {
    if (!remoteCurrentPath) return;
    
    let parentPath = '';
    if (remoteCurrentPath.includes('\\')) {
      let parts = remoteCurrentPath.split('\\').filter(Boolean);
      if (parts.length > 1) {
        parts.pop();
        parentPath = parts.join('\\') + (parts.length === 1 ? '\\' : '');
      }
    } else {
      let parts = remoteCurrentPath.split('/').filter(Boolean);
      if (parts.length > 0) {
        parts.pop();
        parentPath = '/' + parts.join('/');
      }
    }
    
    if (!parentPath || parentPath === '/' || parentPath === '') {
      loadExplorerRoot();
      document.getElementById('explorer-path-input').value = '';
      remoteCurrentPath = '';
    } else {
      document.getElementById('explorer-path-input').value = parentPath;
      remoteCurrentPath = parentPath;
      
      const nodeEl = document.querySelector(`.tree-node[data-path="${parentPath.replace(/\\/g, '\\\\')}"]`);
      if (nodeEl) {
        nodeEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        document.querySelectorAll('.tree-node').forEach(n => n.classList.remove('active'));
        nodeEl.classList.add('active');
        
        // Actually load the children/files of the parent folder to update the file explorer
        const childrenContainer = nodeEl.querySelector('.tree-node-children');
        const toggle = nodeEl.querySelector('.tree-toggle');
        if (childrenContainer && toggle) {
          childrenContainer.style.display = 'block';
          toggle.classList.add('expanded');
          loadFolderChildren(nodeEl, childrenContainer, parentPath);
        }
      } else {
        // If the parent folder node is not present in the DOM tree, load it flat at the root
        loadExplorerPath(parentPath);
      }
    }
  }

  function updateSelectionActionBar() {
    const actionBar = document.getElementById('explorer-actions');
    const countText = document.getElementById('selected-count-text');
    if (!actionBar || !countText) return;
    
    if (remoteSelectedPaths.size > 0) {
      actionBar.style.display = 'flex';
      countText.textContent = `${remoteSelectedPaths.size} item(s) selected`;
    } else {
      actionBar.style.display = 'none';
    }
  }
  
  function clearExplorerSelection() {
    remoteSelectedPaths.clear();
    document.querySelectorAll('.tree-checkbox').forEach(cb => cb.checked = false);
    updateSelectionActionBar();
  }

  async function downloadSelectedFiles() {
    const btn = document.getElementById('btn-download-selected');
    const paths = Array.from(remoteSelectedPaths);
    
    if (paths.length === 0) return;
    
    btn.disabled = true;
    btn.textContent = "Downloading...";
    
    try {
      const response = await fetch(`${BACKEND_URL}/api/remote-control/files/download`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paths })
      });
      
      if (!response.ok) {
        const errText = await response.text();
        throw new Error(errText || "Download generation failed.");
      }
      
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      
      const disposition = response.headers.get('Content-Disposition');
      let filename = 'download.zip';
      if (disposition && disposition.includes('filename=')) {
        filename = disposition.split('filename=')[1].split(';')[0].replace(/['"]/g, '').trim();
      } else {
        filename = paths.length === 1 ? paths[0].split(/[/\\]/).pop() : `adam_transfer_${Date.now()}.zip`;
      }
      
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      
      clearExplorerSelection();
      appendLogConsole(`[SYSTEM] Downloaded ${paths.length} file(s) successfully.`);
    } catch (e) {
      console.error(e);
      alert("Failed to download selected files: " + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "Download";
    }
  }

  // --- INITIALIZATION ---
  renderSessions();
  if (sessions.length > 0 && currentSessionId) {
    selectSession(currentSessionId);
  }
  syncSessions(true);
  initToolsTab();
  initVoiceTab();
  connectEventSource();
});
