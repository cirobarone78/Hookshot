using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Imaging;
using System.Windows.Shell;
using static HookshotBuilder.LaunchList;

namespace HookshotBuilder;

/// The launcher: hookshot.exe in a game folder opens the builder with --launch <folder> (builder/setup/setup.c). What its bar of
/// versions holds is decided in LaunchList.cs; this is the window around it
public partial class MainWindow
{
    static readonly Brush QuietInk = Frozen(0xB8, 0xB8, 0xB8);   // (the panel's small lines)
    static Brush Frozen(byte r, byte g, byte b) { var x = new SolidColorBrush(Color.FromRgb(r, g, b)); x.Freeze(); return x; }

    Lists? launchLists;                          // (the bar's lists, as last made)
    List<ReleaseInfo> launchReleases = new();    // (GitHub's releases, as last answered)
    string? launchBuilt;                         // (the release the launch folder holds)
    string? launchPick;                          // (the version picked: its key)
    bool launchChecking, launchChecked, menuOpen, olderOpen, stepsHalfWay;
    double? typicalBuild;                        // (how long a build took on this PC lately: ReadTypicalBuild)
    RadioButton? menuTab;                         // (the panel's tab last shown)
    // (Play: the game in the folder; Build: there is no game yet, and the button opens the build in the menu)
    enum Go { Play, Build }
    Go launchGo;

    // (while a version is brought the launcher stays: the programs that do it are hidden, and it says how far they are)
    enum LaunchState { Idle, Working, Stopped }
    LaunchState launchState;
    LaunchWork? work;                  // (what is being brought, and how far it is: LaunchWork.cs)
    LaunchChoice? workTarget;
    Process? enginePull;               // (the setup in its engine mode: that version's builder installed beside this one)
    Runner? launchRunner;              // (that version's own make_game.py)
    bool workCancelled, shotWorking, cancelHalfWay;
    string workStopped = "";           // (why it stopped)
    readonly System.Text.StringBuilder workLog = new();

    internal bool LauncherBusy => launchState == LaunchState.Working;

    LaunchChoice? Picked => launchLists?.Picked;

    /// The launcher of a game folder, when the window opens as it (hookshot.exe in the folder, or the game built last)
    async void ShowLauncher(string folder)
    {
        // (development) HOOKSHOT_UI_PREVIEW=versions,older,max,pick=release:v1.1.0,go,pages (any of them): the menu open from the
        // start, its older releases unfolded, the window maximised, that version picked, the button pressed, "Build from
        // game files" pressed; cancel: Cancel pressed when what the button started is 40% done; steps: the menu opened then
        var preview = (Environment.GetEnvironmentVariable("HOOKSHOT_UI_PREVIEW") ?? "").Split(',', StringSplitOptions.TrimEntries);
        olderOpen = preview.Contains("older");
        cancelHalfWay = preview.Contains("cancel");
        stepsHalfWay = preview.Contains("steps");
        var pick = preview.FirstOrDefault(p => p.StartsWith("pick="))?[5..];
        // (the saved choices first: Settings showed its switches off until the Build tab was opened, and a switch changed before
        // that saved the whole file from that screen, the game file chosen last time and the other switches lost with it)
        ApplySettings();
        EnterLauncher(folder, pick, check: false);
        // (tab=build|releases|settings: that tab of the menu, open)
        if (preview.FirstOrDefault(p => p.StartsWith("tab=")) is { } tab)
        {
            ShowTab(tab[4..] == "build" ? TabBuild : tab[4..] == "settings" ? TabSettings : TabReleases);
            ShowMenu(true, atOnce: true);
        }
        if (preview.Contains("versions")) { ShowTab(TabReleases); ShowMenu(true, atOnce: true); }
        if (preview.Contains("max")) WindowState = WindowState.Maximized;
        await CheckReleases(say: false);
        // (development) HOOKSHOT_UI_SHOT=<file.png>: the window as drawn, once the releases are in, and out (the window opens away
        // from the screen and takes no keys, MainWindow's constructor). With go: drawn half way (<file>-working.png) and when
        // what the button started has ended (WorkEnded)
        // (go: the version picked brought, as its row pressed does; never the game started)
        if (preview.Contains("go") && launchLists?.All.FirstOrDefault(c => string.Equals(c.Key, pick, StringComparison.OrdinalIgnoreCase)) is { } pressed)
        {
            if (pressed.Reach) Bring(pressed);
            else if (pressed.Here) Rebuild(pressed);   // (the one in the folder: built again with the settings now)
            if (launchState != LaunchState.Idle) return;
        }
        if (preview.Contains("pages"))   // (the Build tab opened: the game files looked for)
        {
            ShowTab(TabBuild);
            ShowMenu(true, atOnce: true);
            await Task.Delay(2500);
        }
        if (Shot != null)
        {
            await Task.Delay(500);
            SaveShot(Shot);
            Leave();
        }
    }

    /// The screen becomes the launcher of that folder: at the start, and when a build here has made the game (MainWindow.xaml.cs,
    /// ShowReady) or was left for the game that is there. What is on this PC shows at once; GitHub's releases when they come
    void EnterLauncher(string folder, string? pick = null, bool check = true)
    {
        launchFolder = folder;
        updating = false;
        if (OutPath.Text != folder) OutPath.Text = folder;
        launchBuilt = GameVersion(folder) ?? ReadVersion(folder);
        launchPick = pick ?? LastChoice(folder);
        // (a build's choices may have asked for another update track's newest, OpenFiles and TrackChanged: here the latest is
        // the latest release, as CheckReleases had it)
        if (launchReleases.Count > 0) latestTag = launchReleases.FirstOrDefault(r => !r.Pre)?.Tag;
        launchState = LaunchState.Idle;
        ShowFace(Face.Launcher);
        FillChoices();
        if (check && !launchChecked) _ = CheckReleases(say: false);
    }

    static string? Shot => Environment.GetEnvironmentVariable("HOOKSHOT_UI_SHOT") is { Length: > 0 } file ? file : null;

    void SaveShot(string file)
    {
        UpdateLayout();
        var picture = new RenderTargetBitmap((int)ActualWidth, (int)ActualHeight, 96, 96, PixelFormats.Pbgra32);
        picture.Render(this);
        var png = new PngBitmapEncoder();
        png.Frames.Add(BitmapFrame.Create(picture));
        using (var to = File.Create(file)) png.Save(to);
        // (beside it, what the picture shows in words, for a check that reads no picture: tests/builder_launcher/rig)
        var menu = !menuOpen ? "closed" : (menuTab?.Content as string ?? "").ToLowerInvariant();
        string Shown(FrameworkElement e, string text) => e.Visibility == Visibility.Visible ? text : "";
        File.WriteAllLines(System.IO.Path.ChangeExtension(file, ".txt"), new[]
        {
            $"face={face}", $"state={launchState}", $"button={LauncherGoText.Text}",
            $"enabled={LauncherGo.IsEnabled}", $"under={LauncherVersion.Content}", $"menu={menu}",
            $"build={Shown(BuildGame, "Build Game")}{Shown(BuildBar, BuildBarText.Text)}{Shown(BuildStopped, BuildStopped.Content as string ?? "")}",
            $"buildline={Shown(BuildLine, BuildLine.Text)}", $"buildwhy={Shown(BuildWhy, BuildWhy.Text)}",
            $"foot={Shown(LauncherCheck, LauncherCheck.Content as string ?? "")}{Shown(UpdateButton, "Update Available")}{Shown(FootBar, FootBarText.Text)}{Shown(FootStopped, "Update stopped")}",
            $"footline={Shown(FootLine, FootLine.Text)}", $"footwhy={Shown(FootWhy, FootWhy.Text)}",
            $"footnote={Shown(FootNote, FootNote.Text.Replace("\n", " / "))}",
            $"files={SourceText.Text}", $"folder={OutPath.Text}", $"filewhy={Shown(SourceWhy, SourceWhy.Text)}",
            $"rows={string.Join(" | ", ((IEnumerable<LaunchChoice>?)ReleaseList.ItemsSource ?? Array.Empty<LaunchChoice>()).Select(c => c.Label + (c.Ticked ? " [tick]" : c.Busy ? " [busy]" : c.Arrow ? " [get]" : c.Dim ? " [dim]" : "")))}",
            $"fold={Shown(FoldRow, FoldText.Text)}",
            $"steps={string.Join(" | ", rows.Values.Select(r => r.Says))}",
        });
    }

    /// GitHub's releases asked for (when the launcher opens, and by Check for updates, which then says what came of it)
    async Task CheckReleases(bool say)
    {
        if (launchChecking) return;
        launchChecking = true;
        LauncherCheck.IsHitTestVisible = false;
        LauncherCheck.Content = "Checking…";
        List<ReleaseInfo> found;
        string? latest;
        // (development) HOOKSHOT_LATEST_TAG=v1.2.0-rc.1,v1.1.0,v1.0.0?: the releases instead of GitHub's, newest first. One with
        // a part after its numbers is a pre-release, the first without is the latest, one ending in ? has no builder to
        // download; none: no answer
        if (Environment.GetEnvironmentVariable("HOOKSHOT_LATEST_TAG") is { Length: > 0 } fake)
        {
            found = fake == "none" ? new List<ReleaseInfo>()
                : fake.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                      .Select(t => new ReleaseInfo(t.TrimEnd('?'), IsPre(t), !t.EndsWith('?'), !t.EndsWith('?'))).ToList();
            latest = found.FirstOrDefault(r => !r.Pre)?.Tag;
        }
        else
            (found, latest) = await Updater.ReleaseList();
        // (no answer: the releases of the check before stay)
        if (found.Count > 0 || launchReleases.Count == 0) (launchReleases, latestTag) = (found, latest);
        updateTarget = latestTag ?? Tools.Find()?.Version;
        launchChecked = true;
        FillChoices();
        // (a newer release: Update Available takes the button's place at once; else what came of it, for a moment)
        if (say && (found.Count == 0 || !NewerOut()))
        {
            LauncherCheck.Content = found.Count == 0 ? "Could not check" : "Up to date";
            await Task.Delay(2400);
        }
        LauncherCheck.Content = "Check for updates";
        LauncherCheck.IsHitTestVisible = true;
        launchChecking = false;
        Render();
    }

    async void LauncherCheckClick(object sender, RoutedEventArgs e) => await CheckReleases(say: true);

    /// (the latest release is ahead of the one this folder holds)
    bool NewerOut() => latestTag != null && launchBuilt != null && IsRelease(launchBuilt) && Newer(latestTag, launchBuilt);

    /// The bar's lists (LaunchList.cs), from GitHub's releases, this folder's and the builders installed here. The version
    /// picked last time for this folder is picked again, else the one the folder holds
    void FillChoices()
    {
        typicalBuild = ReadTypicalBuild();   // (read again with the lists: after a build it has one more)
        var installed = InstalledTools().Keys;
        var rebuilds = GameVersion(launchFolder) != null;
        launchLists = Make(launchReleases, latestTag, launchBuilt, installed, rebuilds, launchPick, olderOpen);
        // (Play plays what is here: the folder's release. A pick kept from before, a release not here, is not one)
        if (launchLists.Picked is { Here: false })
            launchLists = Make(launchReleases, latestTag, launchBuilt, installed, rebuilds, null, olderOpen);
        // (the version being brought: the mark that turns)
        if (launchState == LaunchState.Working && workTarget != null)
            foreach (var c in launchLists.All) c.Busy = string.Equals(c.Key, workTarget.Key, StringComparison.OrdinalIgnoreCase);
        // (one list, newest first: the pre-releases among the releases while Settings has them on, and always the one in the folder)
        var pre = PreTick.IsChecked == true;
        ReleaseList.ItemsSource = launchLists.Pre.Where(c => pre || c.Here || c.Picked || c.Busy).Concat(launchLists.Releases)
                                             .OrderByDescending(c => c.Tag!, Order).ToList();
        FoldRow.Visibility = launchLists.Older > 0 ? Visibility.Visible : Visibility.Collapsed;
        FoldText.Text = launchLists.Folded ? $"{launchLists.Older} older releases" : "Fewer releases";
        FoldTurn.ScaleY = launchLists.Folded ? 1 : -1;   // (the arrow points down while they are folded, up to fold them again)
        ShowLowMem();
        ShowRebuildNote();
        ReleasesNote.Text = launchChecked && launchReleases.Count == 0 ? "GitHub did not answer: only the versions on this PC are listed." : "";
        ReleasesNote.Visibility = ReleasesNote.Text.Length > 0 ? Visibility.Visible : Visibility.Collapsed;
        Render();
    }

    /// A version pressed in Releases: the one here is what Play plays; another release is brought into the folder (asked first)
    void LauncherRowClick(object sender, RoutedEventArgs e)
    {
        if ((sender as FrameworkElement)?.DataContext is not LaunchChoice c || Busy) return;
        // (the one in the folder: built again with the settings now, asked first; a folder without its game files cannot be)
        if (c.Here && c.Rebuilds && File.Exists(GameExe(launchFolder))) Rebuild(c);
        else if (c.Here) Pick(c);
        else if (c.Reach) Bring(c);
    }

    void Pick(LaunchChoice c)
    {
        launchPick = c.Key;
        SaveChoice(launchFolder, c.Key);
        FillChoices();
    }

    /// (a release brought into the folder: by its row, or by Update Available)
    void Bring(LaunchChoice c)
    {
        if (c.Tag is not { } tag || Busy) return;
        var ahead = launchBuilt == null || !IsRelease(launchBuilt) || Newer(tag, launchBuilt);
        // (kept for this folder, as Play keeps what it played: the builder opened with nothing asked finds the game by it)
        SaveChoice(launchFolder, c.Key);
        // (beside the builder in use, by the setup's engine mode, when the release has what it installs from: LaunchList.ByEngine)
        var engine = ByEngine(launchReleases.FirstOrDefault(r => SameTag(r.Tag, tag)), BuilderHere(tag) != null, EngineSetup() != null);
        // (asked every time: a version is not downloaded ready to play, its tools build the game again from the player's files.
        // The builder goes back too only by its own update: the engine mode leaves the one in use, NextBuilder)
        var name = VersionName(tag);
        var rebuild = $"Your game is rebuilt from your game files with {name}'s tools. That takes {AboutTime()} on this PC, and Play waits until it is done. Your saves and settings stay.";
        var ask = ahead ? $"Update to {name}?\n\n{rebuild}"
                        : $"Switch back to {name}? It replaces {VersionName(launchBuilt!)} in this folder{(engine ? "" : ", and the builder goes back with it")}.\n\n{rebuild}";
        if (Shot == null && MessageBox.Show(this, ask, "Hookshot", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes)
            return;
        if (engine)
        {
            StartWork(c);
            return;
        }
        // (a setup from before it could install a version beside this one, or a release with only the zip: the builder's own
        // update, which takes this builder's place with that version's. The latest release as before; any other by its own tag)
        readyNote = null;
        Updater.UpdateFolder(this, launchFolder, tag, fetched: false, named: !SameTag(tag, latestTag));
    }

    // ---- the game built again as it is, with the settings now: DLSS and FSR 4 take effect at a build, not when they are switched ----

    /// (how the game in the folder was built: FSR 4 by make_game.py's mark, DLSS by NVIDIA's DLL in its ngx folder)
    bool BuiltWithFsr => launchFolder.Length > 0 && File.Exists(System.IO.Path.Combine(launchFolder, ".hookshot_fsr"));
    bool BuiltWithDlss => launchFolder.Length > 0 && File.Exists(System.IO.Path.Combine(launchFolder, "ngx", "nvngx_dlss.dll"));
    LaunchChoice? HereChoice => launchLists?.All.FirstOrDefault(c => c.Here);

    /// Settings' note, when the switches no longer say how the game was built, with Rebuild beside it. (Turning DLSS off is not
    /// one: NVIDIA's DLL stays in the folder, and the game's Upscaler menu chooses whether it is used)
    void ShowRebuildNote()
    {
        if (RebuildRow == null) return;
        string? why = null;
        if (HereChoice is { Rebuilds: true } && File.Exists(GameExe(launchFolder)))
        {
            var fsr = FsrTick.IsChecked == true && fsrLicense;
            if (fsr && !BuiltWithFsr) why = "Built without FSR 4";
            else if (!fsr && BuiltWithFsr) why = "Built with FSR 4";
            else if (DlssTick.IsChecked == true && !BuiltWithDlss) why = "Built without DLSS";
        }
        // (one line, as the panel has room for: the whole under the pointer)
        RebuildNote.Text = why ?? "";
        RebuildNote.ToolTip = why == null ? null
            : $"{why}. Rebuild builds your game again from its game files with your settings now, {AboutTime()} on this PC. Your saves stay.";
        RebuildRow.Visibility = why != null ? Visibility.Visible : Visibility.Collapsed;
        RebuildLink.IsEnabled = !Busy;
    }

    void RebuildClick(object sender, RoutedEventArgs e)
    {
        if (HereChoice is { } c) Rebuild(c);
    }

    /// The version in the folder built again from the game files it keeps, with its own tools and the settings now (asked first)
    void Rebuild(LaunchChoice c)
    {
        if (c.Tag is not { } tag || Busy) return;
        var name = VersionName(tag);
        var saved = BuilderSettings.Load(SettingsPath);
        var with = $"FSR 4 {(saved?.Fsr == true && saved.FsrLicense ? "on" : "off")}, DLSS {(saved?.Dlss == true ? "on" : "off")}";
        var ask = $"Rebuild {name}?\n\nYour game is built again from your game files with your settings now ({with}). That takes {AboutTime()} on " +
                  "this PC, and Play waits until it is done. Your saves and settings stay.";
        if (Shot == null && MessageBox.Show(this, ask, "Hookshot", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes)
            return;
        // (its builder is here, as it built the folder; one removed since is installed again first, as for any version)
        if (BuilderHere(tag) == null && !ByEngine(launchReleases.FirstOrDefault(r => SameTag(r.Tag, tag)), false, EngineSetup() != null))
        {
            MessageBox.Show(this, $"The builder of {name} is not on this PC any more, and its release has none to download here.", "Hookshot",
                            MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }
        StartWork(c, rebuild: true);
    }

    /// Update Available, at the panel's foot: the latest release brought
    void UpdateClick(object sender, RoutedEventArgs e)
    {
        if (launchLists?.All.FirstOrDefault(c => SameTag(c.Tag, latestTag)) is { Reach: true } c) Bring(c);
    }

    /// How long a build took on this PC lately, in seconds (make_game.py's build_times.json, in the build files folder: the
    /// middle of the last five), or null when none was kept
    static double? ReadTypicalBuild()
    {
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(System.IO.Path.Combine(Storage.Work, "build_times.json")));
            var took = doc.RootElement.GetProperty("builds").EnumerateArray()
                          .Select(b => b.TryGetProperty("total_seconds", out var s) && s.TryGetDouble(out var v) ? v : 0)
                          .Where(v => v > 0).TakeLast(5).OrderBy(v => v).ToList();
            return took.Count > 0 ? took[took.Count / 2] : null;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or JsonException or KeyNotFoundException or InvalidOperationException)
        {
            return null;
        }
    }

    /// ("about 30 minutes", from ReadTypicalBuild; with none kept, what a build commonly takes)
    string AboutTime()
    {
        if (typicalBuild is not double t) return "around half an hour or more";
        var minutes = Math.Max(5, (int)Math.Round(t / 300) * 5);   // (to five minutes: it is a guess, not a promise)
        return minutes >= 60 ? $"about {minutes / 60} h {(minutes % 60 > 0 ? $"{minutes % 60} min" : "")}".TrimEnd() : $"about {minutes} minutes";
    }

    /// Settings' "Lower memory use" as the game folder's hookshot_env.txt has it (GameEnv.cs), and the cache file's size under it.
    /// Only with a game folder: the switch is a line beside the game
    void ShowLowMem()
    {
        var game = launchFolder.Length > 0 && Directory.Exists(launchFolder) ? new DirectoryInfo(launchFolder) : null;
        LowMemTick.IsEnabled = game != null;
        LowMemTick.IsChecked = game != null && GameEnv.SkipsCache(game);
        var bytes = game != null ? GameEnv.CacheBytes(game) : -1;
        LowMemNote.Text = game == null ? "" : bytes > 0
            ? $"Skips the {Storage.Gb(bytes)} pipeline cache file: less memory, may stutter more the first time."
            : "Skips the pipeline cache file the game makes as it plays: less memory, may stutter more the first time.";
        LowMemNote.Visibility = LowMemNote.Text.Length > 0 ? Visibility.Visible : Visibility.Collapsed;
        LaunchShare.IsEnabled = game != null;   // (Save my pipeline list: the game folder's)
    }

    void LowMemClick(object sender, RoutedEventArgs e)
    {
        var skip = LowMemTick.IsChecked == true;
        try { GameEnv.SetSkip(new DirectoryInfo(launchFolder), skip); }
        catch (Exception x) when (x is IOException or UnauthorizedAccessException or ArgumentException)
        {
            MessageBox.Show(this, $"The setting could not be saved in the game folder: {x.Message}", "Hookshot", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
        ShowLowMem();   // (what the file says now, whether or not it could be written)
    }

    /// (a build or an update under way, the builder's own update's download too, or the build files let go after one: nothing
    /// else starts)
    bool Busy => runner != null || launchState == LaunchState.Working || download != null || (face == Face.Build && updating) ||
                 freeing != null;

    void LauncherFoldClick(object sender, RoutedEventArgs e)
    {
        olderOpen = !olderOpen;
        FillChoices();
    }

    /// (the builder of a release, when it is installed here: its tools build the folder as that release with nothing downloaded)
    static Tools? BuilderHere(string tag)
    {
        foreach (var (version, tools) in InstalledTools())
            if (SameTag(version, tag)) return tools;
        return null;
    }

    /// What Play plays (the folder's release) and its name under it
    void ShowGo()
    {
        var c = Picked;
        var game = launchFolder.Length > 0 && File.Exists(GameExe(launchFolder));
        launchGo = game ? Go.Play : Go.Build;
        LauncherGoText.Text = launchGo == Go.Build ? "Build" : "Play";
        // (a folder built before it kept its game files has no release here: its version as it says it, else only that it is a game)
        LauncherVersion.Content = c is { Here: true } ? c.Title : game ? (launchBuilt is { } v ? (IsRelease(v) ? VersionName(v) : v) : "Your game") : "No game yet";
        LauncherVersion.IsHitTestVisible = launchGo == Go.Play;
        LauncherVersion.ToolTip = "Open the game folder";
        // (the dot on Menu: something newer is in there)
        MenuDot.Visibility = NewerOut() ? Visibility.Visible : Visibility.Collapsed;
    }

    /// The whole window from what is going on: Play and the version under it, the menu's Build page (Build Game, the bar of a
    /// build under way, the red button of one that stopped) and the menu's foot (Check for updates, Update Available, the bar
    /// of an update under way and Cancel, the red button of one that stopped). Called after anything changes
    void Render()
    {
        if (LauncherGo == null || BuildGame == null) return;
        ShowGo();
        var building = face == Face.Build;
        var buildStopped = face == Face.Problem;
        // (an update the builder runs itself, the game's --update or the builder's own update: at the foot, as the launcher's)
        var footWorking = launchState == LaunchState.Working || (building && updating);
        var footStopped = launchState == LaunchState.Stopped || (buildStopped && updating);
        var tabWorking = building && !updating;
        var tabStopped = buildStopped && !updating;
        var busy = Busy;
        LauncherGo.IsEnabled = !busy;
        MenuButton.Visibility = menuOpen ? Visibility.Collapsed : Visibility.Visible;

        // ---- Build ----
        var idle = !tabWorking && !tabStopped;
        BuildGame.Visibility = idle ? Visibility.Visible : Visibility.Collapsed;
        BuildGame.IsEnabled = SourceReady && OutPath.Text.Length > 2 && !busy;
        BuildBar.Visibility = tabWorking ? Visibility.Visible : Visibility.Collapsed;
        BuildStopped.Visibility = tabStopped ? Visibility.Visible : Visibility.Collapsed;
        BuildArea.BorderThickness = new Thickness(0, 0, 0, idle ? 1 : 0);
        BuildOptions.Visibility = idle ? Visibility.Visible : Visibility.Collapsed;
        BuildLinks.Visibility = idle ? Visibility.Collapsed : Visibility.Visible;
        BuildCancel.Visibility = tabWorking ? Visibility.Visible : Visibility.Collapsed;
        BuildCopy.Visibility = tabStopped ? Visibility.Visible : Visibility.Collapsed;
        SourceChange.IsEnabled = ChangeButton.IsEnabled = !building;
        var (line, lineInk) = tabWorking ? (stepLine, QuietInk) : idle ? IdleLine() : ("", QuietInk);
        (BuildLine.Text, BuildLine.Foreground) = (line, lineInk);
        BuildLine.ToolTip = idle && readyNote != null ? readyTip : null;
        BuildLine.Visibility = line.Length > 0 ? Visibility.Visible : Visibility.Collapsed;
        BuildWhy.Text = tabStopped ? problemWhy : "";
        BuildWhy.ToolTip = BuildWhy.Text.Length > 0 ? BuildWhy.Text : null;   // (whole: MainWindow.xaml cuts a long one)
        BuildWhy.Visibility = tabStopped ? Visibility.Visible : Visibility.Collapsed;
        BuildStopped.Content = problemIsTools ? "Repair build tools" : "Build stopped";
        BuildStopped.ToolTip = problemIsTools ? "Downloads the build tools again from their official releases" : "Try again";

        // ---- the foot ----
        var available = !footWorking && !footStopped && !launchChecking && NewerOut() && launchLists?.All.Any(c => SameTag(c.Tag, latestTag) && c.Reach) == true;
        LauncherCheck.Visibility = !footWorking && !footStopped && !available ? Visibility.Visible : Visibility.Collapsed;
        LauncherCheck.IsEnabled = !busy;
        UpdateButton.Visibility = available ? Visibility.Visible : Visibility.Collapsed;
        UpdateButton.IsEnabled = !busy;
        // (and beside Play, on the main screen: Play plays the version in the folder, Update brings the new one)
        LauncherUpdate.Visibility = available && launchGo == Go.Play ? Visibility.Visible : Visibility.Collapsed;
        LauncherUpdateTo.Text = available ? "to " + VersionName(latestTag!) : "";
        LauncherUpdate.ToolTip = available ? $"Update to {VersionName(latestTag!)}: your game is rebuilt from your game files ({AboutTime()}). Your saves and settings stay." : null;
        FootBar.Visibility = footWorking ? Visibility.Visible : Visibility.Collapsed;
        FootStopped.Visibility = footStopped ? Visibility.Visible : Visibility.Collapsed;
        FootStopped.Content = launchState != LaunchState.Stopped ? "Update stopped" : work?.IsRebuild == true ? "Rebuild stopped"
            : work?.Bar.StartsWith("Switching") == true ? "Switch stopped" : "Update stopped";
        FootCancel.Visibility = footWorking ? Visibility.Visible : Visibility.Collapsed;
        FootLinks.Visibility = footStopped ? Visibility.Visible : Visibility.Collapsed;
        FootLine.Text = available ? $"{VersionName(latestTag!)} Latest" : "";
        FootLine.Visibility = available ? Visibility.Visible : Visibility.Collapsed;
        // (that installing a version is a rebuild of the game, and how long; while it runs, the step and the time left)
        FootNote.Text = available ? $"Rebuilds your game from your game files · {AboutTime()}"
            : launchState == LaunchState.Working && work != null ? work.Note(typicalBuild,(DateTime.Now - work.Started).TotalSeconds)
            : footWorking ? "Rebuilding your game" + (stepLine.Length > 0 ? "\n" + stepLine : "")
            : "";
        FootNote.Visibility = FootNote.Text.Length > 0 ? Visibility.Visible : Visibility.Collapsed;
        FootWhy.Text = launchState == LaunchState.Stopped ? StoppedWhy() : footStopped ? problemWhy : "";
        FootWhy.ToolTip = FootWhy.Text.Length > 0 ? FootWhy.Text : null;
        FootWhy.Visibility = footStopped ? Visibility.Visible : Visibility.Collapsed;
        if (launchState == LaunchState.Working && work != null) SetBar(FootBar, FootFill, FootBarText, work.Fraction, work.Bar);
        else if (building) SetBar(updating ? FootBar : BuildBar, updating ? FootFill : BuildFill, updating ? FootBarText : BuildBarText,
                                  buildFraction, $"{(updating ? "Updating" : "Building")}... {(int)(buildFraction * 100)}%");
        ShowPage();
    }

    static void SetBar(FrameworkElement bar, FrameworkElement fill, TextBlock text, double f, string words)
    {
        var width = bar.ActualWidth > 0 ? bar.ActualWidth : 235;
        fill.Width = Math.Round(width * Math.Clamp(f, 0, 1));
        text.Text = words;
    }

    /// (why the version brought stopped, whole: Nothing was changed, as the folder is swapped only once the new game is complete)
    string StoppedWhy() => workStopped.TrimEnd('.') + ". Nothing was changed in your game folder.";

    /// Play: the version picked, here. Build, with no game yet: the build's choices, in the menu's Build tab
    void LauncherGoClick(object sender, RoutedEventArgs e)
    {
        if (Busy) return;
        if (launchGo == Go.Build)
        {
            ShowTab(TabBuild);
            ShowMenu(true);
            return;
        }
        var c = Picked;
        if (c != null) SaveChoice(launchFolder, c.Key);
        if (StartGame(launchFolder)) Leave();
    }

    /// The red button of a build or an update that stopped: it tries again (or repairs the build tools)
    void LauncherStoppedClick(object sender, RoutedEventArgs e)
    {
        if (Busy) return;
        if (face == Face.Problem)
        {
            RetryProblem(sender, e);
            return;
        }
        if (launchState != LaunchState.Stopped) return;
        if (workTarget != null) StartWork(workTarget);
    }

    /// (Dismiss, beside Copy error log: the update that stopped put away, Check for updates in its place)
    void FootDismissClick(object sender, RoutedEventArgs e)
    {
        if (face == Face.Problem && updating) Back(sender, e);
        else if (launchState == LaunchState.Stopped)
        {
            launchState = LaunchState.Idle;
            ShowDetails(false);
            FillChoices();
        }
    }

    // ---- a version brought: the launcher stays, and hidden programs do it (Paper: "v2 - Updating", "v2 - Update stopped") ----

    /// The setup beside this builder, when it has the engine mode (builder/setup/setup.c, --engine). One from before would take
    /// the word for an ordinary install: it would open its window, make that version the one in use and remove this one
    static string? EngineSetup()
    {
        try
        {
            var setup = System.IO.Path.Combine(AppContext.BaseDirectory, "HookshotBuilder-Setup.exe");
            if (!File.Exists(setup)) return null;
            var has = File.ReadAllBytes(setup).AsSpan().IndexOf(System.Text.Encoding.Unicode.GetBytes("--engine")) >= 0;
            return has ? setup : null;
        }
        catch (Exception) { return null; }
    }

    /// The version picked brought into the launch folder: its builder installed beside this one when it is not on the PC (the
    /// setup, hidden), then the folder built with that builder's own tools (its make_game.py, hidden). The window is the
    /// launcher's throughout
    async void StartWork(LaunchChoice c, bool rebuild = false)
    {
        var tag = c.Tag!;
        var tools = BuilderHere(tag);
        var ahead = launchBuilt == null || !IsRelease(launchBuilt) || Newer(tag, launchBuilt);
        (workTarget, work, workCancelled, workStopped, shotWorking) =
            (c, new LaunchWork(VersionName(tag), ahead, fetch: tools == null, rebuild), false, "", false);
        workLog.Clear();
        launchState = LaunchState.Working;
        readyNote = null;
        (BuildCopy.Content, FootCopy.Content) = ("Copy error log", "Copy error log");
        ShowDetails(false);
        // (its steps, in the menu: the builder got first when it is not here; the shaders' step when that version has one and
        // the player has it on. One downloaded is a version that has it)
        MakeRows(update: true, shaders: BuilderSettings.PrepareNow(SettingsPath) && (tools == null || KnowsShaderStep(tools)), download: tools == null);
        // (its bar at the menu's foot, under Releases with the version's row turning)
        ShowTab(TabReleases);
        ShowMenu(true);
        FillChoices();
        if (tools == null)
        {
            var why = await PullEngine(tag);
            if (why == null && (tools = BuilderHere(tag)) == null)
                why = $"The builder of {VersionName(tag)} is not there after it was installed. Your antivirus may have removed it.";
            if (why != null)
            {
                WorkEnded(why);
                return;
            }
        }
        int? workers = null;
        try { workers = BuildWorkers.Selected(WorkerBox.SelectedItem); } catch (ArgumentException) { }
        // (the build memory as saved, as the builder's own update takes it, BeginUpdate: no menu of options is shown here. Tools
        // from before the choice do not read it)
        var memoryGb = BuilderSettings.Load(SettingsPath)?.MemoryGb is int gb && gb > 0 ? gb : (int?)null;
        // (as the builder's own update does it, UpdateBuild: the saved NVIDIA DLSS tick, or a folder built with DLSS, its license
        // accepted then, is built with it; AMD FSR 4 the same; the build files where the player chose. Each said only to tools that
        // know the word: an older version's make_game.py would stop on an argument it does not know)
        var saved = BuilderSettings.Load(SettingsPath);
        var known = MakeGameText(tools!);
        // (a rebuild is for the settings now: what the folder was built with does not carry over, and FSR 4 switched off is taken
        // out, --no-fsr, where that version's make_game.py knows the word)
        var dlss = (saved?.Dlss == true ||
                    (!rebuild && File.Exists(System.IO.Path.Combine(launchFolder, "ngx", "nvngx_dlss.dll")) &&
                     File.Exists(System.IO.Path.Combine(Storage.NgxSdk, "LICENSE.txt")))) &&
                   Knows(known, "--fetch-ngx-sdk") && Knows(known, "--accept-nvidia-license");
        var fsr = ((saved?.Fsr == true && saved.FsrLicense) ||
                   (!rebuild && File.Exists(System.IO.Path.Combine(launchFolder, ".hookshot_fsr")) &&
                    File.Exists(System.IO.Path.Combine(launchFolder, "amd_fidelityfx_upscaler_vk.dll")) &&
                    File.Exists(System.IO.Path.Combine(launchFolder, "LICENSE-AMD-FSR-SDK.md")))) &&
                  Knows(known, "--fsr") && Knows(known, "--fetch-fsr-runtime") && Knows(known, "--accept-amd-license");
        var args = new List<string> { "--update", launchFolder };
        if (rebuild && !fsr && BuiltWithFsr && Knows(known, "--no-fsr")) args.Add("--no-fsr");
        if (Storage.WorkChosen && Knows(known, "--work")) args.AddRange(new[] { "--work", Storage.Work });
        if (dlss) args.AddRange(new[] { "--fetch-ngx-sdk", "--accept-nvidia-license" });
        if (fsr) args.AddRange(new[] { "--fsr", "--fetch-fsr-runtime", "--accept-amd-license" });
        // (the shaders' step, left to the game's first start when the player unticked it: said only to tools that know the
        // word. A version from before the step has none to leave)
        if (!BuilderSettings.PrepareNow(SettingsPath) && KnowsShaderStep(tools!)) args.Add(ShaderStep.Later);
        launchRunner = new Runner(tools!, args, workers, dlss ? Storage.NgxSdk : null, memoryGb, fsr ? Storage.FfxSdk : null);
        launchRunner.Line += l => Dispatcher.BeginInvoke(() => WorkLine(l));
        launchRunner.Finished += failure => Dispatcher.BeginInvoke(() => WorkEnded(failure));
        launchRunner.Start();
    }

    /// (that version's make_game.py takes --no-prepare-shaders: read from its text, as each version runs its own tools)
    static bool KnowsShaderStep(Tools tools) => MakeGameText(tools).Contains(ShaderStep.Later);

    /// (that version's make_game.py, as text: what it knows is read from it. Empty when it cannot be read)
    static string MakeGameText(Tools tools)
    {
        try { return File.ReadAllText(System.IO.Path.Combine(tools.Root, "nx2", "make_game.py")); }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { return ""; }
    }

    /// (an option make_game.py declares: its name in quotes, as argparse is given it)
    static bool Knows(string makeGame, string option) => makeGame.Contains('"' + option + '"');

    /// The setup in its engine mode: that release installed beside the others, nothing started, nothing removed. null: done
    async Task<string?> PullEngine(string tag)
    {
        try
        {
            var si = new ProcessStartInfo(EngineSetup()!)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                StandardOutputEncoding = System.Text.Encoding.UTF8,
            };
            foreach (var a in new[] { "--engine", "--tag", tag }) si.ArgumentList.Add(a);
            // (this builder's home, a portable one too: the release goes beside the versions there, BuilderHome.cs)
            BuilderHome.PassTo(si);
            using var p = Process.Start(si)!;
            enginePull = p;
            while (await p.StandardOutput.ReadLineAsync() is { } line) WorkLine(line);
            await p.WaitForExitAsync();
            enginePull = null;
            if (workCancelled) return "cancelled";
            return p.ExitCode == 0 ? null : work?.Error ?? "The setup stopped without saying why.";
        }
        catch (Exception e)
        {
            enginePull = null;
            return workCancelled ? "cancelled" : "The setup could not be started: " + e.Message;
        }
    }

    void WorkLine(string line)
    {
        if (work == null) return;
        work.Line(line);
        workLog.AppendLine(line);
        if (workLog.Length > 600_000) workLog.Remove(0, workLog.Length - 400_000);
        if (detailsShown)
        {
            Log.AppendText(line + "\n");
            Log.ScrollToEnd();
        }
        // (the menu's steps: the builder got, then what its make_game.py says of its own)
        if (line.StartsWith("@@setup ") && rows.TryGetValue("download", out var got))
        {
            if (current == null) { current = "download"; got.Begin(); }
            got.Small(line[8..].Trim());
        }
        else if (line.StartsWith("@@installed ") && rows.TryGetValue("download", out got)) { got.Small("Installed beside the one in use"); got.Done(); current = null; }
        else StepsLine(line);
        Render();
        if (Shot != null && !shotWorking && work.Fraction >= 0.4)   // (development: the working state drawn once, on the way)
        {
            shotWorking = true;
            if (stepsHalfWay) ShowMenu(true, atOnce: true);
            SaveShot(System.IO.Path.ChangeExtension(Shot, null) + "-working.png");
            if (stepsHalfWay) ShowMenu(false, atOnce: true);
        }
        if (cancelHalfWay && work.Fraction >= 0.4)
        {
            cancelHalfWay = false;
            CancelLaunchWork();
        }
    }

    /// failure: null (it ended well), "cancelled", or why it stopped
    void WorkEnded(string? failure)
    {
        (launchRunner, enginePull) = (null, null);
        if (work?.Done != null)
        {
            // (the folder holds the version picked now: what the launcher shows is read again from it)
            launchBuilt = GameVersion(launchFolder) ?? ReadVersion(launchFolder);
            if (workTarget?.Tag is { } tag) NextBuilder(tag);
            if (Shot == null) Finder.RefreshShortcuts(launchFolder);   // (the player's shortcuts, onto the folder's launcher again)
            // (as after any build: the build files go but its compiled objects, so the next version compiles only what changed,
            // and a version's builder that is no longer the one in use. Nothing new starts until they are gone, Busy)
            _ = FreeAfterBuild();
            if (Shot != null && freeing?.Wait(20000) == true) freeing = null;   // (development: it is out as soon as it is drawn)
            launchState = LaunchState.Idle;
        }
        else if (failure == "cancelled" || workCancelled) launchState = LaunchState.Idle;
        else
        {
            workStopped = failure ?? work?.Error ?? "The build tools stopped without saying why.";
            launchState = LaunchState.Stopped;
            (BuildCopy.Content, FootCopy.Content) = ("Copy error log", "Copy error log");
            if (current != null && rows.TryGetValue(current, out var row)) row.Stopped();
        }
        if (launchState == LaunchState.Idle) ShowDetails(false);
        FillChoices();
        if (Shot != null)   // (development: drawn as it ended, and out)
        {
            SaveShot(Shot);
            Leave();
        }
    }

    /// After a release ahead of the builder in use was brought: its builder, which came with it, is the one in use from the next
    /// start (versions\current.txt, which the game folder's hookshot.exe reads; what Storage.Free keeps). The launcher never
    /// goes back to an older one this way, and not to a pre-release's
    static void NextBuilder(string tag)
    {
        try
        {
            if (IsPre(tag) || BuilderHere(tag) is not { } tools) return;
            var current = System.IO.Path.Combine(Storage.Base, "versions", "current.txt");
            var app = System.IO.Path.GetDirectoryName(tools.Root.TrimEnd('\\'))!;
            // (only a builder that holds this launcher: the game folder's hookshot.exe opens <that version>\HookshotBuilder\
            // HookshotBuilder.exe, setup.c launch_installed. A build of the builder under another name would leave it nothing to open)
            if (Environment.ProcessPath is not { } self || !File.Exists(System.IO.Path.Combine(app, System.IO.Path.GetFileName(self)))) return;
            var folder = System.IO.Path.GetFileName(System.IO.Path.GetDirectoryName(app));
            var now = File.ReadAllText(current).Trim();
            if (folder is { Length: > 0 } && IsRelease(now) && Newer(tag, now)) File.WriteAllText(current, folder);
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }   // (no current.txt: not a setup's install)
    }

    void LauncherCancelClick(object sender, RoutedEventArgs e)
    {
        if (face == Face.Build) CancelBuild(sender, e);
        else CancelLaunchWork();
    }

    void StoppedCopyClick(object sender, RoutedEventArgs e)
    {
        if (face == Face.Problem) CopyForReport(sender, e);
        else LauncherCopyClick(sender, e);
    }

    internal void CancelLaunchWork()
    {
        if (launchState != LaunchState.Working) return;
        workCancelled = true;
        launchRunner?.Cancel();
        try { enginePull?.Kill(entireProcessTree: true); } catch (Exception) { }
    }

    /// (what stopped, for a bug report: the versions, the reason and the last of what the hidden programs said)
    void LauncherCopyClick(object sender, RoutedEventArgs e)
    {
        var said = workLog.ToString();
        var report = $"Hookshot launcher: {work?.StoppedTitle}\nBuilder {Tools.Find()?.Version ?? "from source"}, the folder holds {launchBuilt ?? "no release"}\n" +
                     $"{workStopped}\n\n{(said.Length > 6000 ? said[^6000..] : said)}";
        try
        {
            Clipboard.SetText(report);
            FootCopy.Content = "Copied";
        }
        catch (Exception) { FootCopy.Content = "Could not copy"; }   // (the clipboard held by another program)
    }

    /// (the version under the button, pressed: the folder it is in)
    void LauncherFolderClick(object sender, RoutedEventArgs e)
    {
        if (launchGo != Go.Play || !Directory.Exists(launchFolder)) return;
        try { Process.Start(new ProcessStartInfo(launchFolder) { UseShellExecute = true }); }
        catch (Exception) { }   // (no Explorer to open it)
    }

    /// (GitHub and Discord: the page in the button's Tag, in the browser)
    void LauncherLinkClick(object sender, RoutedEventArgs e)
    {
        if ((sender as FrameworkElement)?.Tag is not string page) return;
        try { Process.Start(new ProcessStartInfo(page) { UseShellExecute = true }); }
        catch (Exception) { }   // (no browser to open it)
    }

    void LauncherMaxClick(object sender, RoutedEventArgs e) =>
        WindowState = WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized;

    // ---- the menu: a bar from the left (Paper: "Master Menu"), opened by Menu and closed by Close menu ----

    void MenuClick(object sender, RoutedEventArgs e) => ShowMenu(true);

    void MenuCloseClick(object sender, RoutedEventArgs e) => ShowMenu(false);

    /// (a press in the window that no button took: the menu closes)
    void LauncherBackClick(object sender, MouseButtonEventArgs e) => ShowMenu(false);

    /// (a press in the menu itself, between its rows: it stays)
    void LauncherBarClick(object sender, MouseButtonEventArgs e) => e.Handled = true;

    /// The menu opened or closed: a panel that slides in from the left, on the tab last shown
    void ShowMenu(bool open, bool atOnce = false)
    {
        if (VersionBar == null) return;
        if (open && menuTab == null) ShowTab(launchFolder.Length > 0 && File.Exists(GameExe(launchFolder)) ? TabReleases : TabBuild);
        if (open == menuOpen) return;
        menuOpen = open;
        Render();
        VersionBarSlide.BeginAnimation(TranslateTransform.XProperty, null);
        VersionBar.BeginAnimation(OpacityProperty, null);
        if (open) VersionBar.Visibility = Visibility.Visible;
        else if (atOnce) VersionBar.Visibility = Visibility.Collapsed;
        if (atOnce) return;
        var time = TimeSpan.FromMilliseconds(open ? 200 : 150);
        var away = -Math.Max(268, VersionBar.ActualWidth);
        var slide = new DoubleAnimation(open ? away : 0, open ? 0 : away, time)
        {
            EasingFunction = new CubicEase { EasingMode = open ? EasingMode.EaseOut : EasingMode.EaseIn },
        };
        // (opened again before it was away: it stays)
        if (!open) slide.Completed += (_, _) => { if (!menuOpen) VersionBar.Visibility = Visibility.Collapsed; };
        VersionBarSlide.BeginAnimation(TranslateTransform.XProperty, slide);
        VersionBar.BeginAnimation(OpacityProperty, new DoubleAnimation(open ? 0 : 1, open ? 1 : 0, time));
    }

    /// (one of the menu's three tabs shown: Build, Releases, Settings)
    void ShowTab(RadioButton tab)
    {
        menuTab = tab;
        if (tab.IsChecked != true) tab.IsChecked = true;
        ShowPage();
    }

    void TabChecked(object sender, RoutedEventArgs e)
    {
        if (sender is not RadioButton tab) return;
        menuTab = tab;
        ShowPage();
        // (the Build tab opened for the first time: the game files are looked for, as when there is no game yet)
        if (tab == TabBuild && !filesOpened && !Busy && IsLoaded) _ = OpenFiles(first: false);
    }

    void ShowPage()
    {
        if (BuildPage == null) return;
        var tab = menuTab ?? TabBuild;
        BuildPage.Visibility = tab == TabBuild ? Visibility.Visible : Visibility.Collapsed;
        ReleasesPage.Visibility = tab == TabReleases ? Visibility.Visible : Visibility.Collapsed;
        SettingsPage.Visibility = tab == TabSettings ? Visibility.Visible : Visibility.Collapsed;
    }

    /// (a font of the player's own, for the button's word: the first .otf or .ttf in HookshotBuilder\fonts. Never shipped with the
    /// builder (a commercial font such as FOT-Chiaro, which the launcher was drawn with, may not be passed on): Marcellus, OFL, is
    /// the launcher's own)
    void UseOwnFont()
    {
        try
        {
            var dir = System.IO.Path.Combine(Storage.Base, "fonts");
            var file = !Directory.Exists(dir) ? null
                : Directory.GetFiles(dir).Where(f => f.EndsWith(".otf", StringComparison.OrdinalIgnoreCase) || f.EndsWith(".ttf", StringComparison.OrdinalIgnoreCase))
                           .OrderBy(f => f, StringComparer.OrdinalIgnoreCase).FirstOrDefault();
            if (file != null)
            {
                var face = new GlyphTypeface(new Uri(file));
                var family = face.Win32FamilyNames.TryGetValue(System.Globalization.CultureInfo.GetCultureInfo("en-US"), out var en) ? en : face.Win32FamilyNames.Values.First();
                if (LauncherScreen.Child is FrameworkElement screen)
                    screen.Resources["Serif"] = new FontFamily(new Uri(dir.TrimEnd('\\') + "\\"), "./#" + family);
            }
        }
        catch (Exception) { }   // (a font that cannot be read: the launcher's own)
        CentreGoText();
    }

    /// The button's word with its capitals' middle on the button's middle, as it is drawn (a line of text is centred by its whole
    /// height, the room under the baseline too, which sets the word too high or low by a few pixels, differently in each font)
    void CentreGoText()
    {
        try
        {
            var family = LauncherGoText.FontFamily;
            var face = new Typeface(family, FontStyles.Normal, FontWeights.Normal, FontStretches.Normal);
            var size = LauncherGoText.FontSize;
            LauncherGoNudge.Y = Math.Round(family.LineSpacing * size / 2 - family.Baseline * size + face.CapsHeight * size / 2);
        }
        catch (Exception) { }
    }

    // ---- what is on this PC ----

    /// The builders installed here (versions\<tag>, as the setup keeps them): each one's tools build a folder as that release
    static Dictionary<string, Tools> InstalledTools()
    {
        var found = new Dictionary<string, Tools>(StringComparer.OrdinalIgnoreCase);
        try
        {
            foreach (var d in Directory.GetDirectories(System.IO.Path.Combine(Storage.Base, "versions")))
            {
                // (only a version the setup finished: <tag>.part is one being unpacked, <tag>.gone one being removed, and its
                // installed.txt is written last, builder/setup/setup.c)
                if (d.EndsWith(".part", StringComparison.OrdinalIgnoreCase) || d.EndsWith(".gone", StringComparison.OrdinalIgnoreCase) ||
                    !File.Exists(System.IO.Path.Combine(d, "installed.txt")))
                    continue;
                var tools = System.IO.Path.Combine(d, "HookshotBuilder", "tools");
                var py = System.IO.Path.Combine(tools, "python", "python.exe");
                var t = new Tools(tools, py);
                if (File.Exists(System.IO.Path.Combine(tools, "nx2", "make_game.py")) && File.Exists(py) && t.Version is { } v && IsRelease(v))
                    found[v] = t;
            }
        }
        catch (Exception) { }
        return found;
    }

    // ---- the choice, kept per game folder: launcher.json beside the versions ----

    static string ChoicesPath => System.IO.Path.Combine(Storage.Base, "launcher.json");

    static Dictionary<string, string> Choices()
    {
        try { return JsonSerializer.Deserialize<Dictionary<string, string>>(File.ReadAllText(ChoicesPath)) ?? new(); }
        catch (Exception) { return new(); }
    }

    static string? LastChoice(string folder) => Choices().GetValueOrDefault(folder.ToLowerInvariant());

    static void SaveChoice(string folder, string key)
    {
        try
        {
            var all = Choices();
            all[folder.ToLowerInvariant()] = key;
            Directory.CreateDirectory(Storage.Base);
            File.WriteAllText(ChoicesPath, JsonSerializer.Serialize(all));
        }
        catch (Exception) { }
    }
}
