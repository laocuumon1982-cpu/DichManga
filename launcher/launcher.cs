// DichTruyenTranh.exe - trinh khoi dong ban portable (bien dich bang csc.exe cua .NET Framework).
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("Dich Truyen Tranh v2.0 by Duy Anh")]
[assembly: System.Reflection.AssemblyDescription("Dich truyen tranh Trung / Nhat / Anh sang tieng Viet")]
[assembly: System.Reflection.AssemblyProduct("Dich Truyen Tranh")]
[assembly: System.Reflection.AssemblyCompany("Duy Anh")]
[assembly: System.Reflection.AssemblyCopyright("Duy Anh")]
[assembly: System.Reflection.AssemblyFileVersion("2.0.0.0")]
[assembly: System.Reflection.AssemblyVersion("2.0.0.0")]

static class Launcher
{
    const string Title = "Dich Truyen Tranh";

    [STAThread]
    static void Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string pyw = Path.Combine(root, "python", "pythonw.exe");
        string main = Path.Combine(root, "app", "main.py");
        if (!File.Exists(pyw) || !File.Exists(main))
        {
            MessageBox.Show("Khong tim thay python\\pythonw.exe hoac app\\main.py.\n" +
                            "Hay giai nen DAY DU ban portable va giu nguyen cau truc thu muc.",
                            Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }
        string extra = "";
        foreach (string a in args) extra += " \"" + a.Replace("\"", "") + "\"";
        var psi = new ProcessStartInfo(pyw, "\"" + main + "\"" + extra);
        psi.WorkingDirectory = Path.Combine(root, "app");
        psi.UseShellExecute = false;
        try { Process.Start(psi); }
        catch (Exception e)
        {
            MessageBox.Show("Khong mo duoc app: " + e.Message, Title,
                            MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
