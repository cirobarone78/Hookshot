// Offscreen WPF hit testing of production resources and the actual row under a build's bar (Show details, Cancel); no Builder
// startup. The launcher's Build tab (MainWindow.xaml, BuildLinks) holds them as two words side by side: a press on either word
// is that word's, and a press on the blank beside or between them is neither's (it used to toggle the log, issue: the old
// footer's Show details stretched over the whole column).
using System.IO;
using System.Globalization;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Xml.Linq;

static class Program
{
    static readonly XNamespace Presentation = "http://schemas.microsoft.com/winfx/2006/xaml/presentation";
    static readonly XNamespace Xaml = "http://schemas.microsoft.com/winfx/2006/xaml";
    // (event handlers are the window's code, which this does not compile: taken off what is instantiated)
    static readonly string[] Events = { "Click", "Checked", "Unchecked", "MouseLeftButtonDown", "Loaded", "TextChanged", "SelectionChanged" };

    static string Owner(DependencyObject? item, Button show, Button cancel)
    {
        for (; item != null; item = VisualTreeHelper.GetParent(item))
        {
            if (ReferenceEquals(item, show)) return "DetailsRow";
            if (ReferenceEquals(item, cancel)) return "BuildCancel";
        }
        return "neither-control";
    }

    static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    static void StripEvents(XElement root)
    {
        foreach (var element in root.DescendantsAndSelf())
            foreach (var name in Events)
                element.Attribute(name)?.Remove();
    }

    [STAThread]
    static int Main(string[] args)
    {
        try
        {
            Require(args.Length == 2, "expected source snapshot and output directory");
            string source = args[0], output = args[1];
            Directory.CreateDirectory(output);
            var appXml = XDocument.Load(Path.Combine(source, "App.xaml"));
            var resources = appXml.Root?.Element(Presentation + "Application.Resources")
                ?? throw new InvalidDataException("production application resources not found");
            var dictionary = new XElement(Presentation + "ResourceDictionary",
                new XAttribute(XNamespace.Xmlns + "x", Xaml.NamespaceName),
                resources.Elements().Select(value => new XElement(value)));
            var app = new Application { ShutdownMode = ShutdownMode.OnExplicitShutdown };
            app.Resources = (ResourceDictionary)XamlReader.Parse(dictionary.ToString());
            var main = XDocument.Load(Path.Combine(source, "MainWindow.xaml"));
            var linksXml = main.Descendants(Presentation + "StackPanel")
                .Single(element => (string?)element.Attribute(Xaml + "Name") == "BuildLinks");
            // (the launcher screen's own styles, SmallLink among them: the resources of the grid the row is drawn in)
            var screenResources = linksXml.Ancestors().Select(a => a.Element(a.Name + ".Resources")).FirstOrDefault(r => r != null)
                ?? throw new InvalidDataException("the row's styles were not found");
            var screen = new XElement(Presentation + "ResourceDictionary",
                new XAttribute(XNamespace.Xmlns + "x", Xaml.NamespaceName), screenResources.Elements().Select(value => new XElement(value)));
            StripEvents(screen);
            app.Resources.MergedDictionaries.Add((ResourceDictionary)XamlReader.Parse(screen.ToString()));

            var row = new XElement(linksXml);
            row.SetAttributeValue(XNamespace.Xmlns + "x", Xaml.NamespaceName);
            var knownEvents = new[] { ("DetailsRow", "Click", "DetailsClick"), ("BuildCancel", "Click", "LauncherCancelClick"),
                                      ("BuildCopy", "Click", "StoppedCopyClick") };
            foreach (var (name, attribute, handler) in knownEvents)
            {
                var element = row.Descendants().Single(value => (string?)value.Attribute(Xaml + "Name") == name);
                Require((string?)element.Attribute(attribute) == handler, "known event boundary changed: " + name + "." + attribute);
            }
            StripEvents(row);
            // (as while a build runs, Render in Launcher.cs: the row shown, Copy error log not)
            row.SetAttributeValue("Visibility", "Visible");
            row.Descendants().Single(value => (string?)value.Attribute(Xaml + "Name") == "BuildCopy").SetAttributeValue("Visibility", "Collapsed");
            File.WriteAllText(Path.Combine(output, "extracted-row.xaml"), row.ToString());

            var metrics = new List<object>();
            int defects = 0, controls = 0;
            // (the panel's column is 235 wide, as drawn in Paper; a wider one too, as a translation may make it)
            foreach (double width in new[] { 235.0, 400.0 })
            {
                var links = (StackPanel)XamlReader.Parse(row.ToString());
                var host = new Grid { Width = width, Background = Brushes.Transparent };
                host.Children.Add(links);
                var surface = new Border { Background = (Brush)app.Resources["Page"], Child = host };
                surface.Measure(new Size(width, double.PositiveInfinity));
                surface.Arrange(new Rect(0, 0, width, surface.DesiredSize.Height));
                surface.UpdateLayout();
                var show = (Button)links.FindName("DetailsRow");
                var cancel = (Button)links.FindName("BuildCancel");
                show.ApplyTemplate(); cancel.ApplyTemplate(); surface.UpdateLayout();
                var bitmap = new RenderTargetBitmap((int)Math.Ceiling(width), (int)Math.Ceiling(Math.Max(1, surface.ActualHeight)), 96, 96, PixelFormats.Pbgra32);
                bitmap.Render(surface);
                var encoder = new PngBitmapEncoder();
                encoder.Frames.Add(BitmapFrame.Create(bitmap));
                var png = "row-" + width.ToString(CultureInfo.InvariantCulture) + ".png";
                using (var stream = File.Create(Path.Combine(output, png))) encoder.Save(stream);

                var showAt = show.TranslatePoint(new Point(0, 0), host);
                var cancelAt = cancel.TranslatePoint(new Point(0, 0), host);
                var y = showAt.Y + show.ActualHeight / 2;
                var showPoint = new Point(showAt.X + show.ActualWidth / 2, y);
                var cancelPoint = new Point(cancelAt.X + cancel.ActualWidth / 2, y);
                Require(cancelAt.X > showAt.X + show.ActualWidth, "Cancel is not to the right of Show details");
                // (the blanks: before Show details, between the two words, after Cancel)
                var blanks = new List<Point> { new((cancelAt.X + showAt.X + show.ActualWidth) / 2, y) };
                if (showAt.X >= 12) blanks.Add(new Point(showAt.X - 8, y));
                if (width - (cancelAt.X + cancel.ActualWidth) >= 12) blanks.Add(new Point(cancelAt.X + cancel.ActualWidth + 8, y));
                Require(blanks.Count == 3, "authored width has no blank beside the row");
                string showOwner = Owner(VisualTreeHelper.HitTest(host, showPoint)?.VisualHit, show, cancel);
                string cancelOwner = Owner(VisualTreeHelper.HitTest(host, cancelPoint)?.VisualHit, show, cancel);
                Require(showOwner == "DetailsRow", "Show details positive control failed: " + showOwner);
                Require(cancelOwner == "BuildCancel", "Cancel positive control failed: " + cancelOwner);
                controls += 2;
                var blankOwners = blanks.Select(p => Owner(VisualTreeHelper.HitTest(host, p)?.VisualHit, show, cancel)).ToList();
                defects += blankOwners.Count(o => o != "neither-control");
                metrics.Add(new {
                    availableWidth = width, height = surface.ActualHeight, showWidth = show.ActualWidth, cancelWidth = cancel.ActualWidth,
                    showPoint = new { x = showPoint.X, y = showPoint.Y }, showOwner,
                    cancelPoint = new { x = cancelPoint.X, y = cancelPoint.Y }, cancelOwner,
                    blanks = blanks.Zip(blankOwners, (p, o) => new { x = p.X, y = p.Y, owner = o }).ToArray(), png
                });
                Console.WriteLine($"width={width}: Show details->{showOwner}, Cancel->{cancelOwner}, blanks->{string.Join(",", blankOwners)}");
            }
            var result = new {
                status = defects == 0 ? "pass" : "fail",
                negativeBlankExpectationsFailed = defects, positiveControlsPassed = controls, metrics,
                knownEventsRemoved = knownEvents.Select(value => value.Item1 + "." + value.Item2 + "=" + value.Item3).ToArray(),
                boundaries = "Only production Application.Resources, the launcher screen's resources and the exact BuildLinks row are instantiated. No actual Builder/App/MainWindow class, StartupUri, network, window Show or OS input."
            };
            File.WriteAllText(Path.Combine(output, "hitbox-result.json"), JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }));
            Console.WriteLine(JsonSerializer.Serialize(result));
            Console.WriteLine($"Builder details hitbox: {controls + 6} checks, {defects} failed ({controls} positive controls, 6 blank-space expectations).");
            return defects == 0 ? 0 : 1;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error);
            return 2;
        }
    }
}
