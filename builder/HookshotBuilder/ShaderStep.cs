using System.Text.RegularExpressions;

namespace HookshotBuilder;

/// The build's last step, the shaders' preparation (nx2/make_game.py prepare_shaders): the argument that leaves it to the game's
/// first start, and what its row says once the build is done
static class ShaderStep
{
    public const string Id = "shaders";
    public const string Later = "--no-prepare-shaders";
    /// "Compile shaders": what of the preparation runs before play (make_game.py --compile-shaders, written to the folder's
    /// hookshot_options.ini as compile_shaders=; the game's Insert menu has the same row). Later leaves all of it to the game
    public const string Compile = "--compile-shaders";
    public static readonly string[] Levels = { "all", "most", "later" };
    public const string DefaultLevel = "most";
    public static string Level(string? saved) => saved != null && Array.IndexOf(Levels, saved) >= 0 ? saved : DefaultLevel;
    // (make_game.py NOT_PREPARED: a plain line, so a builder that does not know it only shows it)
    static readonly Regex NotPrepared = new(@"^the shaders were not prepared now \((.*)\): ");

    /// make_game's arguments with the player's choice (unticked: the game prepares its shaders at its first start). level: the
    /// builder's Compile shaders, null when it was never chosen here: then not passed, and the folder keeps what the game's own menu
    /// chose (a rebuild does not undo it)
    public static List<string> Args(List<string> args, bool prepare, string? level = null)
    {
        if (!prepare && level != "later") args.Add(Later);
        if (level != null) args.AddRange(new[] { Compile, Level(level) });
        return args;
    }

    /// Whether the build's shaders row is shown: not when they are left to the game (unticked, or Compile shaders on Later)
    public static bool Shown(bool prepare, string? level) => prepare && level != "later";

    /// Why make_game left the shaders to the first start, when this line says so; else null
    public static string? Reason(string line) => NotPrepared.Match(line) is { Success: true } m ? m.Groups[1].Value : null;

    /// The line under the row of a finished build when the shaders were not prepared, or null when they were (a check mark).
    /// began: the game's @@stage shaders came; reason: make_game's not-prepared line
    public static string? Skipped(bool began, string? reason) =>
        reason != null && reason.StartsWith("\"Compile shaders\" is Later") ? "Prepared while you play (Compile shaders: Later)"
        : reason != null ? $"Left to the game's first start: {reason}"
        : began ? null
        : "Left to the game's first start";
}
