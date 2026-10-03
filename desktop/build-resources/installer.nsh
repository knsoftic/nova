; NOVA installer/uninstaller additions (Phase 12). Included by electron-builder's NSIS script.

; NOVA's own backend (Python inside the install folder) must not keep files locked during install/uninstall.
!macro stopNovaBackend
  nsExec::Exec `powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Process python, pythonw -ErrorAction SilentlyContinue | Where-Object { $$_.Path -like '$INSTDIR\*' } | Stop-Process -Force"`
  Pop $0
!macroend

!macro customInit
  !insertmacro stopNovaBackend
!macroend

!macro customUnInit
  !insertmacro stopNovaBackend
!macroend

; electron-builder keeps a copy of the whole installer (~800 MB) for differential auto-updates. NOVA has no
; auto-update, so the copy is only wasted disk space.
!macro removeInstallerCopy
  !ifdef APP_INSTALLER_STORE_FILE
    Delete "$LOCALAPPDATA\${APP_INSTALLER_STORE_FILE}"
    RMDir "$LOCALAPPDATA\${APP_INSTALLER_STORE_FILE}\.."
  !endif
!macroend

!macro customInstall
  !insertmacro removeInstallerCopy
!macroend

!macro customUnInstall
  !insertmacro removeInstallerCopy
  ${ifNot} ${isUpdated}
    ; The "start with Windows" entry NOVA created (Settings / first-run setup).
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "NOVA"
    ; The user's data is kept unless they say yes. A silent uninstall (/S) keeps it.
    MessageBox MB_YESNO|MB_ICONQUESTION "NOVA ka data bhi mitayein?$\r$\n$\r$\nYaadein, history, settings aur NOVA ka browser profile ($LOCALAPPDATA\NOVA).$\r$\n$\r$\nNahi = data rehta hai; dobara install karne par wapas mil jayega." /SD IDNO IDNO keep_data
      RMDir /r "$LOCALAPPDATA\NOVA"
    keep_data:
  ${endIf}
!macroend
