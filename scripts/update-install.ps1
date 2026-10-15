param([Parameter(Mandatory)][string]$Installer,[Parameter(Mandatory)][string]$Target,[Parameter(Mandatory)][int]$ParentPid,[switch]$Portable)
$ErrorActionPreference='Stop'
$installerPath=[IO.Path]::GetFullPath($Installer)
$targetPath=[IO.Path]::GetFullPath($Target)
$contentPath=if(Test-Path -LiteralPath (Join-Path $targetPath 'resources/app_worker.py')){Join-Path $targetPath 'resources'}else{$targetPath}
$appExe=Join-Path $contentPath $(if($contentPath -eq $targetPath){'app/Apex Highlight Clipper.exe'}else{'desktop/Apex Highlight Clipper.exe'})
$logPath=Join-Path ([IO.Path]::GetDirectoryName($installerPath)) 'install.log'
try {
 if(-not (Test-Path -LiteralPath $installerPath -PathType Leaf) -or -not (Test-Path -LiteralPath (Join-Path $contentPath 'app_worker.py') -PathType Leaf) -or -not (Test-Path -LiteralPath $appExe -PathType Leaf)){throw '更新路径无效'}
 $deadline=[DateTime]::UtcNow.AddSeconds(120)
 do {$parent=Get-Process -Id $ParentPid -ErrorAction SilentlyContinue;$active=@(Get-Process -Name 'Apex Highlight Clipper' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $appExe });if(((-not $parent) -or $parent.Path -ne $appExe) -and $active.Count -eq 0){break};if([DateTime]::UtcNow -gt $deadline){throw '等待程序退出超时'};Start-Sleep -Milliseconds 250}while($true)
 Start-Sleep -Milliseconds 750
 $installerArgs=@('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',('/DIR="'+$targetPath+'"'))
 if($Portable){$installerArgs+='/PORTABLE=1'}
 $installProcess=Start-Process -FilePath $installerPath -ArgumentList $installerArgs -WindowStyle Hidden -Wait -PassThru
 if($installProcess.ExitCode -ne 0){throw "安装失败：$($installProcess.ExitCode)"}
 '更新安装成功' | Set-Content -LiteralPath $logPath -Encoding utf8
 $launcher=Join-Path $targetPath 'Apex Highlight Clipper.exe'
 Start-Process -FilePath $launcher -WorkingDirectory $targetPath -WindowStyle Hidden | Out-Null
 Remove-Item -LiteralPath $installerPath
}catch { $_.Exception.Message | Set-Content -LiteralPath $logPath -Encoding utf8; if(Test-Path -LiteralPath $appExe){Start-Process -FilePath $appExe -WorkingDirectory $contentPath -WindowStyle Hidden | Out-Null} }
