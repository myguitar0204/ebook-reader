"""打包可攜版（不產生 exe）：官方 embeddable Python + 依賴套件 + 程式碼，以 start.bat 啟動。

自己打包的 exe（PyInstaller）常被防毒誤判；這個版本執行的是 python.org 官方、有數位簽章的 python.exe。
用法：uv run python build_portable.py   → dist/ebook-reader-portable/ 與 dist/ebook-reader-portable.zip
"""

import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

PY_VERSION = "3.12.10"  # 3.12 最後一個提供 Windows 安裝檔的版本；依賴的二進位套件依此版本挑選
PY_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
# PyMuPDF 選用功能帶進來的（約 60 MB），閱讀器用不到；與 ebook-reader.spec 的 excludes 一致
EXCLUDE = ["numpy", "onnxruntime", "flatbuffers", "protobuf", "packaging"]

ROOT = Path(__file__).parent
OUT = ROOT / "dist" / "ebook-reader-portable"
CACHE = ROOT / "build" / f"python-{PY_VERSION}-embed-amd64.zip"

START_BAT = """@echo off
cd /d "%~dp0"
set EBOOK_PORTABLE=1
set PYTHONUTF8=1
python\\python.exe app.py %*
pause
"""

def run(*cmd):
    print(">", " ".join(map(str, cmd)))
    subprocess.run(cmd, check=True)


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    py = OUT / "python"
    py.mkdir(parents=True)

    # 1. 官方 embeddable Python（下載一次後快取在 build/）
    if not CACHE.exists():
        CACHE.parent.mkdir(exist_ok=True)
        print("下載", PY_URL)
        urllib.request.urlretrieve(PY_URL, CACHE)
    with zipfile.ZipFile(CACHE) as z:
        z.extractall(py)
    # embeddable 版只看 ._pth 決定 sys.path，要把 site-packages 加進去
    pth = next(py.glob("python3*._pth"))
    # 不加 import site，否則會帶入對方電腦的使用者 site-packages（%APPDATA%\Python），套件版本可能互相干擾
    pth.write_text(f"{pth.stem}.zip\n.\nLib\\site-packages\n", encoding="utf-8")

    # 2. 依 uv.lock 的版本安裝依賴（不含 dev 與 EXCLUDE），指定 Windows x64 / 3.12 的 wheel
    req = ROOT / "build" / "requirements-portable.txt"
    run("uv", "export", "--no-dev", "--no-hashes", "--format", "requirements-txt", "--quiet",
        *[a for p in EXCLUDE for a in ("--no-emit-package", p)], "-o", req)
    run("uv", "pip", "install", "--no-deps", "--only-binary", ":all:", "-r", req,
        "--target", py / "Lib" / "site-packages",
        "--python-version", "3.12", "--python-platform", "x86_64-pc-windows-msvc")

    # 3. 程式碼與啟動檔（.bat 只用 ASCII，避免 cp950 解析問題）
    shutil.copy2(ROOT / "app.py", OUT)
    shutil.copytree(ROOT / "static", OUT / "static")
    (OUT / "start.bat").write_text(START_BAT.replace("\n", "\r\n"), encoding="ascii", newline="")
    shutil.copy2(ROOT / "使用手冊.html", OUT)  # 雙擊用瀏覽器開啟，離線可看

    # 4. 壓縮成 zip 方便傳給別人
    archive = shutil.make_archive(str(OUT), "zip", OUT.parent, OUT.name)
    size = Path(archive).stat().st_size / 1024 / 1024
    print(f"完成：{OUT}\n壓縮檔：{archive}（{size:.1f} MB）")


if __name__ == "__main__":
    main()
