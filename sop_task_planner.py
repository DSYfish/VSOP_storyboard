import os
import json
import re

class SOPTaskPlanner:
    def __init__(self, vision_model):
        """
        初始化 SOP 任務解析與精準目標檢索模組。
        :param vision_model: 來自 models.py 的 VisionModel 實例
        """
        self.model = vision_model

    def extract_text_content(self, file_path: str) -> str:
        """從檔案中提取純文字"""
        ext = os.path.splitext(file_path)[1].lower()
        text = ""
        try:
            if ext == '.pdf':
                import pdfplumber
                with pdfplumber.open(file_path) as pdf:
                    for page_num, page in enumerate(pdf.pages):
                        text += f"--- 第 {page_num + 1} 頁 ---\n"
                        text += (page.extract_text() or "") + "\n"
            else:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
        except Exception as e:
            return f"錯誤: {str(e)}"
        return text

    def plan_tasks_from_sop(self, sop_text: str) -> list:
        """
        從 SOP 文本中萃取標準化任務清單 (Task List)。
        """
        prompt = f"""
        你是一位工業工程任務分析師。
        請閱讀以下 SOP 文件內容，並將其拆解成一個依序執行的「標準化任務清單」。
        每個任務代表一個獨立的連續動作。
        
        【SOP 文件內容】
        {sop_text[:30000]}
        
        請務必回傳嚴格的 JSON Array 格式。
        **不要加上任何 Markdown 標記，純粹回傳 JSON，且最外層必須是 `[` 與 `]`。**
        每個物件的格式如下：
        [
            {{
                "step_number": "步驟編號 (例如: 1)",
                "part_name": "操作的零件或設備名稱",
                "action_description": "工單上記載的動作描述"
            }}
        ]
        """
        
        try:
            print("[SOPTaskPlanner] 正在解析 SOP 並拆解為任務清單...")
            response = self.model.generate_text(prompt)
            
            import re
            match = re.search(r'\[.*\]', response, re.DOTALL)
            if match:
                response = match.group(0)
                
            tasks = json.loads(response)
            print(f"[SOPTaskPlanner] 成功拆解出 {len(tasks)} 個標準任務。")
            return tasks
        except Exception as e:
            print(f"[SOPTaskPlanner] SOP 任務拆解失敗: {e}")
            return []

    def _parse_tasks_from_response(self, response_text: str) -> list:
        """強健地解析 AI 回傳的 JSON 資料，防止因回傳錯誤字典或外層封裝結構而造成崩潰"""
        import json
        import re
        if not response_text:
            return []
            
        # 檢查是否為模型或 API 返回的錯誤訊息
        if '"error":' in response_text or "'error':" in response_text:
            try:
                err_data = json.loads(response_text)
                if isinstance(err_data, dict) and "error" in err_data:
                    raise RuntimeError(f"AI 伺服器回應錯誤: {err_data['error']}")
            except RuntimeError as re_err:
                raise re_err
            except Exception:
                pass
            
        # 1. 優先尋找 JSON 陣列 [...]
        match = re.search(r'\[.*\]', response_text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, list):
                    return [item for item in data if isinstance(item, dict)]
            except Exception:
                pass
                
        # 2. 尋找 JSON 物件 {...}，處理被封裝在 {"tasks": [...]} 或 {"steps": [...]} 的狀況
        match_obj = re.search(r'\{.*\}', response_text, re.DOTALL)
        if match_obj:
            try:
                data = json.loads(match_obj.group(0))
                if isinstance(data, dict):
                    if "error" in data:
                        raise RuntimeError(f"AI 伺服器回應錯誤: {data['error']}")
                    # 檢查是否為單一步驟字典
                    if "part_name" in data or "step_number" in data or "action_description" in data:
                        return [data]
                    for k, v in data.items():
                        if isinstance(v, list):
                            dicts = [item for item in v if isinstance(item, dict)]
                            if dicts:
                                return dicts
                        elif isinstance(v, dict):
                            if "part_name" in v or "step_number" in v or "action_description" in v:
                                return [val for val in data.values() if isinstance(val, dict)]
            except RuntimeError as re_err:
                raise re_err
            except Exception:
                pass
                
        return []

    def _extract_tasks_fast_text(self, pdf_path: str, progress_callback=None) -> list:
        """
        [極速秒速] 純表格文字抽取模式。
        免消耗 GPU，直接透過 pdfplumber 讀取文字與表格。
        """
        import pdfplumber
        tasks = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
                for i, page in enumerate(pdf.pages):
                    if progress_callback:
                        progress_callback(i + 1, total_pages, f"[極速模式] 正在抽取表格文字 (第 {i+1}/{total_pages} 頁，已抓取 {len(tasks)} 個步驟)...")
                    
                    page_text = (page.extract_text() or "").strip()
                    is_toc = "Page_" in page_text and "~" in page_text
                    has_step_keywords = ("步驟" in page_text and "工法" in page_text) or ("步驟" in page_text and "序號" in page_text)
                    if len(page_text) > 30 and (is_toc or not has_step_keywords):
                        print(f"[SOPTaskPlanner] 極速模式智慧過濾：第 {i+1} 頁無工法表頭，自動跳過！")
                        continue
                        
                    tables = page.extract_tables()
                    for t in tables:
                        # 尋找「步驟」欄位的起始列，避免抓到上方零件清單
                        step_start_idx = 999
                        for row_idx, row in enumerate(t):
                            if row and len(row) >= 2 and row[0] and "步驟" in str(row[0]):
                                step_start_idx = row_idx
                                break
                                
                        for row_idx, row in enumerate(t):
                            if row_idx > step_start_idx and len(row) >= 2 and row[0] and row[1]:
                                step_num = str(row[0]).strip()
                                action_desc = str(row[1]).replace('\n', ' ').strip()
                                if any(c.isdigit() for c in step_num) and len(action_desc) > 2 and "序號" not in step_num and "步驟" not in step_num:
                                    tasks.append({
                                        "page_number": i + 1,
                                        "step_number": step_num,
                                        "part_name": "工單組裝件",
                                        "action_description": action_desc
                                    })
        except Exception as e:
            print(f"[SOPTaskPlanner] Fast text extraction error: {e}")
            
        print(f"[SOPTaskPlanner] 極速模式抽取完成！共成功抓取 {len(tasks)} 個步驟。")
        return tasks

    def plan_tasks_from_pdf_vision(self, pdf_path: str, max_pages: int = -1, parse_mode: str = "leonton", progress_callback=None) -> list:
        """
        使用 Vision AI 多模態直接讀取 PDF 圖片，或在 fast_text 模式下極速讀取純文字表格。
        """
        if parse_mode == "fast_text":
            print("[SOPTaskPlanner] 啟討 [極速秒速] 純表格文字抽取模式 (免 GPU)...")
            return self._extract_tasks_fast_text(pdf_path, progress_callback)
            
        tasks = []
        try:
            import pdfplumber
            import base64
            from io import BytesIO
            
            # 準備好 prompt 後，再決定要逐頁還是批次分析

            if parse_mode == "leonton":
                prompt = """
                你是一位資深的工業工程任務分析師。
                我上傳了一份 SOP 文件的掃描圖（可能包含多頁）。請直接閱讀圖片中的表格或文字，並將其拆解成一個依序執行的「標準化任務清單」。
                
                【SOP 文件版面結構指南】：
                這份 SOP 具有特定的排版邏輯，請依據以下 4 個區塊來進行解析：
                1. 左上角表格（四欄）：包含「序號」、「元件品號」、「品名」、「用量」。這裡的「品名」是極度重要的零件專有名詞。如果這區是空白的，請勿自行發明品名。
                2. 左側中間表格（兩欄）：包含「步驟」與「工法」。這裡是核心的連續操作動作。
                3. 左下角表格：包含「注意事項」。(注意：如果注意事項底下或旁邊只有空白的一列而沒有實際文字內容，請直接忽略，不要編寫出來)。
                4. 右側區域：工序圖片化展現或作業流程圖。
                
                【防呆機制 (極度重要)】：
                1. 封面與無關頁面：如果你在圖片中 **完全沒有看到** 上述的「步驟」與「工法」表格，這代表此頁並非操作步驟頁。請回傳 `[]`。
                2. 目錄與流程大綱：如果「工法」欄位中寫的是頁碼範圍（例如「Page_ 4 ~ 13」），或者右側標示為「作業流程」，這代表此頁只是「目錄大綱」，不是真實的細部操作步驟。請直接忽略整頁，回傳 `[]`。
                3. 嚴禁從流程圖中瞎掰：**絕對不准**把右側的「作業流程圖」（例如 T1測試、A1組裝）當作步驟提取出來！步驟的來源**只能且唯一只能**來自左側的「步驟」與「工法」表格！
                
                【核心解析任務】：
                1. 只有在確認畫面有真實的「步驟工法」細節時，才以該表格為骨幹整理為任務清單。
                2. 請將左上角的「品名」與步驟對應，填入 part_name 中。如果左上角沒寫，可以從工法中擷取動詞後面的名詞；如果都沒有，請填空字串。
                3. 必須精準保留文件中的「專有名詞」與「關鍵字」。
                4. (文字精準度警告)：請特別注意英文字母、數字與標點符號的差異。例如型號常見的數字「1」絕不可被誤認為單引號「'」。
                5. 請務必使用「繁體中文 (Traditional Chinese)」回答。
                
                請務必回傳嚴格的 JSON Array 格式。
                [
                    {
                        "step_number": "步驟編號 (請如實填寫圖片上的編號，若無請勿瞎掰)",
                        "part_name": "操作的零件名稱或治具 (優先從左上角品名提取，或從工法中擷取)",
                        "action_description": "工法描述 (若有具體的注意事項文字，請一併補充於此)"
                    }
                ]
                """
            else:
                prompt = """
                你是一位資深的工業工程任務分析師。
                我上傳了一份廠商提供的 SOP 文件的掃描圖（可能包含多頁）。請直接閱讀圖片中的表格或文字，並將其拆解成一個依序執行的「標準化任務清單」。
                
                【通用 SOP 解析指南】：
                這份 SOP 沒有固定的排版，請發揮你的智慧通讀全頁：
                1. 請尋找具有「操作步驟」、「工法」、「動作」含義的文字段落或表格。
                2. 請精準抓取操作時涉及的「零件名稱」、「治具」或「型號」作為 part_name。
                
                【防呆機制】：
                如果該頁面很明顯只是「封面」、「純機種清單」、或是只有「作業流程圖」而沒有任何具體的操作步驟說明，請直接回傳一個完全空白的 JSON Array： `[]`。
                
                【核心解析任務】：
                1. 必須精準保留文件中的「專有名詞」與「關鍵字」。
                2. (文字精準度警告)：請特別注意英文字母、數字與標點符號的差異。例如型號常見的數字「1」絕不可被誤認為單引號「'」。
                3. 請務必使用「繁體中文 (Traditional Chinese)」回答。
                
                請務必回傳嚴格的 JSON Array 格式。
                [
                    {
                        "step_number": "步驟編號 (請如實填寫圖片上的編號，若無則照順序自行編號 1, 2, 3...)",
                        "part_name": "操作的零件名稱或治具",
                        "action_description": "工法描述"
                    }
                ]
                """
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                if max_pages is not None or self.model.__class__.__name__ in ['OllamaVisionModel', 'PartnerVisionModel']:
                    total_pdf_pages = len(pdf.pages)
                    if max_pages is None or max_pages <= 0:
                        target_pages = total_pdf_pages
                        max_search_pages = total_pdf_pages
                        print(f"[SOPTaskPlanner] 啟動全檔案逐頁探索模式 (共 {total_pdf_pages} 頁)")
                    else:
                        target_pages = max_pages
                        max_search_pages = min(total_pdf_pages, max_pages + 5)
                        print(f"[SOPTaskPlanner] 啟動動態跳過模式 (目標: {target_pages} 頁有效步驟)")
                        
                    valid_pages_collected = 0
                    last_error = None
                    
                    pages_to_parse = []
                    for i in range(len(pdf.pages)):
                        if target_pages_list and (i + 1) not in target_pages_list:
                            continue
                        pages_to_parse.append((i, pdf.pages[i]))
                        
                    for idx, (i, page) in enumerate(pages_to_parse):
                        if max_pages is not None and max_pages > 0 and idx >= max_search_pages:
                            print(f"[SOPTaskPlanner] 已達到最大探索上限 ({max_search_pages} 頁)，停止探索。")
                            break
                        if max_pages is not None and max_pages > 0 and valid_pages_collected >= target_pages:
                            print(f"[SOPTaskPlanner] 已成功收集 {target_pages} 頁有效步驟，結束探索。")
                            break
                            
                        # 智慧前置過濾：先利用 PDF 內文字特徵過濾無關頁面（封面、修改紀錄、純目錄、設備清單）
                        page_text = (page.extract_text() or "").strip()
                        is_toc = "Page_" in page_text and "~" in page_text
                        has_step_keywords = ("步驟" in page_text and "工法" in page_text) or ("步驟" in page_text and "序號" in page_text)
                        if len(page_text) > 30 and (is_toc or not has_step_keywords):
                            print(f"[SOPTaskPlanner] 智慧過濾：第 {i+1} 頁無工法表頭特徵或為目錄大綱，自動跳過免推論！")
                            if progress_callback:
                                progress_callback(i + 1, total_pdf_pages, f"[智慧過濾] 第 {i+1}/{total_pdf_pages} 頁為封面/目錄，自動跳過 (目前累積 {len(tasks)} 個步驟)...")
                            continue
                            
                        if progress_callback:
                            progress_callback(i + 1, total_pdf_pages, f"[AI推論] 正在分析第 {i+1}/{total_pdf_pages} 頁 (已萃取 {len(tasks)} 個步驟)...")
                            
                        # 轉換單張圖片 (降低解析度減少 VRAM)
                        pil_img = page.to_image(resolution=100).original
                        import io
                        img_byte_arr = io.BytesIO()
                        pil_img.save(img_byte_arr, format='JPEG')
                        img_data = img_byte_arr.getvalue()
                        img_b64 = base64.b64encode(img_data).decode('utf-8')
                        
                        print(f"[SOPTaskPlanner] 正在分析 PDF 第 {i+1} 頁...")
                        try:
                            response = self.model.analyze_multimodal_document([img_b64], prompt)
                            page_tasks = self._parse_tasks_from_response(response)
                            
                            if page_tasks and len(page_tasks) > 0:
                                print(f"[SOPTaskPlanner] 第 {i+1} 頁是有效步驟頁！成功萃取 {len(page_tasks)} 個任務。")
                                for pt in page_tasks:
                                    pt["page_number"] = i + 1
                                tasks.extend(page_tasks)
                                valid_pages_collected += 1
                            else:
                                print(f"[SOPTaskPlanner] 第 {i+1} 頁未分析出有效步驟，自動跳過尋找下一頁。")
                        except Exception as e:
                            print(f"[SOPTaskPlanner] 第 {i+1} 頁分析失敗: {e}")
                            last_error = str(e)
                            
                    if len(tasks) == 0 and last_error:
                        raise RuntimeError(f"所有頁面推論皆無法取得步驟！最後一頁發生錯誤: {last_error}")
                else:
                    # ==========================================
                    # 批次處理模式 (正式產生分鏡稿專用)
                    # 一次性讀取所有頁面並送給 AI，節省時間與 API 次數
                    # ==========================================
                    images_b64 = []
                    print(f"[SOPTaskPlanner] 正在將 PDF 轉換為圖片以供視覺 AI 批次分析...")
                    for i in range(len(pdf)):
                        if target_pages_list and (i + 1) not in target_pages_list:
                            continue
                        page = pdf[i]
                        pix = page.get_pixmap(dpi=120)
                        img_data = pix.tobytes("jpeg")
                        images_b64.append(base64.b64encode(img_data).decode('utf-8'))
                        
                    print(f"[SOPTaskPlanner] 正在呼叫 Vision AI 智慧解析 {len(images_b64)} 頁 PDF (模式: {parse_mode})...")
                    response = self.model.analyze_multimodal_document(images_b64, prompt)
                    tasks = self._parse_tasks_from_response(response)
                    print(f"[SOPTaskPlanner] 成功透過 Vision AI 擷取出 {len(tasks)} 個富含關鍵字的任務！")
        except Exception as e:
            print(f"[SOPTaskPlanner] Vision AI PDF 解析失敗: {str(e)}")
            raise RuntimeError(f"Vision AI 解析失敗: {str(e)}") from e
            
        return tasks

    def filter_tasks_by_video_context(self, tasks: list, video_list: list, progress_callback=None) -> list:
        """
        方案 A：全自動「影片-SOP AI 物件對齊過濾」
        透過抽取實際作業影片的代表截圖，運用 AI/規則分析出影片中操作的核心工件與站點，
        從全檔案抽取的龐大 SOP 任務中，剔除影片中完全未拍到的無關工站步驟！
        """
        if not tasks or not video_list:
            return tasks
            
        print(f"[SOPTaskPlanner] 啟動影片-SOP 跨模態物件對齊過濾 (原始候選步驟: {len(tasks)} 個)...")
        if progress_callback:
            progress_callback(10, 100, "[影片對齊] 正在抽取實際影片代表影格以分析操作工件...")
            
        try:
            import base64
            import json
            from video_processor import VideoProcessor
            
            # 取第一支或主要影片進行代表截圖分析
            first_video = video_list[0]
            vp = VideoProcessor(first_video["path"])
            duration = vp.get_duration()
            
            # 抓取影片中間點 (50%) 與後半點 (75%) 兩張畫面作為作業物件代表
            timestamps = [max(0.5, duration * 0.5), max(0.5, duration * 0.75)]
            sample_frames_b64 = []
            for ts in timestamps:
                frame_data = vp.extract_and_crop_hands(ts, padding=150)
                if frame_data and "image_base64" in frame_data:
                    sample_frames_b64.append(frame_data["image_base64"])
                    
            if not sample_frames_b64:
                print("[SOPTaskPlanner] 警告：無法自影片中截取代表畫面，維持原始步驟清單。")
                return tasks
                
            if progress_callback:
                progress_callback(40, 100, "[影片對齊] 正在將影片畫面與 SOP 步驟進行 AI 跨模態比對...")
                
            # 建立極簡候選清單 (只保留編號與前35字的動作精簡摘要，大幅避免地端 VRAM 溢位與卡死！)
            short_candidates = []
            for idx, t in enumerate(tasks):
                short_candidates.append({
                    "step_number": t.get("step_number", str(idx+1)),
                    "part_name": str(t.get("part_name", ""))[:15],
                    "action": str(t.get("action_description", ""))[:35]
                })
            candidate_json_str = json.dumps(short_candidates, ensure_ascii=False, indent=2)
            
            prompt = f"""
請觀察這 {len(sample_frames_b64)} 張來自實際現場作業影片的截圖。
以下是從整份 SOP 指導書萃取出「所有可能的候選作業步驟」：
{candidate_json_str}

【分析與過濾任務】：
1. 請仔細辨識影片截圖中，作業人員實際上正在組裝或操作的「核心工件、治具、零件外觀或型號」(例如是否在做端子台組裝、鎖付螺絲、或貼標籤)。
2. 請從上述候選步驟中，挑選出「與這段影片實際作業內容與操作工件真正相關」的工法步驟。
3. 請務必剔除影片中完全沒有出現、屬於其他站點或無關的步驟 (例如影片只做端子台組裝，請剔除包裝、測試、無關模組等步驟)。
4. 若在 Mock/測試模式或無法精確判斷時，請預設保留前半段主要組裝工序。

請務必只回傳嚴格的 JSON Array，包含過濾後的有效步驟：
[
  {{
    "step_number": "步驟編號",
    "part_name": "零件名稱",
    "action_description": "工法描述"
  }}
]
"""
            response = self.model.analyze_multimodal_document(sample_frames_b64, prompt)
            filtered_tasks = self._parse_tasks_from_response(response)
            
            if filtered_tasks and len(filtered_tasks) > 0 and len(filtered_tasks) <= len(tasks):
                # 利用 step_number 或 action_description 找回原本完整的 task (包含 page_number)
                matched_orig_tasks = []
                for ft in filtered_tasks:
                    for orig_t in tasks:
                        if (ft.get("step_number") == orig_t.get("step_number") or 
                            ft.get("action_description")[:10] in orig_t.get("action_description", "")):
                            if orig_t not in matched_orig_tasks:
                                matched_orig_tasks.append(orig_t)
                            break
                            
                if matched_orig_tasks:
                    print(f"[SOPTaskPlanner] 影片對齊完成！成功從 {len(tasks)} 個候選步驟過濾出 {len(matched_orig_tasks)} 個相關工序 (支援跨頁)。")
                    if progress_callback:
                        progress_callback(100, 100, f"[影片對齊] 成功對齊！過濾保留 {len(matched_orig_tasks)} 個影片專屬步驟。")
                    return matched_orig_tasks
                else:
                    return filtered_tasks
            else:
                print(f"[SOPTaskPlanner] AI 回傳過濾結果異常或為空。這表示影片內容可能不包含任何已知的 SOP 步驟。")
        except Exception as e:
            print(f"[SOPTaskPlanner] 影片對齊過程發生錯誤 ({e})。")
            
        print(f"[SOPTaskPlanner] 找不到符合的步驟，捨棄強制套用，轉交給純影像分析。")
        if progress_callback:
            progress_callback(100, 100, f"[影片對齊] 無符合步驟，退回純影像分析。")
        return []

    def align_storyboard_with_sop(self, tasks: list, raw_storyboard: list) -> list:
        """
        Frame-Centric 的事後對齊機制。
        將分鏡稿中的每一張圖片，配上 SOP 任務清單，讓 AI 做選擇題。
        """
        if not tasks or not raw_storyboard:
            return raw_storyboard
            
        # 建立簡化的 SOP 清單供 AI 閱讀 (避免 Token 過長)
        sop_text_for_prompt = "SOP 步驟清單：\n"
        for t in tasks:
            sop_text_for_prompt += f"- 步驟代號 [{t.get('step_number')}]: {t.get('action_description')}\n"
            
        refined_storyboard = []
        for i, frame in enumerate(raw_storyboard):
            prompt = f"""
你是一個工業工程稽核員。
請看這張圖片。
以下是標準作業程序 (SOP) 的步驟清單：

{sop_text_for_prompt}

請判斷這張圖片中的動作，最符合哪一個「步驟代號」？
規則：
1. 只能回答符合的步驟代號字串（例如：2-5, 1-1）。
2. 如果圖片中的動作不符合上述任何一個步驟，請直接回答 0。
3. 嚴禁做任何解釋，只要輸出一個步驟代號或 0 即可。
"""
            image_base64 = frame.get("image_base64")
            if not image_base64:
                continue
                
            print(f"[SOPTaskPlanner] 正在對齊第 {i+1}/{len(raw_storyboard)} 張影格...")
            try:
                response = self.model.analyze_multimodal_document([image_base64], prompt)
                matched_step = response.strip().strip('[]').split('\n')[0] # 安全清理字串
                
                # 尋找對應的 task
                matched_task = next((t for t in tasks if t.get('step_number') == matched_step), None)
                
                if matched_task:
                    # 如果配對成功，將原本的白話文替換為 SOP 的精準名詞
                    frame["part_name"] = "SOP 標準動作"
                    frame["action_description"] = f"[{matched_task['step_number']}] {matched_task['action_description']}"
                    if "page_number" in matched_task:
                        frame["page_number"] = matched_task["page_number"]
                    refined_storyboard.append(frame)
                    print(f"  -> 配對成功：{matched_step}")
                else:
                    # 如果回傳 0 或找不到，捨棄此影格
                    print(f"  -> 無對應 SOP 步驟 (AI回答: {response})，已捨棄。")
            except Exception as e:
                print(f"[SOPTaskPlanner] 影格對齊失敗: {e}")
                
        print(f"[SOPTaskPlanner] 對齊完成，共保留 {len(refined_storyboard)} 個有效影格。")
        return refined_storyboard
