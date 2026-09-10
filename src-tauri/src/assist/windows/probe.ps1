$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
try {
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Diagnostics;
public static class PlumdeckObservation {
    [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr window);
    [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr OpenProcess(uint access, bool inherit, uint pid);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    [DllImport("ntdll.dll")] static extern int NtQueryInformationProcess(IntPtr process, int kind, IntPtr data, uint size, out uint needed);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool DuplicateHandle(IntPtr source, IntPtr handle, IntPtr target, out IntPtr copy, uint access, bool inherit, uint flags);
    [DllImport("kernel32.dll")] static extern uint GetFileType(IntPtr handle);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern uint GetFinalPathNameByHandle(IntPtr file, StringBuilder name, uint size, uint flags);
    [StructLayout(LayoutKind.Sequential)] struct HandleEntry {
        public IntPtr handle;
        public UIntPtr handleCount, pointerCount;
        public uint access, type, attributes, reserved;
    }
    public static string[] AudioPaths(uint pid) {
        IntPtr process = OpenProcess(0x440, false, pid); // query + duplicate, never write
        if (process == IntPtr.Zero) throw new InvalidOperationException("rekordbox process access was denied");
        IntPtr memory = IntPtr.Zero;
        try {
            uint size = 65536, needed;
            int status;
            while (true) {
                memory = Marshal.AllocHGlobal((int)size);
                status = NtQueryInformationProcess(process, 51, memory, size, out needed);
                if (status >= 0) break;
                Marshal.FreeHGlobal(memory); memory = IntPtr.Zero;
                if (status != unchecked((int)0xC0000004) || size >= 16*1024*1024)
                    throw new InvalidOperationException("Cannot enumerate rekordbox file handles");
                size = Math.Max(size*2, needed);
            }
            long count = IntPtr.Size == 8 ? Marshal.ReadInt64(memory) : Marshal.ReadInt32(memory);
            int stride = Marshal.SizeOf(typeof(HandleEntry));
            count = Math.Min(count, ((long)size-2*IntPtr.Size)/stride);
            var paths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var watch = Stopwatch.StartNew();
            for (int i=0; i<count && i<16384 && paths.Count<256 && watch.ElapsedMilliseconds<1000; i++) {
                var entry = (HandleEntry)Marshal.PtrToStructure(IntPtr.Add(memory, 2*IntPtr.Size+i*stride), typeof(HandleEntry));
                IntPtr copy;
                if (!DuplicateHandle(process, entry.handle, new IntPtr(-1), out copy, 0, false, 2)) continue;
                try {
                    if (GetFileType(copy) != 1) continue;
                    var name = new StringBuilder(32768);
                    uint n = GetFinalPathNameByHandle(copy, name, (uint)name.Capacity, 0);
                    if (n==0 || n>=name.Capacity) continue;
                    string path = name.ToString();
                    if (path.StartsWith(@"\\?\UNC\")) path = @"\\"+path.Substring(8);
                    else if (path.StartsWith(@"\\?\")) path=path.Substring(4);
                    string ext = System.IO.Path.GetExtension(path).ToLowerInvariant();
                    if (Array.IndexOf(new[]{".mp3",".m4a",".aac",".wav",".wave",".aif",".aiff",".aifc",".flac",".ogg",".oga",".alac",".mp4"},ext)>=0) paths.Add(path);
                } finally { CloseHandle(copy); }
            }
            var result = new string[paths.Count]; paths.CopyTo(result); return result;
        } finally { if (memory!=IntPtr.Zero) Marshal.FreeHGlobal(memory); CloseHandle(process); }
    }
}
'@
$process = Get-Process -Name rekordbox -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (!$process) { @{running=$false; nodes=@(); paths=@()} | ConvertTo-Json -Compress; exit }
$root = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
$scale = [Math]::Max(1, [PlumdeckObservation]::GetDpiForWindow($process.MainWindowHandle)/96.0)
$right = $root.Current.BoundingRectangle.Right / $scale
$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
$nodes = New-Object 'System.Collections.Generic.List[object]'
$queue = New-Object 'System.Collections.Generic.Queue[object]'
$queue.Enqueue(@($root,0))
$clock = [Diagnostics.Stopwatch]::StartNew()
$truncated = $false
while ($queue.Count -gt 0) {
    if ($nodes.Count -ge 1500 -or $clock.ElapsedMilliseconds -gt 1500) { $truncated=$true; break }
    $entry=$queue.Dequeue(); $element=$entry[0]; $depth=$entry[1]
    $current=$element.Current
    if (!$current.IsOffscreen) {
        $type=$current.ControlType.ProgrammaticName
        $role=switch ($type) {
            'ControlType.Text' {'AXStaticText'}
            'ControlType.Edit' {'AXTextArea'}
            'ControlType.Document' {'AXTextArea'}
            'ControlType.ComboBox' {'AXPopUpButton'}
            default {''}
        }
        $value=$current.Name
        if ($role -eq 'AXTextArea') {
            $pattern=$null
            if ($element.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$pattern)) { $value=$pattern.Current.Value }
        }
        $r=$current.BoundingRectangle
        if ($role -and $value -and !$r.IsEmpty) {
            $nodes.Add(@{role=$role;value=$value;x=$r.X/$scale;y=$r.Y/$scale;width=$r.Width/$scale;height=$r.Height/$scale})
        }
        if ($depth -lt 24) {
            $child=$walker.GetFirstChild($element); $children=0
            while ($child -and $children -lt 400 -and $queue.Count -lt 1500) {
                $queue.Enqueue(@($child,($depth+1))); $child=$walker.GetNextSibling($child); $children++
            }
            if ($child) { $truncated=$true }
        }
    }
}
$paths=@(); $pathsError=$null
try { $paths=@([PlumdeckObservation]::AudioPaths($process.Id)) } catch { $pathsError=$_.Exception.Message }
@{running=$true;appPath=$process.Path;right=$right;nodes=@($nodes.ToArray());paths=$paths;pathsError=$pathsError;truncated=$truncated} | ConvertTo-Json -Depth 6 -Compress

} catch {
    @{running=$false;error=$_.Exception.Message;nodes=@();paths=@()} | ConvertTo-Json -Depth 4 -Compress
    exit 1
}
