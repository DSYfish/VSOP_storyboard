# VSOP Storyboard 自動分鏡稿生成系統

## 專案簡介
本專案為一個自動化的工業分鏡稿生成系統，旨在透過視覺 AI 分析操作影片（如 SOP 流程），自動擷取關鍵影格、追蹤作業員手部動作、辨識零件，並利用 Vision AI 直接判讀紙本/PDF SOP 作業指導書。最終將影片動作與 SOP 步驟進行智慧對齊，輸出美觀、專業的 HTML 分鏡表報表。

## 系統架構與核心亮點 

本專案經過多次功能迭代與架構優化，具備以下強大功能：

### 1. 支援地端 AI 與多模型切換 (Local LLM Support)
* **Ollama 地端模型整合**：支援完全離線的本機端 Ollama 模型（例如：`gemma4:12b`, `llava`, `minicpm-v`），確保工廠機密影片與 SOP 資料不外洩。
* **自動偵測模型**：系統會自動掃描本機已安裝的 Ollama 模型並提供下拉選單切換，隨插即用。
* **Google Gemini API**：若需要極致的準確度，亦支援串接 Google Gemini Vision AI (Flash / Pro)。

### 2. PDF SOP 智慧辨識與雙軌解析 (Vision SOP Planner)
* **純圖檔 PDF 萃取**：無需依賴文字萃取套件，直接將 PDF 轉為高畫質圖片 (250 DPI)，交由 Vision AI 進行精準判讀，避免如 `1` 與 `'` 被混淆的問題。
* **雙軌解析模式切換**：
  * **[嚴格鎖定] 連易通專用格式**：針對企業標準 4 欄/2 欄專用格式排版，精準提取「序號、品名、步驟、工法」，並自動過濾無關的流程圖。
  * **[通用彈性] 廠商自訂格式**：適應各種不規則排版，由 AI 自行尋找動作段落與零件名稱。
* **動態跳過目錄機制 (Dynamic Page Skipping)**：預覽分析時，若 AI 判定該頁為「封面」或「目錄」，系統會自動忽略該頁並將額度「+1」，向後尋找真正的步驟頁，確保分析的有效性。

### 3. 電腦視覺手部追蹤與裁切 (Hand Tracking & ROI Cropping)
* **雙重防線追蹤**：
  1. **MediaPipe 裸手追蹤**：精準定位雙手關節位置。
  2. **Motion Diff 動態相減**：當作業員配戴手套或防護網導致無法辨識手部時，自動切換為畫面動態區域追蹤。
* **智能畫面裁切**：自動將影片裁切至雙手操作的局部區域 (ROI)，不僅大幅減少發送給 AI 的圖片大小（省流量與 Token），更能強迫 AI 將注意力集中在零件與組裝細節上。
* **UI 即時預覽**：提供「預覽手部裁切範圍」按鈕，可直接在介面上確認系統判定的紅框 (裸手) 或綠框 (動態)。

### 4. 現代化 Web 介面 (Streamlit)
* **非同步與延遲渲染架構**：採用 Streamlit `st.container()` 延遲渲染技術，確保在呼叫耗時的 Vision AI 分析時，網頁左右兩側的預覽畫面不會突然消失或閃爍。
* **多檔案上傳與合併**：支援一次上傳多部毛片，系統會自動串接時間軸；內建直覺的「上移/下移」排序按鈕與影片第一幀封面預覽。
* **強健的容錯呈現**：捨棄傳統的 `st.table`，改用底層基於 Arrow 的 `st.dataframe` 顯示預覽資料，即使 AI 回傳的欄位有缺漏也能穩定顯示，並帶有 JSON 原始資料降級防護網。

### 5. Frame-Centric AI 事後對齊技術 (Storyboard Alignment)
* 系統會先讓 AI 觀察影片產出「動作草稿」，接著再把「SOP 步驟清單」餵給 AI，讓 AI 針對每一張截圖做「選擇題」，精準配對該動作屬於 SOP 的哪一個步驟代號。
* 自動比對標準工時 (預留擴充)，標記異常操作時間。

### 6. 專業 HTML 報表輸出
* 產出極具現代感的「左側圖片、右側文字」雙欄排版 HTML。
* 內建原生的 JavaScript Lightbox，點擊圖片即可放大檢視。
* 自動在描述後方帶入如 `(00:00:02~00:00:05)` 格式的精確秒數區間。

## 專案目錄結構

* `app.py`: Streamlit Web App 進入點與 UI 核心
* `video_processor.py`: OpenCV 影片讀取、手部追蹤、裁切與抽幀
* `sop_task_planner.py`: PDF 轉檔、雙軌解析模式、動態跳過目錄與 Vision API 對接
* `models.py`: 視覺模型介面 (Gemini / Ollama) 與批次 API 處理
* `analyzer.py`: 連續動作智能合併與事後對齊邏輯
* `storyboard_generator.py`: 將資料注入 HTML 的產生器
* `storyboard_template.html`: 分鏡稿網頁排版模板
* `sop_glossary_builder.py`: 專有名詞與術語庫建置工具

## 核心技術與相依套件 (Dependencies)

本專案依賴以下核心套件進行運作（完整清單請見環境設定檔）：

* **Web UI 與前端**
  * `streamlit`: 構築現代化且具備高度互動性的 Web 介面。
* **電腦視覺與影片處理**
  * `opencv-python` (cv2): 處理影片讀取、關鍵影格抽幀、以及 Motion Diff 動態計算。
  * `mediapipe`: Google 的機器視覺框架，負責精準的雙手節點追蹤與裁切。
  * `numpy`: 提供高效能的陣列與矩陣運算，用於影像比對與處理。
* **文件與 PDF 解析**
  * `pdfplumber` / `pymupdf`: 處理 PDF 讀取與高畫質圖片轉換 (250 DPI)，供 Vision AI 辨識。
* **AI 模型整合**
  * `google-generativeai`: Google 官方 SDK，用於串接 Gemini Flash / Pro 等雲端多模態模型。
  * `requests`: 用於發送 REST API 請求至本機端 Ollama 伺服器，達成地端 LLM 整合。
  * `pydantic`: 用於資料結構驗證。

## 啟動方式

確保已安裝 `uv` 以及所有相依套件，然後在終端機執行：

```bash
uv run streamlit run app.py
```
