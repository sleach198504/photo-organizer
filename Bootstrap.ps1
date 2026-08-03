# Photo Organizer bootstrapper.
#
# The single .exe you actually hand someone. Downloads the latest published
# GitHub Release of the project (source zip, no git required on the target
# PC), extracts it to a temp folder, and hands off to that copy's Setup.ps1 -
# which does everything else (Python, venv, dependencies, shortcut,
# uninstall entry) exactly like running Setup.bat from a manually-cloned
# copy would. Pulls from whatever Release is currently published, never from
# a branch HEAD directly, so pushing a work-in-progress commit can't break
# an install that's already out in the world - only a deliberate "Publish
# release" click changes what this installs.

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$RepoOwner = "sleach198504"
$RepoName = "photo-organizer"
$AppName = "Photo Organizer"

$Form = New-Object System.Windows.Forms.Form
$Form.Text = "$AppName Setup"
$Form.ClientSize = New-Object System.Drawing.Size(460, 160)
$Form.StartPosition = "CenterScreen"
$Form.FormBorderStyle = "FixedDialog"
$Form.MaximizeBox = $false
$Form.MinimizeBox = $false

$StatusLabel = New-Object System.Windows.Forms.Label
$StatusLabel.Location = New-Object System.Drawing.Point(20, 20)
$StatusLabel.Size = New-Object System.Drawing.Size(420, 22)
$StatusLabel.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
$StatusLabel.Text = "Preparing to download..."
$Form.Controls.Add($StatusLabel)

$ProgressBar = New-Object System.Windows.Forms.ProgressBar
$ProgressBar.Location = New-Object System.Drawing.Point(20, 50)
$ProgressBar.Size = New-Object System.Drawing.Size(420, 20)
$ProgressBar.Minimum = 0
$ProgressBar.Maximum = 100
$Form.Controls.Add($ProgressBar)

$DetailLabel = New-Object System.Windows.Forms.Label
$DetailLabel.Location = New-Object System.Drawing.Point(20, 80)
$DetailLabel.Size = New-Object System.Drawing.Size(420, 40)
$DetailLabel.ForeColor = [System.Drawing.Color]::DimGray
$DetailLabel.Text = "This downloads the latest published version of $AppName from GitHub and installs it - a few minutes total, most of it after this window closes."
$Form.Controls.Add($DetailLabel)

function Show-FatalError {
    param([string]$Message)
    [System.Windows.Forms.MessageBox]::Show(
        $Message, "$AppName Setup", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
    $Form.Close()
}

$Form.Add_Shown({
    $Form.Activate()

    # --- Resolve the latest published release ---
    $StatusLabel.Text = "Checking for the latest version..."
    [System.Windows.Forms.Application]::DoEvents()
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $headers = @{ "User-Agent" = "PhotoOrganizerBootstrap" }
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$RepoOwner/$RepoName/releases/latest" -Headers $headers
    } catch {
        Show-FatalError "Couldn't reach GitHub to check for the latest version.`n`nCheck your internet connection and try again.`n`n$($_.Exception.Message)"
        return
    }
    $zipUrl = $release.zipball_url
    $versionName = $release.tag_name
    if (-not $zipUrl) {
        Show-FatalError "GitHub didn't return a downloadable version. Please try again later."
        return
    }

    $workDir = Join-Path $env:TEMP ("PhotoOrganizerSetup_" + [System.Guid]::NewGuid().ToString("N").Substring(0, 8))
    New-Item -ItemType Directory -Path $workDir -Force | Out-Null
    $zipPath = Join-Path $workDir "source.zip"

    # --- Download with real progress ---
    $StatusLabel.Text = "Downloading $AppName $versionName..."
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("User-Agent", "PhotoOrganizerBootstrap")
    $script:downloadDone = $false
    $script:downloadError = $null
    $wc.Add_DownloadProgressChanged({
        param($eventSender, $e)
        $ProgressBar.Value = [Math]::Min(100, $e.ProgressPercentage)
        $mb = [Math]::Round($e.BytesReceived / 1MB, 1)
        $totalMb = [Math]::Round($e.TotalBytesToReceive / 1MB, 1)
        $DetailLabel.Text = "Downloaded $mb MB of $totalMb MB..."
    }.GetNewClosure())
    $wc.Add_DownloadFileCompleted({
        param($eventSender, $e)
        if ($e.Error) { $script:downloadError = $e.Error }
        $script:downloadDone = $true
    }.GetNewClosure())
    $wc.DownloadFileAsync($zipUrl, $zipPath)

    while (-not $script:downloadDone) {
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 50
    }
    if ($script:downloadError) {
        Remove-Item $workDir -Recurse -Force -ErrorAction SilentlyContinue
        Show-FatalError "The download failed.`n`nCheck your internet connection and try again.`n`n$($script:downloadError.Message)"
        return
    }

    # --- Extract ---
    $StatusLabel.Text = "Extracting..."
    $DetailLabel.Text = ""
    $ProgressBar.Value = 100
    [System.Windows.Forms.Application]::DoEvents()
    $extractDir = Join-Path $workDir "extracted"
    try {
        Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force
    } catch {
        Remove-Item $workDir -Recurse -Force -ErrorAction SilentlyContinue
        Show-FatalError "Couldn't extract the downloaded files.`n`n$($_.Exception.Message)"
        return
    }
    # A GitHub source zip always contains exactly one top-level folder
    # (named like owner-repo-shortsha) - that's the real project root.
    $projectRoot = Get-ChildItem -Path $extractDir -Directory | Select-Object -First 1
    $setupScript = Join-Path $projectRoot.FullName "Setup.ps1"
    if (-not (Test-Path $setupScript)) {
        Remove-Item $workDir -Recurse -Force -ErrorAction SilentlyContinue
        Show-FatalError "The downloaded version is missing Setup.ps1 - it may be corrupted. Please try again."
        return
    }

    # --- Hand off to the real installer and wait for it to finish, then
    #     clean up the temp download - Setup.ps1 has already copied
    #     everything it needs into the permanent install location by then. ---
    $StatusLabel.Text = "Starting setup..."
    [System.Windows.Forms.Application]::DoEvents()
    $proc = Start-Process powershell -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", "`"$setupScript`""
    ) -PassThru
    $proc.Handle | Out-Null
    $Form.Hide()
    $proc.WaitForExit()

    Remove-Item $workDir -Recurse -Force -ErrorAction SilentlyContinue
    $Form.Close()
})

[void]$Form.ShowDialog()
