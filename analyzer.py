import json

class StoryboardAnalyzer:
    def __init__(self, vision_model):
        """
        Args:
            vision_model (BaseVisionModel): 已經初始化的視覺模型 (例如 Gemma 或 Qwen)
        """
        self.vision_model = vision_model

    def analyze_video_frames(self, keyframes: list, progress_callback=None, glossary: list = None) -> list:
        """
        將擷取出的關鍵影格送入模型進行分析，並合併連續相同動作的時間區段。
        
        Args:
            keyframes (list): 來自 VideoProcessor 的影格列表
            progress_callback (callable): 進度回報函式 (可選)
            glossary (list): 選擇性傳入的 SOP 專業術語清單
        
        Returns:
            list of dict: 分鏡稿資料 (含起訖時間、零件、動作描述、截圖)
        """
        total_frames = len(keyframes)
        print(f"[Analyzer] 開始分析 {total_frames} 張影格 (採用批次處理以節省 API 額度)...")
        
        # 呼叫批次處理 API (一次發送所有圖片)
        raw_results = self.vision_model.analyze_frames_batch(keyframes, progress_callback, glossary=glossary)

        # 將相鄰且「動作/零件相同」的影格進行合併，計算「持續時間」
        storyboard = self._merge_consecutive_actions(raw_results)
        return storyboard

    def analyze_time_driven_frames(self, keyframes: list, progress_callback=None) -> list:
        """
        針對已經依據標準工時裁切好的單張代表影格，進行精確驗證分析。
        無需進行動作合併，直接輸出。
        """
        total_frames = len(keyframes)
        print(f"[Analyzer] 開始進行工單驅動分析 ({total_frames} 張代表影格)...")
        
        storyboard = []
        for idx, frame in enumerate(keyframes):
            if progress_callback:
                progress_callback(idx, total_frames)
                
            result = self.vision_model.analyze_single_frame_with_context(
                image_base64=frame["image_base64"],
                step_name=frame["step_name"]
            )
            
            storyboard.append({
                "time_sec": frame["start_time"],
                "start_time": frame["start_time"],
                "end_time": frame["end_time"],
                "duration": frame["std_duration"],
                "std_duration": frame["std_duration"],
                "duration_diff": 0.0,
                "source_video": frame["source_video"],
                "part_name": result.get("part_name", frame["step_name"]),
                "action_description": result.get("action_description", ""),
                "image_base64": frame["image_base64"]
            })
            
        return storyboard

    def _merge_consecutive_actions(self, raw_results: list) -> list:
        if not raw_results:
            return []

        merged = []
        current_action = raw_results[0].copy()
        current_action["start_time"] = current_action["time_sec"]
        current_action["end_time"] = current_action["time_sec"]
        
        for i in range(1, len(raw_results)):
            frame = raw_results[i]
            
            # 若零件或動作描述與上一個影格相同，並且「來源影片也相同」，視為同一個動作持續進行
            if (frame.get("source_video") == current_action.get("source_video") and
                frame["part_name"] == current_action["part_name"] and 
                frame["action_description"] == current_action["action_description"]):
                # 更新結束時間
                current_action["end_time"] = frame["time_sec"]
            else:
                # 動作改變或跨影片，結算上一個動作並推入列表
                current_action["duration"] = round(current_action["end_time"] - current_action["start_time"] + 1, 2)
                merged.append(current_action)
                
                # 開啟新的動作區段
                current_action = frame.copy()
                current_action["start_time"] = frame["time_sec"]
                current_action["end_time"] = frame["time_sec"]

        # 結算最後一個動作
        current_action["duration"] = round(current_action["end_time"] - current_action["start_time"] + 1, 2)
        merged.append(current_action)

        print(f"[Analyzer] 分析完成，共梳理出 {len(merged)} 個連續動作分鏡。")
        return merged
