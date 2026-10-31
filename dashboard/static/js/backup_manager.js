/**
 * Intelligent Tracker - System Backup & Restore Modal Controller Submodule.
 * Handles snapshot file import, restore progress indication, and auto-reload.
 */

(function () {
  'use strict';

  function bindBackupManagerModal(showToast) {
    const modalBackup = document.getElementById('modal-backup-manager');
    const btnBackupOpen = document.getElementById('btn-backup-manager');
    const btnBackupClose = document.getElementById('modal-backup-close');
    const btnImport = document.getElementById('btn-import-backup-file');
    const fileInput = document.getElementById('backup-file-input');
    const importStatus = document.getElementById('backup-import-status');

    btnBackupOpen?.addEventListener('click', () => { if (modalBackup) modalBackup.style.display = 'flex'; });
    btnBackupClose?.addEventListener('click', () => { if (modalBackup) modalBackup.style.display = 'none'; });
    modalBackup?.addEventListener('click', (e) => { if (e.target === modalBackup) modalBackup.style.display = 'none'; });

    btnImport?.addEventListener('click', () => fileInput?.click());
    fileInput?.addEventListener('change', async (e) => {
      const file = e.target.files[0];
      if (!file || !importStatus) return;
      if (!confirm(`Import and restore full system state from '${file.name}'? Existing database records will be backed up.`)) return;

      const formData = new FormData();
      formData.append('file', file);
      importStatus.innerHTML = '<span style="color:#06b6d4;">Restoring system snapshot...</span>';

      try {
        const resp = await fetch('/api/backup/import', { method: 'POST', body: formData });
        if (resp.ok) {
          const res = await resp.json();
          importStatus.innerHTML = `<span style="color:#10b981;">✓ Successfully restored ${res.details.restored_files_count} files!</span>`;
          showToast?.('Restore Complete', 'System snapshot restored successfully! Reloading...', 'success');
          setTimeout(() => window.location.reload(), 1200);
        } else {
          const err = await resp.json();
          importStatus.innerHTML = `<span style="color:#ef4444;">✗ Restore failed: ${err.detail || 'Error'}</span>`;
        }
      } catch (err) {
        importStatus.innerHTML = `<span style="color:#ef4444;">✗ Network error: ${err.message}</span>`;
      } finally {
        fileInput.value = '';
      }
    });
  }

  window.BackupManager = {
    bind: bindBackupManagerModal,
  };
})();

