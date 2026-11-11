using System.IO;
using System.Text;
using System.Windows;

namespace HookshotBuilder;

public partial class App : Application
{
    // (RecompLauncher) --cli <make_game.py's options>: no window; its lines on stdout, and its result as the exit code.
    // Why it stopped is one "error <text>" line on stdout (the stream a launcher reads) and again on stderr
    protected override void OnStartup(StartupEventArgs e)
    {
        try { _ = BuilderHome.Base; }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or ArgumentException)
        {
            var why = "The Builder home could not be opened. " + error.Message;
            if (e.Args.Length > 0 && e.Args[0] == "--cli")
            {
                using var output = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { AutoFlush = true };
                output.WriteLine("error " + why);
                Console.Error.WriteLine("error " + why);
            }
            else MessageBox.Show(why, "Hookshot Builder", MessageBoxButton.OK, MessageBoxImage.Error);
            // StartupUri is processed after this handler; a rejected home must never construct MainWindow.
            Environment.Exit(1);
            return;
        }
        if (e.Args.Length > 0 && e.Args[0] == "--cli")
        {
            Environment.Exit(Cli(e.Args.Skip(1).ToList()));
            return;
        }
        // (a mistake of the window's own, in a handler that runs on its own (async void): written down and said, and the window
        // stays, rather than closing with no word and the hidden programs of a build still running)
        DispatcherUnhandledException += (_, x) =>
        {
            var file = WriteError(x.Exception);
            x.Handled = true;
            if (Environment.GetEnvironmentVariable("HOOKSHOT_UI_SHOT") is { Length: > 0 }) return;   // (development: no box, off the screen)
            MessageBox.Show($"Something went wrong in Hookshot Builder: {x.Exception.Message}" +
                            (file != null ? $"\n\nThe details are in {file}." : ""), "Hookshot", MessageBoxButton.OK, MessageBoxImage.Error);
        };
        TaskScheduler.UnobservedTaskException += (_, x) =>
        {
            WriteError(x.Exception);
            x.SetObserved();
        };
        AppDomain.CurrentDomain.UnhandledException += (_, x) => { if (x.ExceptionObject is Exception ex) WriteError(ex); };   // (only written: it cannot be stopped)
        base.OnStartup(e);
    }

    /// (launcher-error.txt beside the versions, appended; started again once it is over 256 KB). The file, or null when it could
    /// not be written
    static string? WriteError(Exception e)
    {
        try
        {
            var file = Path.Combine(Storage.Base, "launcher-error.txt");
            Directory.CreateDirectory(Storage.Base);
            if (File.Exists(file) && new FileInfo(file).Length > 256 << 10) File.Delete(file);
            File.AppendAllText(file, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} Hookshot Builder {Tools.Find()?.Version ?? "(source)"}\n{e}\n\n");
            return file;
        }
        catch (Exception) { return null; }
    }

    static int Cli(List<string> args)
    {
        using var stdout = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { AutoFlush = true };
        var tools = Tools.Find();
        if (tools == null)
        {
            const string missing = "error The build tools were not found next to this program.";
            stdout.WriteLine(missing);
            Console.Error.WriteLine(missing);
            return 1;
        }
        var done = new ManualResetEventSlim();
        string? failure = null, said = null;   // (said: make_game's own "error" line in --prepare mode, already passed on to stdout)
        var runner = new Runner(tools, args);
        runner.Line += line =>
        {
            if (line.StartsWith("error ")) said = line[6..];
            lock (stdout) stdout.WriteLine(line);
        };
        runner.Finished += result => { failure = result; done.Set(); };
        runner.Start();
        done.Wait();
        if (failure == null) return 0;
        var reason = failure == "cancelled" ? failure : said ?? failure;
        if (said == null) lock (stdout) stdout.WriteLine("error " + reason);
        Console.Error.WriteLine("error " + reason);
        return 1;
    }
}
