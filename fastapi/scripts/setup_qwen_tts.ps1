param(
    [string]$Model = "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
    [string]$LocalDir = ".\models\Qwen3-TTS-12Hz-0.6B-Base",
    [int]$Retries = 8
)

$ErrorActionPreference = "Stop"

Write-Host "[Qwen-TTS] Syncing environment..."
uv sync

Write-Host "[Qwen-TTS] Installing hf_xet for more reliable large-file downloads..."
uv pip install hf_xet

$ok = $false
for ($i = 1; $i -le $Retries; $i++) {
    Write-Host "[Qwen-TTS] Download attempt $i/$Retries for $Model"
    try {
        uv run hf download $Model --local-dir $LocalDir
        $ok = $true
        break
    } catch {
        Write-Warning "[Qwen-TTS] Attempt $i failed: $($_.Exception.Message)"
        if ($i -lt $Retries) {
            Start-Sleep -Seconds 5
        }
    }
}

$modelFile = Join-Path $LocalDir "model.safetensors"
if (-not $ok -or -not (Test-Path $modelFile)) {
    throw "[Qwen-TTS] Download did not complete. Re-run this script; it resumes from cache."
}

Write-Host "[Qwen-TTS] Model is ready at $LocalDir"
Write-Host "[Qwen-TTS] Set QWEN_TTS_MODEL=$LocalDir in fastapi/.env"
