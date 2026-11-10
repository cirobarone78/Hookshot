using System.IO;
using System.Text.RegularExpressions;

namespace HookshotBuilder;

// The launcher's profiles, as builder/linux/profiles.py keeps them on Linux (the same profiles.txt): each one is a user of the
// game with saves of its own, save\<id> in the game's user folder (user in the game folder on Windows: host/hos_main.c).
//
// The game plays the profile HOOKSHOT_PROFILE=<id> names (host/nn_applet.c); without it, the default profile, the one user
// every build had before profiles, so its saves stay where they were. The list is profiles.txt in the user folder, one
// "<id> <name>" a line. An id is 32 hex digits, the save folder's name (host/nn_fs.c).
//
// A profile's saves are imported from and exported to the emulators by scripts\oot_saves.py (docs/saves.md), with its
// --hookshot naming the profile's save folder (SaveDir). Removing a profile moves its saves to save-backups\<id>-<time> in
// the user folder: nothing is deleted.
public static class Profiles
{
    public const string Default = "5a3c9e1f0b7d24680000000000000001";   // (the uid host/nn_applet.c always had)
    const string Prefix = "5a3c9e1f0b7d2468";
    const string ListName = "profiles.txt";
    public const int NameMax = 32;
    static readonly Regex Id = new("^[0-9a-f]{32}$");

    public sealed record Profile(string Id, string Name);

    /// The folder the game keeps its saves in when the launcher starts it: user in the game folder
    public static string UserDir(string folder) => Path.Combine(folder, "user");

    /// Whether the game in folder plays the launcher's profile: nx2/make_game.py writes profiles=1 into its hookshot_version.txt.
    /// A game built before profiles ignores HOOKSHOT_PROFILE and plays the default profile's saves, whichever profile is chosen,
    /// so the launcher offers none for it.
    public static bool Supported(string folder)
    {
        try { return File.ReadLines(Path.Combine(folder, "hookshot_version.txt")).Any(l => l.Trim() == "profiles=1"); }
        catch (IOException) { return false; }
        catch (UnauthorizedAccessException) { return false; }
    }

    /// The name the profile list shows: the default profile says it is, whatever it is called, so that it is clear why it
    /// cannot be removed
    public static string ShownName(Profile p) => p.Id == Default ? $"{p.Name} (default)" : p.Name;

    public static string CleanName(string? name)
    {
        var words = string.Join(" ", (name ?? "").Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
        return words.Length > NameMax ? words[..NameMax] : words;
    }

    /// The profiles, the default one first
    public static List<Profile> Load(string user)
    {
        var list = new List<Profile>();
        try
        {
            foreach (var raw in File.ReadAllLines(Path.Combine(user, ListName)))
            {
                var line = raw.Trim();
                var space = line.IndexOf(' ');
                var id = (space < 0 ? line : line[..space]).ToLowerInvariant();
                var name = space < 0 ? "" : line[(space + 1)..];
                if (Id.IsMatch(id) && id != new string('0', 32) && list.All(p => p.Id != id))
                    list.Add(new Profile(id, CleanName(name) is { Length: > 0 } n ? n : id[^4..]));
            }
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
        var first = list.FindIndex(p => p.Id == Default);
        if (first < 0) list.Insert(0, new Profile(Default, "Player"));
        else if (first > 0)
        {
            var d = list[first];
            list.RemoveAt(first);
            list.Insert(0, d);
        }
        return list;
    }

    static void Store(string user, IEnumerable<Profile> profiles)
    {
        Directory.CreateDirectory(user);
        var path = Path.Combine(user, ListName);
        var lines = new List<string> { "# Hookshot's profiles: the save folder (save/<id>) and the name the launcher shows" };
        lines.AddRange(profiles.Select(p => $"{p.Id} {p.Name}"));
        File.WriteAllText(path + ".tmp", string.Join("\n", lines) + "\n");
        File.Move(path + ".tmp", path, overwrite: true);
    }

    /// The profile Play starts the game with: the one chosen last, while it is still on the list
    public static string Chosen(string folder, string? chosen) =>
        chosen != null && Load(UserDir(folder)).Any(p => p.Id == chosen) ? chosen : Default;

    /// A new profile, with no saves yet: the game starts it at an empty file select. Returns its id.
    public static string Add(string user, string? name)
    {
        var clean = CleanName(name);
        if (clean.Length == 0) throw new ArgumentException("Give the profile a name.");
        var list = Load(user);
        if (list.Any(p => string.Equals(p.Name, clean, StringComparison.OrdinalIgnoreCase)))
            throw new ArgumentException($"There is a profile called \"{clean}\" already.");
        var taken = new HashSet<string>(list.Select(p => p.Id));
        try
        {
            foreach (var d in Directory.EnumerateDirectories(Path.Combine(user, "save")))   // (a removed profile's folder is not reused)
                taken.Add(Path.GetFileName(d).ToLowerInvariant());
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
        var n = 2L;
        while (taken.Contains($"{Prefix}{n:x16}")) n++;
        var id = $"{Prefix}{n:x16}";
        list.Add(new Profile(id, clean));
        Store(user, list);
        return id;
    }

    public static void Rename(string user, string id, string? name)
    {
        var clean = CleanName(name);
        if (clean.Length == 0) throw new ArgumentException("Give the profile a name.");
        var list = Load(user);
        if (list.Any(p => p.Id != id && string.Equals(p.Name, clean, StringComparison.OrdinalIgnoreCase)))
            throw new ArgumentException($"There is a profile called \"{clean}\" already.");
        Store(user, list.Select(p => p.Id == id ? p with { Name = clean } : p));
    }

    /// The profile's saves: save\<id>, as host/nn_fs.c names it
    public static string SaveDir(string user, string id) => Path.Combine(user, "save", id);

    /// The folder "Open save folder" shows: the profile's saves, or the nearest folder above them that is there. None is
    /// made: an empty save folder would read to the game as a save that exists.
    public static string? FolderToShow(string user, string id) =>
        new[] { SaveDir(user, id), Path.Combine(user, "save"), user }.FirstOrDefault(Directory.Exists);

    /// Moves the profile's save folder to save-backups; returns where, or null when there were no saves
    static string? Backup(string user, string id)
    {
        var saves = SaveDir(user, id);
        if (!Directory.Exists(saves)) return null;
        if (!Directory.EnumerateFileSystemEntries(saves).Any())
        {
            Directory.Delete(saves);
            return null;
        }
        var root = Path.Combine(user, "save-backups");
        Directory.CreateDirectory(root);
        var stamp = DateTime.Now.ToString("yyyy-MM-dd_HH-mm-ss");
        var dest = Path.Combine(root, $"{id}-{stamp}");
        for (var k = 2; Directory.Exists(dest) || File.Exists(dest); k++) dest = Path.Combine(root, $"{id}-{stamp}-{k}");
        Directory.Move(saves, dest);
        return dest;
    }

    /// Takes the profile off the list; its saves go to save-backups. Returns where they went, or null.
    public static string? Remove(string user, string id)
    {
        if (id == Default)
            throw new ArgumentException("The default profile cannot be removed: the game plays it when it is started without the launcher.");
        var moved = Backup(user, id);
        Store(user, Load(user).Where(p => p.Id != id));
        return moved;
    }
}
