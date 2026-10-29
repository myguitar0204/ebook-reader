# 打包成資料夾版 exe（onedir：啟動快，不必每次解壓 PyMuPDF）
# 建置：uv run pyinstaller ebook-reader.spec  →  dist/ebook-reader/

a = Analysis(
    ["app.py"],
    datas=[("static", "static")],
    hiddenimports=["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
                   "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on"],
    excludes=["numpy", "onnxruntime"],  # PyMuPDF 的選用功能會帶進來，本程式用不到，約 60 MB
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ebook-reader", console=True)  # 主控台視窗關掉即停止伺服器
coll = COLLECT(exe, a.binaries, a.datas, name="ebook-reader")
