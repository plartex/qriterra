$ErrorActionPreference = 'Stop'
$checkerRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$checkerPython = Join-Path $checkerRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $checkerPython -PathType Leaf)) {
    throw 'Create .venv and install Agent Bridge plus Qriterra first.'
}

$codexDir = Join-Path $checkerRoot '.codex'
$agentsDir = Join-Path $checkerRoot '.agents'
New-Item -ItemType Directory -Path $codexDir, $agentsDir -Force | Out-Null

$tomlPath = $checkerPython.Replace("'", "''")
$toml = @"
[mcp_servers.qriterra]
command = '$tomlPath'
args = ["-m", "qriterra.mcp_server"]
tool_timeout_sec = 1800

[mcp_servers.qriterra.env]
BRIDGE_CODEX_URL = "http://127.0.0.1:8765"
BRIDGE_ANTIGRAVITY_URL = "http://127.0.0.1:8766"
"@
Set-Content -LiteralPath (Join-Path $codexDir 'config.toml') -Value $toml -Encoding utf8

$json = @{
    mcpServers = @{
        'qriterra' = @{
            command = $checkerPython
            args = @('-m', 'qriterra.mcp_server')
            env = @{
                BRIDGE_CODEX_URL = 'http://127.0.0.1:8765'
                BRIDGE_ANTIGRAVITY_URL = 'http://127.0.0.1:8766'
            }
        }
    }
} | ConvertTo-Json -Depth 10
Set-Content -LiteralPath (Join-Path $agentsDir 'mcp_config.json') -Value $json -Encoding utf8

Write-Output 'Configured only the Qriterra MCP server in this repository.'
