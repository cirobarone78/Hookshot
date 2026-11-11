# The launcher bringing versions, tried whole without a game, a release or GitHub:
#
#   powershell -File tests/builder_launcher/rig/run.ps1
#
# It makes up releases (rig.py: their setup lists and parts, handed out by a web server on this PC), a scratch install with
# v2.1.0 in use (HOOKSHOT_SETUP_BASE) and a game folder holding v2.1.0, and compiles the setup (builder/setup/setup.c) and a
# stand-in for a version's python.exe that says what make_game.py says while it builds (fakepy.c). Then:
#   1. the setup's engine mode alone (--engine --tag <tag>): what it installs, links, leaves alone and says;
#   2. the launcher itself (the Debug build of builder/HookshotBuilder, when it is built), its button pressed for a version: the
#      builder installed, the folder built, a build that stops, a build cancelled, a download that fails, the latest release, the builder opened
#      with nothing asked. Its window is drawn to PNG files away from the screen (HOOKSHOT_UI_SHOT), for a look.
# Nothing of the real install (%LOCALAPPDATA%\HookshotBuilder) or of a real game is read or written: that is checked too.
#
# -Mingw: llvm-mingw's bin folder (default: an installed Hookshot Builder's, else %LLVM_MINGW%\bin). -Builder: the builder to
# press (default: the Debug build). -Out: where the rig and the pictures go (default: %TEMP%\hookshot-launcher-rig).
param(
    [string]$Mingw = "",
    [string]$Builder = "",
    [string]$Out = "$env:TEMP\hookshot-launcher-rig",
    [int]$Port = 8791
)
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$repo = (Resolve-Path "$here\..\..\..").Path
if (-not $Mingw) {
    $Mingw = Get-ChildItem "$env:LOCALAPPDATA\HookshotBuilder\versions\*\HookshotBuilder\tools\llvm-mingw\bin" -Directory -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
    if (-not $Mingw -and $env:LLVM_MINGW) { $Mingw = "$env:LLVM_MINGW\bin" }
}
if (-not $Mingw -or -not (Test-Path "$Mingw\x86_64-w64-mingw32-clang.exe")) { "llvm-mingw was not found: pass -Mingw <its bin folder>"; exit 2 }
if (-not $Builder) { $Builder = "$repo\builder\HookshotBuilder\bin\Debug\net8.0-windows\HookshotBuilder.exe" }
if (-not $env:DOTNET_ROOT -and (Test-Path "$env:LOCALAPPDATA\Microsoft\dotnet\dotnet.exe")) { $env:DOTNET_ROOT = "$env:LOCALAPPDATA\Microsoft\dotnet" }

New-Item -ItemType Directory -Force $Out | Out-Null
$ErrorActionPreference = "Continue"
& "$Mingw\x86_64-w64-mingw32-windres.exe" "$repo\builder\setup\setup.rc" -I "$repo\builder\setup" -O coff -o "$Out\setup_rc.o"
& "$Mingw\x86_64-w64-mingw32-clang.exe" -O2 -mwindows -municode "$repo\builder\setup\setup.c" "$Out\setup_rc.o" -lwinhttp -lbcrypt -lcomctl32 -lshell32 -lole32 -o "$Out\HookshotBuilder-Setup.exe"
if ($LASTEXITCODE) { "the setup did not compile"; exit 2 }
& "$Mingw\x86_64-w64-mingw32-clang.exe" -O1 "$here\fakepy.c" -o "$Out\fakepy.exe"
if ($LASTEXITCODE) { "fakepy.c did not compile"; exit 2 }
$setup = "$Out\HookshotBuilder-Setup.exe"
$real = "$env:LOCALAPPDATA\HookshotBuilder"
function Real { if (Test-Path $real) { (Get-ChildItem $real | ForEach-Object { "$($_.Name) $($_.LastWriteTimeUtc.Ticks)" }) -join "|" } else { "" } }
$realBefore = Real

$script:fail = 0
function Check([bool]$ok, [string]$what) { if ($ok) { "  ok    $what" } else { "  FAIL  $what"; $script:fail++ } }
function Versions { ((Get-ChildItem "$Out\base\versions" -Directory).Name | Sort-Object) -join ", " }
function Folder { ((Get-Content "$Out\game\hookshot_version.txt") -replace "^version=", "").Trim() }
function Rig { python -I "$here\rig.py" $Out $Port | Out-Null }
# (what a picture shows, in words: the builder writes them beside each picture it draws, Launcher.cs SaveShot)
function Says([string]$name) {
    $said = @{}
    foreach ($line in (Get-Content "$Out\$name.txt" -Encoding UTF8 -ErrorAction SilentlyContinue)) {
        $at = $line.IndexOf("=")
        if ($at -gt 0) { $said[$line.Substring(0, $at)] = $line.Substring($at + 1) }
    }
    $said
}
function Engine([string]$tag, [string]$list) {
    $env:HOOKSHOT_SETUP_LIST = "http://127.0.0.1:$Port/$list"
    $said = & cmd /c "`"$setup`" --engine --tag $tag" 2>&1
    $script:code = $LASTEXITCODE
    $said
}
$named = "HOOKSHOT_SETUP_BASE", "HOOKSHOT_SETUP_LIST", "HOOKSHOT_LATEST_TAG", "HOOKSHOT_UI_PREVIEW", "HOOKSHOT_UI_SHOT", "HOOKSHOT_KEEP_BUILD_FILES", "FAKE_STEP_MS", "FAKE_FAIL"

Rig
$server = Start-Process python -ArgumentList "-I", "-m", "http.server", "$Port", "--bind", "127.0.0.1", "--directory", "`"$Out\www`"" -WindowStyle Hidden -PassThru
Start-Sleep -Milliseconds 900
try {
    $env:HOOKSHOT_SETUP_BASE = "$Out\base"

    "=== the setup's engine mode ==="
    "--- a version not on the PC, beside the one in use"
    $said = Engine "v2.2.0-rc.1" "list-v2.2.0-rc.1.txt"; $said | ForEach-Object { "    $_" }
    $new = "$Out\base\versions\v2.2.0-rc.1\HookshotBuilder"
    Check ($code -eq 0 -and ($said -contains "@@installed v2.2.0-rc.1")) "it says @@installed and ends with 0 (ended with $code)"
    Check ((Get-Content "$new\tools\version.txt" -ErrorAction SilentlyContinue) -eq "v2.2.0-rc.1") "its tools are there, and say their version"
    Check (@($said -match "unchanged: kept").Count -eq 1) "the part it shares with the version in use was not downloaded"
    $names = @(fsutil hardlink list "$new\tools\python\python.exe").Count
    Check ($names -eq 2) "that part's files are linked, not copied ($names names for python.exe)"
    Check ((Get-Content "$Out\base\versions\current.txt") -eq "v2.1.0") "the version in use is still the one in use"
    Check (Test-Path "$Out\base\versions\v2.1.0\HookshotBuilder\tools\python\python.exe") "the version in use kept its python"
    Check (-not (Test-Path "$Out\base\versions\v2.2.0-rc.1.part")) "nothing half-unpacked is left"
    Check (@($said -match "^@@percent ").Count -ge 1) "the download says how far it is"
    "--- again: already there"
    $said = Engine "v2.2.0-rc.1" "list-v2.2.0-rc.1.txt"
    Check ($code -eq 0 -and ($said -contains "@@installed v2.2.0-rc.1") -and -not ($said -match "Downloading")) "nothing downloaded twice"
    "--- the list of another release than the one asked for"
    $said = Engine "v2.2.0" "list-v2.0.14.txt"; $said | Select-Object -Last 1 | ForEach-Object { "    $_" }
    Check ($code -eq 1 -and @($said -match "^@@error ").Count -eq 1 -and -not (Test-Path "$Out\base\versions\v2.2.0")) "it stops with @@error and installs nothing"
    "--- the version in use"
    (Get-Content "$Out\www\list-v2.2.0.txt") -replace "^tag .*", "tag v2.1.0" | Set-Content "$Out\www\list-v2.1.0.txt"
    $said = Engine "v2.1.0" "list-v2.1.0.txt"; $said | Select-Object -Last 1 | ForEach-Object { "    $_" }
    Check ($code -eq 1 -and (Test-Path "$Out\base\versions\v2.1.0\HookshotBuilder\tools\version.txt")) "it is refused and left whole"
    "--- a release with no setup files"
    $said = Engine "v2.0.14" "no-such-list.txt"; $said | Select-Object -Last 1 | ForEach-Object { "    $_" }
    Check ($code -eq 1 -and @($said -match "^@@error ").Count -eq 1) "@@error, exit 1"
    "--- a shared part that cannot be linked (the version in use has no parts list): downloaded"
    Rename-Item "$Out\base\versions\v2.1.0\parts.txt" "parts.off"
    $said = Engine "v2.0.14" "list-v2.0.14.txt"
    Check ($code -eq 0 -and @($said -match "Downloading part 2").Count -ge 1 -and (Test-Path "$Out\base\versions\v2.0.14\HookshotBuilder\tools\python\python.exe")) "the part is downloaded instead"

    if (-not (Test-Path $Builder)) { "=== the launcher: not tried ($Builder is not built) ===" }
    else {
        "=== the launcher ==="
        Rig
        Copy-Item $setup (Join-Path (Split-Path $Builder) "HookshotBuilder-Setup.exe") -Force   # (the setup beside the builder, as a release has it)
        $env:FAKE_STEP_MS = "220"
        function Press([string]$name, [string]$tags, [string]$preview, [string]$list, [switch]$Bare) {
            $env:HOOKSHOT_LATEST_TAG = $tags; $env:HOOKSHOT_UI_PREVIEW = $preview; $env:HOOKSHOT_UI_SHOT = "$Out\$name.png"
            $env:HOOKSHOT_SETUP_LIST = if ($list) { "http://127.0.0.1:$Port/$list" } else { "" }
            Remove-Item "$Out\$name.png", "$Out\$name.txt", "$Out\$name-working.png", "$Out\$name-working.txt" -ErrorAction SilentlyContinue
            $p = if ($Bare) { Start-Process $Builder -PassThru } else { Start-Process $Builder -ArgumentList "--launch", "`"$Out\game`"" -PassThru }
            if (-not $p.WaitForExit(90000)) { $p.Kill(); "  !! $name : stopped by the rig (not out in 90 s)" }
            Test-Path "$Out\$name.png"
        }
        $all = "v2.2.0-rc.1,v2.1.0,v2.0.14"
        "--- a pre-release not on the PC: its builder installed (hidden), then the folder built with it"
        $env:HOOKSHOT_KEEP_BUILD_FILES = "1"; $env:FAKE_FAIL = ""
        $drawn = Press "pre" $all "pick=release:v2.2.0-rc.1,go" "list-v2.2.0-rc.1.txt"
        Check $drawn "the launcher drew itself when it ended"
        Check (Test-Path "$Out\pre-working.png") "and on the way"
        Check ((Folder) -eq "v2.2.0-rc.1") "the folder holds v2.2.0-rc.1 (it says $(Folder))"
        Check ((Versions) -eq "v2.1.0, v2.2.0-rc.1") "both builders are installed, side by side ($(Versions))"
        Check ((Get-Content "$Out\base\versions\current.txt") -eq "v2.1.0") "a pre-release's builder is not made the one in use"
        Check ((Test-Path "$Out\base\launcher.json") -and (Real) -eq $realBefore) "the pick was kept in the scratch install, and the real one is untouched"
        "--- back to the release whose builder is here: no download"
        $drawn = Press "back" $all "pick=release:v2.1.0,go" "no-such-list.txt"
        Check ($drawn -and (Folder) -eq "v2.1.0") "the folder holds v2.1.0 again, with nothing downloaded (it says $(Folder))"
        "--- a build that stops"
        $env:FAKE_FAIL = "1"
        $drawn = Press "stopped" $all "pick=release:v2.2.0-rc.1,go" "list-v2.2.0-rc.1.txt"
        $env:FAKE_FAIL = ""
        Check ($drawn -and (Folder) -eq "v2.1.0") "the launcher drew the stop, and the folder is as it was ($(Folder))"
        "--- a build cancelled half way"
        $drawn = Press "cancelled" $all "pick=release:v2.2.0-rc.1,go,cancel" "list-v2.2.0-rc.1.txt"
        Check ($drawn -and (Folder) -eq "v2.1.0" -and -not (Get-Process fakepy -ErrorAction SilentlyContinue)) "the launcher is back as it was, the folder too, and the build's program is gone"
        "--- a builder that cannot be downloaded"
        $drawn = Press "nolist" $all "pick=release:v2.0.14,go" "no-such-list.txt"
        Check ($drawn -and (Folder) -eq "v2.1.0" -and (Versions) -eq "v2.1.0, v2.2.0-rc.1") "the launcher drew the stop; nothing installed, the folder as it was"
        "--- the latest release, ahead of the builder in use; the build files are let go after it, as after any build"
        $env:HOOKSHOT_KEEP_BUILD_FILES = ""
        $drawn = Press "latest" "v2.2.0,v2.1.0,v2.0.14" "pick=release:v2.2.0,go" "list-v2.2.0.txt"
        $env:HOOKSHOT_KEEP_BUILD_FILES = "1"
        Check ($drawn -and (Folder) -eq "v2.2.0") "the folder holds v2.2.0 (it says $(Folder))"
        Check ((Get-Content "$Out\base\versions\current.txt") -eq "v2.2.0") "its builder is the one in use from the next start"
        Check ((Versions) -eq "v2.2.0") "and the builders no longer in use are gone ($(Versions))"
        $s = Says "pre-working"
        Check ($s.face -eq "Launcher" -and $s.state -eq "Working" -and $s.enabled -eq "False" -and $s.foot -like "Updating... *%" -and $s.rows -like "*v2.2.0-rc.1 ``[busy``]*") "on the way it is the launcher still: Play faint, the bar at the menu's foot, the version's mark turning ($($s.foot))"
        "--- the builder opened with nothing asked: the launcher of the game built last"
        Set-Content "$Out\base\builder-settings.json" ('{"Out":' + (ConvertTo-Json "$Out\game") + '}') -Encoding ascii
        $drawn = Press "home" "v2.2.0,v2.1.0" "" "" -Bare
        Check ($drawn -and (Says "home").face -eq "Launcher" -and (Says "home").button -eq "Play") "it opened as the launcher: $((Says 'home').button), $((Says 'home').under)"
        "--- and with no game it built: the launcher of a game whose own launcher was played from (launcher.json)"
        Remove-Item "$Out\base\builder-settings.json"
        $drawn = Press "home-known" "v2.2.0,v2.1.0" "" "" -Bare
        Check ($drawn -and (Says "home-known").face -eq "Launcher") "it opened as the launcher"
        "--- the menu: the versions"
        # (a version the setup is unpacking, and one it never finished (no installed.txt): neither is a builder here)
        foreach ($half in "v1.9.0.part", "v1.8.0") {
            $t = "$Out\base\versions\$half\HookshotBuilder\tools"
            New-Item -ItemType Directory -Force "$t\nx2", "$t\python" | Out-Null
            Copy-Item "$Out\fakepy.exe" "$t\python\python.exe"
            Set-Content "$t\nx2\make_game.py" "# stand-in" -Encoding ascii
            Set-Content "$t\version.txt" ($half -replace "\.part$", "") -Encoding ascii
        }
        $drawn = Press "menu" "v2.3.0,v2.2.0,v2.1.0" "versions" ""
        $s = Says "menu"
        Check ($drawn -and $s.menu -eq "releases" -and $s.rows -like "v2.3.0 - Latest ``[get``] | v2.2.0 ``[tick``]*") "open on Releases, the folder's version ticked ($($s.rows))"
        Check ($s.rows -notlike "*v1.9.0*" -and $s.rows -notlike "*v1.8.0*") "a version half unpacked, or never finished, is not listed as installed ($($s.rows))"
        Check ($s.foot -eq "Update Available" -and $s.footline -eq "v2.3.0 Latest") "a newer release: Update Available at its foot ($($s.foot); $($s.footline))"
        "--- the menu's Build tab: the build's choices"
        $drawn = Press "pages" "v2.2.0,v2.1.0" "pages" ""
        Check ($drawn -and (Says "pages").face -eq "Files" -and (Says "pages").menu -eq "build") "the choices are in the menu's Build tab ($((Says 'pages').build))"

        # ---- the build itself (builder/HookshotBuilder/MainWindow.xaml.cs), on the same screen: a copy of the builder with the
        # stand-in tools beside it, as a release has its own, and an install of its own with a made-up game file chosen ----
        "=== the build, on the launcher's screen ==="
        $app = "$Out\app"
        Remove-Item $app, "$Out\base2", "$Out\newgame" -Recurse -Force -ErrorAction SilentlyContinue
        Copy-Item (Split-Path $Builder) $app -Recurse
        New-Item -ItemType Directory -Force "$app\tools\nx2", "$app\tools\python", "$Out\base2" | Out-Null
        Copy-Item "$Out\fakepy.exe" "$app\tools\python\python.exe"
        Set-Content "$app\tools\nx2\make_game.py" "# the test rig's stand-in: fakepy.exe plays this part" -Encoding ascii
        Set-Content "$app\tools\version.txt" "v2.1.0" -Encoding ascii
        Set-Content "$Out\made-up.nup" "not a game file: the test rig's" -Encoding ascii
        Set-Content "$Out\base2\builder-settings.json" ('{"Out":' + (ConvertTo-Json "$Out\newgame") + ',"Nup":' + (ConvertTo-Json "$Out\made-up.nup") + '}') -Encoding ascii
        $env:HOOKSHOT_SETUP_BASE = "$Out\base2"
        function Build([string]$name, [string]$preview, [string[]]$asked) {
            $env:HOOKSHOT_LATEST_TAG = "v2.1.0"; $env:HOOKSHOT_UI_PREVIEW = $preview; $env:HOOKSHOT_UI_SHOT = "$Out\$name.png"
            Remove-Item "$Out\$name.png", "$Out\$name.txt", "$Out\$name-working.png", "$Out\$name-working.txt" -ErrorAction SilentlyContinue
            $p = if ($asked) { Start-Process "$app\HookshotBuilder.exe" -ArgumentList $asked -PassThru } else { Start-Process "$app\HookshotBuilder.exe" -PassThru }
            if (-not $p.WaitForExit(90000)) { $p.Kill(); "  !! $name : stopped by the rig (not out in 90 s)" }
            Test-Path "$Out\$name.png"
        }
        "--- with no game yet: the choices"
        $drawn = Build "first-files" "files" @()
        $s = Says "first-files"
        Check ($drawn -and $s.face -eq "Files" -and $s.menu -eq "build" -and $s.build -eq "Build Game" -and $s.files -like "made-up.nup*" -and $s.folder -eq "$Out\newgame") "the game file chosen last time and the folder, and Build Game ($($s.files); $($s.under))"
        "--- Build pressed: the game built, the screen the launcher's throughout"
        $drawn = Build "first" "go,steps" @()
        $s = Says "first-working"
        Check ($s.face -eq "Build" -and $s.enabled -eq "False" -and $s.build -like "Building... *%") "on the way: the bar in Build Game's place, and how far ($($s.build))"
        Check ($s.menu -eq "build" -and $s.buildline -like "Compile...*" -and $s.steps -like "*Translate to PC code: done*Compile: now*Put it together: to come*") "the step under way under it ($($s.buildline); $($s.steps))"
        $s = Says "first"
        Check ($drawn -and $s.face -eq "Launcher" -and $s.button -eq "Play" -and $s.enabled -eq "True" -and $s.buildline -like "Your game is ready*") "when it ended: the launcher of the new game, with Play ($($s.under); $($s.buildline))"
        Check ((Get-Content "$Out\newgame\hookshot_version.txt" -ErrorAction SilentlyContinue) -eq "version=v2.1.0") "the folder holds the game"
        "--- the game's own update offer (--update <folder>): the same build, the same screen"
        $drawn = Build "offer" "x" @("--update", "`"$Out\newgame`"", "--tag", "v2.1.0", "--fetched")
        $s = Says "offer"
        Check ((Says "offer-working").foot -like "Updating... *%" -and (Says "offer-working").menu -eq "releases") "on the way: the bar at the menu's foot, $((Says 'offer-working').foot)"
        Check ($drawn -and $s.face -eq "Launcher" -and $s.button -eq "Play" -and $s.enabled -eq "True" -and $s.buildline -like "Your game is updated*") "when it ended: the launcher, with Play ($($s.buildline))"
        "--- a build that stops"
        Remove-Item "$Out\newgame" -Recurse -Force -ErrorAction SilentlyContinue
        $env:FAKE_FAIL = "1"
        $drawn = Build "first-stopped" "go" @()
        $env:FAKE_FAIL = ""
        $s = Says "first-stopped"
        Check ($drawn -and $s.face -eq "Problem" -and $s.build -eq "Build stopped" -and $s.buildwhy -like "*Nothing was changed in your game folder." -and $s.steps -like "*Compile: stopped*") "the Build tab says so, and why ($($s.buildwhy))"
        Check (-not (Test-Path "$Out\newgame\hookshot_version.txt")) "and no game was made"
        $env:HOOKSHOT_SETUP_BASE = "$Out\base"

        "pictures: $Out\*.png"
    }
    Check ((Real) -eq $realBefore) "the real install is untouched"
}
finally {
    Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    foreach ($n in $named) { Set-Item "env:$n" "" }
}
if ($script:fail) { "$($script:fail) check(s) FAILED"; exit 1 }
"all checks passed"
