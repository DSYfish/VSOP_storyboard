from abc import ABC, abstractmethod
import json

import base64
import time

class BaseVisionModel(ABC):
    """
    視覺模型的抽象基礎類別。
    無論底層是 Gemini 還是地端的千問 (Qwen)，都應實作此介面以供後端統一呼叫。
    """
    @abstractmethod
    def analyze_frame(self, image_base64: str, source_video: str = "", glossary: list = None) -> dict:
        """
        分析單一影格，並回傳該畫面的零件名稱與動作描述。
        """
        pass
        
    def analyze_frames_batch(self, keyframes: list, progress_callback=None, glossary: list = None) -> list:
        """
        批次分析影格。預設實作是透過迴圈呼叫 analyze_frame。
        子類別(如 Gemini)可覆寫此方法以實現單一 API 呼叫的真批次處理。
        """
        raw_results = []
        for idx, frame in enumerate(keyframes):
            if progress_callback:
                progress_callback(idx, len(keyframes))
            res = self.analyze_frame(frame["image_base64"], source_video=frame.get("source_video", ""), glossary=glossary)
            raw_results.append({
                "time_sec": frame["time_sec"],
                "image_base64": frame["image_base64"],
                "source_video": frame.get("source_video", "未知來源"),
                "part_name": res.get("part_name", "未知零件"),
                "action_description": res.get("action_description", "未知動作")
            })
        return raw_results

    @abstractmethod
    def analyze_single_frame_with_context(self, image_base64: str, step_name: str) -> dict:
        """
        針對已經確定的工單步驟，請 AI 進行畫面驗證與細節描述。
        """
        pass

    @abstractmethod
    def analyze_multimodal_document(self, images_b64: list, prompt: str) -> str:
        """
        發送多張圖片與文字咒語進行多模態比對。回傳 JSON 字串。
        """
        pass

    @abstractmethod
    def generate_text(self, prompt: str, expect_json: bool = True) -> str:
        """
        純文字邏輯推論。
        """
        pass

class GeminiVisionModel(BaseVisionModel):
    """
    真實環境使用的 Gemini Vision Model 介面。
    """
    def __init__(self, api_key: str = None, model_name: str = "gemini-3.5-flash"):
        self.api_key = api_key
        if not api_key:
            raise ValueError("必須提供 Gemini API Key。")
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(model_name)
        self.model_name = model_name

    def analyze_frame(self, image_base64: str, source_video: str = "", glossary: list = None) -> dict:
        print(f"[GeminiVisionModel] (單張模式) 正在發送圖片至 Gemini API 分析... (來源: {source_video})")
        # 單張模式僅作保留，我們主要會用 analyze_frames_batch 來避免打爆 Quota
        try:
            image_bytes = base64.b64decode(image_base64)
            image_blob = {"mime_type": "image/jpeg", "data": image_bytes}
            prompt = "你是一個專業的工業工程師。請回傳 JSON: {'part_name': '...', 'action_description': '...'}。請務必使用「繁體中文 (Traditional Chinese)」回答。"
            if glossary:
                steps_str = "\\n".join([f"- {g}" for g in glossary])
                prompt += f" 若畫面中符合，請優先從以下清單選擇步驟並填入 action_description：\\n{steps_str}"
            import google.generativeai as genai
            response = self.model.generate_content(
                [prompt, image_blob],
                generation_config=genai.types.GenerationConfig(response_mime_type="application/json")
            )
            result = json.loads(response.text)
            return {"part_name": result.get("part_name", "未知"), "action_description": result.get("action_description", "未知")}
        except Exception as e:
            return {"part_name": "API 分析錯誤", "action_description": str(e)}
            
    def analyze_frames_batch(self, keyframes: list, progress_callback=None, glossary: list = None) -> list:
        print(f"[GeminiVisionModel] 準備進行終極批次分析 (共 {len(keyframes)} 張影格合併為 1 次 API 呼叫)...")
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                contents = []
                prompt = """
                你是一個專業的工業工程師。我將提供一系列從工廠作業影片中依序擷取的關鍵影格（幾十張）。
                請為「每一張」圖片進行動作分析。
                請勿提及作業員（例如不要寫「人員正在...」），只專注於物件的狀態改變（例如請寫：「螺絲被鎖緊」、「電線被插入」、「外殼被蓋上」等實際畫面上發生的事）。
                
                【重要：時間區段合併規則】
                系統會根據你輸出的文字來計算動作時間。
                1. 如果連續幾張圖片都在進行「同一個連續動作」（例如：花 5 秒鐘鎖螺絲、花 3 秒鐘折紙盒），請務必為這些連續圖片回傳【完全相同】的 `part_name` 與 `action_description`！
                2. 只有當作業員切換到「下一個明顯不同的動作」（例如：放下螺絲起子，拿起新零件）時，你才需要改變輸出的文字。
                3. 請合理地將影片拆解成數個邏輯步驟（如 3~5 個步驟），不要把整支影片幾十張圖全部寫成同一個動作，也不要每一秒都寫不同的微小動作。
                
                請回傳一個嚴格的 JSON Array 格式。陣列中的每一個 JSON 物件，依照順序對應每一張輸入的圖片。
                陣列長度必須剛好等於我輸入的圖片數量。
                每個 JSON 物件需包含兩個欄位：
                - "part_name": "正在被操作的零件或設備名稱" (若無動作，填寫 "等待或無動作")
                - "action_description": "發生的動作描述"
                【重要指令】：請務必且強制使用「繁體中文 (Traditional Chinese)」回答，嚴禁使用英文或簡體中文。
                """
                if glossary:
                    steps_str = "\\n".join([f"- {g}" for g in glossary])
                    prompt += f"""
                    
                    【任務對齊指令】：
                    以下是標準作業程序(SOP)的步驟清單：
                    {steps_str}
                    
                    請務必從上述清單中挑選出與圖片動作最吻合的步驟，並在你的動作描述最後面加上「(對應SOP: 該步驟文字)」。請務必保留你對畫面的「詳細動作描述」，不要只輸出 SOP 文字。若無相符步驟，請依據圖片實際情況造句。
                    """
                contents.append(prompt)
                
                for idx, frame in enumerate(keyframes):
                    if progress_callback:
                        progress_callback(idx, len(keyframes))
                    contents.append(f"Image {idx+1} (Time: {frame['time_sec']}s)")
                    image_bytes = base64.b64decode(frame["image_base64"])
                    contents.append({"mime_type": "image/jpeg", "data": image_bytes})
                    
                print(f"[GeminiVisionModel] 正在向 Google 雲端發送超大包裹...")
                response = self.model.generate_content(
                    contents,
                    generation_config=genai.types.GenerationConfig(response_mime_type="application/json")
                )
                
                import re
                json_str = response.text
                match = re.search(r'\[.*\]', json_str, re.DOTALL)
                if match:
                    json_str = match.group(0)
                
                results_array = json.loads(json_str)
                
                if len(results_array) != len(keyframes):
                    print(f"[警告] AI 回傳數量 ({len(results_array)}) 與圖片數 ({len(keyframes)}) 不符！自動修正。")
                
                final_results = []
                for idx, frame in enumerate(keyframes):
                    if idx < len(results_array):
                        action = results_array[idx]
                    else:
                        action = {"part_name": "分析遺失", "action_description": "AI 未回傳此影格結果"}
                        
                    final_results.append({
                        "time_sec": frame["time_sec"],
                        "image_base64": frame["image_base64"],
                        "source_video": frame.get("source_video", "未知來源"),
                        "part_name": action.get("part_name", "未知零件"),
                        "action_description": action.get("action_description", "未知動作")
                    })
                return final_results
                
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg and attempt < max_retries - 1:
                    print(f"[GeminiVisionModel] 觸發 429 速率限制，等待 15 秒後重試... ({attempt+1}/{max_retries})")
                    time.sleep(15)
                    continue
                else:
                    print(f"[GeminiVisionModel] 批次 API 呼叫失敗: {error_msg}")
                    # 退回給前端錯誤訊息
                    return [{
                        "time_sec": frame["time_sec"],
                        "image_base64": frame["image_base64"],
                        "source_video": frame.get("source_video", ""),
                        "part_name": "API 分析錯誤",
                        "action_description": f"失敗: {error_msg}"
                    } for frame in keyframes]

    def analyze_single_frame_with_context(self, image_base64: str, step_name: str) -> dict:
        try:
            import google.generativeai as genai
            prompt = f"""
            你是一個專業的工業工程師。
            這張工廠作業畫面的任務對應工單上的步驟：「{step_name}」。
            請觀察畫面，確認人員是否正在進行此動作，並詳細描述畫面中物件的狀態。
            
            請務必使用「繁體中文 (Traditional Chinese)」回答。
            請回傳嚴格的 JSON 格式，包含兩個欄位：
            - "part_name": "{step_name}" (請直接填入工單步驟名稱)
            - "action_description": "發生的具體動作細節描述"
            """
            
            image_bytes = base64.b64decode(image_base64)
            contents = [
                prompt,
                {"mime_type": "image/jpeg", "data": image_bytes}
            ]
            response = self.model.generate_content(
                contents,
                generation_config=genai.types.GenerationConfig(response_mime_type="application/json")
            )
            
            import re
            json_str = response.text
            match = re.search(r'\{.*\}', json_str, re.DOTALL)
            if match:
                json_str = match.group(0)
            
            result = json.loads(json_str)
            return result
        except Exception as e:
            print(f"[GeminiVisionModel] 驗證分析發生錯誤: {str(e)}")
            return {"part_name": step_name, "action_description": f"分析錯誤: {str(e)}"}

    def analyze_multimodal_document(self, images_b64: list, prompt: str) -> str:
        try:
            import google.generativeai as genai
            contents = [prompt]
            for img_b64 in images_b64:
                image_bytes = base64.b64decode(img_b64)
                contents.append({"mime_type": "image/jpeg", "data": image_bytes})
            print(f"[GeminiVisionModel] 發送多模態文件分析 ({len(images_b64)} 張圖片)...")
            response = self.model.generate_content(
                contents,
                generation_config=genai.types.GenerationConfig(response_mime_type="application/json")
            )
            return response.text
        except Exception as e:
            print(f"[GeminiVisionModel] 多模態分析失敗: {str(e)}")
            return '{"error": "API 分析錯誤"}'

    def generate_text(self, prompt: str, expect_json: bool = True) -> str:
        try:
            print("[GeminiVisionModel] 發送純文字推論...")
            import google.generativeai as genai
            config = genai.types.GenerationConfig(response_mime_type="application/json") if expect_json else None
            response = self.model.generate_content(prompt, generation_config=config)
            return response.text
        except Exception as e:
            print(f"[GeminiVisionModel] 文字推論失敗: {str(e)}")
            return '{"error": "API 推論錯誤"}'

def get_available_ollama_models(host: str = "http://localhost:11434") -> list:
    """
    獲取本機 Ollama 伺服器已安裝的所有模型清單。
    """
    import requests
    try:
        response = requests.get(f"{host.rstrip('/')}/api/tags", timeout=2)
        response.raise_for_status()
        models_data = response.json().get("models", [])
        return [m.get("name") for m in models_data if "name" in m]
    except Exception as e:
        print(f"[Ollama] 無法獲取模型清單: {str(e)}")
        return []

class OllamaVisionModel(BaseVisionModel):
    """
    地端環境使用的 Ollama Vision Model 介面。
    支援兩階段推論架構 (Dual-Model Pipeline)：先以 VLM 處理影像，再交由 LLM 處理邏輯。
    """
    def __init__(self, model_name: str = "llava-llama3", host: str = "http://localhost:11434"):
        self.model_name = model_name
        self.host = host.rstrip('/')
        self.api_url = f"{self.host}/api/generate"
        self.current_video = None
        self.last_action_memory = None
        self.vlm_helper = self._find_vlm_helper()

    def _find_vlm_helper(self):
        try:
            import requests
            resp = requests.get(f"{self.host}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                for vlm in ["minicpm-v:latest", "llava-llama3:latest", "llava:34b", "llava:13b", "llava:latest"]:
                    if vlm in models:
                        return vlm
        except Exception:
            pass
        return None # 未安裝輔助 VLM

    def analyze_frame(self, image_base64: str, source_video: str = "", glossary: list = None) -> dict:
        if source_video and source_video != self.current_video:
            self.current_video = source_video
            self.last_action_memory = None
            
        print(f"[OllamaVisionModel] 正在發送圖片至 Ollama ({self.model_name}) 分析... (來源: {source_video})")
        try:
            import requests
            prompt = """
            你是一個專業的工業工程師。請觀察這張工廠作業畫面，告訴我「什麼物件」正在被「做什麼動作」。
            請不要提及作業員（例如：不要寫「作業員將...」或「人員正在...」），只專注於物件的狀態改變（例如請寫：「螺絲被鎖緊」、「電線被插入設備」、「外殼被蓋上」等實際發生的動作）。
            
            【重要：動作歸類規則】
            請合理判斷當前的動作屬於哪一個「主要邏輯步驟」。
            不要給出過度瑣碎的每秒微小動作，而是給出一個能涵蓋當下 3~5 秒操作的具體步驟名稱（例如：「將成品裝入 PE 袋」或「折疊外箱」）。
            
            【重要指令】：請務必且強制使用「繁體中文 (Traditional Chinese)」回答，嚴禁使用英文或簡體中文。
            請回傳嚴格的 JSON 格式，包含兩個欄位：
            - "part_name": "正在被操作的主要零件或設備名稱"
            - "action_description": "發生的具體動作描述"
            
            若畫面中沒有明顯動作，可以回傳 "等待或無動作"。
            """
            if glossary:
                steps_str = "\n".join([f"- {g}" for g in glossary])
                prompt += f"""
                
                【任務對齊指令】：
                以下是標準作業程序(SOP)的步驟清單：
                {steps_str}
                
                請務必從上述清單中挑選出與圖片動作最吻合的步驟，並在你的動作描述最後面加上「(對應SOP: 該步驟文字)」。請務必保留你對畫面的「詳細動作描述」，不要只輸出 SOP 文字。若無相符步驟，請依據圖片實際情況造句。
                """
                
            if self.last_action_memory:
                prompt += f"\n\n💡【時間連續性提示】：前一秒（上一張影格）的動作為『{self.last_action_memory}』。如果當前畫面沒有明顯改變，請務必直接繼續回傳同樣的動作，避免動作過度破碎！"
                
            import json
            import re

            # --- 第一階段：視覺特徵萃取 (使用輕量級 VLM) ---
            if self.vlm_helper:
                print(f"[OllamaVisionModel] 第一階段：使用 {self.vlm_helper} 進行視覺特徵萃取...")
                vlm_prompt = f"請詳細描述這張圖片中的人員動作、手部特寫以及主要物件狀態，越詳細越好。請用繁體中文回答。"
                vlm_payload = {
                    "model": self.vlm_helper,
                    "prompt": vlm_prompt,
                    "images": [image_base64],
                    "stream": False,
                    "options": {
                        "num_predict": 1024,
                        "temperature": 0.1
                    }
                }
                try:
                    vlm_resp = requests.post(self.api_url, json=vlm_payload, timeout=240)
                    vlm_resp.raise_for_status()
                    vision_context = vlm_resp.json().get("response", "無法獲取影像描述").strip()
                except Exception as e:
                    print(f"[OllamaVisionModel] 第一階段視覺萃取失敗: {str(e)}")
                    vision_context = f"影像解析失敗: {str(e)}。請僅依據你的常識進行推論。"
                
                prompt += f"\n\n【前置視覺系統回報的畫面內容】：\n{vision_context}\n"
                prompt += "請根據上述「前置視覺系統回報的畫面內容」，並結合你的專業判斷，輸出最終的 JSON 動作描述。"
            else:
                print(f"[OllamaVisionModel] 尚未安裝輔助視覺模型，自動降級。純影片模式下可能導致無效推論...")
                prompt += "\n\n【注意】：系統環境未偵測到輔助視覺模型。請僅依據你的常識進行合理的情境擴寫推測。"

            # --- 第二階段：核心邏輯判斷 ---
            payload = {
                "model": self.model_name,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "num_ctx": 4096,
                    "num_predict": -1,
                    "temperature": 0.1
                }
            }
            response = requests.post(self.api_url, json=payload, timeout=240)
            response.raise_for_status()
            
            json_resp = response.json()
            result_text = json_resp.get("response", "{}")
            thinking_text = json_resp.get("thinking", "")
            match = re.search(r'\{.*\}', result_text, re.DOTALL)
            
            if match:
                try:
                    result = json.loads(match.group(0))
                except Exception:
                    fallback_txt = result_text.strip() or thinking_text.strip() or "模型未回傳任何描述內容。"
                    result = {"part_name": "未識別", "action_description": fallback_txt}
            else:
                fallback_txt = result_text.strip() or thinking_text.strip() or "模型未回傳任何描述內容。"
                result = {"part_name": "未識別", "action_description": fallback_txt}
                
            action_desc = result.get("action_description", "未知動作")
            self.last_action_memory = action_desc
            
            return {
                "part_name": result.get("part_name", "未知零件"),
                "action_description": action_desc
            }
        except Exception as e:
            print(f"[OllamaVisionModel] API 呼叫失敗: {str(e)}")
            return {"part_name": "Ollama 分析錯誤", "action_description": str(e)}

    def analyze_single_frame_with_context(self, image_base64: str, step_name: str) -> dict:
        try:
            import requests
            import json
            import re
            
            # --- 第一階段：視覺特徵萃取 (使用輕量級 VLM) ---
            if self.vlm_helper:
                print(f"[OllamaVisionModel] 第一階段：使用 {self.vlm_helper} 進行視覺特徵萃取...")
                vlm_prompt = f"請詳細描述這張圖片中的人員動作、手部特寫以及主要物件狀態，越詳細越好。請用繁體中文回答。"
                vlm_payload = {
                    "model": self.vlm_helper,
                    "prompt": vlm_prompt,
                    "images": [image_base64],
                    "stream": False,
                    "options": {
                        "num_predict": 1024,
                        "temperature": 0.1
                    }
                }
                
                try:
                    vlm_resp = requests.post(self.api_url, json=vlm_payload, timeout=240)
                    vlm_resp.raise_for_status()
                    vision_context = vlm_resp.json().get("response", "無法獲取影像描述").strip()
                except Exception as e:
                    print(f"[OllamaVisionModel] 第一階段視覺萃取失敗: {str(e)}")
                    vision_context = f"影像解析失敗: {str(e)}。請僅依據標準步驟名稱進行推論。"
            else:
                print(f"[OllamaVisionModel] 未安裝輔助視覺模型，自動降級為「SOP 擴寫工具」模式...")
                vision_context = "【注意】：系統環境未偵測到視覺神經網路，無法處理影像。請直接忽略視覺內容，並嚴格依據標準步驟名稱與您的專業知識，進行情境的合理擴寫與動作描述。"

            # --- 第二階段：核心邏輯判斷 (使用公司指定 LLM，如 gemma4) ---
            print(f"[OllamaVisionModel] 第二階段：交由 {self.model_name} 進行核心動作比對與生成...")
            core_prompt = f"""
            你是一個專業的工業工程師。
            這張工廠作業畫面的任務對應工單上的步驟：「{step_name}」。
            
            【前置視覺系統回報的畫面內容】：
            {vision_context}
            
            請根據上述「前置視覺系統回報的畫面內容」，判斷該畫面是否符合「{step_name}」的動作，並詳細描述畫面中物件的狀態與人員動作。
            如果視覺系統回報的內容與步驟不符，請根據步驟名稱「{step_name}」進行合理的動作推論描述。
            
            請務必使用「繁體中文 (Traditional Chinese)」回答。
            請回傳嚴格的 JSON 格式，包含兩個欄位：
            - "part_name": "{step_name}" (請直接填入此名稱)
            - "action_description": "發生的具體動作細節描述"
            """
            
            payload = {
                "model": self.model_name,
                "prompt": core_prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "num_ctx": 4096,
                    "num_predict": -1,
                    "temperature": 0.1
                }
            }
            
            response = requests.post(self.api_url, json=payload, timeout=240)
            response.raise_for_status()
            
            json_resp = response.json()
            result_text = json_resp.get("response", "{}")
            thinking_text = json_resp.get("thinking", "")
            match = re.search(r'\{.*\}', result_text, re.DOTALL)
            
            if match:
                try:
                    result_dict = json.loads(match.group(0))
                except Exception:
                    fallback_txt = result_text.strip() or thinking_text.strip() or "模型未回傳任何描述內容。"
                    result_dict = {"part_name": step_name, "action_description": fallback_txt}
            else:
                fallback_txt = result_text.strip() or thinking_text.strip() or "模型未回傳任何描述內容。"
                result_dict = {"part_name": step_name, "action_description": fallback_txt}
            
            # 確保欄位存在
            if "part_name" not in result_dict:
                result_dict["part_name"] = step_name
            if "action_description" not in result_dict:
                result_dict["action_description"] = "無動作描述"
                
            return result_dict
            
        except Exception as e:
            print(f"[OllamaVisionModel] 驗證呼叫失敗: {str(e)}")
            return {"part_name": step_name, "action_description": f"連線錯誤: {str(e)}"}

    def analyze_multimodal_document(self, images_b64: list, prompt: str) -> str:
        try:
            import requests
            import re
            
            chat_url = f"{self.host}/api/chat"
            payload = {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt + "\n【重要指令】：請務必且強制使用「繁體中文 (Traditional Chinese)」回答，嚴禁使用英文或簡體中文。",
                        "images": images_b64
                    }
                ],
                "options": {
                    "num_ctx": 8192,
                    "num_predict": 1024,
                    "temperature": 0.1
                },
                "stream": False
            }
            print(f"[OllamaVisionModel] 發送多模態文件分析至 {self.model_name} (使用 Chat API, {len(images_b64)} 張圖片)...")
            response = requests.post(chat_url, json=payload, timeout=300)
            response.raise_for_status()
            
            result_text = response.json().get("message", {}).get("content", "{}").strip()
            match = re.search(r'\[.*\]|\{.*\}', result_text, re.DOTALL)
            if match:
                result_text = match.group(0)
                
            return result_text
        except Exception as e:
            print(f"[OllamaVisionModel] 多模態分析失敗: {str(e)}")
            import json
            return json.dumps({"error": f"Ollama 連線或推論失敗 ({str(e)})"})

    def generate_text(self, prompt: str, expect_json: bool = True) -> str:
        try:
            import requests
            import re
            
            chat_url = f"{self.host}/api/chat"
            content_prompt = prompt
            if expect_json:
                content_prompt += "\n【重要指令】：請務必且強制使用「繁體中文 (Traditional Chinese)」回答，包含 JSON 內的所有值，嚴禁使用英文或簡體中文。"
            else:
                content_prompt += "\n【重要指令】：請務必且強制使用「繁體中文 (Traditional Chinese)」回答。"
            
            payload = {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": content_prompt
                    }
                ],
                "options": {
                    "num_ctx": 8192,
                    "num_predict": 2048,
                    "temperature": 0.1
                },
                "stream": False
            }
            if expect_json:
                payload["format"] = "json"
                
            print(f"[OllamaVisionModel] 發送純文字推論至 {self.model_name}...")
            response = requests.post(chat_url, json=payload, timeout=300)
            response.raise_for_status()
            
            result_text = response.json().get("message", {}).get("content", "{}").strip()
            if expect_json:
                match = re.search(r'\[.*\]|\{.*\}', result_text, re.DOTALL)
                if match:
                    result_text = match.group(0)
            return result_text
        except Exception as e:
            print(f"[OllamaVisionModel] 文字推論失敗: {str(e)}")
            if expect_json:
                return '{"error": "Ollama 推論錯誤"}'
            return f"Ollama 推論錯誤: {str(e)}"

class MockVisionModel(BaseVisionModel):
    """
    測試環境使用的 Mock 模擬器。
    """
    def __init__(self, api_key: str = None):
        self.frame_counter = 0
        self.current_video = None

    def analyze_frame(self, image_base64: str, source_video: str = "", glossary: list = None) -> dict:
        if source_video and source_video != self.current_video:
            self.current_video = source_video
            self.frame_counter = 0
            
        self.frame_counter += 1
        
        if self.current_video and "1.3" in self.current_video:
            cycle = self.frame_counter % 25
            if cycle <= 2: return {"part_name": "條碼掃描", "action_description": "黑色的電子設備主體被拿起並進行條碼掃描。"}
            elif cycle <= 7: return {"part_name": "裝入靜電袋", "action_description": "電子設備主體被放入粉紅色的防靜電包裝袋中。"}
            elif cycle <= 10: return {"part_name": "拿取標籤貼紙", "action_description": "一小張條碼標籤貼紙被拿起。"}
            elif cycle <= 17: return {"part_name": "黏貼標籤", "action_description": "條碼標籤貼紙被小心地黏貼於瓦楞紙盒的內側翻蓋上。"}
            else: return {"part_name": "裝盒入庫", "action_description": "裝在靜電袋中的設備被放入專屬瓦楞紙盒內。"}
        else:
            cycle = self.frame_counter % 31
            if cycle <= 2: return {"part_name": "拿取零件", "action_description": "黑色的電子設備主體被拿起。"}
            elif cycle <= 5: return {"part_name": "安裝第一個綠色端子", "action_description": "較長的綠色端子排被插入黑色設備側邊的插槽中。"}
            elif cycle <= 10: return {"part_name": "第一次清潔", "action_description": "設備的端子與外殼被噴氣清潔除塵。"}
            elif cycle <= 14: return {"part_name": "安裝第二個綠色端子", "action_description": "較短的綠色端子被插入設備的另一個插槽。"}
            elif cycle <= 18: return {"part_name": "第二次清潔", "action_description": "剛安裝好的第二個端子及其周圍被噴氣清潔。"}
            elif cycle <= 22: return {"part_name": "外觀檢查與標籤確認", "action_description": "設備被翻轉，正面的圓形標誌與標籤貼紙被檢查是否平整。"}
            elif cycle <= 25: return {"part_name": "第三次清潔", "action_description": "設備的正面標籤處與外殼進行最後的噴氣清潔。"}
            elif cycle <= 27: return {"part_name": "條碼掃描", "action_description": "設備上的條碼被掃描紀錄。"}
            else: return {"part_name": "裝盒入庫", "action_description": "設備被放入專屬瓦楞紙盒（包裝盒）中。"}

    def analyze_single_frame_with_context(self, image_base64: str, step_name: str) -> dict:
        return {"part_name": step_name, "action_description": f"模擬畫面驗證: 確認正在執行 {step_name}"}

    def analyze_multimodal_document(self, images_b64: list, prompt: str) -> str:
        if "候選步驟清單" in prompt or "分析與過濾任務" in prompt or "真正相關" in prompt:
            return '[{"step_number": "1-1", "part_name": "Label 前", "action_description": "雙面膠撕剝除確認Label 前 (1)~(2)"}, {"step_number": "1-3", "part_name": "MES系統", "action_description": "MES: 開啟工序管理系統x1 PCS"}, {"step_number": "1-4", "part_name": "治具", "action_description": "MES刷入工序條碼"}, {"step_number": "1-5", "part_name": "BARCODE", "action_description": "BARCODE條碼讀取 標籤序號 & 貼標籤序號"}, {"step_number": "1-6", "part_name": "Thermal PAD", "action_description": "Thermal PAD 14x20x5mm 貼於U11 IC(背面)"}, {"step_number": "1-7", "part_name": "金屬外殼", "action_description": "上蓋外殼組裝與定位"}, {"step_number": "1-8", "part_name": "BO開關", "action_description": "BO位置放置上蓋, 鎖螺絲(E1->E2->E3->E4)*4"}, {"step_number": "1-9", "part_name": "LED導光柱", "action_description": "導光LED放置於面板孔位"}, {"step_number": "2", "part_name": "S/N序號", "action_description": "S/N流水編號檢查與確認"}]'
        if "任務清單" in prompt or "標準化任務" in prompt or "步驟" in prompt:
            return '[{"step_number": "1-1", "part_name": "TB 6PIN 端子", "action_description": "將綠色端子對準設備側邊插槽並安裝到位"}, {"step_number": "1-2", "part_name": "條碼標籤", "action_description": "手持條碼掃描器進行序號讀取與黏貼"}]'
        return '{"anchor_step": "模擬基準錨點 (P.17 2-6)", "audit_results": [], "missing_steps": [], "overall_conclusion": "這是測試環境的模擬多模態稽核結果。"}'

    def generate_text(self, prompt: str, expect_json: bool = True) -> str:
        return '{"extracted_glossary": ["TB 6PIN 端子", "網路交換器"], "refined_storyboard": []}' if expect_json else "模擬純文字推論結果"

class PartnerVisionModel(BaseVisionModel):
    """
    合作廠商地端 API (假設使用相容於 OpenAI /v1/chat/completions 的格式)
    """
    def __init__(self, endpoint_url: str, model_name: str = "default"):
        url = endpoint_url.rstrip('/')
        if not url.endswith("/chat/completions"):
            if url.endswith("/v1"):
                url = f"{url}/chat/completions"
            else:
                url = f"{url}/v1/chat/completions"
        self.endpoint_url = url
        self.model_name = model_name
        self.current_video = None
        self.last_action_memory = None

    def _get_headers(self):
        headers = {"Content-Type": "application/json"}
        return headers

    def analyze_frame(self, image_base64: str, source_video: str = "", glossary: list = None) -> dict:
        if source_video and source_video != self.current_video:
            self.current_video = source_video
            self.last_action_memory = None
            
        try:
            import requests
            prompt = f"""
            你是一個專業的工業工程師，負責分析工廠作業影片。
            這是一張從影片「{source_video}」中擷取的畫面。
            請觀察畫面中的人員動作、手部操作、以及接觸的機器或零件。
            
            請務必使用「繁體中文 (Traditional Chinese)」回答。
            請回傳嚴格的 JSON 格式，包含兩個欄位：
            - "part_name": "正在被操作的主要零件或設備名稱"
            - "action_description": "發生的具體動作描述"
            
            若畫面中沒有明顯動作，可以回傳 "等待或無動作"。
            """
            if glossary:
                steps_str = "\\n".join([f"- {g}" for g in glossary])
                prompt += f"""
                
                【任務對齊指令】：
                以下是標準作業程序(SOP)的步驟清單：
                {steps_str}
                
                請務必從上述清單中，挑選出與圖片動作最吻合的「一個步驟」，並將該步驟的完整文字直接填入 "action_description" 中。若無相符步驟，請依據圖片實際情況造句。
                """
                
            if self.last_action_memory:
                prompt += f"\\n\\n💡【時間連續性提示】：前一秒（上一張影格）的動作為『{self.last_action_memory}』。如果當前畫面沒有明顯改變，請務必直接繼續回傳同樣的動作，避免動作過度破碎！"
                
            payload = {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                        ]
                    }
                ],
                "stream": False
            }
            
            auth = None
            url = self.endpoint_url
            
            response = requests.post(url, json=payload, headers=self._get_headers(), auth=auth, timeout=240)
            response.raise_for_status()
            
            result_json = response.json()
            if "choices" in result_json and len(result_json["choices"]) > 0:
                result_text = result_json["choices"][0].get("message", {}).get("content", "{}")
            else:
                result_text = "{}"
                
            import re
            import json
            match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if match:
                result_text = match.group(0)
            result = json.loads(result_text)
            
            action_desc = result.get("action_description", "未知動作")
            self.last_action_memory = action_desc
            
            return {
                "part_name": result.get("part_name", "未知零件"),
                "action_description": action_desc
            }
        except Exception as e:
            print(f"[PartnerVisionModel] API 呼叫失敗: {str(e)}")
            return {"part_name": "廠商 API 分析錯誤", "action_description": str(e)}

    def analyze_single_frame_with_context(self, image_base64: str, step_name: str) -> dict:
        try:
            import requests
            prompt = f"""
            你是一個專業的工業工程師。
            這張工廠作業畫面的任務對應工單上的步驟：「{step_name}」。
            請觀察畫面，確認人員是否正在進行此動作，並詳細描述畫面中物件的狀態。
            
            請務必使用「繁體中文 (Traditional Chinese)」回答。
            請回傳嚴格的 JSON 格式，包含兩個欄位：
            - "part_name": "{step_name}" (請直接填入此名稱)
            - "action_description": "發生的具體動作細節描述"
            """
            
            payload = {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                        ]
                    }
                ],
                "stream": False
            }
            
            auth = None
            url = self.endpoint_url
            
            response = requests.post(url, json=payload, headers=self._get_headers(), auth=auth, timeout=240)
            response.raise_for_status()
            
            result_json = response.json()
            if "choices" in result_json and len(result_json["choices"]) > 0:
                result_text = result_json["choices"][0].get("message", {}).get("content", "{}")
            else:
                result_text = "{}"
                
            import json
            import re
            match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if match:
                result_text = match.group(0)
            result_dict = json.loads(result_text)
            
            if "part_name" not in result_dict:
                result_dict["part_name"] = step_name
            if "action_description" not in result_dict:
                result_dict["action_description"] = "無動作描述"
                
            return result_dict
        except Exception as e:
            print(f"[PartnerVisionModel] 驗證呼叫失敗: {str(e)}")
            return {"part_name": step_name, "action_description": f"連線錯誤: {str(e)}"}

    def analyze_multimodal_document(self, images_b64: list, prompt: str) -> str:
        try:
            import requests
            import re
            
            content_list = [{"type": "text", "text": prompt + "\n【重要指令】：請務必且強制使用「繁體中文 (Traditional Chinese)」回答，嚴禁使用英文或簡體中文。"}]
            for b64 in images_b64:
                content_list.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
                
            payload = {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": content_list
                    }
                ],
                "stream": False
            }
            
            auth = None
            url = self.endpoint_url
            
            print(f"[PartnerVisionModel] 發送多模態文件分析 ({len(images_b64)} 張圖片)...")
            response = requests.post(url, json=payload, headers=self._get_headers(), auth=auth, timeout=300)
            response.raise_for_status()
            
            result_json = response.json()
            if "choices" in result_json and len(result_json["choices"]) > 0:
                result_text = result_json["choices"][0].get("message", {}).get("content", "{}").strip()
            else:
                result_text = "{}"
                
            match = re.search(r'\[.*\]|\{.*\}', result_text, re.DOTALL)
            if match:
                result_text = match.group(0)
                
            return result_text
        except Exception as e:
            print(f"[PartnerVisionModel] 多模態分析失敗: {str(e)}")
            import json
            return json.dumps({"error": f"廠商 API 連線或推論失敗 ({str(e)})"})

    def generate_text(self, prompt: str, expect_json: bool = True) -> str:
        try:
            import requests
            import re
            
            content_prompt = prompt
            if expect_json:
                content_prompt += "\n【重要指令】：請務必且強制使用「繁體中文 (Traditional Chinese)」回答，包含 JSON 內的所有值，嚴禁使用英文或簡體中文。"
            else:
                content_prompt += "\n【重要指令】：請務必且強制使用「繁體中文 (Traditional Chinese)」回答。"
            
            payload = {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": content_prompt
                    }
                ],
                "stream": False
            }
            
            auth = None
            url = self.endpoint_url
            
            print(f"[PartnerVisionModel] 發送純文字推論...")
            response = requests.post(url, json=payload, headers=self._get_headers(), auth=auth, timeout=300)
            response.raise_for_status()
            
            result_json = response.json()
            if "choices" in result_json and len(result_json["choices"]) > 0:
                result_text = result_json["choices"][0].get("message", {}).get("content", "{}").strip()
            else:
                result_text = "{}" if expect_json else ""
                
            if expect_json:
                match = re.search(r'\[.*\]|\{.*\}', result_text, re.DOTALL)
                if match:
                    result_text = match.group(0)
                
            return result_text
        except Exception as e:
            print(f"[PartnerVisionModel] 文字推論失敗: {str(e)}")
            if expect_json:
                return '{"error": "廠商 API 推論錯誤"}'
            return f"廠商 API 推論錯誤: {str(e)}"

# Factory pattern to get the desired model
def get_vision_model(model_type: str = "mock", **kwargs) -> BaseVisionModel:
    if model_type.lower() == "gemini":
        model_name = kwargs.get("model_name", "gemini-3.5-flash")
        return GeminiVisionModel(api_key=kwargs.get("api_key"), model_name=model_name)
    elif model_type.lower() == "ollama":
        model_name = kwargs.get("model_name", "llava-llama3")
        return OllamaVisionModel(model_name=model_name)
    elif model_type.lower() == "mock":
        return MockVisionModel(api_key=kwargs.get("api_key"))
    elif model_type.lower() == "partner":
        return PartnerVisionModel(
            endpoint_url=kwargs.get("endpoint_url"),
            model_name=kwargs.get("model_name", "default")
        )
    else:
        raise ValueError(f"不支援的模型類型: {model_type}")
