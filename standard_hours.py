import json
import csv
import os

class StandardHoursIntegrator:
    def __init__(self, file_path: str = None):
        """
        初始化標準工時對照模組。
        支援 JSON 或 CSV 格式。
        """
        self.file_path = file_path
        self.std_hours_data = self._load_data() if file_path else {}

    def _load_data(self) -> list:
        """
        讀取標準工時檔案並轉換為依序排列的區段清單。
        支援 CSV 格式 (name, seconds)。
        """
        if not os.path.exists(self.file_path):
            print(f"[StandardHours] 找不到檔案: {self.file_path}")
            return []

        ext = os.path.splitext(self.file_path)[1].lower()
        segments = []
        current_time = 0.0

        try:
            if ext == '.csv':
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        key = row.get('name', '').strip()
                        val = row.get('seconds', '0').strip()
                        if key and val.replace('.', '', 1).isdigit():
                            duration = float(val)
                            segments.append({
                                "step_name": key,
                                "duration": duration,
                                "start_time": current_time,
                                "end_time": current_time + duration
                            })
                            current_time += duration
            elif ext == '.json':
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for key, val in data.items():
                        duration = float(val)
                        segments.append({
                            "step_name": key,
                            "duration": duration,
                            "start_time": current_time,
                            "end_time": current_time + duration
                        })
                        current_time += duration
            else:
                print(f"[StandardHours] 不支援的檔案格式: {ext}")
        except Exception as e:
            print(f"[StandardHours] 讀取標準工時失敗: {e}")

        print(f"[StandardHours] 成功載入 {len(segments)} 筆標準工時片段，總長度 {current_time} 秒。")
        return segments

    def get_time_segments(self) -> list:
        return self.std_hours_data

    def compare_and_annotate(self, storyboard_data: list) -> list:
        """
        將初步分析的分鏡稿資料與標準工時進行比對，標註差異。
        這支函式保留給舊架構使用。在新架構中，我們會直接依賴 get_time_segments()。
        """
        if not self.std_hours_data:
            for item in storyboard_data:
                item["std_duration"] = None
                item["duration_diff"] = None
                item["is_abnormal"] = False
            return storyboard_data

        for item in storyboard_data:
            # 嘗試使用「零件名稱」或「動作描述」作為 Key 去尋找標準工時
            key_part = item.get("part_name", "")
            key_action = item.get("action_description", "")
            
            std_time = self.std_hours_data.get(key_action) or self.std_hours_data.get(key_part)
            
            if std_time is not None:
                actual_time = item.get("duration", 0.0)
                diff = round(actual_time - std_time, 2)
                
                item["std_duration"] = std_time
                item["duration_diff"] = diff
                # 若差異超過標準工時的 20%，標記為異常
                item["is_abnormal"] = abs(diff) > (std_time * 0.2)
            else:
                item["std_duration"] = None
                item["duration_diff"] = None
                item["is_abnormal"] = False

        return storyboard_data
