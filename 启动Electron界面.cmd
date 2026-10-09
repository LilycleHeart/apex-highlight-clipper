@echo off
set "APEX_APP_DIR=%~dp0electron-ui"
if exist "%APEX_APP_DIR%\release-page\Apex Highlight Clipper-win32-x64\Apex Highlight Clipper.exe" (
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
