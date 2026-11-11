using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using Path = System.Windows.Shapes.Path;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Effects;
using System.Windows.Shapes;
using System.Windows.Threading;
using Microsoft.Win32;

namespace HookshotBuilder;

/// One 960x640 window that looks the same throughout, as drawn in Paper (the file Hookshot): the launcher of a game that is
/// built (Launcher.cs), and, here, the build itself in that window. A build is the launcher's screen with other things in
/// its places: the game files and the folder between the wordmark and the button, the button that says Build, then the strip
/// that fills, then Play. Its options and its steps are in the menu. The game's update offer (Updater.cs) is the same build.
public partial class MainWindow : Window
{
    /// What the screen is showing: the launcher of a built game (Launcher.cs), the choices of a build from game files, a build
    /// or an update under way, or one that stopped
    enum Face { Launcher, Files, Build, Problem }
    Face face = Face.Launcher;
    bool searching;            // (the game files are being looked for)
    string problemTitle = "", problemWhy = "", stepLine = "";
    double buildFraction;
    bool detailsShown, desktopShortcut = true, startShortcut = true;
    (string Folder, string? Tag)? lastUpdate;   // (the update last begun: Retry begins it again)

    static readonly Brush BadInk = Frozen(0xFF, 0x83, 0x73);

    const long NeededBytes = 45L << 30;   // (measured 2026-11-09: the game data 24.4 GB, the shader caches ~8 GB, the game 0.4 GB, the build files ~5 GB at their peak; the rest headroom)
    Language lang = Strings.Default();
    string T(S s) => (int)s < lang.Text.Length ? lang.Text[(int)s] : Strings.All[0].Text[(int)s];

    readonly DispatcherTimer clock = new() { Interval = TimeSpan.FromSeconds(1) };
    readonly Stopwatch elapsed = new();
    readonly Stopwatch compileClock = new();
    readonly Stopwatch shaderClock = new();   // (the shaders' step, and how far it is: Tick)
    double shaderDone;
    readonly Dictionary<string, StepRow> rows = new();
    readonly Dictionary<string, (bool Ok, string Text)?> checks = new(StringComparer.OrdinalIgnoreCase);
    readonly List<Dump> dumps = new();
    readonly System.Text.StringBuilder log = new();
    Runner? runner;
    string? current;
    string finished = "";
    string? chosenNup, romfs, exefs;
    // (issue 650) "Using the folders ...", while romfs and exefs are the game files: said under the pointer on their row
    string? foldersNote;
    bool updating, checking;
    double compiled;
    int filesDone, filesOf;
    int filesChanged = -1, filesCompiled;
    double compileEta = -1;
    long thisCompile, previousTotal = -1;
    string lastFailure = "";
    /// The game folder this window opens as the launcher of (Launcher.cs): the one hookshot.exe in a game folder names
    /// (--launch), or, opened with nothing asked, the game built last. null: the installer's own pages
    readonly string? launchAt;

    public MainWindow()
    {
        InitializeComponent();
        launchAt = LaunchArg() ?? HomeGame();
        OutPath.Text = BuilderHome.DefaultGame;
        // (a portable home on a USB drive: no shortcuts on this PC unless asked, as the setup's portable install)
        if (BuilderHome.Portable) desktopShortcut = startShortcut = false;
        LanguageBox.ItemsSource = Strings.All;
        LanguageBox.SelectedItem = lang;
        WorkerBox.ItemsSource = BuildWorkers.Choices(Environment.ProcessorCount);
        WorkerBox.SelectedIndex = 0;
        MemoryBox.ItemsSource = BuildMemory.Choices(BuildMemory.TotalGb());
        MemoryBox.SelectedIndex = 0;
        PreTick.IsChecked = Track != Updater.Release;
        PreTick.ToolTip = PreTip;
        clock.Tick += (_, _) => Tick();
        Drop += Dropped;
        // (its own dark page from the first frame, no grey acrylic before it draws)
        SourceInitialized += (_, _) => Glass.Plain(this, Color.FromRgb(0x12, 0x12, 0x12));
        Loaded += (_, _) => Start();
        UseOwnFont();
        StateChanged += (_, _) =>
        {
            var full = WindowState == WindowState.Maximized;
            Root.Margin = full ? Glass.Overhang(this) : new Thickness(0);
            LauncherMax.Content = ((char)(full ? 0xE923 : 0xE922)).ToString();   // (Segoe Fluent Icons: restore, maximise)
            LauncherMax.ToolTip = full ? "Restore" : "Maximize";
            System.Windows.Automation.AutomationProperties.SetName(LauncherMax, full ? "Restore" : "Maximize");
        };
        PreviewKeyDown += (_, e) =>
        {
            if (e.Key != System.Windows.Input.Key.Escape || !menuOpen) return;
            ShowMenu(false);
            e.Handled = true;
        };
        ShowFace(face);
        // (development, HOOKSHOT_UI_SHOT: the window drawn to a file, Launcher.cs. Away from the screen, and it takes no keys)
        if (Shot != null)
        {
            ShowActivated = false;
            ShowInTaskbar = false;
            WindowStartupLocation = WindowStartupLocation.Manual;
            (Left, Top) = (-20000, -20000);
        }
    }

    // ================= the start =================

    async void Start()
    {
        // (development) HOOKSHOT_TEST_SHORTCUTS=<game folder>: both shortcuts made for it, the result in the log beside the app, and out
        if (Environment.GetEnvironmentVariable("HOOKSHOT_TEST_SHORTCUTS") is { Length: > 0 } testFolder)
        {
            Finder.Shortcuts(testFolder, true, true);
            File.WriteAllText(System.IO.Path.Combine(AppContext.BaseDirectory, "shortcut-test.txt"),
                              $"desktop {File.Exists(Finder.DesktopLink)} start {File.Exists(Finder.StartLink)} error {Finder.ShortcutError}");
            Leave();
            return;
        }
        if (launchAt is { } launchFolder)   // (hookshot.exe in the game folder, or the game built last: the launcher at once, Launcher.cs)
        {
            ShowLauncher(launchFolder);
            return;
        }
        if (Environment.GetCommandLineArgs().Contains("--update"))
        {
            Updater.FromCommandLine(this);
            await ShotWhenEnded();
            return;
        }
        await OpenFiles(first: true);
        await ShotWhenEnded();
    }

    /// (development) HOOKSHOT_UI_SHOT with no game to launch: the build's screen as drawn, once what was started here (an
    /// update, or the button pressed by the preview's "go") has ended, and out
    async Task ShotWhenEnded()
    {
        if (Shot == null) return;
        await Task.Delay(400);
        while (runner != null || download != null || checking || freeing != null) await Task.Delay(100);
        await Task.Delay(700);
        SaveShot(Shot);
        Leave();
    }

    /// The build's choices on the screen: when there is no game yet (first), or from the menu's "Build from game files". The
    /// game files are looked for while they show
    async Task OpenFiles(bool first)
    {
        searching = filesOpened == false;
        filesOpened = true;   // (before the tab is shown: showing it looks for them the first time)
        if (face != Face.Build && face != Face.Problem) ShowFace(Face.Files);
        if (first) ShowMenu(true, atOnce: true);
        ShowTab(TabBuild);
        FillDumps();
        Refresh();
        if (!searching) return;
        var found = await Task.Run(Finder.FindDumps);
        searching = false;
        // (after any the player gave while they were looked for: dropped on the window, browsed to)
        dumps.AddRange(found.Where(f => !dumps.Any(d => string.Equals(d.Path, f.Path, StringComparison.OrdinalIgnoreCase))));
        ApplySettings();
        if (!first) OutPath.Text = launchFolder;   // (from a game's launcher: that game's folder, not the one built last)
        FillDumps();
        Refresh();
        // (development) the preview's screens are made up and nothing is run; with "go" the game files are checked and the button
        // is pressed, as a player would ("steps": the menu open in the picture drawn on the way)
        var go = false;
        if (first && Environment.GetEnvironmentVariable("HOOKSHOT_UI_PREVIEW") is { Length: > 0 } preview)
        {
            Preview(preview);
            var asked = preview.Split(',', StringSplitOptions.TrimEntries);
            (go, stepsHalfWay) = (asked.Contains("go"), asked.Contains("steps"));
            if (!go) return;
        }
        CheckAll();
        // (with no game yet, GitHub's releases are asked for here: Releases lists them, and the builder's own update is offered
        // at the menu's foot when there is a newer one)
        if (first && launchFolder.Length == 0) _ = CheckReleases(say: false);
        if (!go) return;
        while (checking) await Task.Delay(100);
        Refresh();
        if (BuildGame.IsEnabled) StartBuild(this, new RoutedEventArgs());
    }
    bool filesOpened;

    /// The build's state: none under way (Launcher, Files), one building (Build), one that stopped (Problem). The window is
    /// drawn from it (Launcher.cs, Render): the build in the menu's Build tab, an update at the menu's foot
    void ShowFace(Face to)
    {
        face = to;
        if (to != Face.Build && to != Face.Problem) ShowDetails(false);
        Render();
    }

    // ================= what the button does: build, update the game, play it, or get the newer builder =================
    // (as NX2navi's launcher: whatever version the player opens, it checks the latest release and says what is there)

    string? latestTag, updateTarget;
    bool sourcePicked;   // (the player chose game files here: a build from them)

    /// The release a game folder was built with (its hookshot_version.txt), when it keeps its game files for updates
    static string? GameVersion(string folder)
    {
        try
        {
            if (!Directory.Exists(System.IO.Path.Combine(folder, ".hookshot_exefs")) || !Directory.Exists(System.IO.Path.Combine(folder, "romfs")))
                return null;
            foreach (var line in File.ReadAllLines(System.IO.Path.Combine(folder, "hookshot_version.txt")))
                if (line.StartsWith("version=")) return line[8..].Trim() is { Length: > 0 } v ? v : null;
        }
        catch (Exception) { }
        return null;
    }

    void RefreshMode() => Render();

    // ---- the launcher: Hookshot Launcher.exe in a game folder starts this with --launch <folder> (builder/setup/setup.c) ----
    string launchFolder = "";

    /// (opened with nothing asked: the builder is the launcher of the game it built last, when that game is still there; else of
    /// a game whose own launcher was played from on this PC (launcher.json: one built from the command line, or by a builder
    /// installed before). Anything asked of it (--update, --build, a development switch) opens its own pages as before)
    static string? HomeGame()
    {
        if (Environment.GetCommandLineArgs().Length > 1) return null;
        foreach (var asked in new[] { "HOOKSHOT_UI_PREVIEW", "HOOKSHOT_TEST_SHORTCUTS" })
            if (Environment.GetEnvironmentVariable(asked) is { Length: > 0 }) return null;
        string? folder = null;
        try { folder = System.Text.Json.JsonSerializer.Deserialize<BuilderSettings>(File.ReadAllText(SettingsPath))?.Out; } catch (Exception) { }
        if (string.IsNullOrWhiteSpace(folder))
            folder = System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Games", "Hookshot");
        foreach (var known in new[] { folder }.Concat(Choices().Keys))
            if (File.Exists(GameExe(known))) return AsOnDisk(known.TrimEnd('\\', '/'));
        return null;
    }

    /// (launcher.json keeps its folders in small letters: the folder as the disk writes it, for what is shown and for the
    /// shortcuts made onto it)
    static string AsOnDisk(string path)
    {
        try
        {
            var d = new DirectoryInfo(path);
            if (d.Parent == null) return d.FullName.ToUpperInvariant();   // (a drive)
            var name = d.Parent.GetFileSystemInfos(d.Name).FirstOrDefault()?.Name ?? d.Name;
            return System.IO.Path.Combine(AsOnDisk(d.Parent.FullName), name);
        }
        catch (Exception) { return path; }
    }

    static string? LaunchArg()
    {
        var a = Environment.GetCommandLineArgs();
        var i = Array.IndexOf(a, "--launch");
        return i >= 0 && i + 1 < a.Length ? a[i + 1].TrimEnd('\\', '/') : null;
    }

    /// (a folder built before it kept its game files has a version too: only shown)
    static string? ReadVersion(string folder)
    {
        try
        {
            foreach (var line in File.ReadAllLines(System.IO.Path.Combine(folder, "hookshot_version.txt")))
                if (line.StartsWith("version=")) return line[8..].Trim() is { Length: > 0 } v ? v : null;
        }
        catch (Exception) { }
        return null;
    }

    /// The game in a folder: bin\hookshot.exe below its launcher (hookshot.exe), or hookshot.exe in a folder built before the launcher
    static string GameExe(string folder)
    {
        var game = System.IO.Path.Combine(folder, "bin", "hookshot.exe");
        return File.Exists(game) ? game : System.IO.Path.Combine(folder, "hookshot.exe");
    }

    /// (the launcher already checked for updates: the game does not ask again). false: it could not be started (an antivirus
    /// that took bin\hookshot.exe), and the player was told so
    bool StartGame(string folder)
    {
        try
        {
            var si = new ProcessStartInfo(GameExe(folder)) { UseShellExecute = false, WorkingDirectory = folder };
            si.Environment["HOOKSHOT_NO_UPDATE_CHECK"] = "1";
            Process.Start(si);
            return true;
        }
        catch (Exception e)
        {
            MessageBox.Show(this, $"The game could not be started: {e.Message.TrimEnd('.')}. Your antivirus may have removed it.",
                            "Hookshot", MessageBoxButton.OK, MessageBoxImage.Warning);
            return false;
        }
    }

    // ---- the update track (Updater.cs): Settings' Enable pre-releases, saved; by default these tools' own ----
    static readonly string[] TrackIds = { Updater.Release, Updater.Candidate, Updater.Nightly };
    string? chosenTrack;
    string Track
    {
        get
        {
            if (chosenTrack != null) return chosenTrack;
            var saved = BuilderSettings.Load(SettingsPath)?.Track;
            return saved != null && TrackIds.Contains(saved) ? saved : Updater.TrackOf(Tools.Find()?.Version);
        }
    }

    const string PreTip = "Off: the tested releases. On: release candidates too, the next version to try before it is released " +
                          "(a Nightly track chosen before stays Nightly while this is on).";

    /// Enable pre-releases: the update track, Release or Release candidate (one on Nightly stays there while it is on), saved.
    /// Releases lists the pre-releases while it is on
    void PreClick(object sender, RoutedEventArgs e)
    {
        chosenTrack = PreTick.IsChecked == true ? (Track == Updater.Nightly ? Updater.Nightly : Updater.Candidate) : Updater.Release;
        SaveSettings();
        FillChoices();
    }

    /// (Prepare Shaders, Enable FSR 4: kept at once, not only when Build Game is pressed)
    void SettingClick(object sender, RoutedEventArgs e) => SaveSettings();

    // ---- Save my pipeline list: the game folder's pipeline list and the "Submit your pipelines" issue's template, filled in,
    // zipped into the Downloads folder by nx2/pipeline_share.py (as the Linux builder and the game's menu do), then the template
    // on the clipboard, the zip shown in its folder and the issue opened. Nothing is uploaded: the player attaches the zip ----
    const string ShareIssue = "https://github.com/NotRexed/Hookshot/issues/2034";

    async void LaunchShareClick(object sender, RoutedEventArgs e)
    {
        var tools = Tools.Find();
        LaunchShareStatus.Visibility = Visibility.Visible;
        if (tools == null)
        {
            LaunchShareStatus.Text = "The builder's tools were not found: start it again from its own folder.";
            LaunchShareStatus.ToolTip = LaunchShareStatus.Text;
            return;
        }
        LaunchShare.IsEnabled = false;
        LaunchShareStatus.Text = "Saving…";
        var folder = launchFolder;
        var (zip, template, count, error) = await Task.Run(() => SharePipelines(tools, folder, DownloadsFolder()));
        LaunchShare.IsEnabled = true;
        if (zip == null)
        {
            LaunchShareStatus.Text = error ?? "The pipeline list could not be saved.";
            LaunchShareStatus.ToolTip = LaunchShareStatus.Text;   // (whole: the note is cut at three lines)
            return;
        }
        var copied = false;
        try { Clipboard.SetText(template ?? ""); copied = true; } catch (Exception) { }
        var explorer = System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "explorer.exe");   // (not one found on the path)
        try { Process.Start(new ProcessStartInfo(File.Exists(explorer) ? explorer : "explorer.exe", $"/select,\"{zip}\"") { UseShellExecute = true }); } catch (Exception) { }
        var opened = false;
        try { Process.Start(new ProcessStartInfo(ShareIssue) { UseShellExecute = true }); opened = true; } catch (Exception) { }
        var said = $"Saved {System.IO.Path.GetFileName(zip)} ({count} pipelines) in {System.IO.Path.GetDirectoryName(zip)}. " +
            (copied ? "The report is copied. " : "The report is in the zip. ") +
            (opened ? "Issue #2034 is open in your browser: attach" : $"Open {ShareIssue} and attach") +
            " the zip to a comment, then paste the report and say where you played.";
        // (the menu's panel is narrow: the short of it there, the whole under the pointer)
        LaunchShareStatus.Text = $"Saved in {System.IO.Path.GetFileName(System.IO.Path.GetDirectoryName(zip))}: attach it to issue #2034" +
            (copied ? " with the copied report." : ", with the report in it.");
        LaunchShareStatus.ToolTip = said;
    }

    /// nx2/pipeline_share.py --json: (the zip, the template, the pipelines) or the reason there is none
    static (string? Zip, string? Template, int Count, string? Error) SharePipelines(Tools tools, string folder, string outDir)
    {
        var si = new ProcessStartInfo(tools.Python)
        {
            WorkingDirectory = tools.Root,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = System.Text.Encoding.UTF8,
        };
        si.Environment["PYTHONIOENCODING"] = "utf-8";
        foreach (var a in tools.PythonArgs ?? Array.Empty<string>()) si.ArgumentList.Add(a);
        si.ArgumentList.Add("-I");
        si.ArgumentList.Add(System.IO.Path.Combine(tools.Root, "nx2", "pipeline_share.py"));
        si.ArgumentList.Add(folder);
        si.ArgumentList.Add("--out-dir");
        si.ArgumentList.Add(outDir);
        si.ArgumentList.Add("--json");
        try
        {
            using var p = Process.Start(si)!;
            var stderr = p.StandardError.ReadToEndAsync();   // (drained, so a long complaint cannot stall it)
            var line = p.StandardOutput.ReadToEnd().Trim().Split('\n').LastOrDefault() ?? "";
            p.WaitForExit();
            if (!line.StartsWith("{"))   // (the script stopped before its answer: what it said last)
            {
                var last = stderr.Result.Trim().Split('\n').LastOrDefault()?.Trim();
                return (null, null, 0, "The pipeline list could not be saved" + (string.IsNullOrEmpty(last) ? "." : ": " + last));
            }
            using var doc = System.Text.Json.JsonDocument.Parse(line);
            var r = doc.RootElement;
            if (r.GetProperty("ok").GetBoolean())
                return (r.GetProperty("zip").GetString(), r.GetProperty("template").GetString(), r.GetProperty("pipelines").GetInt32(), null);
            return (null, null, 0, r.GetProperty("error").GetString());
        }
        catch (Exception ex)
        {
            return (null, null, 0, tools.OwnPythonMissing ? Tools.OwnPythonMissingText : "The pipeline list could not be saved: " + ex.Message);
        }
    }

    [System.Runtime.InteropServices.DllImport("shell32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode, ExactSpelling = true)]
    static extern int SHGetKnownFolderPath([System.Runtime.InteropServices.MarshalAs(System.Runtime.InteropServices.UnmanagedType.LPStruct)] Guid id,
                                           uint flags, IntPtr token, out string path);

    /// Where a browser's file picker opens: the Downloads folder, else the user's own
    static string DownloadsFolder()
    {
        try
        {
            if (SHGetKnownFolderPath(new Guid("374DE290-123F-4565-9164-39C4925E467B"), 0, IntPtr.Zero, out var path) == 0 && Directory.Exists(path))
                return path;
        }
        catch (Exception) { }
        return Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
    }

    // ---- what the player chose last time (BuilderSettings.cs): builder-settings.json beside the versions ----
    static string SettingsPath => System.IO.Path.Combine(Storage.Base, "builder-settings.json");

    void ApplySettings()
    {
        var s = BuilderSettings.Load(SettingsPath);
        if (s == null) return;
        s.Out = BuilderHome.LoadPath(s.Out);
        s.Nup = BuilderHome.LoadPath(s.Nup);
        s.Romfs = BuilderHome.LoadPath(s.Romfs);
        s.Exefs = BuilderHome.LoadPath(s.Exefs);
        PrepareTick.IsChecked = !s.PrepareLater;
        if (!string.IsNullOrEmpty(s.Out)) OutPath.Text = s.Out;
        DlssTick.IsChecked = s.Dlss;
        dlssLicense = s.DlssLicense;
        FsrTick.IsChecked = s.Fsr;
        fsrLicense = s.FsrLicense;
        MemoryBox.SelectedItem = BuildMemory.Saved(MemoryBox.ItemsSource.Cast<object>(), s.MemoryGb);
        if (sourcePicked) return;   // (game files given here already, dropped on the window: not last time's over them)
        if (s.Romfs != null && s.Exefs != null && Directory.Exists(s.Romfs) && File.Exists(System.IO.Path.Combine(s.Exefs, "main")))
        {
            romfs = s.Romfs;
            exefs = s.Exefs;
            foldersNote = $"Using the folders {romfs} and {exefs} (as last time)";
        }
        else if (s.Nup != null && File.Exists(s.Nup))
        {
            // (the file as the list writes it: a path kept in Windows' short form, C:\USERS\LONGNA~1, is written out whole
            // there, and the file chosen was then one the list did not have, never checked and never built from)
            var info = new FileInfo(s.Nup);
            if (!dumps.Any(d => string.Equals(d.Path, info.FullName, StringComparison.OrdinalIgnoreCase)))
                dumps.Insert(0, new Dump(info.FullName, "Last time", info.Length, info.LastWriteTime));
            chosenNup = info.FullName;
        }
    }

    void SaveSettings()
    {
        try
        {
            var s = new BuilderSettings { Out = BuilderHome.SavePath(OutPath.Text),
                                          Nup = BuilderHome.SavePath(romfs == null ? chosenNup : null),
                                          Romfs = BuilderHome.SavePath(romfs), Exefs = BuilderHome.SavePath(exefs),
                                          Dlss = DlssTick.IsChecked == true, DlssLicense = dlssLicense,
                                          Fsr = FsrTick.IsChecked == true,
                                          FsrLicense = fsrLicense,
                                          PrepareLater = PrepareTick.IsChecked != true,
                                          MemoryGb = MemoryBox.SelectedItem is int gb ? gb : null,
                                          Track = chosenTrack ?? BuilderSettings.Load(SettingsPath)?.Track };
            Directory.CreateDirectory(System.IO.Path.GetDirectoryName(SettingsPath)!);
            File.WriteAllText(SettingsPath, System.Text.Json.JsonSerializer.Serialize(s));
        }
        catch (Exception) { }
    }

    /// (development) HOOKSHOT_UI_PREVIEW=found|build|ready|problem|stopped|update, and menu after any of them: one screen with
    /// made-up progress, nothing run. found: the choices with a game file found (with none of them: as this PC has it)
    void Preview(string what)
    {
        foreach (var part in what.Split(',', StringSplitOptions.TrimEntries))
            switch (part)
            {
                case "found":
                    var made = new Dump(@"C:\Users\you\Downloads\ocarina.nup", "Downloads", 24L << 30, DateTime.Now);
                    dumps.Insert(0, made);
                    checks[made.Path] = (true, "This is the version Hookshot supports.");
                    chosenNup = made.Path;
                    romfs = exefs = null;
                    FillDumps();
                    Refresh();
                    break;
                case "build":
                    prepareNow = true;
                    MakeRows(update: false, shaders: true);
                    ShowFace(Face.Build);
                    rows["read"].Begin(); rows["read"].Done();
                    rows["lift"].Begin(); rows["lift"].Done();
                    rows["compile"].Begin(); rows["compile"].Count("31 of 58");
                    current = "compile";
                    (filesDone, filesOf, compileEta) = (31, 58, 18 * 60);
                    SetProgress(0.25);
                    Tick();
                    ShowTab(TabBuild);
                    ShowMenu(true, atOnce: true);
                    break;
                case "ready":
                    finished = OutPath.Text;
                    elapsed.Reset();
                    ShowReady();
                    break;
                case "problem":
                    ShowProblem("Files of the builder's own compiler are missing (clang.exe in tools\\llvm-mingw\\bin).", tools: true);
                    break;
                case "stopped":
                    ShowProblem("The compiler stopped on src_4.c.", tools: false);
                    break;
                case "update":
                    BeginUpdate(OutPath.Text, "v2.2.0");
                    rows["download"].Done(); rows["download"].Small("3 MB · build tools unchanged");
                    rows["read"].Begin(); rows["read"].Done();
                    rows["lift"].Begin(); rows["lift"].Done();
                    rows["compile"].Begin(); rows["compile"].Count("7 of 516");
                    SetProgress(0.43);
                    break;
                case "menu":
                    ShowMenu(true, atOnce: true);
                    break;
                case "releases": case "settings":
                    ShowTab(part == "releases" ? TabReleases : TabSettings);
                    ShowMenu(true, atOnce: true);
                    break;
            }
    }

    // ================= 1: game files =================

    /// The game file's box (what is chosen, in a few words) and, under it, why the file chosen cannot be used
    void FillDumps()
    {
        var (text, ink) = ("Browse files", (Brush)Frozen(0xD6, 0xD6, 0xD6));
        string? tip = null;
        if (romfs != null && exefs != null) (text, tip) = ("romfs and exefs folders", foldersNote);
        else if (chosenNup != null)
        {
            checks.TryGetValue(chosenNup, out var c);
            (text, tip) = (System.IO.Path.GetFileName(chosenNup), chosenNup);
            if (c is { Ok: false }) ink = BadInk;
        }
        else if (searching) text = "Looking for your game files…";
        else if (dumps.Count > 0) text = $"{dumps.Count} found: choose one";
        (SourceText.Text, SourceText.Foreground, SourceChange.ToolTip) = (text, ink, tip);
        ShowFilesNote();
    }

    /// (issue 563: "Can't be read" said why only under the pointer, which players did not find: the reason is said, under the box)
    void ShowFilesNote()
    {
        if (SourceWhy == null) return;
        (bool Ok, string Text)? check = null;
        if (chosenNup != null && romfs == null) checks.TryGetValue(chosenNup, out check);
        SourceWhy.Text = check is { Ok: false } ? (check.Value.Text.StartsWith("This is build") ? "Not the supported version. " + check.Value.Text : check.Value.Text) : "";
        SourceWhy.Visibility = SourceWhy.Text.Length > 0 ? Visibility.Visible : Visibility.Collapsed;
    }

    /// The word at the right of the game files' row: the files found (the one chosen marked, each with what its check said)
    /// and the two ways to choose others. With none found, the file is browsed for at once
    void SourceChangeClick(object sender, RoutedEventArgs e)
    {
        if (face == Face.Problem && !updating) Back(sender, e);   // (another file after a build that stopped: its choices again)
        if (dumps.Count == 0 && romfs == null)
        {
            BrowseNup(sender, e);
            return;
        }
        // (made here, so not under the screen in the tree: its look is the screen's own, given by hand)
        var list = new ContextMenu
        {
            PlacementTarget = SourceChange, Placement = System.Windows.Controls.Primitives.PlacementMode.Bottom,
            Style = (Style)SourceChange.FindResource(typeof(ContextMenu)), ItemContainerStyle = (Style)SourceChange.FindResource(typeof(MenuItem)),
        };
        foreach (var d in dumps)
        {
            checks.TryGetValue(d.Path, out var c);
            var said = c == null ? "checking…" : c.Value.Ok ? "supported version"
                     : c.Value.Text.StartsWith("This is build") ? "not the supported version" : "can't be read";
            var item = new MenuItem
            {
                Header = $"{System.IO.Path.GetFileName(d.Path)} · {d.Where} · {Finder.Size(d.Size)} · {said}", ToolTip = c is { Ok: false } ? c.Value.Text : d.Path,
                IsChecked = romfs == null && string.Equals(d.Path, chosenNup, StringComparison.OrdinalIgnoreCase),
            };
            item.Click += (_, _) => Choose(d.Path);
            list.Items.Add(item);
        }
        var browse = new MenuItem { Header = "Browse for a .nup file…" };
        browse.Click += BrowseNup;
        list.Items.Add(browse);
        var folders = new MenuItem { Header = "Use romfs and exefs folders…" };
        folders.Click += BrowseFolders;
        list.Items.Add(folders);
        list.IsOpen = true;
    }

    /// Each found file's version, one at a time (the check unpacks into one probe folder); the first good one is chosen
    async void CheckAll()
    {
        if (checking) return;
        checking = true;
        var tools = Tools.Find();
        while (tools != null && dumps.FirstOrDefault(d => !checks.ContainsKey(d.Path)) is { } d)
        {
            checks[d.Path] = null;
            FillDumps();
            var r = await Runner.Check(tools, new[] { "--check", "--nup", d.Path });
            checks[d.Path] = r;
            if (!r.Ok && r.Text.Contains("antivirus", StringComparison.OrdinalIgnoreCase))
            {
                checking = false;
                ShowProblem(r.Text, tools: true);
                return;
            }
            // (issue 650: not over the romfs and exefs folders the player chose, here or last time: the found .nup showed as chosen)
            if (chosenNup == null && romfs == null && r.Ok) chosenNup = d.Path;
            FillDumps();
            Refresh();
        }
        if (chosenNup == null && romfs == null && dumps.Count > 0 && tools != null) { chosenNup = dumps[0].Path; FillDumps(); }
        checking = false;
        Refresh();
    }

    void Choose(string path)
    {
        sourcePicked = true;
        chosenNup = path;
        romfs = exefs = null;
        FillDumps();
        Refresh();
    }

    void AddDump(string path, string where)
    {
        var info = new FileInfo(path);
        if (!dumps.Any(d => string.Equals(d.Path, info.FullName, StringComparison.OrdinalIgnoreCase)))
            dumps.Insert(0, new Dump(info.FullName, where, info.Length, info.LastWriteTime));
        sourcePicked = true;
        chosenNup = info.FullName;
        romfs = exefs = null;
        FillDumps();
        CheckAll();
        Refresh();
    }

    bool SourceReady => romfs != null && exefs != null
        || chosenNup != null && checks.TryGetValue(chosenNup, out var c) && c is { Ok: true };

    void PathsChanged(object sender, RoutedEventArgs e)
    {
        OutPath.ToolTip = OutPath.Text;   // (a folder longer than its row: whole under the pointer)
        Refresh();
    }

    void Refresh()
    {
        if (LauncherGo == null) return;
        Render();
    }

    /// The line under Build Game while nothing is under way: that the game was just built, and in how long (this once); else how
    /// long and how much room, in red when the drive has not got it; else that the files are being checked
    (string, Brush) IdleLine()
    {
        if (readyNote != null) return (readyNote, QuietInk);
        if (Tools.Find() == null) return ("The build tools are missing from Hookshot's folder: reinstall Hookshot Builder.", BadInk);
        if (chosenNup != null && romfs == null && !checks.ContainsKey(chosenNup)) return ("Checking that it is the supported version…", QuietInk);
        if (!SourceReady || OutPath.Text.Length <= 2) return ("", QuietInk);
        try
        {
            var root = System.IO.Path.GetPathRoot(System.IO.Path.GetFullPath(OutPath.Text))!;
            var free = new DriveInfo(root).AvailableFreeSpace;
            return ($"About 45 minutes · needs 45 GB, {root.TrimEnd('\\')} has {free >> 30} GB free", free < NeededBytes ? BadInk : QuietInk);
        }
        catch (Exception) { return ("About 45 minutes · needs 45 GB", QuietInk); }
    }

    /// The game folder or the build files folder on a hard drive: the build works, but much more slowly than on an SSD. Null
    /// when both are on an SSD (or their drive cannot be told, as on a network share)
    string? HardDriveWarning()
    {
        foreach (var (what, folder) in new[] { ("game folder", OutPath.Text), ("build files folder", Storage.Work) })
        {
            if (Disk.Spinning(folder) != true) continue;
            string root;
            try { root = System.IO.Path.GetPathRoot(System.IO.Path.GetFullPath(folder))!.TrimEnd('\\'); }
            catch (Exception e) when (e is ArgumentException or NotSupportedException or PathTooLongException) { root = folder; }
            return $"The {what} is on a hard drive ({root}). An SSD builds the game much faster: build there if you can.\n\n" +
                   "Choose OK to build here anyway, or Cancel to choose another folder.";
        }
        return null;
    }

    void Dropped(object sender, DragEventArgs e)
    {
        if (Busy || e.Data.GetData(DataFormats.FileDrop) is not string[] { Length: > 0 } paths) return;
        // (game files dropped on the window: a build from them, the menu's Build tab open)
        if (face == Face.Problem) Back(sender, new RoutedEventArgs());
        ShowTab(TabBuild);
        ShowMenu(true);
        foreach (var p in paths)
        {
            if (p.EndsWith(".nup", StringComparison.OrdinalIgnoreCase) && File.Exists(p)) AddDump(p, "Dropped");
            else if (Directory.Exists(System.IO.Path.Combine(p, "romfs")) && Directory.Exists(System.IO.Path.Combine(p, "exefs")))
                UseFolders(System.IO.Path.Combine(p, "romfs"), System.IO.Path.Combine(p, "exefs"));
        }
    }

    void BrowseNup(object sender, RoutedEventArgs e)
    {
        var d = new OpenFileDialog { Filter = "Game file (*.nup)|*.nup", Title = "Choose your game file" };
        if (d.ShowDialog(this) == true) AddDump(d.FileName, "Chosen");
    }

    /// The other way in: an unpacked game, its romfs and exefs folders (or one folder holding both)
    void BrowseFolders(object sender, RoutedEventArgs e)
    {
        var both = PickFolder("Choose the folder with romfs and exefs (or the romfs folder)");
        if (both == null) return;
        if (Directory.Exists(System.IO.Path.Combine(both, "romfs")) && Directory.Exists(System.IO.Path.Combine(both, "exefs")))
        {
            UseFolders(System.IO.Path.Combine(both, "romfs"), System.IO.Path.Combine(both, "exefs"));
            return;
        }
        var ex = PickFolder("Now choose the exefs folder");
        if (ex != null) UseFolders(both, ex);
    }

    void UseFolders(string r, string x)
    {
        if (!File.Exists(System.IO.Path.Combine(x, "main")))
        {
            MessageBox.Show(this, "That exefs folder has no file named main.", "Hookshot");
            return;
        }
        sourcePicked = true;
        romfs = r;
        exefs = x;
        chosenNup = null;
        foldersNote = $"Using the folders {r} and {x}";
        FillDumps();
        Refresh();
    }

    static string? PickFolder(string title)
    {
        var d = new OpenFolderDialog { Title = title };
        return d.ShowDialog() == true ? d.FolderName : null;
    }

    void BrowseOut(object sender, RoutedEventArgs e)
    {
        if (face == Face.Problem && !updating) Back(sender, e);
        OutPath.Text = PickFolder("Choose where the game goes") ?? OutPath.Text;
    }

    void LanguageChanged(object sender, SelectionChangedEventArgs e)
    {
        if (LanguageBox.SelectedItem is not Language l) return;
        lang = l;
        BuildCancel.Content = T(S.Cancel);
        DetailsRow.Content = FootDetails.Content = T(detailsShown ? S.HideDetails : S.ShowDetails);
    }

    // ================= 2: the build =================

    void StartBuild(object sender, RoutedEventArgs e)
    {
        if (Busy || !BuildGame.IsEnabled) return;
        readyNote = null;
        SaveSettings();
        var tools = Tools.Find();
        if (tools == null)
        {
            ShowProblem("The build tools are not in Hookshot's folder.", tools: true);
            return;
        }
        var args = new List<string>();
        if (romfs != null && exefs != null) args.AddRange(new[] { "--romfs", romfs, "--exefs", exefs });
        else if (chosenNup != null) args.AddRange(new[] { "--nup", chosenNup });
        else return;
        args.AddRange(new[] { "--out", OutPath.Text, "--language", lang.Code });
        if (FsrTick.IsChecked == true) args.Add("--fsr");   // (an --update of the folder keeps it: make_game.py's mark)
        prepareNow = PrepareTick.IsChecked == true;
        Run(tools, ShaderStep.Args(args, prepareNow), dlss: DlssTick.IsChecked == true,
            fsr: FsrTick.IsChecked == true && fsrLicense);
    }

    const string DlssLicense =
        "NVIDIA DLSS is NVIDIA's, not Hookshot's. With it ticked, the build downloads NVIDIA's DLSS SDK (release v310.9.16) from " +
        "github.com/NVIDIA/DLSS, under NVIDIA's own license, the NVIDIA RTX SDKs license:\n\n" +
        "https://github.com/NVIDIA/DLSS/blob/9981c6350dc58c0ce21f024fd65e31e851c31689/LICENSE.txt\n\n" +
        "Its files stay on this PC (in the builder's ngx-sdk folder, and nvngx_dlss.dll in the game folder's ngx folder). " +
        "Hookshot never includes or shares them: never share a game folder built with them.\n\n" +
        "Do you accept NVIDIA's license?";

    /// NVIDIA's license accepted on the DLSS tick, kept in the settings (DlssLicense): an update keeps a folder's DLSS by it.
    /// It was the SDK's LICENSE.txt, a download: with the SDK gone, the update built without DLSS and its runtime went
    bool dlssLicense;

    /// The NVIDIA DLSS tick: NVIDIA's license first, and the tick stays only when it is accepted
    void DlssChanged(object sender, RoutedEventArgs e)
    {
        if (DlssTick.IsChecked == true &&
            MessageBox.Show(this, DlssLicense, "NVIDIA DLSS", MessageBoxButton.YesNo, MessageBoxImage.Information) != MessageBoxResult.Yes)
            DlssTick.IsChecked = false;
        else if (DlssTick.IsChecked == true)
            dlssLicense = true;
        SaveSettings();   // (kept at once, not only when Build is pressed: ticked and closed, it is still ticked next time)
        ShowRebuildNote();
    }

    const string FsrLicense =
        "AMD FSR 4 is AMD's, not Hookshot's. With it ticked, the build downloads AMD's FSR runtime for Vulkan (FidelityFX SDK " +
        "v2.4.0: amd_fidelityfx_loader_vk.dll and amd_fidelityfx_upscaler_vk.dll, signed by AMD) from " +
        "github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK, each file checked against its SHA-256, under AMD's FSR SDK license:\n\n" +
        "https://github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK/blob/7539ae8b6568ad29ed78a753404351daf3b5cca7/Kits/FidelityFX/docs/license.md\n\n" +
        "Its files stay on this PC (in the builder's ffx-sdk folder, and the two DLLs with LICENSE-AMD-FSR-SDK.md in the game " +
        "folder).\n\n" +
        "Do you accept AMD's license?";

    /// AMD's license accepted on the FSR 4 tick. A tick saved before the builder asked builds with FSR 4 as it did, its DLLs
    /// the player's own, and fetches nothing until it is ticked again
    bool fsrLicense;

    /// The AMD FSR 4 tick: AMD's license first, and the tick stays only when it is accepted (as DLSS's; this builder is
    /// Windows', where AMD publishes the runtime)
    void FsrChanged(object sender, RoutedEventArgs e)
    {
        if (FsrTick.IsChecked == true)
        {
            fsrLicense = MessageBox.Show(this, FsrLicense, "AMD FSR 4", MessageBoxButton.YesNo, MessageBoxImage.Information) ==
                         MessageBoxResult.Yes;
            if (!fsrLicense) FsrTick.IsChecked = false;
        }
        SaveSettings();
        ShowRebuildNote();
    }

    static readonly (string Id, string Build, string Update)[] Stages =
    {
        // (as the menu has room for them: a row of 192 in a text of 16)
        ("download", "", "Get the update"),
        ("read", "Read the game files", "Read the kept files"),
        ("lift", "Translate to PC code", "Translate to PC code"),
        ("compile", "Compile", "Compile"),
        ("finish", "Put it together", "Swap in the game"),
        (ShaderStep.Id, "Prepare the shaders", "Prepare the shaders"),
    };
    static readonly Dictionary<string, (double From, double Size)> WithShaders = new()
    {
        ["download"] = (0, 0.04), ["read"] = (0.04, 0.04), ["lift"] = (0.08, 0.14), ["compile"] = (0.22, 0.68), ["finish"] = (0.90, 0.02),
        [ShaderStep.Id] = (0.92, 0.08),   // (hookshot --prepare-shaders: minutes on some GPUs, the first start's wait moved here)
    };
    static readonly Dictionary<string, (double From, double Size)> WithoutShaders = new()
    {
        ["download"] = (0, 0.04), ["read"] = (0.04, 0.04), ["lift"] = (0.08, 0.14), ["compile"] = (0.22, 0.74), ["finish"] = (0.96, 0.04),
    };
    Dictionary<string, (double From, double Size)> Weight = WithoutShaders;
    // (this build prepares the shaders: the tick for a build, the saved choice for an update. The game's @@stage shaders came, and
    // make_game's line when it left them to the first start: the row's end says which)
    bool prepareNow, shadersBegan;
    string? shadersLater;
    TimeSpan? builtIn;   // (at @@times: the build without the shaders' minutes, as build_times.json keeps it)

    /// The steps (said one at a time under the build's bar). download: the update, or a version's builder, is downloaded first
    void MakeRows(bool update, bool shaders, bool download = true)
    {
        rows.Clear();
        current = null;
        filesChanged = -1;
        filesDone = filesOf = filesCompiled = 0;
        Weight = shaders ? WithShaders : WithoutShaders;
        var list = Stages.Where(s => ((update && download) || s.Id != "download") && (shaders || s.Id != ShaderStep.Id)).ToList();
        foreach (var s in list)
        {
            rows[s.Id] = new StepRow(update ? s.Update : s.Build);
        }
    }

    /// What a line of the build tools means for the steps: the step that begins (the one before it is done), and how many of
    /// the files to compile are. The build here and a version the launcher brings (Launcher.cs) both say these
    void StepsLine(string line)
    {
        if (line.StartsWith("@@stage "))
        {
            var id = line.Split(' ')[1];
            if (current != null && rows.TryGetValue(current, out var was)) was.Done();
            current = id;
            if (rows.TryGetValue(id, out var row)) row.Begin();
        }
        else if (line.StartsWith("@@plan ") || line.StartsWith("@@file ")) Number(line);
    }

    /// dlss: NVIDIA DLSS, its license accepted: NVIDIA's SDK fetched into Storage.NgxSdk first (only what is missing), and built in.
    /// fsr: AMD FSR 4, its license accepted: built with it, AMD's runtime fetched into Storage.FfxSdk and put in the game folder
    void Run(Tools tools, List<string> args, bool keepRows = false, bool dlss = false, bool fsr = false)
    {
        // (a warning, not a stop: the player may have no other folder with the room. An update keeps its rows and its own flow)
        if (!keepRows && Shot == null && HardDriveWarning() is { } slow &&
            MessageBox.Show(this, slow, "Hookshot", MessageBoxButton.OKCancel, MessageBoxImage.Warning) != MessageBoxResult.OK)
            return;
        int? workers, memoryGb;
        try
        {
            workers = BuildWorkers.Selected(WorkerBox.SelectedItem);
            memoryGb = BuildMemory.Selected(MemoryBox.SelectedItem);
        }
        catch (ArgumentException e)
        {
            MessageBox.Show(this, e.Message, "Hookshot");
            return;
        }
        if (!keepRows)
        {
            updating = false;
            MakeRows(update: false, shaders: prepareNow);
        }
        log.Clear();
        Log.Clear();
        current = null;
        finished = "";
        compiled = 0;
        filesDone = filesOf = 0;
        filesChanged = -1;
        filesCompiled = 0;
        compileEta = -1;
        thisCompile = 0;
        previousTotal = -1;
        shadersBegan = false;
        shadersLater = null;
        builtIn = null;
        ShowFace(Face.Build);
        SetProgress(updating ? Weight["read"].From : 0);
        elapsed.Restart();
        compileClock.Reset();
        clock.Start();
        Tick();
        (BuildCopy.Content, FootCopy.Content) = ("Copy error log", "Copy error log");
        if (Storage.WorkChosen && !args.Contains("--work")) args.AddRange(new[] { "--work", Storage.Work });   // (the build files where the player chose)
        if (dlss && !args.Contains("--fetch-ngx-sdk")) args.AddRange(new[] { "--fetch-ngx-sdk", "--accept-nvidia-license" });
        if (fsr && !args.Contains("--fsr")) args.Add("--fsr");
        if (fsr && !args.Contains("--fetch-fsr-runtime")) args.AddRange(new[] { "--fetch-fsr-runtime", "--accept-amd-license" });
        runner = new Runner(tools, args, workers, dlss ? Storage.NgxSdk : null, memoryGb, fsr ? Storage.FfxSdk : null);
        runner.Line += l => Dispatcher.BeginInvoke(() => Line(l));
        runner.Finished += failure => Dispatcher.BeginInvoke(() => Ended(failure));
        runner.Start();
    }

    static readonly Regex FilesLine = new(@"^(\d+) files, "), FileLine = new(@"^\s+\S+\s+\d+ MB\s+\d+s");

    void Line(string line)
    {
        if (line.StartsWith("@@stage "))
        {
            var id = line.Split(' ')[1];
            StepsLine(line);
            if (id == "compile") compileClock.Restart();
            if (id == ShaderStep.Id) (shadersBegan, shaderDone) = (true, 0);
            if (id == ShaderStep.Id) shaderClock.Restart();
            if (Weight.TryGetValue(id, out var w)) SetProgress(w.From);
            Tick();
        }
        else if (line.StartsWith("@@progress "))
        {
            if (double.TryParse(line[11..], System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var f) && current != null
                && Weight.TryGetValue(current, out var w))
            {
                if (current == "compile") compiled = f;
                if (current == ShaderStep.Id) shaderDone = Math.Max(shaderDone, Math.Clamp(f, 0, 1));
                SetProgress(w.From + w.Size * Math.Clamp(f, 0, 1));
            }
            return;
        }
        else if (line.StartsWith("@@plan ") || line.StartsWith("@@file ") || line.StartsWith("@@eta ") || line.StartsWith("@@times "))
        {
            Number(line);
            return;
        }
        else if (line.StartsWith("@@done ")) finished = line[7..];
        else if (ShaderStep.Reason(line) is { } later) shadersLater = later;
        else if (FilesLine.Match(line) is { Success: true } m) filesOf = int.Parse(m.Groups[1].Value);
        else if (FileLine.IsMatch(line)) filesDone++;
        if (current == "compile" && filesChanged < 0 && filesOf > 0 && rows.TryGetValue("compile", out var c))
        {
            c.Count($"{filesDone} of {filesOf}");
            Tick();
        }
        AddLog(line);
    }

    /// The compile timer's lines: build.py says which files this run really rebuilds and how long each took before (the
    /// countdown), and make_game.py gives this build's times beside the last one's. Not shown in details: the compiler's
    /// own lines there already carry each file's seconds.
    void Number(string line)
    {
        var p = line.Split(' ');
        switch (p[0])
        {
            case "@@plan" when p.Length == 3 && int.TryParse(p[1], out var changed) && int.TryParse(p[2], out var total):
                filesChanged = changed;
                filesOf = total;
                filesCompiled = 0;
                ChangedFiles();
                break;
            case "@@file" when p.Length == 4 && (p[3] is "new" or "again"):
                filesCompiled++;
                ChangedFiles();
                break;
            case "@@eta" when p.Length == 2 && double.TryParse(p[1], System.Globalization.NumberStyles.Float,
                                                              System.Globalization.CultureInfo.InvariantCulture, out var eta):
                compileEta = eta;
                break;
            case "@@times" when p.Length == 4:
                builtIn = elapsed.Elapsed;
                long.TryParse(p[2], out thisCompile);
                long.TryParse(p[3], out previousTotal);
                break;
        }
    }

    void ChangedFiles()
    {
        if (filesChanged < 0 || !rows.TryGetValue("compile", out var row)) return;
        // (the count at the row's right, as drawn: "31 of 58")
        if (filesChanged == 0) row.Small("Everything is already built");
        else row.Count($"{filesCompiled} of {filesChanged}");
    }

    void AddLog(string line)
    {
        log.AppendLine(line);
        if (log.Length > 600_000) log.Remove(0, log.Length - 400_000);
        if (Log.Visibility == Visibility.Visible)
        {
            Log.AppendText(line + "\n");
            Log.ScrollToEnd();
        }
    }

    /// How far the build is: the bar fills from the left in Build Game's place (an update's, at the menu's foot), its number in it
    void SetProgress(double f)
    {
        buildFraction = Math.Clamp(f, 0, 1);
        Render();
        if (Shot != null && runner != null && !shotWorking && f >= 0.4)   // (development: the build drawn once, on the way)
        {
            shotWorking = true;
            Tick();
            if (stepsHalfWay) ShowMenu(true, atOnce: true);
            SaveShot(System.IO.Path.ChangeExtension(Shot, null) + "-working.png");
            if (stepsHalfWay) ShowMenu(false, atOnce: true);
        }
    }

    /// The line under the build's bar: the step under way, with the files compiled and the time left while it compiles
    void Tick()
    {
        if (face != Face.Build) return;
        var row = current != null ? rows.GetValueOrDefault(current) : null;
        if (row == null) stepLine = updating ? "Getting the update..." : "Starting...";
        else if (current == "compile")
        {
            // (the countdown build.py works out from what this PC measured before, else from how far it is)
            var left = compileEta >= 0 ? TimeLeft(compileEta)
                : compiled > 0.03 ? TimeLeft(compileClock.Elapsed.TotalSeconds / compiled * (1 - compiled) + 60) : "";
            var count = row.Counted is { Length: > 0 } n ? " " + n : "";
            stepLine = $"{row.Name}...{count}" + (left.Length > 0 ? " · " + char.ToLowerInvariant(left[0]) + left[1..] : "");
        }
        // (the shaders' step: its own number and time, as the bar has only a small share for it: LaunchWork.ShaderPart)
        else if (current == ShaderStep.Id) stepLine = row.Name + "..." + LaunchWork.ShaderPart(shaderDone, shaderClock.Elapsed.TotalSeconds);
        else stepLine = row.Name + "...";
        Render();
    }

    /// What the hidden programs said, over the picture: Show details in the menu's steps, and the line that says why a build
    /// stopped (the launcher's own work too, Launcher.cs: whichever of the two last ran)
    void ShowDetails(bool show)
    {
        if (Log == null) return;
        detailsShown = show;
        Log.Visibility = show ? Visibility.Visible : Visibility.Collapsed;
        DetailsRow.Content = FootDetails.Content = T(show ? S.HideDetails : S.ShowDetails);
        if (!show) return;
        var said = face is Face.Build or Face.Problem ? log.ToString() : workLog.ToString();
        Log.Text = said.Length > 200_000 ? said[^200_000..] : said;
        Log.ScrollToEnd();
    }

    void DetailsClick(object sender, RoutedEventArgs e) => ShowDetails(!detailsShown);

    static string Clock(TimeSpan t) => $"{(int)t.TotalMinutes}:{t.Seconds:00}";

    static string TimeLeft(double seconds)
    {
        if (seconds < 45) return "Less than a minute left";
        if (seconds < 90) return "About a minute left";
        var minutes = (int)Math.Round(seconds / 60);
        return minutes >= 60 ? $"About {minutes / 60} h {minutes % 60} min left" : $"About {minutes} minutes left";
    }

    void Ended(string? failure)
    {
        clock.Stop();
        elapsed.Stop();
        runner = null;
        if (finished.Length > 0)
        {
            foreach (var (id, r) in rows)
            {
                if (id != ShaderStep.Id) r.Done();
                else if (ShaderStep.Skipped(shadersBegan, shadersLater) is { } why) { r.Skipped(); r.Small(why); }
                else r.Done();
            }
            SetProgress(1);
            ShowReady();
            return;
        }
        if (failure == "cancelled")
        {
            BackFromBuild();
            return;
        }
        if (current != null && rows.TryGetValue(current, out var row)) row.Stopped();
        ShowProblem(failure ?? "The build tools stopped without saying why.", tools: failure?.Contains("antivirus", StringComparison.OrdinalIgnoreCase) == true);
    }

    void CancelBuild(object sender, RoutedEventArgs e)
    {
        download?.Cancel();
        runner?.Cancel();
    }

    // ================= 3: play =================

    /// The game is built: the window is its launcher from here on (Launcher.cs), and, this once, the line under Build Game says so
    /// and in how long. The desktop and Start menu shortcuts are made as before
    void ShowReady()
    {
        var compiledNote = thisCompile > 0 ? $" (compiled in {Span(TimeSpan.FromSeconds(thisCompile))})" : "";
        readyNote = $"Your game is {(updating ? "updated" : "ready")} · {(updating ? "updated" : "built")} in {Span(elapsed.Elapsed)}";
        readyTip = $"{(updating ? "Updated" : "Built")} in {Span(elapsed.Elapsed)}{compiledNote}{Against(builtIn ?? elapsed.Elapsed)} · {finished}";
        // (development: a screen drawn to a file, or made up, makes and moves no shortcut of the player's)
        var real = Shot == null && Environment.GetEnvironmentVariable("HOOKSHOT_UI_PREVIEW") == null;
        if (!updating && real)
            Finder.Shortcuts(finished, desktopShortcut, startShortcut);
        else if (updating && real)
        {   // (the ones the player has, onto the folder's launcher; the rows say which there are, and their word makes one)
            desktopShortcut = File.Exists(Finder.DesktopLink);
            startShortcut = File.Exists(Finder.StartLink);
            Finder.RefreshShortcuts(finished);
        }
        if (Finder.ShortcutError != null) AddLog("shortcut not made: " + Finder.ShortcutError);
        EnterLauncher(finished);
        _ = FreeAfterBuild();
    }
    string? readyNote, readyTip;

    // (players asked for the space back: the translated code, the setup's and updater's downloads and older builder versions go as soon
    // as the game is ready. The compiled objects stay (~1 GB): without them every update compiled all ~600 files again, an hour and
    // more (issue 1287). HOOKSHOT_KEEP_BUILD_FILES=1 keeps everything)
    async Task FreeAfterBuild()
    {
        if (Storage.KeepBuildFiles || freeing != null) return;
        // (the builder of the release the folder holds now stays: switched back to an older one, switching again downloads nothing)
        var keep = launchBuilt is { } built && LaunchList.IsRelease(built) ? built : null;
        var task = Task.Run(() => Storage.Free(afterBuild: true, keep));
        freeing = task;
        Render();
        long left;
        try { left = await task; }
        finally
        {
            freeing = null;
            Render();
        }
        if (left >= 100L << 20) AddLog($"build files: {Storage.Gb(left)} could not be deleted (a file in use); they go after the next build");
    }
    // (FreeAfterBuild under way: nothing new starts until it is done, Busy. A build started at once had its new version's folder
    // or its translated code deleted under it)
    Task? freeing;

    static string Span(TimeSpan t) => t.TotalHours >= 1 ? $"{(int)t.TotalHours} h {t.Minutes} min" : t.TotalMinutes >= 1 ? $"{(int)t.TotalMinutes} minutes" : $"{t.Seconds} seconds";

    /// This build beside the last one on this PC (build_times.json, through make_game.py's @@times): "last time 45 minutes
    /// (4 minutes faster)"
    string Against(TimeSpan now)
    {
        if (previousTotal <= 0) return "";
        var last = TimeSpan.FromSeconds(previousTotal);
        var diff = last.TotalSeconds - now.TotalSeconds;
        var how = Math.Abs(diff) < 30 ? "about the same"
                : diff > 0 ? $"{Span(TimeSpan.FromSeconds(diff))} faster" : $"{Span(TimeSpan.FromSeconds(-diff))} slower";
        return $" · last time {Span(last)} ({how})";
    }

    void Play(object sender, RoutedEventArgs e)
    {
        if (StartGame(finished)) WindowState = WindowState.Minimized;
    }

    // ================= when something goes wrong =================

    bool problemIsTools;

    void ShowProblem(string why, bool tools)
    {
        lastFailure = why;
        problemIsTools = tools;
        // (the folder is swapped only once the new game is complete, make_game.py: a build that stopped left it as it was)
        var kept = updating ? "Your current game is unchanged and still plays." : "Nothing was changed in your game folder.";
        var line = why.TrimEnd('.', ' ', '\n', '\r') + ".";
        if (tools)
        {
            problemTitle = "The build tools need repairing";
            var base_ = Storage.Base;
            problemWhy = $"Your antivirus removed part of the build tools. {line} Restore them in Windows Security (Protection history), " +
                         $"or add {base_} to its exclusions, then press Repair build tools.";
        }
        else
        {
            problemTitle = updating ? "The update stopped" : "The build stopped";
            problemWhy = line + " " + kept;
        }
        ShowFace(Face.Problem);
        (BuildCopy.Content, FootCopy.Content) = ("Copy error log", "Copy error log");
    }

    void CopyForReport(object sender, RoutedEventArgs e)
    {
        var lines = log.ToString().Split('\n');
        var text = $"Hookshot Builder {Tools.Find()?.Version ?? "(source)"} on Windows {Environment.OSVersion.Version}\n" +
                   $"{problemTitle}: {lastFailure}\n\n" + string.Join("\n", lines.Skip(Math.Max(0, lines.Length - 200)));
        var said = "Copied";
        try { Clipboard.SetText(text); }
        catch (Exception) { said = "Could not copy"; }   // (the clipboard held by another program)
        (BuildCopy.Content, FootCopy.Content) = (said, said);
    }

    /// (from a build that stopped: to what was there before it, the launcher of a game that is there, else the choices)
    void Back(object sender, RoutedEventArgs e) => BackFromBuild();

    /// From a build or an update that stopped (Back) or was cancelled, to what was there before it: the launcher of the game that
    /// is there, which offers the update again (EnterLauncher: the releases are asked for, or the ones already in are listed),
    /// also after a start with --update that went straight to the update (#2129); else the build's choices. One way back, so a
    /// cancel and a stop cannot leave the window in two different states
    void BackFromBuild()
    {
        if (updating && File.Exists(GameExe(OutPath.Text)))
        {
            EnterLauncher(OutPath.Text);   // (updating = false there)
            return;
        }
        updating = false;
        ShowFace(Face.Files);
        FillDumps();
        Refresh();
    }

    /// (the button of a build that stopped: the tools repaired, the update begun again, or the build)
    void RetryProblem(object sender, RoutedEventArgs e)
    {
        if (problemIsTools)
        {
            Repair(sender, e);
            return;
        }
        if (updating && lastUpdate is { } u)
        {
            Updater.UpdateFolder(this, u.Folder, u.Tag, fetched: false, named: u.Tag != null && !LaunchList.SameTag(u.Tag, latestTag));
            return;
        }
        updating = false;
        ShowFace(Face.Files);
        FillDumps();
        Refresh();
        if (BuildGame.IsEnabled) StartBuild(sender, e);
    }

    /// The setup (HookshotBuilder-Setup.exe beside this app) checks every part against its checksum and downloads the missing ones
    void Repair(object sender, RoutedEventArgs e)
    {
        var setup = System.IO.Path.Combine(AppContext.BaseDirectory, "HookshotBuilder-Setup.exe");
        if (File.Exists(setup))
        {
            try { Process.Start(new ProcessStartInfo(setup, "--repair") { UseShellExecute = false, WorkingDirectory = AppContext.BaseDirectory }); }
            catch (Exception x)
            {
                MessageBox.Show(this, $"The setup could not be started: {x.Message.TrimEnd('.')}. Your antivirus may have removed it.",
                                "Hookshot", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }
            Leave();
            return;
        }
        try { Process.Start(new ProcessStartInfo("https://github.com/NotRexed/Hookshot/releases/latest") { UseShellExecute = true }); }
        catch (Exception) { }   // (no browser to open it)
    }

    // ================= the update (Updater.cs): the game started this app with --update <folder> =================

    CancellationTokenSource? download;

    public void BeginUpdate(string folder, string? tag)
    {
        updating = true;
        lastUpdate = (folder, tag);
        OutPath.Text = folder;
        finished = "";
        var to = tag ?? "the latest version";
        var from = GameVersion(folder) ?? Tools.Find()?.Version;
        prepareNow = BuilderSettings.PrepareNow(SettingsPath);
        // (the updates show no menu: the saved choice, as ApplySettings may not have run)
        MemoryBox.SelectedItem = BuildMemory.Saved(MemoryBox.ItemsSource.Cast<object>(), BuilderSettings.Load(SettingsPath)?.MemoryGb);
        MakeRows(update: true, shaders: prepareNow);
        AddLog(from != null && from != to ? $"Updating {from} to {to}" : $"Updating to {to}");
        ShowFace(Face.Build);
        // (its bar at the menu's foot, under Releases)
        ShowTab(TabReleases);
        ShowMenu(true, atOnce: true);
        SetProgress(0);
        rows["download"].Begin();
        Tick();
    }

    public CancellationToken DownloadToken => (download = new CancellationTokenSource()).Token;

    public void DownloadProgress(double f)
    {
        rows.GetValueOrDefault("download")?.Small($"{(int)(f * 100)}%");
        SetProgress(Weight["download"].Size * f);
    }

    public void Note(string line)
    {
        AddLog(line);
        rows.GetValueOrDefault("download")?.Small(line);
    }

    public void DownloadFailed(string why)
    {
        download = null;
        rows.GetValueOrDefault("download")?.Stopped();
        ShowProblem(why, tools: false);
        problemTitle = "The update could not be downloaded";
    }

    /// The new tools are here: the folder built again with them (only what changed is compiled)
    internal void UpdateBuild(Tools tools, string folder)
    {
        download = null;
        if (rows.TryGetValue("download", out var d)) { d.Done(); d.Small("Build tools checked"); }
        // (the saved tick also opts an existing game into DLSS. After a self-update ApplySettings has not run yet;
        // a folder already built with DLSS keeps it, its license accepted then: the settings' record, or for a license accepted
        // before the record, the SDK's LICENSE.txt)
        var saved = BuilderSettings.Load(SettingsPath);
        var dlss = saved?.Dlss == true ||
                   (File.Exists(System.IO.Path.Combine(folder, "ngx", "nvngx_dlss.dll")) &&
                    (saved?.DlssLicense == true || File.Exists(System.IO.Path.Combine(Storage.NgxSdk, "LICENSE.txt"))));
        // (AMD FSR 4, the same: the saved tick with AMD's license accepted, or a folder built with FSR 4 whose AMD runtime
        // was fetched, AMD's license saved beside it then, keeps it and its runtime)
        var fsr = (saved?.Fsr == true && saved.FsrLicense) ||
                  (File.Exists(System.IO.Path.Combine(folder, ".hookshot_fsr")) &&
                   File.Exists(System.IO.Path.Combine(folder, "amd_fidelityfx_upscaler_vk.dll")) &&
                   File.Exists(System.IO.Path.Combine(folder, "LICENSE-AMD-FSR-SDK.md")));
        // (prepareNow: the saved choice, read in BeginUpdate. The launcher's Update and the --update start after a self-update never
        // ran ApplySettings, so the tick there is only its default)
        Run(tools, ShaderStep.Args(new List<string> { "--update", folder }, prepareNow), keepRows: true, dlss: dlss, fsr: fsr);
    }

    // ================= the window =================

    void Minimize(object sender, RoutedEventArgs e) => WindowState = WindowState.Minimized;

    void CloseWindow(object sender, RoutedEventArgs e) => Close();

    /// However the window is closed (its own button, Alt+F4, the taskbar): a build or an update under way, the installer's or
    /// one the launcher started, is asked about first, and the hidden programs doing it stop with the window. Not when the
    /// builder leaves on purpose, Leave
    protected override void OnClosing(CancelEventArgs e)
    {
        var busy = runner != null || LauncherBusy || download != null;
        if (busy && !leaving && Shot == null &&
            MessageBox.Show(this, T(S.CloseQuestion), "Hookshot", MessageBoxButton.YesNo) != MessageBoxResult.Yes)
        {
            e.Cancel = true;
            return;
        }
        if (!leaving)
        {
            runner?.Cancel();
            CancelLaunchWork();
            download?.Cancel();
        }
        base.OnClosing(e);
    }

    /// The builder leaves on purpose: the game started, the setup or another builder started to carry on, a development
    /// picture drawn. The window closes with nothing asked (OnClosing)
    internal void Leave()
    {
        leaving = true;
        Application.Current.Shutdown();
    }
    bool leaving;
}

/// One step of the build, a row of the menu as a version is (Paper: "v3 - Building"): dim until it begins, in the accent while
/// it is the one under way (with a count at its right, "31 of 58"), then plain with the mark at its right. A line under its
/// name says more when there is more to say.
sealed class StepRow
{
    public readonly Grid Root = new() { MinHeight = 40, Margin = new Thickness(0, 0, 0, 4) };
    readonly TextBlock name = Text(16, 20), count = Text(16, 20), small = Text(13, 18);
    readonly Path tick = new()
    {
        Data = Geometry.Parse("M4.5,12.75 l6,6 l9,-13.5"), Width = 24, Height = 24, StrokeThickness = 1.5, Visibility = Visibility.Collapsed,
        StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round, StrokeLineJoin = PenLineJoin.Round, VerticalAlignment = VerticalAlignment.Center,
    };
    bool running;

    static readonly Brush Ink = Frozen(0xBC, 0xBC, 0xBC), Dim = Frozen(0x74, 0x74, 0x74), Now = Frozen(0xEB, 0xB0, 0x7E), Bad = Frozen(0xE2, 0x77, 0x6B);
    static Brush Frozen(byte r, byte g, byte b) { var x = new SolidColorBrush(Color.FromRgb(r, g, b)); x.Freeze(); return x; }
    static TextBlock Text(double size, double line) => new()
    {
        FontFamily = new FontFamily("Segoe UI"), FontSize = size, LineHeight = line, LineStackingStrategy = LineStackingStrategy.BlockLineHeight,
    };

    public StepRow(string text)
    {
        Root.ColumnDefinitions.Add(new ColumnDefinition());
        Root.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto, MinWidth = 24 });
        Root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(40) });
        Root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        name.Text = text;
        name.TextTrimming = TextTrimming.CharacterEllipsis;
        name.VerticalAlignment = count.VerticalAlignment = VerticalAlignment.Center;
        name.Margin = new Thickness(0, 0, 8, 0);
        count.Visibility = small.Visibility = Visibility.Collapsed;
        small.TextWrapping = TextWrapping.Wrap;
        small.Margin = new Thickness(0, -6, 0, 6);
        Grid.SetColumn(count, 1);
        Grid.SetColumn(tick, 1);
        Grid.SetRow(small, 1);
        Grid.SetColumnSpan(small, 2);
        foreach (var part in new UIElement[] { name, count, tick, small }) Root.Children.Add(part);
        Ink_(Dim);
    }

    void Ink_(Brush ink) => name.Foreground = count.Foreground = small.Foreground = tick.Stroke = ink;

    /// (the step's name, and the count while it is under way: said under the build's bar)
    public string Name => name.Text;
    public string? Counted => running && count.Text.Length > 0 ? count.Text : null;

    /// (in words, for a check that reads no picture: "Compile: now 31 of 58")
    public string Says => $"{name.Text}: {(tick.Stroke == Now ? "now" : tick.Stroke == Bad ? "stopped" : tick.Visibility == Visibility.Visible ? "done" : "to come")}" +
                          (count.Visibility == Visibility.Visible ? " " + count.Text : "");

    /// (a line under the step's name)
    public void Small(string text)
    {
        small.Text = text;
        small.Visibility = Visibility.Visible;
    }

    /// (at the row's right while the step is under way: how many of how many)
    public void Count(string text)
    {
        count.Text = text;
        count.Visibility = running ? Visibility.Visible : Visibility.Collapsed;
    }

    public void Begin()
    {
        running = true;
        tick.Visibility = Visibility.Collapsed;
        count.Visibility = count.Text.Length > 0 ? Visibility.Visible : Visibility.Collapsed;
        Ink_(Now);
    }

    public void Done()
    {
        running = false;
        count.Visibility = Visibility.Collapsed;
        tick.Visibility = Visibility.Visible;
        Ink_(Ink);
    }

    /// (not done: left to later, the shaders' step when they were not prepared now)
    public void Skipped()
    {
        running = false;
        count.Visibility = tick.Visibility = Visibility.Collapsed;
        Ink_(Dim);
    }

    public void Stopped()
    {
        running = false;
        tick.Visibility = Visibility.Collapsed;
        Ink_(Bad);
    }
}
