# Photo Organizer installer.
#
# Launched hidden (no console window) by Setup.bat. Copies the app to a
# proper per-user install location, sets up Python + a venv there, installs
# dependencies (CPU or GPU build, detected/chosen up front), downloads the
# content-tagging model, creates a Desktop shortcut, and registers a real
# uninstall entry - all through one WinForms wizard window.

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$AppName = "Photo Organizer"
$InstallDir = Join-Path $env:LocalAppData "Programs\Photo Organizer"
$SourceDir = $PSScriptRoot
$RegKeyPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\PhotoOrganizer"

# ============================================================
#  Process tracking (async, non-blocking, cancellable)
# ============================================================

function New-TrackedProcess {
    <#
        Runs a process without blocking the UI thread. Output is redirected
        to temp log files (native Start-Process redirection, not manual
        stream plumbing - simpler and more reliable) and re-read in full
        each tick, reporting only lines beyond what's already been seen.
        Cheap enough for a log that's at most a few dozen KB and a process
        that runs for seconds to minutes.

        Returns an object with .Cancel() (kills the process) - the caller
        is responsible for starting/stopping polling via the returned Timer
        if it wants manual control, but normally just waits for -OnExit.
    #>
    param(
        [string]$FilePath,
        [string]$Arguments,
        [scriptblock]$OnOutputLine,
        [scriptblock]$OnExit
    )

    $logPath = [System.IO.Path]::GetTempFileName()
    $errPath = "$logPath.err"

    $proc = Start-Process -FilePath $FilePath -ArgumentList $Arguments -PassThru -NoNewWindow `
        -RedirectStandardOutput $logPath -RedirectStandardError $errPath
    # Touching .Handle forces PowerShell to open the process handle with the
    # query rights needed to read .ExitCode later - without this, ExitCode
    # comes back empty on a Start-Process -PassThru object (documented quirk).
    $proc.Handle | Out-Null

    $state = [PSCustomObject]@{ Cancelled = $false; LinesReported = 0 }

    $readNewLines = {
        if (-not (Test-Path $logPath)) { return }
        $allLines = @(Get-Content -Path $logPath -ErrorAction SilentlyContinue)
        if ($allLines.Count -gt $state.LinesReported) {
            for ($i = $state.LinesReported; $i -lt $allLines.Count; $i++) {
                if ($OnOutputLine -and $allLines[$i]) { & $OnOutputLine $allLines[$i] }
            }
            $state.LinesReported = $allLines.Count
        }
    }.GetNewClosure()

    $timer = New-Object System.Windows.Forms.Timer
    $timer.Interval = 150
    $timer.Add_Tick({
        & $readNewLines
        if ($proc.HasExited) {
            $timer.Stop()
            $proc.WaitForExit()
            Start-Sleep -Milliseconds 100
            & $readNewLines
            $errText = ""
            if (Test-Path $errPath) { $errText = (Get-Content $errPath -Raw -ErrorAction SilentlyContinue) }
            try { Remove-Item $logPath, $errPath -Force -ErrorAction SilentlyContinue } catch {}
            if ($OnExit) { & $OnExit $state.Cancelled $proc.ExitCode $errText }
        }
    }.GetNewClosure())
    $timer.Start()

    $cancelAction = {
        $state.Cancelled = $true
        try { if (-not $proc.HasExited) { $proc.Kill() } } catch {}
    }.GetNewClosure()

    return [PSCustomObject]@{ Timer = $timer; Cancel = $cancelAction }
}

# ============================================================
#  Python detection / install
# ============================================================

function Find-PythonExe {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    foreach ($base in @("$env:LocalAppData\Programs\Python", "$env:ProgramFiles\Python")) {
        if (Test-Path $base) {
            $found = Get-ChildItem $base -Directory -Filter "Python3*" -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending | Select-Object -First 1
            if ($found -and (Test-Path (Join-Path $found.FullName "python.exe"))) {
                return Join-Path $found.FullName "python.exe"
            }
        }
    }
    return $null
}

function Install-PythonDirectDownload {
    <#
        Fallback used when winget is unavailable or didn't work. Calls
        -OnDone with the found python.exe path, or $null on failure -
        never returns synchronously, so this must always be the last thing
        a caller does (no code after calling this expects to run next).
    #>
    param([scriptblock]$AppendLog, [scriptblock]$OnDone)

    & $AppendLog "Downloading the official Python installer..."
    $installerPath = Join-Path $env:TEMP "photo-organizer-python-installer.exe"
    try {
        $wc = New-Object System.Net.WebClient
        $wc.DownloadFile("https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe", $installerPath)
    } catch {
        & $AppendLog "Download failed: $($_.Exception.Message)"
        & $OnDone $null
        return
    }

    & $AppendLog "Installing Python..."
    $tracked = New-TrackedProcess -FilePath $installerPath `
        -Arguments "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=0 Include_test=0" `
        -OnOutputLine $AppendLog -OnExit {
            param($cancelled, $exitCode, $errText)
            $script:CurrentCancelAction = $null
            Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
            if ($cancelled) { return }
            & $OnDone (Find-PythonExe)
        }.GetNewClosure()
    $script:CurrentCancelAction = $tracked.Cancel
}

function Install-Python {
    <#
        Tries winget first, falls back to a direct download. Calls -OnDone
        with the found python.exe path, or $null if every attempt failed -
        asynchronous throughout, never returns a value synchronously.
    #>
    param([scriptblock]$AppendLog, [scriptblock]$OnDone)

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        Install-PythonDirectDownload -AppendLog $AppendLog -OnDone $OnDone
        return
    }

    & $AppendLog "Trying winget..."
    $tracked = New-TrackedProcess -FilePath $winget.Source `
        -Arguments "install --id Python.Python.3.12 -e --scope user --silent --accept-package-agreements --accept-source-agreements" `
        -OnOutputLine $AppendLog -OnExit {
            param($cancelled, $exitCode, $errText)
            $script:CurrentCancelAction = $null
            if ($cancelled) { return }
            $found = Find-PythonExe
            if ($found) { & $OnDone $found; return }
            Install-PythonDirectDownload -AppendLog $AppendLog -OnDone $OnDone
        }.GetNewClosure()
    $script:CurrentCancelAction = $tracked.Cancel
}

function Test-NvidiaGpu {
    return $null -ne (Get-Command nvidia-smi -ErrorAction SilentlyContinue)
}

# ============================================================
#  Install location + data migration
# ============================================================

function Copy-DirectoryResponsively {
    <#
        Copy-Item -Recurse copies an entire directory tree as one blocking
        call with no opportunity to repaint - for a folder with enough
        files (or a slow disk / antivirus scanning each new .py file), that
        alone is long enough for Windows to mark the window "(Not
        Responding)" even though nothing is actually stuck. This copies
        file-by-file instead, yielding to the message loop periodically so
        the window stays responsive and repainting throughout - safe to do
        now that nothing else is using nested DoEvents() loops.
    #>
    param([string]$Source, [string]$Destination, [scriptblock]$OnOutputLine)

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $files = Get-ChildItem -Path $Source -Recurse -File
    $count = 0
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($Source.Length).TrimStart('\')
        $destPath = Join-Path $Destination $relative
        $destDir = Split-Path $destPath -Parent
        if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Force -Path $destDir | Out-Null }
        Copy-Item -Path $file.FullName -Destination $destPath -Force
        $count++
        if ($count % 3 -eq 0) {
            & $OnOutputLine "Copying $relative..."
            [System.Windows.Forms.Application]::DoEvents()
            if ($script:SetupCancelled) { return }
        }
    }
}

function Install-ToProgramsFolder {
    param([scriptblock]$OnOutputLine)

    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

    $itemsToCopy = @("app", "requirements.txt", "requirements-cpu.txt", "requirements-gpu.txt",
        "config.example.yaml", "README.md", "launch.bat", "Setup.ps1", "Setup.bat")
    foreach ($item in $itemsToCopy) {
        $src = Join-Path $SourceDir $item
        if (-not (Test-Path $src)) { continue }
        $dest = Join-Path $InstallDir $item
        & $OnOutputLine "Copying $item..."
        [System.Windows.Forms.Application]::DoEvents()
        if ($script:SetupCancelled) { return }
        if ((Get-Item $src) -is [System.IO.DirectoryInfo]) {
            Copy-DirectoryResponsively -Source $src -Destination $dest -OnOutputLine $OnOutputLine
        } else {
            Copy-Item -Path $src -Destination $dest -Force
        }
        if ($script:SetupCancelled) { return }
    }

    # Migrate existing config/data only if this install location doesn't
    # already have its own - pure copy, never overwrites, never touches the
    # original source folder.
    $destConfig = Join-Path $InstallDir "config.yaml"
    $srcConfig = Join-Path $SourceDir "config.yaml"
    if (-not (Test-Path $destConfig) -and (Test-Path $srcConfig)) {
        & $OnOutputLine "Bringing over your existing settings..."
        Copy-Item -Path $srcConfig -Destination $destConfig -Force
    }
    $destData = Join-Path $InstallDir "data"
    $srcData = Join-Path $SourceDir "data"
    if (-not (Test-Path $destData) -and (Test-Path $srcData)) {
        & $OnOutputLine "Bringing over your existing photo index..."
        Copy-Item -Path $srcData -Destination $destData -Recurse -Force
    }
}

function Register-UninstallEntry {
    $uninstallScript = Join-Path $InstallDir "Uninstall.ps1"
    $iconPath = Join-Path $InstallDir "app\web\static\icons\app.ico"
    $version = "2"
    $versionFile = Join-Path $InstallDir "app\version.py"
    if (Test-Path $versionFile) {
        $found = Select-String -Path $versionFile -Pattern '__version__\s*=\s*"([^"]+)"' | Select-Object -First 1
        if ($found) { $version = $found.Matches[0].Groups[1].Value }
    }

    New-Item -Path $RegKeyPath -Force | Out-Null
    Set-ItemProperty -Path $RegKeyPath -Name "DisplayName" -Value $AppName
    Set-ItemProperty -Path $RegKeyPath -Name "DisplayVersion" -Value $version
    Set-ItemProperty -Path $RegKeyPath -Name "Publisher" -Value $AppName
    Set-ItemProperty -Path $RegKeyPath -Name "InstallLocation" -Value $InstallDir
    Set-ItemProperty -Path $RegKeyPath -Name "UninstallString" `
        -Value "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$uninstallScript`""
    Set-ItemProperty -Path $RegKeyPath -Name "DisplayIcon" -Value $iconPath
    Set-ItemProperty -Path $RegKeyPath -Name "NoModify" -Value 1 -Type DWord
    Set-ItemProperty -Path $RegKeyPath -Name "NoRepair" -Value 1 -Type DWord
    try {
        $sizeKb = [math]::Round((Get-ChildItem $InstallDir -Recurse -File -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum).Sum / 1KB)
        Set-ItemProperty -Path $RegKeyPath -Name "EstimatedSize" -Value $sizeKb -Type DWord
    } catch {}
}

function New-UninstallScript {
    $desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "$AppName.lnk"
    $startMenuShortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "$AppName.lnk"
    $content = @"
`$ErrorActionPreference = 'SilentlyContinue'
Remove-Item -Path '$desktopShortcut' -Force
Remove-Item -Path '$startMenuShortcut' -Force
Remove-Item -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\PhotoOrganizer' -Recurse -Force
Start-Sleep -Milliseconds 300
`$installDir = '$InstallDir'
`$self = `$MyInvocation.MyCommand.Path
Start-Process powershell -ArgumentList "-NoProfile -WindowStyle Hidden -Command `"Start-Sleep -Seconds 1; Remove-Item -Path '`$installDir' -Recurse -Force`"" -WindowStyle Hidden
"@
    Set-Content -Path (Join-Path $InstallDir "Uninstall.ps1") -Value $content -Encoding UTF8
}

function New-DesktopShortcut {
    # One shortcut on the Desktop and one in the Start Menu, both with the app's own icon.
    $shell = New-Object -ComObject WScript.Shell
    $icon = Join-Path $InstallDir "app\web\static\icons\app.ico"
    foreach ($folder in @("Desktop", "Programs")) {
        $shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath($folder)) "$AppName.lnk"))
        $shortcut.TargetPath = Join-Path $InstallDir "venv\Scripts\pythonw.exe"
        $shortcut.Arguments = "-m app.gui_launcher"
        $shortcut.WorkingDirectory = $InstallDir
        $shortcut.Description = "Find duplicates, blurry shots and clutter in your phone photos"
        if (Test-Path $icon) { $shortcut.IconLocation = $icon }
        $shortcut.Save()
    }
}

# ============================================================
#  Wizard window + shared chrome
# ============================================================

$Form = New-Object System.Windows.Forms.Form
$Form.Text = $AppName + " Setup"
$Form.ClientSize = New-Object System.Drawing.Size(560, 420)
$Form.StartPosition = "CenterScreen"
$Form.FormBorderStyle = "FixedDialog"
$Form.MaximizeBox = $false
$Form.MinimizeBox = $false

$Banner = New-Object System.Windows.Forms.Panel
$Banner.Size = New-Object System.Drawing.Size(560, 56)
$Banner.BackColor = [System.Drawing.Color]::FromArgb(47, 110, 113)
$BannerLabel = New-Object System.Windows.Forms.Label
$BannerLabel.Text = $AppName + " Setup"
$BannerLabel.ForeColor = [System.Drawing.Color]::White
$BannerLabel.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
$BannerLabel.Location = New-Object System.Drawing.Point(20, 14)
$BannerLabel.AutoSize = $true
$Banner.Controls.Add($BannerLabel)
$Form.Controls.Add($Banner)

$ContentPanel = New-Object System.Windows.Forms.Panel
$ContentPanel.Location = New-Object System.Drawing.Point(0, 56)
$ContentPanel.Size = New-Object System.Drawing.Size(560, 364)
$Form.Controls.Add($ContentPanel)

$script:CurrentCancelAction = $null
# Set by the Progress page's Cancel button. The one synchronous, DoEvents-
# yielding phase (the file copy in Install-ToProgramsFolder) has no tracked
# child process to kill, so it polls this flag directly to stop itself
# instead of silently finishing the whole install in the background after
# the user has already been shown the cancelled screen.
$script:SetupCancelled = $false
$Form.Add_FormClosing({
    if ($script:CurrentCancelAction) { & $script:CurrentCancelAction }
})

function Set-Page {
    param([System.Windows.Forms.Control[]]$Controls)
    $ContentPanel.Controls.Clear()
    foreach ($c in $Controls) { $ContentPanel.Controls.Add($c) }
}

function New-BodyLabel {
    param([string]$Text, [int]$Y, [int]$Height = 220)
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $Text
    $label.Location = New-Object System.Drawing.Point(24, $Y)
    $label.Size = New-Object System.Drawing.Size(512, $Height)
    return $label
}

function New-WizardButton {
    param([string]$Text, [int]$X, [int]$Y = 322)
    $btn = New-Object System.Windows.Forms.Button
    $btn.Text = $Text
    $btn.Size = New-Object System.Drawing.Size(110, 32)
    $btn.Location = New-Object System.Drawing.Point($X, $Y)
    return $btn
}

# ============================================================
#  Page: Welcome / disclosure
# ============================================================

function Show-WelcomePage {
    $message = @"
This will:

- Install Python if it isn't already on this computer. Python is a free,
  open-source programming language Photo Organizer is built on - it will
  show up as its own program in your Start Menu and installed-apps list.
  That's expected, not a mistake; you won't need to do anything with it
  yourself, and Photo Organizer still gets its own separate shortcut on
  your Desktop when this finishes.

- Install Photo Organizer itself into your user Programs folder, with a
  proper entry in Windows Settings > Apps so it can be uninstalled like
  any other program.

- Download a handful of other free, open-source components (image and
  video processing libraries, and the AI model used for content tagging)
  - roughly 500MB to a few GB total depending on your PC, one time only,
  from official sources (python.org, PyPI, Hugging Face).

- Everything installs and runs locally on this PC only. Nothing is ever
  uploaded anywhere, during setup or afterward.
"@
    $label = New-BodyLabel -Text $message -Y 20 -Height 270
    $cancelBtn = New-WizardButton -Text "Cancel" -X 426
    $confirmBtn = New-WizardButton -Text "Confirm" -X 308
    $confirmBtn.DialogResult = [System.Windows.Forms.DialogResult]::None

    $cancelBtn.Add_Click({ $Form.Close() }.GetNewClosure())
    $confirmBtn.Add_Click({
        if (Test-NvidiaGpu) { Show-GpuChoicePage } else { Show-ProgressPage -TorchVariant "cpu" }
    }.GetNewClosure())

    Set-Page -Controls @($label, $cancelBtn, $confirmBtn)
    $Form.AcceptButton = $confirmBtn
    $Form.CancelButton = $cancelBtn
}

# ============================================================
#  Page: GPU / CPU choice
# ============================================================

function Show-GpuChoicePage {
    $message = "An NVIDIA graphics card was detected on this PC.`n`nUsing it can make photo and video analysis significantly faster, but is a larger one-time download."
    $label = New-BodyLabel -Text $message -Y 20 -Height 100

    $gpuBtn = New-WizardButton -Text "Use GPU (~3.5 GB)" -X 190 -Y 160
    $gpuBtn.Size = New-Object System.Drawing.Size(170, 32)
    $cpuBtn = New-WizardButton -Text "Use CPU (~500 MB)" -X 370 -Y 160
    $cpuBtn.Size = New-Object System.Drawing.Size(170, 32)
    $backBtn = New-WizardButton -Text "Back" -X 24 -Y 322

    $backBtn.Add_Click({ Show-WelcomePage }.GetNewClosure())
    $gpuBtn.Add_Click({ Show-ProgressPage -TorchVariant "gpu" }.GetNewClosure())
    $cpuBtn.Add_Click({ Show-ProgressPage -TorchVariant "cpu" }.GetNewClosure())

    Set-Page -Controls @($label, $gpuBtn, $cpuBtn, $backBtn)
    $Form.CancelButton = $backBtn
}

# ============================================================
#  Page: Progress
# ============================================================

function Show-ProgressPage {
    <#
        Sets up the page, then hands off to Start-InstallFlow. Every step
        after this is a callback chain (each Step-* function calls the next
        one only from a New-TrackedProcess -OnExit callback, i.e. from a
        genuine top-level Timer tick, or directly for fast synchronous work)
        - nothing here ever blocks the UI thread waiting in a loop, and
        nothing is ever invoked from inside another step's own wait, so
        there's no nested-DoEvents reentrancy possible.
    #>
    param([string]$TorchVariant)

    $statusLabel = New-Object System.Windows.Forms.Label
    $statusLabel.Location = New-Object System.Drawing.Point(24, 20)
    $statusLabel.Size = New-Object System.Drawing.Size(512, 22)
    $statusLabel.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
    $statusLabel.Text = "Getting ready..."

    $progressBar = New-Object System.Windows.Forms.ProgressBar
    $progressBar.Location = New-Object System.Drawing.Point(24, 50)
    $progressBar.Size = New-Object System.Drawing.Size(512, 20)
    $progressBar.Minimum = 0
    $progressBar.Maximum = 100
    $progressBar.Value = 0

    $detailLabel = New-Object System.Windows.Forms.Label
    $detailLabel.Location = New-Object System.Drawing.Point(24, 80)
    $detailLabel.Size = New-Object System.Drawing.Size(512, 20)
    $detailLabel.ForeColor = [System.Drawing.Color]::DimGray

    $logBox = New-Object System.Windows.Forms.TextBox
    $logBox.Location = New-Object System.Drawing.Point(24, 108)
    $logBox.Size = New-Object System.Drawing.Size(512, 180)
    $logBox.Multiline = $true
    $logBox.ScrollBars = "Vertical"
    $logBox.ReadOnly = $true
    $logBox.Font = New-Object System.Drawing.Font("Consolas", 8.5)

    $cancelBtn = New-WizardButton -Text "Cancel" -X 426

    Set-Page -Controls @($statusLabel, $progressBar, $detailLabel, $logBox, $cancelBtn)
    $Form.CancelButton = $cancelBtn

    $appendLog = {
        param($line)
        $detailLabel.Text = $line
        $logBox.AppendText("$line`r`n")
    }.GetNewClosure()

    $script:stepIndex = 0
    # Relocate, FindPython, CreateVenv, InstallBase, InstallRequirements,
    # InstallTorch, DownloadModel, Finish - one AdvanceStep call each.
    $stepCount = 8
    $advanceStep = {
        param($label)
        $script:stepIndex++
        $statusLabel.Text = $label
        $progressBar.Value = [Math]::Min(100, [int](($script:stepIndex - 1) * 100 / $stepCount))
    }.GetNewClosure()

    $cancelBtn.Add_Click({
        $script:SetupCancelled = $true
        if ($script:CurrentCancelAction) {
            & $script:CurrentCancelAction
            $script:CurrentCancelAction = $null
        }
        Show-ErrorPage -Title "Setup cancelled" -Message "Nothing was installed. You can close this window."
    }.GetNewClosure())

    $ctx = [PSCustomObject]@{
        TorchVariant = $TorchVariant
        AppendLog    = $appendLog
        AdvanceStep  = $advanceStep
        ProgressBar  = $progressBar
        LogBox       = $logBox
        PythonExe    = $null
    }
    Step-Relocate -Ctx $ctx
}

function Step-Relocate {
    param($Ctx)
    & $Ctx.AdvanceStep "Setting up install location..."
    try {
        Install-ToProgramsFolder -OnOutputLine $Ctx.AppendLog
    } catch {
        Show-ErrorPage -Title "Setup failed" -Message $_.Exception.Message -LogText $Ctx.LogBox.Text
        return
    }
    # The copy above yields via DoEvents(), which is the one place a Cancel
    # click can get processed while this synchronous step is still on the
    # stack - if that happened, stop here instead of continuing the install
    # underneath the cancelled screen the user is now looking at.
    if ($script:SetupCancelled) { return }
    Step-FindPython -Ctx $Ctx
}

function Step-FindPython {
    param($Ctx)
    & $Ctx.AdvanceStep "Checking for Python..."
    $pythonExe = Find-PythonExe
    if ($pythonExe) {
        $Ctx.PythonExe = $pythonExe
        Step-CreateVenv -Ctx $Ctx
        return
    }
    & $Ctx.AppendLog "Python not found - installing automatically..."
    Install-Python -AppendLog $Ctx.AppendLog -OnDone {
        param($foundExe)
        if (-not $foundExe) {
            Show-ErrorPage -Title "Couldn't install Python" `
                -Message "Please install Python yourself from https://www.python.org/downloads/ (check `"Add python.exe to PATH`" during install), then run Setup again." `
                -LogText $Ctx.LogBox.Text
            return
        }
        $Ctx.PythonExe = $foundExe
        Step-CreateVenv -Ctx $Ctx
    }.GetNewClosure()
}

function Step-CreateVenv {
    param($Ctx)
    & $Ctx.AdvanceStep "Creating a Python environment..."
    $tracked = New-TrackedProcess -FilePath $Ctx.PythonExe -Arguments "-m venv `"$InstallDir\venv`"" `
        -OnOutputLine $Ctx.AppendLog -OnExit {
            param($cancelled, $exitCode, $errText)
            $script:CurrentCancelAction = $null
            if ($cancelled) { return }
            if ($exitCode -ne 0) {
                Show-ErrorPage -Title "Setup failed" -Message "Could not create the Python environment." `
                    -LogText ($Ctx.LogBox.Text + "`r`n" + $errText)
                return
            }
            Step-InstallBase -Ctx $Ctx
        }.GetNewClosure()
    $script:CurrentCancelAction = $tracked.Cancel
}

function Step-InstallBase {
    param($Ctx)
    & $Ctx.AdvanceStep "Preparing the package installer..."
    $venvPython = Join-Path $InstallDir "venv\Scripts\python.exe"
    $tracked = New-TrackedProcess -FilePath $venvPython -Arguments "-m pip install --upgrade pip --quiet" `
        -OnOutputLine $Ctx.AppendLog -OnExit {
            param($cancelled, $exitCode, $errText)
            $script:CurrentCancelAction = $null
            if ($cancelled) { return }
            # A pip self-upgrade hiccup isn't fatal on its own - proceed either way,
            # the real requirements install below is what actually matters.
            Step-InstallRequirements -Ctx $Ctx
        }.GetNewClosure()
    $script:CurrentCancelAction = $tracked.Cancel
}

function Step-InstallRequirements {
    <#
        No -quiet here (unlike the pip self-upgrade above) - this is the
        slowest ordinary step, and pip's normal (non-progress-bar, since
        output is redirected to a file rather than a real console) output
        still prints "Collecting/Downloading/Installing" lines as it goes,
        which is exactly what keeps the log moving so this doesn't look
        stuck for minutes at a time.
    #>
    param($Ctx)
    & $Ctx.AdvanceStep "Installing required components (this can take several minutes)..."
    $venvPython = Join-Path $InstallDir "venv\Scripts\python.exe"
    $tracked = New-TrackedProcess -FilePath $venvPython `
        -Arguments "-m pip install -r `"$InstallDir\requirements.txt`"" `
        -OnOutputLine $Ctx.AppendLog -OnExit {
            param($cancelled, $exitCode, $errText)
            $script:CurrentCancelAction = $null
            if ($cancelled) { return }
            if ($exitCode -ne 0) {
                Show-ErrorPage -Title "Setup failed" -Message "Could not install required components." `
                    -LogText ($Ctx.LogBox.Text + "`r`n" + $errText)
                return
            }
            Step-InstallTorch -Ctx $Ctx
        }.GetNewClosure()
    $script:CurrentCancelAction = $tracked.Cancel
}

function Step-InstallTorch {
    param($Ctx)
    & $Ctx.AdvanceStep $(if ($Ctx.TorchVariant -eq "gpu") { "Installing GPU-accelerated components (this can take a while)..." } else { "Installing components for photo/video analysis (this can take a few minutes)..." })
    $venvPython = Join-Path $InstallDir "venv\Scripts\python.exe"
    $tracked = New-TrackedProcess -FilePath $venvPython `
        -Arguments "-m pip install -r `"$InstallDir\requirements-$($Ctx.TorchVariant).txt`" --force-reinstall" `
        -OnOutputLine $Ctx.AppendLog -OnExit {
            param($cancelled, $exitCode, $errText)
            $script:CurrentCancelAction = $null
            if ($cancelled) { return }
            if ($exitCode -ne 0) {
                Show-ErrorPage -Title "Setup failed" -Message "Could not install torch." `
                    -LogText ($Ctx.LogBox.Text + "`r`n" + $errText)
                return
            }
            Step-DownloadModel -Ctx $Ctx
        }.GetNewClosure()
    $script:CurrentCancelAction = $tracked.Cancel
}

function Step-DownloadModel {
    param($Ctx)
    & $Ctx.AdvanceStep "Downloading the content-tagging AI model..."
    $venvPython = Join-Path $InstallDir "venv\Scripts\python.exe"
    $tracked = New-TrackedProcess -FilePath $venvPython `
        -Arguments "-c `"from app.content_tagging import download_models; download_models()`"" `
        -OnOutputLine $Ctx.AppendLog -OnExit {
            param($cancelled, $exitCode, $errText)
            $script:CurrentCancelAction = $null
            if ($cancelled) { return }
            if ($exitCode -ne 0) {
                & $Ctx.AppendLog "Note: could not download the content-tagging model - Photo Organizer will still work, just without content tagging until you run Setup again with a working connection."
            }
            Step-Finish -Ctx $Ctx
        }.GetNewClosure()
    $script:CurrentCancelAction = $tracked.Cancel
}

function Step-Finish {
    param($Ctx)
    & $Ctx.AdvanceStep "Finishing up..."
    try {
        $configPath = Join-Path $InstallDir "config.yaml"
        if (-not (Test-Path $configPath)) {
            Copy-Item -Path (Join-Path $InstallDir "config.example.yaml") -Destination $configPath -Force
        }
        New-DesktopShortcut
        New-UninstallScript
        Register-UninstallEntry
    } catch {
        Show-ErrorPage -Title "Setup failed" -Message $_.Exception.Message -LogText $Ctx.LogBox.Text
        return
    }
    $Ctx.ProgressBar.Value = 100
    Show-FinishPage
}

# ============================================================
#  Page: Finish / Error
# ============================================================

function Show-FinishPage {
    $label = New-BodyLabel -Text "Setup complete!`n`nDouble-click the `"$AppName`" icon on your Desktop to run it." -Y 40 -Height 120
    $label.Font = New-Object System.Drawing.Font("Segoe UI", 10)
    $closeBtn = New-WizardButton -Text "Finish" -X 426
    $closeBtn.Add_Click({ $Form.Close() }.GetNewClosure())
    Set-Page -Controls @($label, $closeBtn)
    $Form.AcceptButton = $closeBtn
    $Form.CancelButton = $closeBtn
}

function Show-ErrorPage {
    param([string]$Title, [string]$Message, [string]$LogText = "")

    $label = New-BodyLabel -Text "$Title`n`n$Message" -Y 20 -Height 80
    $controls = @($label)

    if ($LogText) {
        $logBox = New-Object System.Windows.Forms.TextBox
        $logBox.Location = New-Object System.Drawing.Point(24, 100)
        $logBox.Size = New-Object System.Drawing.Size(512, 188)
        $logBox.Multiline = $true
        $logBox.ScrollBars = "Vertical"
        $logBox.ReadOnly = $true
        $logBox.Font = New-Object System.Drawing.Font("Consolas", 8.5)
        $logBox.Text = $LogText
        $controls += $logBox
    }

    $closeBtn = New-WizardButton -Text "Close" -X 426
    $closeBtn.Add_Click({ $Form.Close() }.GetNewClosure())
    $controls += $closeBtn

    Set-Page -Controls $controls
    $Form.AcceptButton = $closeBtn
    $Form.CancelButton = $closeBtn
}

# ============================================================
#  Entry point
# ============================================================

Show-WelcomePage
$Form.Add_Shown({ $Form.Activate() })
[void]$Form.ShowDialog()
