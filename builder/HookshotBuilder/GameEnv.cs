using System.IO;

namespace HookshotBuilder;

/// hookshot_env.txt beside the game (host/hos_main.c, load_hookshot_env): NAME=VALUE lines the game sets at every start,
/// however it is started (Play, a shortcut, bin\hookshot.exe itself). The launcher's "Lower memory use" switch (Settings) is one
/// such line, RX_VK_PCACHE_LOAD=0 (#2206): the game neither loads nor saves its pipeline cache file, mkw_vk_pipelines.bin, which
/// can reach 2.5 GB and is held by the driver for the whole session. The rest of the file is the player's and stays as it is,
/// and the cache file is never deleted: switched off again, the game takes it up where it was. Nothing here touches the window
static class GameEnv
{
    public const string FileName = "hookshot_env.txt";
    public const string CacheFile = "mkw_vk_pipelines.bin";
    const string Name = "RX_VK_PCACHE_LOAD";

    /// (the value of a line that sets Name, as the game reads it: Notepad's BOM and spaces around it, # notes and lines with no
    /// = left out, the name exact; null: the line does not set it)
    static string? ValueOf(string line)
    {
        var s = line.TrimStart('﻿').Trim(' ', '\t', '\r');
        if (s.Length == 0 || s[0] == '#') return null;
        var eq = s.IndexOf('=');
        return eq > 0 && s[..eq] == Name ? s[(eq + 1)..] : null;
    }

    /// (as the game's atoi takes a value: its leading digits, after an optional sign; none is 0)
    static bool Zero(string value)
    {
        var v = value.TrimStart(' ', '\t');
        var i = v.Length > 0 && (v[0] == '-' || v[0] == '+') ? 1 : 0;
        var digits = v[i..].TakeWhile(char.IsAsciiDigit).ToArray();
        return digits.Length == 0 || digits.All(d => d == '0');
    }

    /// The cache file is skipped by this file's text: the last line that sets the switch is the one the game keeps
    public static bool SkipsCache(string text)
    {
        string? last = null;
        foreach (var line in text.Split('\n'))
            if (ValueOf(line) is { } v) last = v;
        return last != null && Zero(last);
    }

    /// The file's text with the switch on (its line, once, at the end) or off (every line that sets it gone). Every other line,
    /// and the file's line ends, as they were
    public static string WithSkip(string text, bool skip)
    {
        var nl = text.Contains("\r\n") ? "\r\n" : "\n";
        var kept = text.Split('\n').Where(l => ValueOf(l) == null).Select(l => l.TrimEnd('\r')).ToList();
        while (kept.Count > 0 && kept[^1].Trim().Length == 0) kept.RemoveAt(kept.Count - 1);
        if (skip) kept.Add(Name + "=0");
        return kept.Count == 0 ? "" : string.Join(nl, kept) + nl;
    }

    /// The game folder's file says the cache is skipped (no file: it is not)
    public static bool SkipsCache(DirectoryInfo folder)
    {
        try { return SkipsCache(File.ReadAllText(Path.Combine(folder.FullName, FileName))); }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { return false; }
    }

    /// The switch written to the game folder's file: replaced whole (a .new beside it, then moved over), deleted when nothing is
    /// left in it. Throws what the disk said (a folder that cannot be written)
    public static void SetSkip(DirectoryInfo folder, bool skip)
    {
        var file = Path.Combine(folder.FullName, FileName);
        var text = File.Exists(file) ? File.ReadAllText(file) : "";
        var now = WithSkip(text, skip);
        if (now == text) return;
        if (now.Length == 0)
        {
            File.Delete(file);
            return;
        }
        File.WriteAllText(file + ".new", now, new System.Text.UTF8Encoding(false));
        File.Move(file + ".new", file, overwrite: true);
    }

    /// The cache file's size in bytes (-1: there is none yet: the game makes it as it plays)
    public static long CacheBytes(DirectoryInfo folder)
    {
        try
        {
            var f = new FileInfo(Path.Combine(folder.FullName, CacheFile));
            return f.Exists ? f.Length : -1;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { return -1; }
    }
}
