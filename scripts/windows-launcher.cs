using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

[assembly: AssemblyTitle("Apex Highlight Clipper")]
[assembly: AssemblyProduct("Apex Highlight Clipper")]

internal static class Launcher
{
    // Windows command-line quoting also preserves trailing slashes and embedded quotes.
    private static string Quote(string value)
    {
        var text = new StringBuilder("\"");
        int slashes = 0;
        foreach (char ch in value)
        {
            if (ch == '\\') { slashes++; continue; }
            text.Append('\\', ch == '"' ? slashes * 2 + 1 : slashes);
            text.Append(ch);
            slashes = 0;
        }
        return text.Append('\\', slashes * 2).Append('"').ToString();
    }

    [STAThread]
    private static int Main(string[] args)
    {
        Application.EnableVisualStyles();
        string root = AppDomain.CurrentDomain.BaseDirectory;
        // Old updater scripts restart app\*.exe. The installer temporarily supplies this same
        // launcher there; the desktop process removes that compatibility entry after it exits.
        if (new DirectoryInfo(root).Name.Equals("app", StringComparison.OrdinalIgnoreCase))
        {
            string parent = Directory.GetParent(root.TrimEnd(Path.DirectorySeparatorChar)).FullName;
            if (File.Exists(Path.Combine(parent, "resources", "app_worker.py"))) root = parent;
        }
        string content = Path.Combine(root, "resources");
        string executable = Path.Combine(content, "desktop", "Apex Highlight Clipper.exe");
        string setup = Path.Combine(content, "scripts", "setup-ffmpeg.ps1");
        try
        {
            if (!File.Exists(executable) || !File.Exists(setup))
                throw new IOException("请先完整解压软件，并将启动 EXE 与 resources 程序文件夹一起保留。");
            string powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                "WindowsPowerShell", "v1.0", "powershell.exe");
            var start = new ProcessStartInfo(powershell,
                "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File " + Quote(setup))
            {
                WorkingDirectory = content, UseShellExecute = false, CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
                RedirectStandardOutput = true, RedirectStandardError = true,
                StandardErrorEncoding = Encoding.Default
            };
            // PowerShell 7 terminals can export a module path incompatible with Windows PowerShell.
            // The bootstrap only needs the inbox Windows modules, independent of the parent shell.
            start.EnvironmentVariables["PSModulePath"] = Path.Combine(Path.GetDirectoryName(powershell), "Modules");
            using (var process = new Process { StartInfo = start })
            using (var progress = new Form
            {
                Text = "Apex Highlight Clipper", ClientSize = new Size(340, 90),
                StartPosition = FormStartPosition.CenterScreen, FormBorderStyle = FormBorderStyle.FixedDialog,
                MaximizeBox = false, MinimizeBox = false,
                Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath)
            })
            {
                progress.Controls.Add(new Label { Text = "正在准备视频工具，请稍候…", AutoSize = true, Left = 20, Top = 16 });
                progress.Controls.Add(new ProgressBar { Style = ProgressBarStyle.Marquee, Left = 20, Top = 49, Width = 300 });
                var error = new StringBuilder();
                process.OutputDataReceived += (sender, e) => { /* Drain progress output without a console window. */ };
                process.ErrorDataReceived += (sender, e) =>
                {
                    if (e.Data != null) lock (error) { error.AppendLine(e.Data); if (error.Length > 4000) error.Remove(0, error.Length - 4000); }
                };
                process.Start();
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                var elapsed = Stopwatch.StartNew();
                while (!process.WaitForExit(50))
                {
                    if (elapsed.ElapsedMilliseconds > 1000 && !progress.Visible) progress.Show();
                    Application.DoEvents();
                    if (progress.IsDisposed) { if (!process.HasExited) process.Kill(); process.WaitForExit(); return 2; }
                }
                process.WaitForExit(); // Finish the asynchronous error-output callbacks.
                progress.Hide();
                if (process.ExitCode != 0)
                    throw new IOException("视频工具准备失败，请检查网络后重新启动。\n\n" + error.ToString());
            }
            var forwarded = new StringBuilder();
            foreach (string arg in args) { if (forwarded.Length > 0) forwarded.Append(' '); forwarded.Append(Quote(arg)); }
            Process.Start(new ProcessStartInfo(executable, forwarded.ToString())
            { WorkingDirectory = content, UseShellExecute = false });
            return 0;
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "Apex 启动失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
