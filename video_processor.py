import cv2
import os
import base64
import numpy as np
try:
    import mediapipe as mp
    mp_hands = mp.solutions.hands
except (ImportError, AttributeError):
    mp = None
    mp_hands = None

class VideoProcessor:
    def __init__(self, video_path: str):
        self.video_path = video_path

    def get_duration(self) -> float:
        """取得影片總長度 (秒)"""
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            return 0.0
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        return total_frames / fps if fps > 0 else 0.0

    def get_video_cover(self) -> str:
        """快速讀取影片第一幀作為封面，回傳 Base64 字串"""
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            return ""
            
        ret, frame = cap.read()
        cap.release()
        
        if ret:
            frame = cv2.resize(frame, (640, 360))
            _, buffer = cv2.imencode('.jpg', frame)
            return base64.b64encode(buffer).decode('utf-8')
        return ""

    def _get_motion_bounding_box(self, cap, time_sec, fps, padding=150, top_exclusion_ratio=0.25):
        """利用畫面相減找出動態區域的 bounding box"""
        # 抓取前 0.5 秒的畫面
        prev_time = max(0.0, time_sec - 0.5)
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(prev_time * fps))
        ret_prev, frame_prev = cap.read()
        
        # 抓取當前畫面
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(time_sec * fps))
        ret_curr, frame_curr = cap.read()
        
        if not ret_prev or not ret_curr:
            return None, None
            
        # 轉灰階並模糊化處理
        gray_prev = cv2.cvtColor(frame_prev, cv2.COLOR_BGR2GRAY)
        gray_curr = cv2.cvtColor(frame_curr, cv2.COLOR_BGR2GRAY)
        gray_prev = cv2.GaussianBlur(gray_prev, (21, 21), 0)
        gray_curr = cv2.GaussianBlur(gray_curr, (21, 21), 0)
        
        # 計算差異
        frame_diff = cv2.absdiff(gray_prev, gray_curr)
        _, thresh = cv2.threshold(frame_diff, 25, 255, cv2.THRESH_BINARY)
        # 恢復適度的 dilate，避免將遠處的大型干擾物(如紙箱)與手部強制融合
        thresh = cv2.dilate(thresh, None, iterations=2)
        
        # 找出輪廓
        contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            return None, frame_curr
            
        h, w = frame_curr.shape[:2]
        
        valid_contours = []
        for contour in contours:
            if cv2.contourArea(contour) < 200: # 稍微提高雜訊過濾門檻
                continue
            
            # 過濾掉畫面上方的動態 (排除背景人員與頭部)
            x, y, cw, ch = cv2.boundingRect(contour)
            if y < h * top_exclusion_ratio:
                continue
                
            valid_contours.append(contour)
            
        if not valid_contours:
            return None, frame_curr
            
        # 依面積排序，取最大的前 5 個動態區域 (確保能同時涵蓋雙手、零件，而不是只死鎖在單一最大物件上)
        valid_contours = sorted(valid_contours, key=cv2.contourArea, reverse=True)[:5]
            
        x_min, y_min = w, h
        x_max, y_max = 0, 0
        for contour in valid_contours:
            x, y, cw, ch = cv2.boundingRect(contour)
            x_min = min(x_min, x)
            y_min = min(y_min, y)
            x_max = max(x_max, x + cw)
            y_max = max(y_max, y + ch)
            
        # 加入 padding，並確保不超出邊界
        x_min = max(0, x_min - padding)
        y_min = max(0, y_min - padding)
        x_max = min(w, x_max + padding)
        y_max = min(h, y_max + padding)
        
        return (x_min, y_min, x_max, y_max), frame_curr

    def extract_and_crop_hands(self, time_sec: float, padding: int = 150, top_exclusion_ratio: float = 0.25) -> dict:
        """抽取指定秒數畫面並偵測雙手座標進行智能裁切"""
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            return None
            
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_idx = int(time_sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        
        ret, frame = cap.read()
        
        if not ret:
            cap.release()
            return None
            
        cropped = False
        # 第一防線：進行 MediaPipe 手部偵測
        try:
            if mp_hands:
                with mp_hands.Hands(static_image_mode=True, max_num_hands=2, min_detection_confidence=0.3) as hands:
                    img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = hands.process(img_rgb)
                    
                    if results and results.multi_hand_landmarks:
                        h, w, _ = frame.shape
                        x_min, y_min = w, h
                        x_max, y_max = 0, 0
                        
                        for hand_landmarks in results.multi_hand_landmarks:
                            for lm in hand_landmarks.landmark:
                                x, y = int(lm.x * w), int(lm.y * h)
                                x_min = min(x_min, x)
                                y_min = min(y_min, y)
                                x_max = max(x_max, x)
                                y_max = max(y_max, y)
                                
                        # 加入 padding，並確保不超出邊界
                        x_min = max(0, x_min - padding)
                        y_min = max(0, y_min - padding)
                        x_max = min(w, x_max + padding)
                        y_max = min(h, y_max + padding)
                        
                        # 進行裁切
                        frame = frame[y_min:y_max, x_min:x_max]
                        cropped = True
                        print(f"[VideoProcessor] 成功偵測裸手，裁切畫面大小: {frame.shape[1]}x{frame.shape[0]}")
        except Exception as e:
            print(f"[VideoProcessor] 手部偵測發生例外: {e}")
            
        # 第二防線：若找不到手，改用動態相減追蹤
        if not cropped:
            box, curr_frame = self._get_motion_bounding_box(cap, time_sec, fps, padding, top_exclusion_ratio)
            if box and curr_frame is not None:
                x_min, y_min, x_max, y_max = box
                frame = curr_frame[y_min:y_max, x_min:x_max]
                print(f"[VideoProcessor] 成功偵測動態區域(手套防護網)，裁切畫面大小: {frame.shape[1]}x{frame.shape[0]}")
            else:
                if curr_frame is not None:
                    frame = curr_frame
                print(f"[VideoProcessor] 未偵測到手部與明顯動態，使用原始畫面")
                
        cap.release()
            
        # 調整大小以節省 API 負擔與 GPU 記憶體 (最長邊不超過 640，大幅降低 ViT Token 與運算時間)
        orig_h, orig_w = frame.shape[:2]
        if max(orig_h, orig_w) > 640:
            scale = 640 / max(orig_h, orig_w)
            frame = cv2.resize(frame, (int(orig_w * scale), int(orig_h * scale)))
            
        _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        img_b64 = base64.b64encode(buffer).decode('utf-8')
        
        return {
            "time_sec": time_sec,
            "image_base64": img_b64
        }

    def preview_hand_crop(self, padding: int = 150, top_exclusion_ratio: float = 0.25):
        """用於 UI 預覽：在原始畫面上畫出紅框(裸手)或綠框(動態)，展示系統判定保留的裁切範圍"""
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            return None
            
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        duration = total_frames / fps
        midpoint = duration / 2.0
        
        start_scan = max(0.0, midpoint - 3.0)
        end_scan = min(duration, midpoint + 3.0)
        
        hands_detector = None
        if mp_hands:
            try:
                hands_detector = mp_hands.Hands(static_image_mode=True, max_num_hands=2, min_detection_confidence=0.3)
            except Exception:
                pass
                
        try:
            # 掃描中間正負 3 秒，每 0.5 秒抽一張
            for time_sec in np.arange(start_scan, end_scan + 0.5, 0.5):
                frame_idx = int(time_sec * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                
                ret, frame = cap.read()
                if not ret:
                    continue
                    
                # 第一防線：MediaPipe 偵測裸手
                if hands_detector:
                    img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = hands_detector.process(img_rgb)
                    
                    if results and results.multi_hand_landmarks:
                        h, w, _ = frame.shape
                        x_min, y_min = w, h
                        x_max, y_max = 0, 0
                        
                        for hand_landmarks in results.multi_hand_landmarks:
                            for lm in hand_landmarks.landmark:
                                x, y = int(lm.x * w), int(lm.y * h)
                                x_min = min(x_min, x)
                                y_min = min(y_min, y)
                                x_max = max(x_max, x)
                                y_max = max(y_max, y)
                                
                        x_min = max(0, x_min - padding)
                        y_min = max(0, y_min - padding)
                        x_max = min(w, x_max + padding)
                        y_max = min(h, y_max + padding)
                        
                        cv2.rectangle(img_rgb, (x_min, y_min), (x_max, y_max), (255, 0, 0), 5)
                        orig_h, orig_w = img_rgb.shape[:2]
                        if max(orig_h, orig_w) > 800:
                            scale = 800 / max(orig_h, orig_w)
                            img_rgb = cv2.resize(img_rgb, (int(orig_w * scale), int(orig_h * scale)))
                        cap.release()
                        if hands_detector:
                            hands_detector.close()
                        return img_rgb

                # 第二防線：動態追蹤 (OpenCV)
                box, curr_frame = self._get_motion_bounding_box(cap, time_sec, fps, padding, top_exclusion_ratio)
                if box and curr_frame is not None:
                    x_min, y_min, x_max, y_max = box
                    img_rgb = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2RGB)
                    # 畫上綠框，代表 OpenCV 動態追蹤成功 (可能戴手套)
                    cv2.rectangle(img_rgb, (x_min, y_min), (x_max, y_max), (0, 255, 0), 5)
                    orig_h, orig_w = img_rgb.shape[:2]
                    if max(orig_h, orig_w) > 800:
                        scale = 800 / max(orig_h, orig_w)
                        img_rgb = cv2.resize(img_rgb, (int(orig_w * scale), int(orig_h * scale)))
                    cap.release()
                    if hands_detector:
                        hands_detector.close()
                    return img_rgb
                else:
                    print(f"[VideoProcessor] time_sec {time_sec} motion box failed")
                    
        except Exception as e:
            import traceback
            err = traceback.format_exc()
            print(f"[VideoProcessor] Exception in preview_hand_crop: {e}")
            if hands_detector:
                hands_detector.close()
            cap.release()
            return f"Error: {e}\n{err}"
            
        if hands_detector:
            hands_detector.close()
        cap.release()
        return None

    def extract_keyframes(self, interval_seconds: float = 2.0, use_scene_detection: bool = False, time_offset: float = 0.0, max_frames: int = 30):
        """
        從影片中擷取關鍵影格。
        """
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            raise ValueError(f"無法開啟影片檔案: {self.video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30.0

        interval_frames = int(fps * interval_seconds)
        if interval_frames <= 0:
            interval_frames = 1
            
        keyframes = []
        prev_frame_gray = None
        threshold = 20.0  # 調降場景切換閾值，更敏感

        current_frame = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            time_sec = (current_frame / fps) + time_offset
            save_frame = False

            if use_scene_detection:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if prev_frame_gray is None:
                    save_frame = True
                else:
                    diff = cv2.absdiff(gray, prev_frame_gray)
                    mean_diff = np.mean(diff)
                    if mean_diff > threshold:
                        save_frame = True
                prev_frame_gray = gray
            else:
                if current_frame % interval_frames == 0:
                    save_frame = True

            if save_frame:
                # 關鍵優化：對 AI 進行 640px 輕量化縮放，減少 75% ViT Token，加速 4~8 倍！
                orig_h, orig_w = frame.shape[:2]
                if max(orig_h, orig_w) > 640:
                    scale = 640 / max(orig_h, orig_w)
                    frame = cv2.resize(frame, (int(orig_w * scale), int(orig_h * scale)))
                    
                _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                img_base64 = base64.b64encode(buffer).decode('utf-8')
                
                keyframes.append({
                    "time_sec": round(time_sec, 2),
                    "image_base64": img_base64,
                    "frame_idx": current_frame
                })

            current_frame += 1

        cap.release()
        
        # 智慧限速保護：若影格總數超過 max_frames (預設 30 張)，等比均勻採樣，大幅加速地端模型推論！
        if max_frames and max_frames > 0 and len(keyframes) > max_frames:
            step = len(keyframes) / float(max_frames)
            sampled_keyframes = [keyframes[int(i * step)] for i in range(max_frames)]
            print(f"[VideoProcessor] 觸發智慧限速保護：原始 {len(keyframes)} 張影格已均勻採樣收斂至 {len(sampled_keyframes)} 張。")
            keyframes = sampled_keyframes

        print(f"[VideoProcessor] 成功從影片擷取 {len(keyframes)} 張關鍵影格。")
        return keyframes

    def extract_video_clip(self, target_time: float, output_path: str, margin: float = 1.5):
        """
        從影片中精準裁切 target_time - margin 到 target_time + margin 的片段。
        儲存為 mp4 格式。
        """
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            print(f"[VideoProcessor] 無法開啟影片檔案: {self.video_path}")
            return False

        fps = cap.get(cv2.CAP_PROP_FPS)
        width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        if fps <= 0: fps = 30.0

        start_time = max(0, target_time - margin)
        end_time = target_time + margin
        
        start_frame = int(start_time * fps)
        end_frame = int(end_time * fps)
        
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        
        # Windows 上使用 'mp4v' 或 'avc1'
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        
        current_frame = start_frame
        while current_frame <= end_frame:
            ret, frame = cap.read()
            if not ret:
                break
            out.write(frame)
            current_frame += 1
            
        out.release()
        cap.release()
        print(f"[VideoProcessor] 已成功匯出精華短片: {output_path} ({start_time:.1f}s ~ {end_time:.1f}s)")
        return True
