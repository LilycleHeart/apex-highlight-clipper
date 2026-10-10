@echo off
set "APEX_APP_DIR=%~dp0electron-ui"
if exist "%APEX_APP_DIR%\release-v3\Apex Highlight Clipper-win32-x64\Apex Highlight Clipper.exe" (
  start "" "%APEX_APP_DIR%\release-v3\Apex Highlight Clipper-win32-x64\Apex Highlight Clipper.exe" %*
) else if exist "%APEX_APP_DIR%\release-filter\Apex Highlight Clipper-win32-x64\Apex Highlight Clipper.exe" (
  start "" "%APEX_APP_DIR%\release-filter\Apex Highlight Clipper-win32-x64\Apex Highlight Clipper.exe" %*
) else if exist "%APEX_APP_DIR%\release-player\Apex Highlight Clipper-win32-x64\Apex Highlight Clipper.exe" (
  start "" "%APEX_APP_DIR%\release-player\Apex Highlight Clipper-win32-x64\Apex Highlight Clipper.exe" %*
) else if exist "%APEX_APP_DIR%\release-updates\Apex Highlight Clipper-win32-x64\Apex Highlight Clipper.exe" (
  start "" "%APEX_APP_DIR%\release-updates\Apex Highlight Clipper-win32-x64\Apex Highlight Clipper.exe" %*
) else if exist "%APEX_APP_DIR%\release-accuracy\Apex Highlight Clipper-win32-x64\Apex Highlight Clipper.exe" (
  start "" "%APEX_APP_DIR%\release-accuracy\Apex Highlight Clipper-win32-x64\Apex Highlight Clipper.exe" %*
) else if exist "%APEX_APP_DIR%\release-stats\Apex Highlight Clipper-win32-x64\Apex Highlight Clipper.exe" (
  start "" "%APEX_APP_DIR%\release-stats\Apex Highlight Clipper-win32-x64\Apex Highlight Clipper.exe" %*
) else if exist "%APEX_APP_DIR%\release-page\Apex Highlight Clipper-win32-x64\Apex Highlight Clipper.exe" (
  start "" "%APEX_APP_DIR%\release-page\Apex Highlight Clipper-win32-x64\Apex Highlight Clipper.exe" %*
) else if exist "%APEX_APP_DIR%\release-indexed\Apex Highlight Clipper-win32-x64\Apex Highlight Clipper.exe" (
  start "" "%APEX_APP_DIR%\release-indexed\Apex Highlight Clipper-win32-x64\Apex Highlight Clipper.exe" %*
) else if exist "%APEX_APP_DIR%\release-puppet\Apex Highlight Clipper-win32-x64\Apex Highlight Clipper.exe" (
  start "" "%APEX_APP_DIR%\release-puppet\Apex Highlight Clipper-win32-x64\Apex Highlight Clipper.exe" %*
) else if exist "%APEX_APP_DIR%\release\Apex Highlight Clipper-win32-x64\Apex Highlight Clipper.exe" (
  start "" "%APEX_APP_DIR%\release\Apex Highlight Clipper-win32-x64\Apex Highlight Clipper.exe" %*
) else (
  start "" "%APEX_APP_DIR%\node_modules\electron\dist\electron.exe" "%APEX_APP_DIR%" %*
)
