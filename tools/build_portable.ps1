<#
  Tạo bản Portable của "Dịch Truyện Tranh":
    <Out>\DichTruyenTranh.exe   trình khởi động (có icon)
    <Out>\python\               Python nhúng + PyTorch + thư viện
    <Out>\app\                  code app
    <Out>\models\               model (tải khi dùng hoặc tải sẵn bằng -Prefetch)

  Ví dụ:
    powershell -ExecutionPolicy Bypass -File tools\build_portable.ps1                 (tự nhận GPU, hỏi tải model)
    powershell -ExecutionPolicy Bypass -File tools\build_portable.ps1 -Torch cpu -Prefetch none -NoPause
    powershell -ExecutionPolicy Bypass -File tools\build_portable.ps1 -AppOnly         (chỉ cập nhật code)
#>
param(
    [ValidateSet("auto", "cpu", "cu126", "cu128")] [string]$Torch = "auto",
    [string]$Out = "",
    [ValidateSet("ask", "none", "zh", "ja", "en", "all")] [string]$Prefetch = "ask",
    [switch]$AppOnly,
    [switch]$NoPause
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest nhanh hơn nhiều khi tắt thanh tiến độ
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Src = Split-Path -Parent $PSScriptRoot
$PyVer = "3.11.9"
$Ver = ([regex]::Match((Get-Content "$Src\core\__init__.py" -Raw), 'APP_VERSION\s*=\s*"([^"]+)"')).Groups[1].Value
if (-not $Out) { $Out = Join-Path $Src "dist\DichTruyenTranh_v${Ver}_Portable" }
$Build = Join-Path $Src "build"
$Py = Join-Path $Out "python\python.exe"

function Step($msg) { Write-Host ""; Write-Host "==== $msg ====" -ForegroundColor Cyan }
function Run([string]$exe, [string[]]$argv) {
    & $exe @argv
    if ($LASTEXITCODE -ne 0) { throw "Lệnh lỗi ($LASTEXITCODE): $exe $($argv -join ' ')" }
}
function Download($url, $dest) {
    if (Test-Path $dest) { return }
    Write-Host "Tải $url"
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile "$dest.part"
    Move-Item -Force "$dest.part" $dest
}

Write-Host "Dịch Truyện Tranh v$Ver by Duy Anh – tạo bản Portable" -ForegroundColor Magenta
Write-Host "Thư mục ra: $Out"
New-Item -ItemType Directory -Force -Path $Build | Out-Null

if (-not $AppOnly) {
    # ---------- chọn bản PyTorch ----------
    if ($Torch -eq "auto") {
        $Torch = "cpu"
        $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
        if ($smi) {
            $prevEap = $ErrorActionPreference; $ErrorActionPreference = "Continue"
            $name = (& nvidia-smi --query-gpu=name --format=csv,noheader 2>$null | Select-Object -First 1)
            $cc = (& nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>$null | Select-Object -First 1)
            $ErrorActionPreference = $prevEap
            if ($name) {
                Write-Host "GPU: $name (compute $cc)"
                $Torch = "cu126"
                if ($cc -match '^(\d+)') { if ([int]$Matches[1] -ge 7) { $Torch = "cu128" } elseif ([int]$Matches[1] -lt 5) { $Torch = "cpu" } }
                elseif ($name -match 'RTX 50') { $Torch = "cu128" }
            }
        }
    }
    Write-Host "Bản PyTorch: $Torch"

    if (Test-Path $Out) {
        Step "Xoá bản cũ"
        Remove-Item -Recurse -Force $Out
    }
    New-Item -ItemType Directory -Force -Path "$Out\python", "$Out\app", "$Out\models" | Out-Null

    Step "1/5 Python $PyVer nhúng"
    $zip = Join-Path $Build "python-$PyVer-embed-amd64.zip"
    Download "https://www.python.org/ftp/python/$PyVer/python-$PyVer-embed-amd64.zip" $zip
    Expand-Archive -Force $zip "$Out\python"
    $pth = Get-ChildItem "$Out\python\python*._pth" | Select-Object -First 1
    (Get-Content $pth.FullName) -replace '^#\s*import site', 'import site' | Set-Content -Encoding ascii $pth.FullName

    Step "2/5 pip"
    $getpip = Join-Path $Build "get-pip.py"
    Download "https://bootstrap.pypa.io/get-pip.py" $getpip
    Run $Py @($getpip, "--no-warn-script-location")
    Run $Py @("-m", "pip", "install", "--no-warn-script-location", "setuptools", "wheel", "hatchling", "flit_core", "poetry-core")

    Step "3/5 PyTorch ($Torch) – file lớn, chờ vài phút"
    Run $Py @("-m", "pip", "install", "--no-warn-script-location", "--no-cache-dir", "torch", "torchvision",
              "--index-url", "https://download.pytorch.org/whl/$Torch")
    $cons = Join-Path $Build "constraints.txt"
    (& $Py -m pip freeze) | Where-Object { $_ -match '^(torch|torchvision)==' } | Set-Content -Encoding ascii $cons
    Get-Content $cons

    Step "4/5 Thư viện còn lại"
    Run $Py @("-m", "pip", "install", "--no-warn-script-location", "--no-cache-dir", "--no-build-isolation",
              "-r", "$Src\requirements.txt", "-c", $cons)
    Run $Py @("-c", "import torch, easyocr, manga_ocr, fitz, PySide6, ctranslate2, transformers; print('OK torch', torch.__version__, 'cuda', torch.version.cuda)")
}

Step "5/5 Chép app + tạo DichTruyenTranh.exe"
if (-not (Test-Path "$Out\python\python.exe")) { throw "Chưa có Python trong $Out – chạy lại không kèm -AppOnly" }
$app = Join-Path $Out "app"
New-Item -ItemType Directory -Force -Path $app | Out-Null
foreach ($f in @("main.py", "prefetch_models.py", "requirements.txt", "icon.ico", "README.md")) {
    Copy-Item -Force (Join-Path $Src $f) $app
}
foreach ($d in @("core", "ui", "fonts")) {
    if (Test-Path "$app\$d") { Remove-Item -Recurse -Force "$app\$d" }
    Copy-Item -Recurse -Force (Join-Path $Src $d) "$app\$d"
    Get-ChildItem -Recurse -Directory "$app\$d" -Filter "__pycache__" | Remove-Item -Recurse -Force
}
Set-Content -Encoding ascii "$app\version.txt" $Ver

$csc = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { $csc = "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe" }
$exe = Join-Path $Out "DichTruyenTranh.exe"
if (Test-Path $csc) {
    Run $csc @("/nologo", "/target:winexe", "/optimize+", "/win32icon:$Src\icon.ico",
               "/r:System.Windows.Forms.dll", "/out:$exe", "$Src\launcher\launcher.cs")
} else {
    Write-Warning "Không có csc.exe – tạo DichTruyenTranh.bat thay cho .exe"
    Set-Content -Encoding ascii (Join-Path $Out "DichTruyenTranh.bat") '@start "" "%~dp0python\pythonw.exe" "%~dp0app\main.py"'
}
Set-Content -Encoding ascii (Join-Path $Out "Chay_xem_loi.bat") @(
    '@echo off', 'title Dich Truyen Tranh - che do xem loi',
    '"%~dp0python\python.exe" "%~dp0app\main.py"', 'pause')
Set-Content -Encoding utf8 (Join-Path $Out "HUONG_DAN.txt") @(
    "DỊCH TRUYỆN TRANH v$Ver by Duy Anh – bản Portable",
    "",
    "1. Mở DichTruyenTranh.exe",
    "2. Kéo thả thư mục ảnh truyện hoặc file PDF vào cửa sổ, bấm BẮT ĐẦU DỊCH.",
    "3. Lần dịch đầu tiên app tự tải model (cần Internet), lưu trong thư mục models\ – mang đi máy khác vẫn dùng được.",
    "4. Bấm 'Cập nhật' ở góc trên để lấy bản mới từ GitHub.",
    "",
    "Lỗi không mở được app: chạy Chay_xem_loi.bat để xem thông báo, hoặc xem app\app_log.txt.",
    "Máy cần Microsoft Visual C++ Redistributable 2015-2022 (x64): https://aka.ms/vs/17/release/vc_redist.x64.exe",
    "",
    "https://github.com/laocuumon1982-cpu/DichManga")

# ---------- tải sẵn model ----------
if ($Prefetch -eq "ask") {
    Write-Host ""
    Write-Host "Tải sẵn model vào models\ để chạy offline?"
    Write-Host "  1 = Tiếng Trung   2 = Tiếng Nhật (~3 GB)   3 = Trung + Nhật + Anh   4 = Bỏ qua"
    $c = Read-Host "Chọn"
    $Prefetch = @{ "1" = "zh"; "2" = "ja"; "3" = "all" }[$c]
    if (-not $Prefetch) { $Prefetch = "none" }
}
if ($Prefetch -ne "none") {
    $langs = if ($Prefetch -eq "all") { @("zh", "ja", "en") } else { @($Prefetch) }
    Step "Tải model: $($langs -join ', ')"
    Run $Py (@("$app\prefetch_models.py") + $langs)
}

Write-Host ""
Write-Host "XONG! Bản portable: $Out" -ForegroundColor Green
Write-Host "Mở app: DichTruyenTranh.exe – chép CẢ THƯ MỤC sang máy khác là chạy được."
if (-not $NoPause) { Read-Host "Nhấn Enter để đóng" | Out-Null; explorer $Out }
