const BACKEND_URL = (window.location.protocol === 'file:' || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') 
  ? 'http://127.0.0.1:8000' 
  : window.location.origin;

document.addEventListener('DOMContentLoaded', () => {
  if (typeof window.api === 'undefined') {
    document.body.classList.add('not-electron');
  }
  const statusTitle = document.getElementById('status-title');
  const progressBar = document.getElementById('progress-bar');
  
  const errorCard = document.getElementById('error-card');
  const errorType = document.getElementById('error-type');
  const errorCause = document.getElementById('error-cause');
  
  const btnBack = document.getElementById('btn-back');
  const btnStart = document.getElementById('btn-start');
  const glowContainer = document.getElementById('glow-container');
  const corePulseOrb = document.getElementById('core-pulse-orb');

  let pollInterval = null;

  async function checkSetupProgress() {
    try {
      const response = await fetch(`${BACKEND_URL}/api/setup/status`);
      if (!response.ok) return;

      const data = await response.json();
      const progress = data.progress;
      // Update global progress bar
      progressBar.style.width = `${progress}%`;

      // Update vertical timeline track fill
      const timelineFill = document.getElementById('timeline-fill');
      if (timelineFill) {
        timelineFill.style.height = `${progress}%`;
      }

      // Dynamically show/hide service pipeline steps based on selection
      if (data.stt_enabled === false) {
        document.getElementById('step-4').style.display = 'none';
        document.getElementById('step-7').style.display = 'none';
      } else {
        document.getElementById('step-4').style.display = 'flex';
        document.getElementById('step-7').style.display = 'flex';
      }

      if (data.tts_enabled === false) {
        document.getElementById('step-5').style.display = 'none';
      } else {
        document.getElementById('step-5').style.display = 'flex';
      }

      // Update vertical steps list
      // Progress thresholds mapping to completed steps
      const thresholds = [15, 30, 45, 65, 80, 90, 95, 100];
      const activeTitles = [
        "Releasing system resources...",
        "Configuring context matrices...",
        "Launching inference server...",
        "Caching active model weights...",
        "Allocating transcription memory...",
        "Optimizing speaker synthesis...",
        "Warming up vocal paths...",
        "Binding duplex speech queues..."
      ];

      let activeIndex = 0;
      for (let i = 0; i < 8; i++) {
        const stepEl = document.getElementById(`step-${i}`);
        if (!stepEl) continue;

        // Skip updates for skipped elements
        if (i === 4 && data.stt_enabled === false) continue;
        if (i === 7 && data.stt_enabled === false) continue;
        if (i === 5 && data.tts_enabled === false) continue;

        if (progress >= thresholds[i]) {
          stepEl.className = 'step-item completed';
        } else if ((i === 0 && progress < thresholds[0]) || (i > 0 && progress >= thresholds[i-1] && progress < thresholds[i])) {
          stepEl.className = 'step-item active';
          activeIndex = i;
        } else {
          stepEl.className = 'step-item';
        }
      }

      // Update status title dynamically
      if (progress === 100) {
        statusTitle.textContent = "Adam is Online";
      } else if (data.error) {
        statusTitle.textContent = "Initialization Failed";
      } else {
        statusTitle.textContent = activeTitles[activeIndex] || "Initializing components...";
      }

      // Handle Errors
      if (data.error) {
        clearInterval(pollInterval);
        
        // Show errors
        statusTitle.textContent = "Engine Initialization Failure";
        statusTitle.style.background = "none";
        statusTitle.style.color = "var(--danger)";
        
        errorType.textContent = `${data.error}`;
        errorCause.textContent = data.cause || "No cause specified. Check python terminal console logs.";
        errorCard.style.display = "block";
        
        // Highlight active step as failed
        for (let i = 0; i < 8; i++) {
          const stepEl = document.getElementById(`step-${i}`);
          if (stepEl && stepEl.classList.contains('active')) {
            stepEl.className = 'step-item failed';
          }
        }

        btnBack.classList.remove('hidden');
        btnStart.disabled = true;

        // Change container style to error theme
        glowContainer.classList.remove('glowing');
        glowContainer.classList.add('errored');
        progressBar.style.background = 'var(--danger)';
        progressBar.style.boxShadow = '0 0 10px rgba(239, 68, 68, 0.8)';
        
        // Turn core pulse red
        corePulseOrb.style.background = 'var(--danger)';
        corePulseOrb.style.boxShadow = '0 0 20px rgba(239, 68, 68, 0.8)';
        return;
      }

      // Handle Completion
      if (progress === 100) {
        clearInterval(pollInterval);
        statusTitle.textContent = "Neural Engine Online";
        
        // Auto-proceed after a small pleasant delay
        setTimeout(() => {
          if (typeof window.api !== 'undefined' && window.api.navigateToMain) {
            window.api.navigateToMain();
          } else {
            window.location.href = 'main.html';
          }
        }, 1200);
      }
    } catch (e) {
      console.error("Error fetching progress:", e);
    }
  }

  // Bind Buttons
  btnBack.addEventListener('click', async () => {
    try {
      await fetch(`${BACKEND_URL}/api/unload`, { method: 'POST' });
    } catch (e) {
      console.error("Failed to reset setup status:", e);
    }
    if (typeof window.api !== 'undefined' && window.api.navigateToSelection) {
      window.api.navigateToSelection();
    } else {
      window.location.href = 'selection.html';
    }
  });

  btnStart.addEventListener('click', () => {
    if (typeof window.api !== 'undefined' && window.api.navigateToMain) {
      window.api.navigateToMain();
    } else {
      window.location.href = 'main.html';
    }
  });

  // Start Polling progress
  pollInterval = setInterval(checkSetupProgress, 400);
  checkSetupProgress();
});
