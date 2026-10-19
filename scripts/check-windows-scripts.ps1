$ErrorActionPreference='Stop'
foreach($file in @('scripts/update-install.ps1','scripts/setup-ffmpeg.ps1','scripts/migrate-layout.ps1','scripts/cleanup-validation.ps1','scripts/launch-preview.ps1')){
 $tokens=$null;$parseErrors=$null
 [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path -LiteralPath $file),[ref]$tokens,[ref]$parseErrors) | Out-Null
 if($parseErrors.Count){$parseErrors | ForEach-Object {Write-Error $_.Message};exit 1}
}
Write-Output 'Windows PowerShell scripts parsed successfully'
