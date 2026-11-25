# 📚 本機電子書閱讀器

在自己電腦上管理與閱讀電子書的小工具。以瀏覽器操作，書籍與閱讀紀錄全部留在本機，不需要網路，也不會上傳到任何地方。

支援 **EPUB**、**KEPUB**、**PDF**、**TXT**。

## 功能

**書庫**
- 指定資料夾自動掃描（含子資料夾），或直接上傳檔案
- 以封面方格顯示書名、作者、檔名與閱讀進度
- 搜尋（檔名／書名／作者／資料夾）、格式篩選、閱讀狀態篩選、多種排序
- 自訂標籤分類、標記「閱讀完畢」
- 移除書籍不會刪除原始檔案

**閱讀**
- 自動記住每本書讀到的位置，下次開啟從原處繼續
- 字級（PDF 為縮放）與左右留白可調整
- 支援直排書，翻頁方向可依書切換（向左／向右）
- 目錄跳轉、顯示目前章節與頁碼
- 翻頁動畫
- 鍵盤操作：<kbd>←</kbd> <kbd>→</kbd> 翻頁，<kbd>PageUp</kbd> / <kbd>PageDown</kbd> / <kbd>空白鍵</kbd> 上下頁
- TXT 自動判斷編碼（UTF-8、Big5、GB18030、UTF-16）

## 執行

需要 [uv](https://docs.astral.sh/uv/)（會自動安裝所需的 Python 與套件）。

```powershell
uv sync
uv run python app.py                  # 開啟 http://127.0.0.1:8000/，並自動開瀏覽器
uv run python app.py --host 0.0.0.0   # 讓同一網路的手機、平板也能連入
uv run python app.py --port 8001      # 更換埠號
```

Windows 也可以直接雙擊 `start.bat`。

> 必須以 `python app.py` 啟動（資料庫在此時初始化），不要直接用 `uvicorn app:app`。

## 打包給沒有 Python 的電腦離線使用

兩種方式擇一，產出都在 `dist/`，把整個資料夾或 zip 交給對方即可，對方不需要安裝任何東西，也不需要網路。

| 方式 | 指令 | 啟動方式 | 說明 |
|---|---|---|---|
| 可攜版（建議） | `uv run python build_portable.py` | 雙擊 `start.bat` | 使用 python.org 官方、具數位簽章的 embeddable Python，不含自行打包的 exe，較不會被防毒誤判。附 `使用手冊.html` |
| exe 版 | `uv run pyinstaller ebook-reader.spec --noconfirm` | 雙擊 `ebook-reader.exe` | PyInstaller 打包 |

打包版不預設任何掃描資料夾，第一次啟動時會引導使用者設定。書庫資料存在程式資料夾內的 `data\` 與 `books\`，整個資料夾複製到別台電腦即可連同閱讀進度一起搬移。

## 架構

- **後端**：`app.py`，FastAPI + SQLite。負責資料夾掃描、書籍 API、閱讀進度與標籤儲存；EPUB 封面與書名從 OPF 讀取，PDF 封面以 PyMuPDF 渲染首頁
- **前端**：`static/index.html`（書庫）、`static/reader.html`（閱讀頁），純 HTML/JS，沒有建置步驟
- **第三方函式庫**放在 `static/vendor/`，不走 CDN，確保離線可用

執行時產生的資料（`data/` 資料庫與封面快取、`books/` 上傳的書）不納入版控。

## 第三方元件

| 元件 | 版本 | 授權 |
|---|---|---|
| [epub.js](https://github.com/futurepress/epub.js) | 0.3.93 | BSD-2-Clause |
| [JSZip](https://github.com/Stuk/jszip) | 3.10.1 | MIT 或 GPLv3 |
| [PDF.js](https://github.com/mozilla/pdf.js) | 3.11.174 | Apache-2.0 |
| Adobe CMap（`static/vendor/cmaps/`） | — | BSD-3-Clause（見該目錄 `LICENSE`） |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | 依 `uv.lock` | AGPL-3.0 |

本專案不包含任何電子書內容，請自行準備合法取得的書籍。
