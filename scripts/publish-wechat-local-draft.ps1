param(
    [Parameter(Mandatory = $true)]
    [string]$Article,

    [Parameter(Mandatory = $true)]
    [string]$Cover,

    [string]$PreviewHtml,
    [string]$OutputPrefix
)

$ErrorActionPreference = "Stop"
if (Test-Path variable:global:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

function Resolve-RequiredPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Label not found: $Path"
    }

    return (Resolve-Path -LiteralPath $Path).Path
}

function Invoke-Md2Wechat {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$OutputFile
    )

    function Quote-ProcessArgument {
        param([string]$Value)

        if ($Value -notmatch '[\s"]') {
            return $Value
        }

        $escaped = $Value.Replace('\', '\\').Replace('"', '\"')
        return '"' + $escaped + '"'
    }

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = "md2wechat"
    $startInfo.Arguments = ($Arguments | ForEach-Object { Quote-ProcessArgument $_ }) -join " "
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    $exitCode = $process.ExitCode

    $output = @()
    if ($stdout) {
        $output += ($stdout -split "`r?`n")
    }
    if ($stderr) {
        $output += ($stderr -split "`r?`n")
    }

    $output = $output | Where-Object { $_ -ne "" }
    $output | Set-Content -LiteralPath $OutputFile -Encoding UTF8

    if ($exitCode -ne 0) {
        throw "md2wechat $($Arguments -join ' ') failed with exit code $exitCode. See: $OutputFile"
    }

    return $output
}

function Invoke-Md2WechatJson {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$OutputFile
    )

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = "md2wechat"
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    foreach ($argument in $Arguments) {
        [void]$startInfo.ArgumentList.Add($argument)
    }

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    $exitCode = $process.ExitCode

    $combined = @()
    if ($stdout) {
        $combined += ($stdout -split "`r?`n")
    }
    if ($stderr) {
        $combined += ($stderr -split "`r?`n")
    }
    $combined = $combined | Where-Object { $_ -ne "" }
    $combined | Set-Content -LiteralPath $OutputFile -Encoding UTF8

    if ($exitCode -ne 0) {
        throw "md2wechat $($Arguments -join ' ') failed with exit code $exitCode. See: $OutputFile"
    }

    try {
        return ($stdout | ConvertFrom-Json)
    }
    catch {
        throw "md2wechat $($Arguments -join ' ') did not return valid JSON on stdout. See: $OutputFile"
    }
}

function Read-ArticleMetadata {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ArticlePath
    )

    $raw = Get-Content -LiteralPath $ArticlePath -Raw
    $metadata = @{
        title = "未命名文章"
        author = ""
        digest = ""
    }

    $frontmatterMatch = [regex]::Match($raw, "(?s)^---\s*\r?\n(.*?)\r?\n---")
    if (-not $frontmatterMatch.Success) {
        return $metadata
    }

    foreach ($line in ($frontmatterMatch.Groups[1].Value -split "`r?`n")) {
        $match = [regex]::Match($line, "^\s*([A-Za-z0-9_-]+):\s*[""']?(.+?)[""']?\s*$")
        if (-not $match.Success) {
            continue
        }

        $key = $match.Groups[1].Value
        $value = $match.Groups[2].Value
        if ($metadata.ContainsKey($key)) {
            $metadata[$key] = $value
        }
    }

    return $metadata
}

function Get-MarkdownImageSources {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ArticlePath
    )

    $raw = Get-Content -LiteralPath $ArticlePath -Raw
    $matches = [regex]::Matches($raw, "!\[[^\]]*\]\(([^)]+)\)")
    $sources = New-Object System.Collections.Generic.List[string]
    foreach ($match in $matches) {
        $src = $match.Groups[1].Value.Trim()
        if ($src -and $src -notmatch "^(https?:|data:)") {
            $sources.Add($src)
        }
    }

    return $sources | Select-Object -Unique
}

$articlePath = Resolve-RequiredPath -Path $Article -Label "Article"
$coverPath = Resolve-RequiredPath -Path $Cover -Label "Cover"
$articleItem = Get-Item -LiteralPath $articlePath
$articleDir = $articleItem.DirectoryName
$articleBase = [System.IO.Path]::GetFileNameWithoutExtension($articleItem.Name)

if (-not $OutputPrefix) {
    $OutputPrefix = Join-Path $articleDir $articleBase
}

if (-not $PreviewHtml) {
    $PreviewHtml = "$OutputPrefix-preview.html"
}

$inspectOutput = "$OutputPrefix-inspect.txt"
$previewOutput = "$OutputPrefix-preview-output.txt"
$coverUploadOutput = "$OutputPrefix-cover-upload-output.txt"
$draftJsonPath = "$OutputPrefix-draft.json"
$draftOutput = "$OutputPrefix-create-draft-output.txt"

Invoke-Md2Wechat -Arguments @("config", "validate") -OutputFile "$OutputPrefix-config-validate.txt"

Invoke-Md2Wechat -Arguments @("inspect", $articlePath) -OutputFile $inspectOutput

$previewLog = Invoke-Md2Wechat -Arguments @("preview", $articlePath) -OutputFile $previewOutput

$renderer = Join-Path $PSScriptRoot "render-wechat-local-html.js"
if (-not (Test-Path -LiteralPath $renderer)) {
    throw "Local WeChat renderer not found: $renderer"
}

& node $renderer $articlePath $PreviewHtml
if ($LASTEXITCODE -ne 0) {
    throw "Local WeChat renderer failed with exit code $LASTEXITCODE"
}

$html = Get-Content -LiteralPath $PreviewHtml -Raw
$imageIndex = 0
foreach ($imageSource in (Get-MarkdownImageSources -ArticlePath $articlePath)) {
    $resolvedImage = Join-Path $articleDir $imageSource
    if (-not (Test-Path -LiteralPath $resolvedImage)) {
        throw "Article image not found: $resolvedImage"
    }

    $imageIndex++
    $imageUploadOutput = "$OutputPrefix-image-$imageIndex-upload-output.txt"
    $imageUpload = Invoke-Md2WechatJson -Arguments @("upload_image", (Resolve-Path -LiteralPath $resolvedImage).Path, "--json") -OutputFile $imageUploadOutput
    $uploadedImageUrl = $imageUpload.data.wechat_url
    if (-not $uploadedImageUrl) {
        $uploadedImageUrl = $imageUpload.data.url
    }
    if (-not $uploadedImageUrl) {
        throw "Image upload did not return data.wechat_url or data.url. See: $imageUploadOutput"
    }
    $html = $html.Replace('src="' + $imageSource + '"', 'src="' + $uploadedImageUrl + '"')
}

$coverUpload = Invoke-Md2WechatJson -Arguments @("upload_image", $coverPath, "--json") -OutputFile $coverUploadOutput
if (-not $coverUpload.data.media_id) {
    throw "Cover upload did not return data.media_id. See: $coverUploadOutput"
}

$metadata = Read-ArticleMetadata -ArticlePath $articlePath
$draft = @{
    articles = @(
        @{
            title = $metadata.title
            author = $metadata.author
            digest = $metadata.digest
            content = $html
            thumb_media_id = $coverUpload.data.media_id
            content_source_url = ""
            need_open_comment = 0
            only_fans_can_comment = 0
        }
    )
}

$draft | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $draftJsonPath -Encoding UTF8
Invoke-Md2Wechat -Arguments @("create_draft", $draftJsonPath, "--json") -OutputFile $draftOutput

Write-Host "Preview HTML: $PreviewHtml"
Write-Host "Draft output: $draftOutput"
