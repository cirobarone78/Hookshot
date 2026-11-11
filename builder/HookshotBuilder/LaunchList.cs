using System.Text.RegularExpressions;

namespace HookshotBuilder;

/// A release as GitHub lists it: its tag, whether it is a pre-release, and whether it holds the builder to download (the setup
/// and its list, or the whole zip). One without can only be played or built here when it is already on this PC. SetupList: it
/// holds the setup and its list, what the setup's engine mode installs from (one with only the zip is brought by the builder's
/// own update instead, LaunchList.ByEngine)
sealed record ReleaseInfo(string Tag, bool Pre, bool Download, bool SetupList = false);

enum LaunchKind { Release, Pre }

/// One version in the launcher's Releases tab: a release or a pre-release, played in the launch folder, which holds one of them
/// at a time and is built again as another first
sealed class LaunchChoice
{
    public LaunchKind Kind { get; init; }
    public string Label { get; init; } = "";   // (in the list: "v2.1.0 - Latest", "v2.2.0-rc.1")
    public string Title { get; init; } = "";   // (under Play: "v2.2.0-rc.1 - Pre-release")
    public string? Tag { get; init; }          // (its tag, v1.0.0)
    public bool Here { get; init; }            // (the release the launch folder holds)
    public bool Reach { get; init; }           // (not here, and a press brings it: its builder is installed, or its release has one)
    public bool Rebuilds { get; init; } = true;   // (the launch folder keeps its game files: it can be built as another release)
    public bool Picked { get; set; }
    public bool Busy { get; set; }             // (the version being brought now: its mark turns)
    public string Key => "release:" + Tag;

    // (the row, MainWindow.xaml's VersionRow: the tick on what Play plays, the arrow on one a press brings, dim that nothing can)
    public bool Ticked => Picked && Here && !Busy;   // (the one being rebuilt shows the turning mark alone)
    public bool Arrow => !Here && Reach && !Busy;
    public bool Dim => !Here && !Reach && !Picked;
    public string? Tip => Here ? (Rebuilds ? "Your game. Press it to rebuild it with your settings now" : null) : Reach ? "Not on this PC yet"
        : !Rebuilds ? "This game folder was built before it kept its game files: build it again from the Build tab"
        : "Not on this PC, and its release has no builder to download";
}

/// The Releases tab's lists (MainWindow.xaml, Paper's "Releases Menu"): what a version is comes first, whether it is on this PC
/// is the mark at its right. Nothing here touches the window, the disk or the network
static class LaunchList
{
    /// (the five newest releases stay in sight, as Paper's "Releases Menu" lists them; the rest fold into one row when that
    /// hides two or more)
    const int Newest = 5;

    public sealed record Lists(List<LaunchChoice> All, List<LaunchChoice> Releases, int Older, bool Folded,
                               List<LaunchChoice> Pre, LaunchChoice? Picked);

    /// github: GitHub's releases; latest: its latest release's tag; built: the release the launch folder holds; builders: the
    /// releases whose builder is installed here; rebuilds: the folder keeps its game files (it can be built as another release);
    /// pick: the key of the version picked; open: the older releases are unfolded.
    /// Older: how many releases the fold row stands for (0: no fold row); Folded: they are out of the list now
    public static Lists Make(IReadOnlyList<ReleaseInfo> github, string? latest, string? built, ICollection<string> builders,
                             bool rebuilds, string? pick, bool open)
    {
        var known = new Dictionary<string, ReleaseInfo>(StringComparer.OrdinalIgnoreCase);
        foreach (var r in github) known[VersionName(r.Tag)] = r;
        // (on this PC and no longer, or not yet, among GitHub's: the folder's own release, an installed builder's)
        foreach (var t in built != null ? builders.Append(built) : builders)
            if (IsRelease(t)) known.TryAdd(VersionName(t), new ReleaseInfo(t, IsPre(t), false));

        var all = new List<LaunchChoice>();
        foreach (var r in known.Values.OrderByDescending(r => r.Tag, Order))
        {
            var here = SameTag(r.Tag, built);
            var name = VersionName(r.Tag);
            var newest = SameTag(r.Tag, latest);
            all.Add(new LaunchChoice
            {
                Kind = r.Pre ? LaunchKind.Pre : LaunchKind.Release,
                Tag = r.Tag,
                Label = newest ? name + " - Latest" : name,
                Title = newest ? name + " - Latest" : r.Pre ? name + " - Pre-release" : name,
                Here = here,
                Reach = !here && rebuilds && (r.Download || builders.Any(b => SameTag(b, r.Tag))),
                Rebuilds = rebuilds,
            });
        }

        // (a key holds a tag: it does not mind capitals)
        var picked = all.FirstOrDefault(c => string.Equals(c.Key, pick, StringComparison.OrdinalIgnoreCase))
                     ?? all.FirstOrDefault(c => SameTag(c.Tag, built))
                     ?? all.FirstOrDefault(c => c.Kind == LaunchKind.Release)
                     ?? all.FirstOrDefault();
        if (picked != null) picked.Picked = true;

        var releases = all.Where(c => c.Kind == LaunchKind.Release).ToList();
        var stay = releases.Where((c, i) => i < Newest || c.Here || c.Picked).ToList();
        var older = releases.Count - stay.Count;
        if (older < 2) (stay, older) = (releases, 0);   // (a row that says "1 older release" takes the place of the release itself)
        // (the pre-releases among the releases in sight, in version order: every one newer than the oldest release in sight, and
        // all of them once the older releases are unfolded. Hookshot's release candidates come before their release
        // (v2.1.0-rc.3, then v2.1.0), so one that is out is still listed, below its release. The one the folder holds, or the
        // one picked, always is)
        var floor = open || older == 0 ? null : stay.Where(c => !c.Here && !c.Picked).LastOrDefault()?.Tag ?? stay.LastOrDefault()?.Tag;
        var pre = all.Where(c => c.Kind == LaunchKind.Pre && (c.Here || c.Picked || floor == null || Newer(c.Tag!, floor))).ToList();
        return new Lists(all, open ? releases : stay, older, older > 0 && !open, pre, picked);
    }

    /// How a release is brought: by the setup's engine mode beside the builder in use (true), or by the builder's own update,
    /// Updater.UpdateFolder (false). The engine mode installs only from a release's setup list: one with only the zip, or a setup
    /// from before the engine mode, takes the builder's own update. A builder installed here needs nothing downloaded
    public static bool ByEngine(ReleaseInfo? release, bool builderHere, bool engineSetup) =>
        builderHere || (engineSetup && release?.SetupList != false);

    /// (v1.0.0, 1.0.0, v2.2.0-rc.1: a release's tag, not a branch's or a build's name such as "nightly")
    public static bool IsRelease(string tag) => Regex.IsMatch(tag, @"^v?\d+\.\d+\.\d+(-[0-9A-Za-z][0-9A-Za-z.-]*)?$");
    /// (a tag GitHub has not told us about: the part after the numbers says it is a pre-release, as Semantic Versioning has it)
    public static bool IsPre(string tag) => tag.Contains('-');
    public static bool SameTag(string? a, string? b) =>
        a != null && b != null && string.Equals(a.TrimStart('v', 'V'), b.TrimStart('v', 'V'), StringComparison.OrdinalIgnoreCase);
    public static Version ReleaseOrder(string tag) =>
        Version.TryParse(tag.TrimStart('v', 'V').Split('-')[0], out var v) ? v : new Version(0, 0);
    /// (as the launcher writes a release: v1.0.0)
    public static string VersionName(string tag) => "v" + tag.TrimStart('v', 'V');
    /// (a is ahead of b: a later release, the release itself after its own pre-releases, or a later pre-release of it: rc.2 after rc.1)
    public static bool Newer(string a, string b) => Compare(a, b) > 0;

    /// Releases in order, as Semantic Versioning orders them: by their numbers; then a release after its pre-releases; then the
    /// pre-releases by their parts, a number by its value (rc.10 after rc.9), a word by its letters, and more parts after fewer
    public static readonly IComparer<string> Order = Comparer<string>.Create(Compare);

    public static int Compare(string a, string b)
    {
        var byNumbers = ReleaseOrder(a).CompareTo(ReleaseOrder(b));
        if (byNumbers != 0) return byNumbers;
        var pa = PrePart(a);
        var pb = PrePart(b);
        if (pa == null || pb == null) return pa == null ? (pb == null ? 0 : 1) : -1;
        var x = pa.Split('.');
        var y = pb.Split('.');
        for (var i = 0; i < Math.Min(x.Length, y.Length); i++)
        {
            var xn = int.TryParse(x[i], out var xi);
            var yn = int.TryParse(y[i], out var yi);
            var c = xn && yn ? xi.CompareTo(yi) : xn ? -1 : yn ? 1 : string.CompareOrdinal(x[i].ToLowerInvariant(), y[i].ToLowerInvariant());
            if (c != 0) return c;
        }
        return x.Length.CompareTo(y.Length);
    }

    static string? PrePart(string tag)
    {
        var dash = tag.IndexOf('-');
        return dash >= 0 && dash + 1 < tag.Length ? tag[(dash + 1)..] : null;
    }
}
