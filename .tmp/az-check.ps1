$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
Write-Output "config=$env:AZURE_CONFIG_DIR"
az account show --query "{sub:id,user:user.name}" -o json 2>&1
Write-Output "exit=$LASTEXITCODE"
