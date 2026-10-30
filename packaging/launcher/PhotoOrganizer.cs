// The program Windows starts for Photo Organizer (the Start menu shortcut and the Microsoft Store
// package both point at it). It does one job: run the bundled Python on the app, with no console
// window, and say so plainly if that fails.
//
// Compiled by packaging/build_payload.py with the C# compiler that ships inside Windows
// (csc.exe, .NET Framework 4), so the result is a ~10 KB program that needs nothing installed.
// That compiler speaks C# 5, so no newer syntax here.

using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("Photo Organizer")]
[assembly: AssemblyProduct("Photo Organizer")]
[assembly: AssemblyDescription("Find duplicates, blurry shots and clutter in your phone photos")]
[assembly: AssemblyVersion("0.0.0.0")]

static class Launcher
{
    // The app starts a web server and opens a window onto it; if the process dies this quickly,
    // the person never saw a window, so tell them something happened.
    const int EarlyExitSeconds = 20;

    [STAThread]
    static int Main(string[] args)
    {
        string home = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(home, "runtime", "pythonw.exe");
        if (!File.Exists(python))
        {
            return Fail("Photo Organizer's files are incomplete (runtime\\pythonw.exe is missing). Please reinstall it.");
        }

        ProcessStartInfo start = new ProcessStartInfo(python, "-m app.gui_launcher");
        start.WorkingDirectory = home;
        start.UseShellExecute = false;
        start.CreateNoWindow = true;
        start.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";
        start.EnvironmentVariables["PYTHONUTF8"] = "1";

        DateTime began = DateTime.UtcNow;
        Process child;
        try
        {
            child = Process.Start(start);
        }
        catch (Exception ex)
        {
            return Fail("Photo Organizer couldn't start: " + ex.Message);
        }

        child.WaitForExit();
        bool tooQuick = (DateTime.UtcNow - began).TotalSeconds < EarlyExitSeconds;
        if (child.ExitCode != 0 && tooQuick)
        {
            string log = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Photo Organizer", "data", "photo-organizer.log");
            return Fail("Photo Organizer stopped unexpectedly while starting.\n\nDetails, if any, are in:\n" + log);
        }
        return child.ExitCode;
    }

    static int Fail(string message)
    {
        MessageBox.Show(message, "Photo Organizer", MessageBoxButtons.OK, MessageBoxIcon.Error);
        return 1;
    }
}
