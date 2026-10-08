param(
    [Parameter(Mandatory)][string]$Subscription,
    [Parameter(Mandatory)][string[]]$AccountResourceIds,
    [int]$Hours = 24
)

$ErrorActionPreference = 'Stop'
$start = (Get-Date).ToUniversalTime().AddHours(-$Hours).ToString('yyyy-MM-ddTHH:mm:ssZ')
$end = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$seriesKeys = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)

foreach ($account in $AccountResourceIds) {
    if ($account -notmatch "^/subscriptions/$([regex]::Escape($Subscription))/resourceGroups/[^/]+/providers/Microsoft.CognitiveServices/accounts/[^/]+$") {
        throw "Account resource ID must belong to the explicitly selected subscription: $account"
    }
    $raw = az rest --method get --url "https://management.azure.com${account}/deployments?api-version=2024-10-01" --subscription $Subscription -o json
    if ($LASTEXITCODE -ne 0) { throw "Deployment configuration read failed: $account" }
    $deployments = ($raw | ConvertFrom-Json).value
    $byName = @{}
    foreach ($deployment in $deployments) {
        $byName[$deployment.name] = $deployment
        foreach ($key in @('request', 'token')) {
            $rules = @($deployment.properties.rateLimits | Where-Object key -eq $key)
            if ($rules.Count -gt 1) { throw "Ambiguous $key rules: $($deployment.id)" }
            $limit = $null
            if ($rules.Count -eq 1 -and $null -ne $rules[0].count -and $rules[0].renewalPeriod -gt 0) {
                $limit = 60 * $rules[0].count / $rules[0].renewalPeriod
            }
            [pscustomobject]@{ DeploymentId = $deployment.id; Rule = $key; PerMinute = $limit }
        }
    }

    foreach ($metric in @('TotalTokens', 'ModelRequests', 'ProvisionedUtilization')) {
        $aggregation = if ($metric -eq 'ProvisionedUtilization') { 'Average,Maximum' } else { 'Total' }
        $url = "https://management.azure.com${account}/providers/microsoft.insights/metrics?api-version=2018-01-01&metricnames=$metric&aggregation=$aggregation&interval=PT1M&autoAdjustTimegrain=false&top=1000&timespan=$start/$end&`$filter=ModelDeploymentName eq '*'"
        $raw = az rest --method get --url $url --subscription $Subscription -o json
        if ($LASTEXITCODE -ne 0) { throw "Metric read failed: $account / $metric" }
        $result = $raw | ConvertFrom-Json
        if ($result.interval -ne 'PT1M') { throw "Unexpected metric interval: $($result.interval)" }
        foreach ($value in $result.value) {
            if ($value.errorCode -and $value.errorCode -ne 'Success') {
                throw "Metric error for $account / $metric : $($value.errorCode) $($value.errorMessage)"
            }
        }
        if (@($result.value[0].timeseries).Count -ge 1000) {
            Write-Warning "Returned 1000 series for $account / $metric. Coverage may be truncated; Metrics List has no documented pagination/completeness marker."
        }
        foreach ($series in $result.value[0].timeseries) {
            $name = ($series.metadatavalues | Where-Object { $_.name.value -ieq 'ModelDeploymentName' }).value
            if (-not $byName.ContainsKey($name)) { throw "Metric deployment has no current ARM deployment: $account / $name" }
            $identity = "$account/deployments/$name|$metric"
            if (-not $seriesKeys.Add($identity)) { throw "Duplicate resource/deployment series: $identity" }
            $reported = @($series.data | Where-Object {
                if ($metric -eq 'ProvisionedUtilization') { $null -ne $_.average } else { $null -ne $_.total }
            })
            $zeroes = @($reported | Where-Object {
                if ($metric -eq 'ProvisionedUtilization') { $_.average -eq 0 } else { $_.total -eq 0 }
            })
            $positive = @($reported | Where-Object {
                if ($metric -eq 'ProvisionedUtilization') { $_.average -gt 0 } else { $_.total -gt 0 }
            })
            [pscustomobject]@{
                AccountId = $account; Deployment = $name; Metric = $metric
                ReportedSamples = $reported.Count; MeasuredZeroes = $zeroes.Count
                PositiveSamples = $positive.Count; MissingSamples = @($series.data).Count - $reported.Count
            }
        }
        if (@($result.value[0].timeseries).Count -eq 0) {
            [pscustomobject]@{ AccountId = $account; Metric = $metric; State = 'No series (not zero)' }
        }
    }
}
