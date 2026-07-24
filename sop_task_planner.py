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
                import fitz
                doc = fitz.open(file_path)
                for page_num, page in enumerate(doc):
                    text += f"--- 第 {page_num + 1} 頁 ---\n"
                    text += page.get_text() + "\n"
                doc.close()
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

    def plan_tasks_from_pdf_vision(self, pdf_path: str, max_pages: int = None, parse_mode: str = "leonton") -> list:
        """
        使用 Vision AI 多模態直接讀取 PDF 圖片，
        根據 parse_mode (leonton 或 general) 採用嚴格或通用的解析策略。
        """
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
            with pdfplumber.open(pdf_path) as pdf:
                if max_pages is not None:
                    # ==========================================
                    # 動態跳過模式 (Preview 專用)
                    # 逐頁發送給 AI，若 AI 回傳空陣列 []，代表是封面或目錄
                    # 此時不計入 max_pages 額度，繼續找下一頁
                    # ==========================================
                    print(f"[SOPTaskPlanner] 啟動動態跳過模式 (目標: {max_pages} 頁有效步驟)")
                    valid_pages_collected = 0
                    max_search_pages = max_pages + 5 # 最多往後多找 5 頁，避免無窮迴圈
                    
                    for i, page in enumerate(pdf.pages):
                        if i >= max_search_pages:
                            print(f"[SOPTaskPlanner] 已達到最大探索上限 ({max_search_pages} 頁)，停止探索。")
                            break
                        if valid_pages_collected >= max_pages:
                            print(f"[SOPTaskPlanner] 已成功收集 {max_pages} 頁有效步驟，結束探索。")
                            break
                            
                        # 轉換單張圖片
                        img = page.to_image(resolution=250)
                        buffer = BytesIO()
                        img.original.save(buffer, format="JPEG")
                        img_data = buffer.getvalue()
                        img_b64 = base64.b64encode(img_data).decode('utf-8')
                        
                        print(f"[SOPTaskPlanner] 正在分析 PDF 第 {i+1} 頁...")
                        try:
                            response = self.model.analyze_multimodal_document([img_b64], prompt)
                            
                            import json
                            import re
                            match = re.search(r'\[.*\]', response, re.DOTALL)
                            if match:
                                response = match.group(0)
                            
                            page_tasks = json.loads(response)
                            
                            if page_tasks and len(page_tasks) > 0:
                                print(f"[SOPTaskPlanner] 第 {i+1} 頁是有效步驟頁！成功萃取 {len(page_tasks)} 個任務。")
                                tasks.extend(page_tasks)
                                valid_pages_collected += 1
                            else:
                                print(f"[SOPTaskPlanner] 第 {i+1} 頁被 AI 判定為無效 (封面/目錄)，自動跳過 (+1 尋找下一頁)。")
                        except Exception as e:
                            print(f"[SOPTaskPlanner] 第 {i+1} 頁分析失敗: {e}")
                else:
                    # ==========================================
                    # 批次處理模式 (正式產生分鏡稿專用)
                    # 一次性讀取所有頁面並送給 AI，節省時間與 API 次數
                    # ==========================================
                    images_b64 = []
                    print(f"[SOPTaskPlanner] 正在將 PDF 轉換為圖片以供視覺 AI 批次分析...")
                    for i, page in enumerate(pdf.pages):
                        img = page.to_image(resolution=250)
                        buffer = BytesIO()
                        img.original.save(buffer, format="JPEG")
                        img_data = buffer.getvalue()
                        images_b64.append(base64.b64encode(img_data).decode('utf-8'))
                        
                    print(f"[SOPTaskPlanner] 正在呼叫 Vision AI 智慧解析 {len(images_b64)} 頁 PDF (模式: {parse_mode})...")
                    response = self.model.analyze_multimodal_document(images_b64, prompt)
                    
                    import json
                    import re
                    match = re.search(r'\[.*\]', response, re.DOTALL)
                    if match:
                        response = match.group(0)
                        
                    tasks = json.loads(response)
                    print(f"[SOPTaskPlanner] 成功透過 Vision AI 擷取出 {len(tasks)} 個富含關鍵字的任務！")
        except Exception as e:
            print(f"[SOPTaskPlanner] Vision AI PDF 解析失敗: {str(e)}")
            
        return tasks
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
                response = self.vision_model.analyze_image_with_prompt(image_base64, prompt)
                matched_step = response.strip().strip('[]').split('\n')[0] # 安全清理字串
                
                # 尋找對應的 task
                matched_task = next((t for t in tasks if t.get('step_number') == matched_step), None)
                
                if matched_task:
                    # 如果配對成功，將原本的白話文替換為 SOP 的精準名詞
                    frame["part_name"] = "SOP 標準動作"
                    frame["action_description"] = f"[{matched_task['step_number']}] {matched_task['action_description']}"
                    refined_storyboard.append(frame)
                    print(f"  -> 配對成功：{matched_step}")
                else:
                    # 如果回傳 0 或找不到，捨棄此影格
                    print(f"  -> 無對應 SOP 步驟 (AI回答: {response})，已捨棄。")
            except Exception as e:
                print(f"[SOPTaskPlanner] 影格對齊失敗: {e}")
                
        print(f"[SOPTaskPlanner] 對齊完成，共保留 {len(refined_storyboard)} 個有效影格。")
        return refined_storyboard
