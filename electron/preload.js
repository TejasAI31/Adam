const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  navigateToSetup: (data) => ipcRenderer.send('navigate-to-setup', data),
  navigateToMain: (data) => ipcRenderer.send('navigate-to-main', data),
  navigateToSelection: (data) => ipcRenderer.send('navigate-to-selection', data),
  windowControl: (command) => ipcRenderer.send('window-control', command),
  getSharingConfig: () => ipcRenderer.invoke('get-sharing-config'),
  saveSharingConfig: (config) => ipcRenderer.invoke('save-sharing-config', config),
  toggleSharing: (enable, config) => ipcRenderer.invoke('toggle-sharing', enable, config),
  getSharingStatus: () => ipcRenderer.invoke('get-sharing-status'),
  onSharingStatusChanged: (callback) => ipcRenderer.on('sharing-status-changed', (event, value) => callback(value))
});
