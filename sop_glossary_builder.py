import os
import json

class SOPGlossaryBuilder:
    def __init__(self, vision_model):
        """
        初始化 SOP 字典模組。
        :param vision_model: 來自 models.py 的 VisionModel 實例 (支援 generate_text)
        """
        self.model = vision_model

    def extract_text_content(self, file_path: str) -> str:
        """從檔案中提取純文字 (支援 PDF, TXT, JSON, CSV) 以便地端快速推論"""
        ext = os.path.splitext(file_path)[1].lower()
        text = ""
        try:
            if ext == '.pdf':
                try:
                    import fitz
                    doc = fitz.open(file_path)
                    for page_num, page in enumerate(doc):
                        text += f"--- 第 {page_num + 1} 頁 ---\n"
                        text += page.get_text() + "\n"
                    doc.close()
                except ImportError:
                    return "錯誤：缺少 PyMuPDF 套件，無法解析 PDF。"
            else:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
        except Exception as e:
            print(f"[SOPGlossaryBuilder] 讀取檔案失敗: {e}")
            return f"錯誤: {str(e)}"
            
        return text

    def run_two_pass_refinement(self, raw_storyboard: list, sop_text: str) -> list:
        """
        執行雙層過濾 RAG 架構：
        1. 錨點定位與字典萃取
        2. 術語精煉重寫
        """
        if not self.model:
            print("[SOPGlossaryBuilder] 未設定 VisionModel。")
            return raw_storyboard
        
        if not raw_storyboard or sop_text.startswith("錯誤"):
            print("[SOPGlossaryBuilder] 無效的分鏡稿或 SOP 文件。")
            return raw_storyboard

        # 將草稿分鏡的動作列出
        actions_summary = []
        for idx, item in enumerate(raw_storyboard):
            desc = f"動作 {idx+1}: {item.get('part_name', '')} - {item.get('action_description', '')}"
            actions_summary.append(desc)
        actions_text = "\n".join(actions_summary)

        # ---------------------------------------------------------
        # PASS 1: 錨點定位與字典萃取 (Localize & Extract)
        # ---------------------------------------------------------
        print("[SOPGlossaryBuilder] PASS 1: 正在比對影片草稿與 SOP，萃取專屬字典...")
        
        extract_prompt = f"""
        你是一位工業工程名詞專家。
        我有一份「影片動作草稿」，以及一份「長篇的 SOP 規定文件」。
        
        請你先比對這兩者，找出「影片動作草稿」最可能對應到 SOP 裡面的哪一個特定章節或步驟（基準錨點）。
        然後，請從該 SOP 段落中，萃取出所有相關的「專業零件名稱」與「專業工法動作詞彙」，建立一份專屬字典。

        【影片動作草稿】
        {actions_text}

        【長篇 SOP 文件內容】
        {sop_text[:30000]}  # 節錄參考

        請回傳嚴格的 JSON 格式 (不要有 Markdown code block)，包含：
        {{
            "anchor_location": "SOP 中的哪一頁或哪個段落",
            "extracted_glossary": ["專有名詞1", "專有名詞2", "專業動詞3"]
        }}
        """

        try:
            extract_response = self.model.generate_text(extract_prompt)
            
            import re
            match = re.search(r'\{.*\}', extract_response, re.DOTALL)
            if match:
                extract_response = match.group(0)
                
            glossary_json = json.loads(extract_response)
            glossary_list = glossary_json.get("extracted_glossary", [])
            print(f"[SOPGlossaryBuilder] 成功定位錨點: {glossary_json.get('anchor_location')}")
            print(f"[SOPGlossaryBuilder] 成功萃取字典: {glossary_list}")
            
            if not glossary_list:
                return raw_storyboard
                
        except Exception as e:
            print(f"[SOPGlossaryBuilder] PASS 1 萃取失敗: {e}")
            return raw_storyboard

        # ---------------------------------------------------------
        # PASS 2: 術語精煉重寫 (Refine Storyboard)
        # ---------------------------------------------------------
        print("[SOPGlossaryBuilder] PASS 2: 帶著專屬字典，重新精煉分鏡稿術語...")
        
        # 為了避免遺失原始時間與圖片資訊，我們要求 AI 傳回一個陣列，順序對應 raw_storyboard
        refine_prompt = f"""
        你是一位極度嚴謹的工廠廠長。
        我有一份「影片動作草稿」，以及一份我們工廠專用的「專業術語字典」。
        影片動作草稿裡面可能有很多外行人的俗稱（例如把端子叫成綠色塊）。
        請你將草稿中的俗稱，全部「替換」成字典中的專業術語，並讓動作描述更具工業水準。
        請勿改變原本的動作數量與順序。

        【專業術語字典】
        {', '.join(glossary_list)}

        【原始影片動作草稿】
        {actions_text}

        請回傳嚴格的 JSON Array 格式，陣列長度必須剛好等於 {len(raw_storyboard)}。每個物件包含：
        [
            {{
                "part_name": "修正後的專業零件名稱",
                "action_description": "修正後的專業動作描述"
            }}
        ]
        """

        try:
            refine_response = self.model.generate_text(refine_prompt)
            
            match = re.search(r'\[.*\]', refine_response, re.DOTALL)
            if match:
                refine_response = match.group(0)
                
            refined_array = json.loads(refine_response)
            
            # 將精煉後的文字覆蓋回原來的 storyboard
            final_storyboard = []
            for idx, item in enumerate(raw_storyboard):
                new_item = item.copy()
                if idx < len(refined_array):
                    new_item["part_name"] = refined_array[idx].get("part_name", item.get("part_name"))
                    new_item["action_description"] = refined_array[idx].get("action_description", item.get("action_description"))
                final_storyboard.append(new_item)
                
            print("[SOPGlossaryBuilder] 分鏡稿術語精煉完成！")
            return final_storyboard
            
        except Exception as e:
            print(f"[SOPGlossaryBuilder] PASS 2 精煉失敗: {e}")
            return raw_storyboard
