Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
. .\infra\demo\environment.ps1
$path = "/subscriptions/$DemoSubscription/resourceGroups/$DemoResourceGroup/providers/Microsoft.App/jobs/job-desk-snprobe"
$job = Invoke-DemoArm -Path "$($path)?api-version=2024-03-01"
"job provisioningState=$($job.properties.provisioningState) command=$($job.properties.template.containers[0].command[0..1] -join ' ')"
$executions = Invoke-DemoArm -Path "$path/executions?api-version=2024-03-01"
$executions.value | Select-Object -First 3 | ForEach-Object { "$($_.name) $($_.properties.status) $($_.properties.startTime)" }
exit 0
