"""本機電子書閱讀器：掃描資料夾 / 上傳書籍，提供書庫 API 與閱讀頁面。"""

import argparse
import os
import posixpath
import sqlite3
import sys
import time
import webbrowser
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from urllib.parse import unquote

import pymupdf
import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 打包成 exe 時：網頁在解壓出的 bundle 內，資料與上傳的書放在 exe 旁邊
FROZEN = getattr(sys, "frozen", False)
BASE = Path(sys.executable).parent if FROZEN else Path(__file__).parent
STATIC = Path(sys._MEIPASS) / "static" if FROZEN else BASE / "static"
DATA = BASE / "data"
COVERS = DATA / "covers"
UPLOADS = BASE / "books"
DB_PATH = DATA / "library.db"
PORTABLE = FROZEN or os.environ.get("EBOOK_PORTABLE") == "1"  # 可攜版（embeddable Python）由 start.bat 設定
DEFAULT_FOLDER = None if PORTABLE else r"D:\091\電子書"  # 打包版給別人用，由對方自行設定資料夾

# 副檔名 → 閱讀格式（kepub 是 Kobo 版 epub，可直接用 epub 方式開）
FORMATS = {".epub": "epub", ".kepub": "epub", ".pdf": "pdf", ".txt": "txt"}
TXT_ENCODINGS = ("utf-8-sig", "cp950", "gb18030", "utf-16")

NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS folders (path TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    title TEXT,
    author TEXT,
    fmt TEXT NOT NULL,
    size INTEGER,
    added_at REAL,
    last_read REAL,
    position TEXT,
    progress REAL DEFAULT 0,
    cover TEXT,
    hidden INTEGER DEFAULT 0,
    missing INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tags (
    book_id INTEGER NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (book_id, tag)
);
"""


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DATA.mkdir(exist_ok=True)
    COVERS.mkdir(exist_ok=True)
    UPLOADS.mkdir(exist_ok=True)
    with db() as conn:
        conn.executescript(SCHEMA)
        if DEFAULT_FOLDER and conn.execute("SELECT COUNT(*) FROM folders").fetchone()[0] == 0:
            conn.execute("INSERT INTO folders VALUES (?)", (DEFAULT_FOLDER,))


# ---------- 中繼資料與封面 ----------

def epub_meta(path: Path) -> tuple[str, str, bytes | None, str]:
    """回傳 (書名, 作者, 封面位元組, 封面副檔名)。"""
    with zipfile.ZipFile(path) as z:
        container = ET.fromstring(z.read("META-INF/container.xml"))
        opf_path = container.find(".//c:rootfile", NS).get("full-path")
        opf = ET.fromstring(z.read(opf_path))
        title = (opf.findtext(".//dc:title", "", NS) or "").strip()
        author = (opf.findtext(".//dc:creator", "", NS) or "").strip()

        items = opf.findall(".//opf:manifest/opf:item", NS)
        images = [i for i in items if (i.get("media-type") or "").startswith("image/")]
        # 依序嘗試：EPUB3 cover-image → EPUB2 <meta name="cover"> → 名稱含 cover 的圖
        cover = next((i for i in images if "cover-image" in (i.get("properties") or "").split()), None)
        if cover is None:
            meta = opf.find(".//opf:metadata/opf:meta[@name='cover']", NS)
            if meta is not None:
                cover = next((i for i in images if i.get("id") == meta.get("content")), None)
        if cover is None:
            cover = next((i for i in images if "cover" in (i.get("id", "") + i.get("href", "")).lower()), None)
        if cover is None:
            return title, author, None, ""

        href = posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), unquote(cover.get("href"))))
        return title, author, z.read(href), posixpath.splitext(href)[1] or ".jpg"


def pdf_meta(path: Path) -> tuple[str, str, bytes | None, str]:
    with pymupdf.open(path) as doc:
        meta = doc.metadata or {}
        page = doc[0]
        zoom = 300 / page.rect.width
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        return (meta.get("title") or "").strip(), (meta.get("author") or "").strip(), pix.tobytes("png"), ".png"


def read_txt(path: Path) -> str:
    data = path.read_bytes()
    for enc in TXT_ENCODINGS:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def add_book(conn: sqlite3.Connection, path: Path) -> None:
    fmt = FORMATS[path.suffix.lower()]
    title = author = ""
    cover_bytes, cover_ext = None, ""
    try:
        if fmt == "epub":
            title, author, cover_bytes, cover_ext = epub_meta(path)
        elif fmt == "pdf":
            title, author, cover_bytes, cover_ext = pdf_meta(path)
    except Exception as e:  # 損毀或格式特殊的檔案仍列入書庫，只是沒有封面
        print(f"[警告] 無法讀取中繼資料：{path.name}（{e}）")

    cur = conn.execute(
        "INSERT INTO books (path, filename, title, author, fmt, size, added_at) VALUES (?,?,?,?,?,?,?)",
        (str(path), path.name, title, author, fmt, path.stat().st_size, time.time()),
    )
    if cover_bytes:
        name = f"{cur.lastrowid}{cover_ext}"
        (COVERS / name).write_bytes(cover_bytes)
        conn.execute("UPDATE books SET cover=? WHERE id=?", (name, cur.lastrowid))


def scan() -> dict:
    """掃描所有資料夾：新增未登錄的書，並標記已不存在（或資料夾已移除）的書。"""
    with db() as conn:
        roots = [Path(r["path"]) for r in conn.execute("SELECT path FROM folders")] + [UPLOADS]
        known = {r["path"] for r in conn.execute("SELECT path FROM books")}
        added = 0
        for root in roots:
            if not root.is_dir():
                print(f"[警告] 資料夾不存在：{root}")
                continue
            for p in root.rglob("*"):
                if p.is_file() and p.suffix.lower() in FORMATS and str(p) not in known:
                    add_book(conn, p)
                    known.add(str(p))
                    added += 1

        missing = 0
        for row in conn.execute("SELECT id, path FROM books").fetchall():
            p = Path(row["path"])
            gone = not (p.is_file() and any(p.is_relative_to(r) for r in roots))
            missing += gone
            conn.execute("UPDATE books SET missing=? WHERE id=?", (int(gone), row["id"]))
    return {"added": added, "missing": missing}


# ---------- API ----------

app = FastAPI()


def book_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    d = dict(row)
    d["tags"] = [t["tag"] for t in conn.execute("SELECT tag FROM tags WHERE book_id=? ORDER BY tag", (row["id"],))]
    d["has_cover"] = bool(d.pop("cover"))
    d["folder"] = Path(row["path"]).parent.name  # 系列書常以子資料夾分組，檔名本身看不出是哪一套
    return d


def get_row(conn: sqlite3.Connection, book_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "找不到這本書")
    return row


@app.get("/api/books")
def list_books():
    with db() as conn:
        rows = conn.execute("SELECT * FROM books WHERE hidden=0 AND missing=0").fetchall()
        return [book_dict(conn, r) for r in rows]


@app.get("/api/books/{book_id}")
def get_book(book_id: int):
    with db() as conn:
        return book_dict(conn, get_row(conn, book_id))


@app.get("/api/books/{book_id}/file")
def book_file(book_id: int):
    with db() as conn:
        row = get_row(conn, book_id)
    return FileResponse(row["path"])


@app.get("/api/books/{book_id}/text", response_class=PlainTextResponse)
def book_text(book_id: int):
    with db() as conn:
        row = get_row(conn, book_id)
    if row["fmt"] != "txt":
        raise HTTPException(400, "不是 txt 檔")
    return read_txt(Path(row["path"]))


@app.get("/api/books/{book_id}/cover")
def book_cover(book_id: int):
    with db() as conn:
        row = get_row(conn, book_id)
    if not row["cover"]:
        raise HTTPException(404, "沒有封面")
    return FileResponse(COVERS / row["cover"], headers={"Cache-Control": "max-age=86400"})


class Progress(BaseModel):
    position: str
    progress: float


@app.put("/api/books/{book_id}/progress")
def save_progress(book_id: int, body: Progress):
    with db() as conn:
        get_row(conn, book_id)
        conn.execute(
            "UPDATE books SET position=?, progress=?, last_read=? WHERE id=?",
            (body.position, max(0.0, min(1.0, body.progress)), time.time(), book_id),
        )
    return {"ok": True}


class Tags(BaseModel):
    tags: list[str]


@app.put("/api/books/{book_id}/tags")
def set_tags(book_id: int, body: Tags):
    tags = sorted({t.strip() for t in body.tags if t.strip()})
    with db() as conn:
        get_row(conn, book_id)
        conn.execute("DELETE FROM tags WHERE book_id=?", (book_id,))
        conn.executemany("INSERT INTO tags VALUES (?,?)", [(book_id, t) for t in tags])
    return {"tags": tags}


@app.delete("/api/books/{book_id}")
def remove_book(book_id: int):
    """從書庫移除。上傳的副本連檔案一起刪；掃描資料夾的原始檔不動，只隱藏。"""
    with db() as conn:
        row = get_row(conn, book_id)
        path = Path(row["path"])
        if path.is_relative_to(UPLOADS):
            path.unlink(missing_ok=True)
            conn.execute("DELETE FROM tags WHERE book_id=?", (book_id,))
            conn.execute("DELETE FROM books WHERE id=?", (book_id,))
            if row["cover"]:
                (COVERS / row["cover"]).unlink(missing_ok=True)
        else:
            conn.execute("UPDATE books SET hidden=1 WHERE id=?", (book_id,))
    return {"ok": True}


@app.post("/api/scan")
def api_scan():
    return scan()


@app.get("/api/folders")
def list_folders():
    with db() as conn:
        return [r["path"] for r in conn.execute("SELECT path FROM folders ORDER BY path")]


class Folder(BaseModel):
    path: str


@app.post("/api/folders")
def add_folder(body: Folder):
    p = Path(body.path.strip().strip('"'))
    if not p.is_dir():
        raise HTTPException(400, f"資料夾不存在：{p}")
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO folders VALUES (?)", (str(p),))
    return scan()


@app.delete("/api/folders")
def remove_folder(body: Folder):
    with db() as conn:
        conn.execute("DELETE FROM folders WHERE path=?", (body.path,))
    return scan()


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)):
    skipped = []
    for f in files:
        name = Path(f.filename or "").name
        if Path(name).suffix.lower() not in FORMATS:
            skipped.append(name)
            continue
        dest = UPLOADS / name
        n = 1
        while dest.exists():  # 同名不覆蓋，改加序號
            dest = UPLOADS / f"{Path(name).stem} ({n}){Path(name).suffix}"
            n += 1
        dest.write_bytes(await f.read())
    return {**scan(), "skipped": skipped}


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="本機電子書閱讀器")
    parser.add_argument("--host", default="127.0.0.1", help="改成 0.0.0.0 可讓區網其他裝置連入")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="啟動時不自動開啟瀏覽器")
    args = parser.parse_args()

    init_db()
    print("掃描書庫中…", scan())
    if not args.no_browser:
        webbrowser.open(f"http://127.0.0.1:{args.port}/")
    uvicorn.run(app, host=args.host, port=args.port)
