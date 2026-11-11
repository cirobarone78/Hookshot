using HookshotBuilder;

// The launcher's bar of versions (builder/HookshotBuilder/LaunchList.cs): which list a version is in, its mark, and what is
// picked. No window, no game: dotnet run --project tests/builder_launcher/BuilderLauncherTests.csproj
static class Program
{
    static int checks;

    static void Require(bool ok, string message)
    {
        if (!ok) throw new Exception(message);
        checks++;
    }

    static ReleaseInfo R(string tag, bool download = true) => new(tag, LaunchList.IsPre(tag), download);
    static string Names(IEnumerable<LaunchChoice> list) => string.Join(" | ", list.Select(c => c.Label));
    static readonly string[] NoBuilders = Array.Empty<string>();

    static int Main()
    {
        // ---- the drawing (Paper's "Hookshot v2", "Releases Menu"): v2.1.0 in the folder and the latest, a pre-release ahead
        // of it, thirteen releases before it ----
        var github = new List<ReleaseInfo> { R("v2.2.0-rc.1"), R("v2.1.0") };
        for (var i = 14; i >= 2; i--) github.Add(R($"v2.0.{i}"));
        var l = LaunchList.Make(github, "v2.1.0", "v2.1.0", NoBuilders, rebuilds: true, pick: null, open: false);
        Require(Names(l.Releases) == "v2.1.0 - Latest | v2.0.14 | v2.0.13 | v2.0.12 | v2.0.11", "the five newest releases stay in sight: " + Names(l.Releases));
        Require(l.Older == 9 && l.Folded, $"nine releases fold into one row: {l.Older}, {l.Folded}");
        Require(Names(l.Pre) == "v2.2.0-rc.1", "one pre-release");
        Require(l.Picked?.Tag == "v2.1.0" && l.Picked.Ticked && !l.Picked.Arrow, "the folder's release is picked and ticked");
        Require(l.Picked!.Title == "v2.1.0 - Latest", "the latest says so under the button");
        var before = l.Releases[1];
        Require(!before.Here && before.Reach && before.Arrow && !before.Dim && !before.Ticked, "a release not here has the arrow");
        before.Busy = true;
        Require(!before.Arrow, "the one being brought has the turning mark in the arrow's place");
        Require(l.Pre[0].Arrow && l.Pre[0].Title == "v2.2.0-rc.1 - Pre-release", "a pre-release not here: the arrow, and its kind under the button");

        // (unfolded: every release, the row still there to fold them again)
        l = LaunchList.Make(github, "v2.1.0", "v2.1.0", NoBuilders, true, null, open: true);
        Require(l.Releases.Count == 14 && l.Older == 9 && !l.Folded, $"unfolded: {l.Releases.Count} releases, {l.Older}, {l.Folded}");

        // (the pre-release picked: it has the accent's place, keeps its arrow, and the folder's release loses its tick)
        l = LaunchList.Make(github, "v2.1.0", "v2.1.0", NoBuilders, true, "release:v2.2.0-rc.1", false);
        Require(l.Picked?.Tag == "v2.2.0-rc.1" && l.Picked.Arrow && !l.Picked.Ticked, "the pre-release picked keeps its arrow");
        Require(!l.Releases[0].Ticked && !l.Releases[0].Arrow && l.Releases[0].Here, "the folder's release: here, not picked, no mark");

        // (a folded release picked comes into sight, and the fold is one shorter)
        l = LaunchList.Make(github, "v2.1.0", "v2.1.0", NoBuilders, true, "release:v2.0.5", false);
        Require(Names(l.Releases) == "v2.1.0 - Latest | v2.0.14 | v2.0.13 | v2.0.12 | v2.0.11 | v2.0.5" && l.Older == 8, "a picked older release is shown: " + Names(l.Releases));

        // (a pick written in other capitals, as launcher.json may keep it: still the one picked)
        l = LaunchList.Make(github, "v2.1.0", "v2.1.0", NoBuilders, true, "RELEASE:V2.0.13", false);
        Require(l.Picked?.Tag == "v2.0.13", "a pick is found whatever its capitals");

        // ---- a newer release is out: it is first in Releases with the arrow, the folder's below it, still picked ----
        github = new List<ReleaseInfo> { R("v2.2.0"), R("v2.2.0-rc.1"), R("v2.1.0"), R("v2.0.14") };
        l = LaunchList.Make(github, "v2.2.0", "v2.1.0", NoBuilders, true, null, false);
        Require(Names(l.Releases) == "v2.2.0 - Latest | v2.1.0 | v2.0.14" && l.Older == 0, "one older release is not folded: " + Names(l.Releases));
        Require(l.Releases[0].Arrow && l.Picked?.Tag == "v2.1.0", "the new release has the arrow; the folder's stays picked");
        Require(Names(l.Pre) == "v2.2.0-rc.1", "a pre-release of a release that is out is still listed, below its release");
        // (Hookshot's own list today: the candidates came before their release, v2.1.0-rc.3 before v2.1.0; with older releases
        // folded, the candidates among the releases in sight are listed, the older ones' only once they are unfolded)
        var today = new List<ReleaseInfo> { R("v2.1.0"), R("v2.1.0-rc.3"), R("v2.1.0-rc.2"), R("v2.1.0-rc.1"), R("v2.0.14"), R("v2.0.13"),
                                         R("v2.0.12"), R("v2.0.11"), R("v2.0.10"), R("v2.0.9"), R("v2.0.8"), R("v2.0.8-rc.5"), R("v2.0.8-rc.1") };
        l = LaunchList.Make(today, "v2.1.0", "v2.1.0", NoBuilders, true, null, false);
        Require(Names(l.Pre) == "v2.1.0-rc.3 | v2.1.0-rc.2 | v2.1.0-rc.1", "the candidates of the releases in sight: " + Names(l.Pre));
        l = LaunchList.Make(today, "v2.1.0", "v2.1.0", NoBuilders, true, null, open: true);
        Require(Names(l.Pre) == "v2.1.0-rc.3 | v2.1.0-rc.2 | v2.1.0-rc.1 | v2.0.8-rc.5 | v2.0.8-rc.1", "unfolded, all of them: " + Names(l.Pre));
        Require(LaunchList.Newer("v2.2.0", "v2.1.0") && LaunchList.Newer("v2.2.0", "v2.2.0-rc.1") && !LaunchList.Newer("v2.2.0-rc.1", "v2.2.0")
                && !LaunchList.Newer("v2.1.0", "v2.1.0") && LaunchList.Newer("v2.2.0-rc.1", "v2.1.0"), "what is ahead of what");
        // (release candidates of one release, as Hookshot tags them: by their number, rc.10 after rc.9; an update from one to the
        // next is an update, not a switch back)
        Require(LaunchList.Newer("v2.2.0-rc.2", "v2.2.0-rc.1") && !LaunchList.Newer("v2.2.0-rc.1", "v2.2.0-rc.2")
                && LaunchList.Newer("v2.2.0-rc.10", "v2.2.0-rc.9") && LaunchList.Newer("v2.2.0-rc.1", "v2.2.0-beta.3")
                && LaunchList.Newer("v2.2.0-rc.1.1", "v2.2.0-rc.1") && LaunchList.Compare("v2.2.0-RC.1", "2.2.0-rc.1") == 0, "pre-releases in order");
        l = LaunchList.Make(new List<ReleaseInfo> { R("v2.2.0-rc.1"), R("v2.2.0-rc.10"), R("v2.2.0-rc.2"), R("v2.1.0") }, "v2.1.0", "v2.1.0",
                            NoBuilders, true, null, false);
        Require(Names(l.Pre) == "v2.2.0-rc.10 | v2.2.0-rc.2 | v2.2.0-rc.1", "the newest candidate first, whatever order GitHub gave: " + Names(l.Pre));
        // (the folder holds that old pre-release: it is listed, as what is here)
        l = LaunchList.Make(github, "v2.2.0", "v2.2.0-rc.1", NoBuilders, true, null, false);
        Require(Names(l.Pre) == "v2.2.0-rc.1" && l.Pre[0].Ticked, "the pre-release the folder holds is listed and picked");

        // ---- what can be brought ----
        // (Hookshot today: one release, with nothing to download; the folder holds it)
        l = LaunchList.Make(new[] { R("v1.0.0", download: false) }, "v1.0.0", "v1.0.0", new[] { "v1.0.0" }, true, null, false);
        Require(Names(l.Releases) == "v1.0.0 - Latest" && l.Picked!.Ticked && l.Pre.Count == 0 && l.Older == 0, "one release, here");
        // (a release with no builder to download is dim; one whose builder is installed here is not; nothing is, in a folder
        // that does not keep its game files)
        github = new List<ReleaseInfo> { R("v1.2.0"), R("v1.1.0", download: false), R("v1.0.0", download: false) };
        l = LaunchList.Make(github, "v1.2.0", "v1.2.0", new[] { "v1.0.0" }, true, null, false);
        Require(l.Releases[1].Dim && !l.Releases[1].Arrow, "no builder to download, none here: dim");
        Require(l.Releases[2].Arrow && !l.Releases[2].Dim, "its builder is installed here: the arrow");
        l = LaunchList.Make(github, "v1.2.0", "v1.1.0", NoBuilders, rebuilds: false, null, false);
        Require(l.Releases[0].Dim && !l.Releases[0].Arrow, "a folder without its game files: nothing can be brought");
        // (and its dim rows say why: the folder, not the release)
        Require(l.Releases[0].Tip!.StartsWith("This game folder was built before it kept its game files"), "the dim row's reason: " + l.Releases[0].Tip);
        l = LaunchList.Make(github, "v1.2.0", "v1.2.0", NoBuilders, rebuilds: true, null, false);
        Require(l.Releases[1].Tip == "Not on this PC, and its release has no builder to download", "a release with nothing to download says so: " + l.Releases[1].Tip);
        // (the one in the folder, which keeps its game files: pressed, it is rebuilt with the settings now)
        Require(l.Releases[0].Tip == "Your game. Press it to rebuild it with your settings now", "the version here can be rebuilt: " + l.Releases[0].Tip);
        Require(l.Releases[0].Ticked, "the version here is ticked");
        l.Releases[0].Busy = true;
        Require(!l.Releases[0].Ticked, "...and, being rebuilt, shows the turning mark alone");
        Require(LaunchList.Make(github, "v1.2.0", "v1.2.0", NoBuilders, rebuilds: false, null, false).Releases[0].Tip == null,
                "a folder without its game files: the version here says nothing of a rebuild");

        // ---- how a release is brought: the setup's engine mode installs only from a setup list ----
        Require(LaunchList.ByEngine(new ReleaseInfo("v1.3.0", false, true, SetupList: true), builderHere: false, engineSetup: true), "the setup and its list: the engine mode");
        Require(!LaunchList.ByEngine(new ReleaseInfo("v1.3.0", false, true, SetupList: false), false, true), "only the zip: the builder's own update, not an engine mode that cannot install it");
        Require(LaunchList.ByEngine(new ReleaseInfo("v1.3.0", false, true, SetupList: false), builderHere: true, engineSetup: true), "its builder installed here: nothing downloaded, either way");
        Require(!LaunchList.ByEngine(new ReleaseInfo("v1.3.0", false, true, SetupList: true), false, engineSetup: false), "a setup from before the engine mode: the builder's own update");
        Require(LaunchList.ByEngine(null, false, true), "a release GitHub did not list: the engine mode, as before");
        // (the same release written with and without its v is one release; GitHub's word on it wins)
        l = LaunchList.Make(new[] { R("v1.1.0") }, "v1.1.0", "1.1.0", new[] { "1.1.0" }, true, null, false);
        Require(l.Releases.Count == 1 && l.Releases[0].Here && l.Releases[0].Label == "v1.1.0 - Latest", "v1.1.0 and 1.1.0 are one");
        // (nothing known at all: GitHub did not answer and the folder has no version)
        l = LaunchList.Make(Array.Empty<ReleaseInfo>(), null, null, NoBuilders, false, null, false);
        Require(l.All.Count == 0 && l.Picked == null, "nothing to list");
        // (GitHub did not answer: what is on this PC is still listed, a pre-release the folder holds by its name)
        l = LaunchList.Make(Array.Empty<ReleaseInfo>(), null, "v1.2.0-rc.1", NoBuilders, true, null, false);
        Require(Names(l.Pre) == "v1.2.0-rc.1" && l.Releases.Count == 0 && l.Picked!.Kind == LaunchKind.Pre, "offline: the folder's pre-release");

        Require(LaunchList.IsRelease("v1.0.0") && LaunchList.IsRelease("2.0.14") && LaunchList.IsRelease("v2.2.0-rc.1")
                && !LaunchList.IsRelease("pre-1.1.0 6353e9b") && !LaunchList.IsRelease("dev 86148ce") && !LaunchList.IsRelease("main"), "what a release's tag is");

        var lists = checks;
        Work();
        var work = checks - lists;
        Env();
        Console.WriteLine($"launcher list: {lists} checks passed; launcher work: {work} checks passed; game settings: {checks - lists - work} checks passed");
        return 0;
    }

    /// Settings' "Lower memory use" (builder/HookshotBuilder/GameEnv.cs): RX_VK_PCACHE_LOAD=0 in the game folder's
    /// hookshot_env.txt, the rest of the player's file as it was
    static void Env()
    {
        Require(!GameEnv.SkipsCache("") && !GameEnv.SkipsCache("RX_VK_NOOPT=1\n"), "no line: the cache is loaded");
        Require(GameEnv.SkipsCache("RX_VK_PCACHE_LOAD=0\n") && GameEnv.SkipsCache("﻿  RX_VK_PCACHE_LOAD=0  \r\n"), "the line, as the game reads it (a BOM, spaces, CRLF)");
        Require(!GameEnv.SkipsCache("# RX_VK_PCACHE_LOAD=0\n") && !GameEnv.SkipsCache("RX_VK_PCACHE_LOAD=1\n") && !GameEnv.SkipsCache("XRX_VK_PCACHE_LOAD=0\n"),
                "a note, another value or another name is not it");
        Require(!GameEnv.SkipsCache("RX_VK_PCACHE_LOAD=0\nRX_VK_PCACHE_LOAD=1\n") && GameEnv.SkipsCache("RX_VK_PCACHE_LOAD=1\nRX_VK_PCACHE_LOAD=00\n"),
                "the last line wins, as the game sets them in order; 00 is atoi's 0");
        // (switched on and off: the player's other lines, notes and line ends kept; the switch's line once, at the end)
        var mine = "# my switches\r\nRX_VK_NOOPT=1\r\n";
        var on = GameEnv.WithSkip(mine, true);
        Require(on == "# my switches\r\nRX_VK_NOOPT=1\r\nRX_VK_PCACHE_LOAD=0\r\n" && GameEnv.SkipsCache(on), "on: its line added, CRLF kept: " + on);
        Require(GameEnv.WithSkip(on, true) == on, "on twice: one line");
        Require(GameEnv.WithSkip(on, false) == mine, "off again: the file as it was");
        Require(GameEnv.WithSkip("RX_VK_PCACHE_LOAD=1\nHOS_X=2\nRX_VK_PCACHE_LOAD=0", false) == "HOS_X=2\n", "off: every line that sets it goes");
        Require(GameEnv.WithSkip("", true) == "RX_VK_PCACHE_LOAD=0\n" && GameEnv.WithSkip("RX_VK_PCACHE_LOAD=0\n", false) == "", "a file of its own: made, and empty again");
        // (on the disk: written beside the game, removed when nothing is left, the cache file never touched)
        var folder = Directory.CreateTempSubdirectory("hookshot env ü ");
        try
        {
            File.WriteAllText(Path.Combine(folder.FullName, GameEnv.CacheFile), "cache");
            Require(!GameEnv.SkipsCache(folder) && GameEnv.CacheBytes(folder) == 5, "no file: off; the cache's size");
            GameEnv.SetSkip(folder, true);
            Require(GameEnv.SkipsCache(folder) && File.ReadAllText(Path.Combine(folder.FullName, GameEnv.FileName)) == "RX_VK_PCACHE_LOAD=0\n", "on: written");
            GameEnv.SetSkip(folder, false);
            Require(!File.Exists(Path.Combine(folder.FullName, GameEnv.FileName)) && File.Exists(Path.Combine(folder.FullName, GameEnv.CacheFile)),
                    "off: the file it made is gone, the cache is still there");
            Require(GameEnv.CacheBytes(new DirectoryInfo(Path.Combine(folder.FullName, "none"))) == -1, "no cache yet");
        }
        finally { folder.Delete(recursive: true); }
    }

    /// What the launcher says while it brings a version (builder/HookshotBuilder/LaunchWork.cs), from the lines of the hidden
    /// programs that do it: the setup's engine mode (builder/setup/setup.c), then that version's make_game.py
    static void Work()
    {
        static void Feed(LaunchWork w, params string[] lines) { foreach (var l in lines) w.Line(l); }

        // ---- a version whose builder is downloaded first ----
        var w = new LaunchWork("v2.2.0", ahead: true, fetch: true);
        Require(w.Title == "Updating to v2.2.0 - 0%" && w.Detail == "Getting its builder", "before a line: " + w.Title + " / " + w.Detail);
        Feed(w, "@@setup Looking for the Hookshot Builder of v2.2.0...", "@@setup Downloading part 1 of 4 (310 MB)...", "@@percent 50");
        Require(w.Fraction is > 0.014 and < 0.016, $"half of the first of four parts is an eighth of the builder's share: {w.Fraction}");
        Require(w.Detail == "Getting its builder: downloading part 1 of 4 (310 MB)", "the setup's words, in the launcher's sentence: " + w.Detail);
        Feed(w, "@@percent 100", "@@setup Unpacking part 1 of 4...", "@@setup Part 2 of 4 unchanged: kept from the installed version");
        Require(w.Fraction is > 0.029 and < 0.031, $"the second part begun: {w.Fraction}");
        Feed(w, "@@percent 20");   // (a late line of the part before must not move it back)
        var before = w.Fraction;
        Feed(w, "@@setup Downloading part 1 of 4 (310 MB)...", "@@percent 0");
        Require(w.Fraction >= before, "the number never goes back");
        Feed(w, "@@installed v2.2.0");
        Require(Math.Abs(w.Fraction - 0.12) < 1e-9, $"the builder is here: its whole share, {w.Fraction}");
        Feed(w, "@@stage read", "@@stage lift", "@@progress 0.5");
        Require(Math.Abs(w.Fraction - (0.12 + 0.88 * (0.05 + 0.15 * 0.5))) < 1e-9, $"make_game.py's stages fill the rest: {w.Fraction}");
        Require(w.Detail == "Translating the game to PC code", w.Detail);
        // (under the bar: that it is a rebuild, then the step; until the compile's own time, what a build took here before)
        Require(w.Note(1800, 600) == "Rebuilding your game as v2.2.0\nTranslating the game to PC code · about 20 minutes left", w.Note(1800, 600));
        Require(w.Note(null, 600) == "Rebuilding your game as v2.2.0\nTranslating the game to PC code", "no build kept: no time guessed");
        Require(w.Note(1800, 1750) == "Rebuilding your game as v2.2.0\nTranslating the game to PC code", "past the usual time: no time guessed");
        Feed(w, "@@percent 99");
        Require(Math.Abs(w.Fraction - (0.12 + 0.88 * 0.125)) < 1e-9, "the setup's percent means nothing once the build runs");
        Feed(w, "@@stage compile", "@@plan 8 516", "@@file a.c 3 new", "@@file b.c 4 again", "@@file c.c 1 kept", "@@progress 0.25", "@@eta 190");
        Require(w.Detail == "Compiling changed files (2 of 8) · about 3 minutes left", w.Detail);
        Require(w.Note(1800, 60) == "Rebuilding your game as v2.2.0\n" + w.Detail, "the compile's own time wins: " + w.Note(1800, 60));
        Require(w.Title == $"Updating to v2.2.0 - {(int)((0.12 + 0.88 * (0.20 + 0.70 * 0.25)) * 100)}%", w.Title);
        Require(w.Bar == $"Updating... {(int)((0.12 + 0.88 * (0.20 + 0.70 * 0.25)) * 100)}%", "the bar at the menu's foot: " + w.Bar);
        Require(w.Done == null && w.Error == null, "not done, no error");
        // (the shaders' step, where the version has it: the game's own lines, passed on by make_game.py, and its plain one
        // when it left them to the first start)
        Feed(w, "@@stage finish", "@@stage shaders Preparing the shaders", "@@progress 0.5");
        Require(Math.Abs(w.Fraction - (0.12 + 0.88 * 0.96)) < 1e-9 && w.Detail == "Preparing the shaders · 50%", $"the shaders' step has its share, and its own number: {w.Fraction}, {w.Detail}");
        // (the shaders' own time, from how fast the step goes: its share of the bar is small and the step can be as long as the compile)
        Require(LaunchWork.ShaderPart(0.25, 600) == " · 25% · about 30 minutes left", LaunchWork.ShaderPart(0.25, 600));
        Require(LaunchWork.ShaderPart(0.25, 10) == " · 25%" && LaunchWork.ShaderPart(0.01, 600) == " · 1%" && LaunchWork.ShaderPart(1, 600) == " · 100%",
                "no time until it can be told, and none at the end");
        Require(w.Note(1800, 60) == "Rebuilding your game as v2.2.0\nPreparing the shaders · 50%", "the build's usual time is not the shaders': " + w.Note(1800, 60));
        Feed(w, "the shaders were not prepared now (no usable Vulkan here): the game prepares them at its first start");
        Require(w.Done == null && w.Error == null, "shaders left to the first start are not a failure");
        Feed(w, @"@@done C:\Games\Hookshot");
        Require(w.Done == @"C:\Games\Hookshot" && w.Fraction == 1, "done, and the folder it says");

        // ---- one whose builder is here: the build is the whole of it; a switch back says so ----
        w = new LaunchWork("v2.0.14", ahead: false, fetch: false);
        Require(w.Title == "Switching to v2.0.14 - 0%" && w.Detail == "Starting" && w.Bar == "Switching... 0%", w.Title + " / " + w.Detail + " / " + w.Bar);
        Feed(w, "@@stage compile", "@@progress 0.5");
        Require(Math.Abs(w.Fraction - (0.20 + 0.35)) < 1e-9, $"no share kept for a download: {w.Fraction}");
        Require(w.Detail == "Compiling changed files", "no count and no time until the tools give them: " + w.Detail);
        Feed(w, "@@eta 20");
        Require(w.Detail == "Compiling changed files · less than a minute left", w.Detail);
        Feed(w, "@@error The compiler stopped on src_4.c.");
        Require(w.Error == "The compiler stopped on src_4.c." && w.Done == null && w.StoppedTitle == "The switch to v2.0.14 stopped", "why it stopped, and what the launcher calls it");
        Require(new LaunchWork("v2.2.0", true, true).StoppedTitle == "The update to v2.2.0 stopped", "an update that stopped");
        // (the version in the folder built again with the settings now: Settings' Rebuild, or its own row)
        var again = new LaunchWork("v2.2.0", ahead: false, fetch: false, rebuild: true);
        Require(again.IsRebuild && again.Bar == "Rebuilding... 0%" && again.Title == "Rebuilding v2.2.0 - 0%", "a rebuild's bar: " + again.Bar);
        Require(again.Rebuild == "Rebuilding your game with your settings now", "a rebuild's line: " + again.Rebuild);
        Require(again.StoppedTitle == "The rebuild of v2.2.0 stopped", "a rebuild that stopped: " + again.StoppedTitle);

        // ---- tools that say what this launcher does not know (a later version's, an older one's) ----
        w = new LaunchWork("v3.0.0", ahead: true, fetch: false);
        Feed(w, "@@stage lift", "@@progress 1", "@@stage polish", "@@progress 0.5", "@@whatever 12", "plain words from a compiler", "@@progress nonsense");
        Require(Math.Abs(w.Fraction - 0.20) < 1e-9 && w.Detail == "Working", $"an unknown stage moves nothing and has plain words: {w.Fraction}, {w.Detail}");
        Feed(w, "@@stage finish");
        Require(Math.Abs(w.Fraction - 0.90) < 1e-9, $"a version with no shaders' step is at its last step here: {w.Fraction}");
        Feed(w, "@@done X");
        Require(w.Fraction == 1 && w.Done == "X", "and the build still ends");
        Require(LaunchWork.TimeLeft(100) == "about 2 minutes left" && LaunchWork.TimeLeft(60) == "about a minute left" && LaunchWork.TimeLeft(4000) == "about 1 h 7 min left", "time left, in words");
    }
}
