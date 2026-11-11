using System.Globalization;
using System.Text.RegularExpressions;

namespace HookshotBuilder;

/// What the launcher says while it brings a version (Paper: "v2 - Updating"): the lines of the programs that do it, read into
/// one number and two lines of words. Those programs are hidden and not the launcher's own: the setup, in its engine mode,
/// installs that version's builder beside the others (builder/setup/setup.c: @@setup, @@percent), and then that version's own
/// make_game.py builds the folder (@@stage, @@progress, @@plan, @@file, @@eta, @@done), the game's own shaders step last where
/// that version has one. Nothing here touches the window, the disk or a process.
///
/// A version's tools may say things this launcher does not know (a stage added later, a line worded differently): what is not
/// understood moves nothing and is kept in the details, and the number never goes back.
sealed class LaunchWork
{
    /// (how much of the whole each part is: getting the builder, when it has to be downloaded, then make_game.py's stages as
    /// the builder's own window weighs them)
    const double Fetch = 0.12;
    static readonly Dictionary<string, (double From, double Size, string Says)> Stages = new()
    {
        ["read"] = (0, 0.05, "Reading the game files kept in the folder"),
        ["lift"] = (0.05, 0.15, "Translating the game to PC code"),
        ["compile"] = (0.20, 0.70, "Compiling changed files"),
        ["finish"] = (0.90, 0.02, "Swapping in the new game"),
        // (the last step of the versions that have it, ShaderStep.cs: minutes on some GPUs. One without it, or with it switched
        // off, is done at "finish", and the number goes from there to the end)
        [ShaderStep.Id] = (0.92, 0.08, "Preparing the shaders"),
    };
    static readonly Regex PartOf = new(@"[Pp]art (\d+) of (\d+)");

    readonly string name, verb;
    readonly bool fetch;
    /// (the version in the folder built again, with the settings now: Settings' Rebuild, or its own row in Releases)
    public bool IsRebuild { get; }
    string? stage;          // (make_game.py's stage now; null while the builder is still being got)
    int part = 1, parts = 1;
    int changed = -1, compiled;
    double eta = -1;
    string says;
    // (the shaders' step: its own share of the bar is small, but on some GPUs it takes as long as the compile. Its own number and
    // a time worked out from how fast it goes are said under the bar, so a bar near its end is not taken for a stuck one)
    double shaderDone;
    DateTime shaderStarted;

    /// name: the version, as written ("v2.2.0"); ahead: it is ahead of the one the folder holds (an update), else a switch back;
    /// fetch: its builder is not on this PC and is downloaded first; rebuild: it is the version in the folder, built again
    public LaunchWork(string name, bool ahead, bool fetch, bool rebuild = false)
    {
        (this.name, this.fetch, IsRebuild) = (name, fetch, rebuild);
        verb = rebuild ? "Rebuilding" : ahead ? "Updating to" : "Switching to";
        says = fetch ? "Getting its builder" : "Starting";
    }

    public double Fraction { get; private set; }
    public DateTime Started { get; } = DateTime.Now;
    /// (under the button: "Updating to v2.2.0 - 42%")
    public string Title => $"{verb} {name} - {(int)(Fraction * 100)}%";
    /// (in the bar at the menu's foot: "Updating... 43%", "Switching... 12%")
    public string Bar => $"{verb.Split(' ')[0]}... {(int)(Fraction * 100)}%";
    /// (the line under that: "Compiling changed files (7 of 516) · about 3 minutes left")
    public string Detail
    {
        get
        {
            if (stage == ShaderStep.Id) return says + ShaderPart(shaderDone, (DateTime.Now - shaderStarted).TotalSeconds);
            if (stage != "compile") return says;
            var files = changed > 0 ? $" ({compiled} of {changed})" : "";
            return says + files + (eta >= 0 ? " · " + TimeLeft(eta) : "");
        }
    }
    /// (the first line under the bar: a version is never downloaded ready to play, its tools build the game again from the
    /// player's own files, and that is said plainly)
    public string Rebuild => IsRebuild ? "Rebuilding your game with your settings now" : $"Rebuilding your game as {name}";

    /// The two lines under the bar: what it is, then the step and the time left. Until the compile gives its own time, the time
    /// is what a build took on this PC before (typical, in seconds; null when none was kept) less the time gone (elapsed)
    public string Note(double? typical, double elapsed)
    {
        var step = Detail;
        // (the build's usual time has no shaders in it: their step has its own, ShaderPart)
        if (!(stage == "compile" && eta >= 0) && stage != ShaderStep.Id && typical is double t && t - elapsed >= 90) step += " · " + TimeLeft(t - elapsed);
        return Rebuild + "\n" + step;
    }

    /// The game folder, once make_game.py said it is done (the build succeeded whatever comes after)
    public string? Done { get; private set; }
    /// Why it stopped, as the program that stopped said it
    public string? Error { get; private set; }

    /// What the stopped state says under the button's "Retry": the version, and the reason in one line
    public string StoppedTitle => IsRebuild ? $"The rebuild of {name} stopped"
        : $"The {(verb.StartsWith("Updating") ? "update" : "switch")} to {name} stopped";

    public void Line(string line)
    {
        if (line.StartsWith("@@error ")) Error = line[8..].Trim();
        else if (line.StartsWith("@@done "))
        {
            Done = line[7..].Trim();
            Reach(1);
        }
        else if (line.StartsWith("@@setup "))
        {
            // ("Downloading part 2 of 7 (310 MB)...", "Part 3 of 7 unchanged: kept from the installed version")
            var text = line[8..].Trim().TrimEnd('.');
            if (PartOf.Match(text) is { Success: true } m && int.TryParse(m.Groups[1].Value, out var i) && int.TryParse(m.Groups[2].Value, out var n) && n > 0)
            {
                (part, parts) = (Math.Clamp(i, 1, n), n);
                Reach(Fetch * (part - 1) / parts);
            }
            if (text.Length > 0) says = "Getting its builder: " + char.ToLowerInvariant(text[0]) + text[1..];
        }
        else if (line.StartsWith("@@percent "))
        {
            if (stage == null && int.TryParse(line[10..], out var p)) Reach(Fetch * (part - 1 + Math.Clamp(p, 0, 100) / 100.0) / parts);
        }
        else if (line.StartsWith("@@installed ")) Reach(Fetch);
        else if (line.StartsWith("@@stage "))
        {
            stage = line[8..].Trim().Split(' ')[0];
            if (stage == ShaderStep.Id) (shaderDone, shaderStarted) = (0, DateTime.Now);
            if (Stages.TryGetValue(stage, out var s))
            {
                says = s.Says;
                Reach(Whole(s.From));
            }
            else says = "Working";   // (a stage this launcher has no words for)
        }
        else if (line.StartsWith("@@progress "))
        {
            if (stage != null && Stages.TryGetValue(stage, out var s)
                && double.TryParse(line[11..], NumberStyles.Float, CultureInfo.InvariantCulture, out var f))
            {
                Reach(Whole(s.From + s.Size * Math.Clamp(f, 0, 1)));
                if (stage == ShaderStep.Id) shaderDone = Math.Max(shaderDone, Math.Clamp(f, 0, 1));
            }
        }
        else if (line.StartsWith("@@plan "))
        {
            var p = line.Split(' ');
            if (p.Length == 3 && int.TryParse(p[1], out var c)) (changed, compiled) = (c, 0);
        }
        else if (line.StartsWith("@@file "))
        {
            var p = line.Split(' ');
            if (p.Length == 4 && p[3] is "new" or "again") compiled++;
        }
        else if (line.StartsWith("@@eta "))
        {
            if (double.TryParse(line[6..], NumberStyles.Float, CultureInfo.InvariantCulture, out var seconds)) eta = seconds;
        }
    }

    /// (make_game.py's share of the whole: all of it when nothing is downloaded first)
    double Whole(double f) => fetch ? Fetch + (1 - Fetch) * f : f;
    void Reach(double f) => Fraction = Math.Max(Fraction, Math.Clamp(f, 0, 1));

    /// (the shaders' step, under the bar: " · 25% · about 30 minutes left", the time from how fast it has gone so far, once it
    /// has gone far enough to tell)
    public static string ShaderPart(double done, double seconds)
    {
        var part = $" · {(int)(done * 100)}%";
        if (done >= 0.02 && done < 1 && seconds >= 20) part += " · " + TimeLeft(seconds / done * (1 - done));
        return part;
    }

    public static string TimeLeft(double seconds)
    {
        if (seconds < 45) return "less than a minute left";
        if (seconds < 90) return "about a minute left";
        var minutes = (int)Math.Round(seconds / 60);
        return minutes >= 60 ? $"about {minutes / 60} h {minutes % 60} min left" : $"about {minutes} minutes left";
    }
}
