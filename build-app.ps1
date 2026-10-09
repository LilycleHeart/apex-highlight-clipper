param([ValidatePattern('^[^\\/:*?"<>|]+\.exe$')][string]$Name = 'Apex自动剪辑.exe')
$ErrorActionPreference = 'Stop'
$Compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$Source = Join-Path $PSScriptRoot 'desktop\ApexClipper.cs'
$Program = Join-Path $PSScriptRoot $Name
& $Compiler /nologo /target:winexe /platform:x64 /optimize+ /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll "/out:$Program" $Source
if ($LASTEXITCODE -ne 0) { throw '桌面程序编译失败' }
Write-Output $Program
