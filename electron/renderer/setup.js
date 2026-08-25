const BACKEND_URL = (window.location.protocol === 'file:' || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') 
  ? 'http://127.0.0.1:8000' 
  : window.location.origin;

document.addEventListener('DOMContentLoaded', () => {
  if (typeof window.api === 'undefined') {
    document.body.classList.add('not-electron');
  }
  const statusTitle = document.getElementById('status-title');
  const telemetrySubtext = document.getElementById('telemetry-subtext');
  const progressBar = document.getElementById('progress-bar');
  
  const errorCard = document.getElementById('error-card');
  const errorType = document.getElementById('error-type');
  const errorCause = document.getElementById('error-cause');
  
  const btnBack = document.getElementById('btn-back');
  const btnStart = document.getElementById('btn-start');
  const glowContainer = document.getElementById('glow-container');
  const corePulseOrb = document.getElementById('core-pulse-orb');

  let pollInterval = null;

  // Cinematic status title update helper (smooth fade/slide transition)
  function setStatusTitle(text) {
    if (statusTitle.textContent === text) return;
    statusTitle.classList.add('updating');
    setTimeout(() => {
      statusTitle.textContent = text;
      statusTitle.classList.remove('updating');
    }, 200);
  }

  async function checkSetupProgress() {
    try {
      const response = await fetch(`${BACKEND_URL}/api/setup/status`);
      if (!response.ok) return;

      const data = await response.json();
      const progress = data.progress;
      
      // Update global progress bar width
      progressBar.style.width = `${progress}%`;

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

      // Build visible steps mapping
      const visibleSteps = [];
      for (let i = 0; i < 8; i++) {
        const stepEl = document.getElementById(`step-${i}`);
        if (stepEl && stepEl.style.display !== 'none') {
          visibleSteps.push({ index: i, element: stepEl });
        }
      }

      // Hide trailing connector strictly on the last visible step
      visibleSteps.forEach(step => {
        const conn = step.element.querySelector('.step-connector');
        if (conn) conn.style.display = 'block';
      });
      if (visibleSteps.length > 0) {
        const lastStep = visibleSteps[visibleSteps.length - 1];
        const lastConn = lastStep.element.querySelector('.step-connector');
        if (lastConn) lastConn.style.display = 'none';
      }

      // Update vertical timeline and node circles
      let activeIndex = -1;
      
      // First pass: identify active index
      visibleSteps.forEach((step, idx) => {
        const i = step.index;
        const prevThresh = i > 0 ? thresholds[i - 1] : 0;
        const currThresh = thresholds[i];
        if (progress >= prevThresh && progress < currThresh && activeIndex === -1) {
          activeIndex = idx;
        }
      });
      if (progress === 100) {
        activeIndex = visibleSteps.length;
      }

      // Second pass: style nodes and connectors
      visibleSteps.forEach((step, idx) => {
        const i = step.index;
        const prevThresh = i > 0 ? thresholds[i - 1] : 0;
        const currThresh = thresholds[i];
        const fill = document.getElementById(`fill-${i}`);

        if (idx < activeIndex) {
          // Completed node
          step.element.className = 'step-item completed';
          if (fill) {
            fill.style.height = '100%';
            // If it is the segment right before the active step, color it sky-blue
            if (idx === activeIndex - 1) {
              fill.style.backgroundColor = '#38bdf8';
              fill.style.boxShadow = '0 0 6px rgba(56, 189, 248, 0.5)';
            } else {
              fill.style.backgroundColor = '#10b981';
              fill.style.boxShadow = '0 0 6px rgba(16, 185, 129, 0.5)';
            }
          }
        } else if (idx === activeIndex) {
          // Active node
          step.element.className = 'step-item active';
          if (fill) {
            const ratio = (progress - prevThresh) / (currThresh - prevThresh);
            fill.style.height = `${Math.min(100, Math.max(0, ratio * 100))}%`;
            fill.style.backgroundColor = '#38bdf8';
            fill.style.boxShadow = '0 0 6px rgba(56, 189, 248, 0.5)';
          }
        } else {
          // Pending node
          step.element.className = 'step-item';
          if (fill) {
            fill.style.height = '0%';
          }
        }
      });

      // Update status title smoothly
      if (progress === 100) {
        setStatusTitle("Neural Engine Online");
      } else if (data.error) {
        setStatusTitle("Initialization Failed");
      } else {
        setStatusTitle(activeTitles[activeIndex >= 0 ? visibleSteps[activeIndex].index : 0] || "Initializing components...");
      }

      // Display the accurate backend status text directly (short and to the point)
      let telemetryText = data.status || "Initializing systems...";
      if (progress === 100) {
        telemetryText = "Duplex speech assistant ready.";
      }
      telemetrySubtext.textContent = telemetryText;

      // Handle Errors
      if (data.error) {
        clearInterval(pollInterval);
        
        setStatusTitle("Engine Initialization Failure");
        statusTitle.style.background = "none";
        statusTitle.style.color = "var(--danger)";
        
        errorType.textContent = `${data.error}`;
        errorCause.textContent = data.cause || "No cause specified. Check python terminal console logs.";
        errorCard.style.display = "block";
        
        // Mark active step as failed
        visibleSteps.forEach(step => {
          if (step.element.classList.contains('active')) {
            step.element.className = 'step-item failed';
          }
        });

        btnBack.classList.remove('hidden');
        btnStart.disabled = true;

        glowContainer.classList.remove('glowing');
        glowContainer.classList.add('errored');
        progressBar.style.background = 'var(--danger)';
        progressBar.style.boxShadow = '0 0 10px rgba(239, 68, 68, 0.8)';
        
        if (corePulseOrb) {
          corePulseOrb.style.background = 'var(--danger)';
          corePulseOrb.style.boxShadow = '0 0 20px rgba(239, 68, 68, 0.8)';
        }
        return;
      }

      // Handle Completion
      if (progress === 100) {
        clearInterval(pollInterval);
        
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

  // Bind glass tactile action buttons
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

  // Start polling
  pollInterval = setInterval(checkSetupProgress, 300);
  checkSetupProgress();
});
