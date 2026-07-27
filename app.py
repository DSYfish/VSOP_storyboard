import streamlit as st
import time
import os
import base64
import importlib
from io import BytesIO

st.set_page_config(
    page_title="分鏡稿自動生成系統",
    page_icon="🎬",
    layout="wide"
)

def move_up(index):
    if index > 0:
        st.session_state.video_list[index], st.session_state.video_list[index-1] = st.session_state.video_list[index-1], st.session_state.video_list[index]

def move_down(index):
    if index < len(st.session_state.video_list) - 1:
        st.session_state.video_list[index], st.session_state.video_list[index+1] = st.session_state.video_list[index+1], st.session_state.video_list[index]

def main():
    # --- Sidebar 設定區 ---
    with st.sidebar:
        st.header("⚙️ 系統設定")
        model_selection = st.selectbox("視覺模型選擇", ["gemini", "ollama (地端模型)", "mock (測試模擬器)", "partner (合作廠商地端API)"])
        
        gemini_model_version = "gemini-3.5-flash"
        ollama_model_version = "llava-llama3"
        
        if model_selection == "gemini":
            gemini_model_version = st.selectbox("Gemini 模型版本 (若遇到 404 可嘗試切換)", [
                "gemini-3.5-flash",
                "gemini-3.1-flash-lite",
                "gemini-2.5-flash",
                "gemini-2.0-flash",
                "gemini-flash-latest",
                "gemini-pro-latest"
            ])
        elif "ollama" in model_selection:
            import models
            ollama_models = models.get_available_ollama_models()
            if ollama_models:
                default_idx = 0
                for i, m in enumerate(ollama_models):
                    if "minicpm-v" in m.lower() or "qwen2.5-vl" in m.lower():
                        default_idx = i
                        break
                    elif "34b" in m.lower():
                        default_idx = i
                    elif "llava" in m.lower():
                        if default_idx == 0:
                            default_idx = i
                ollama_model_version = st.selectbox("Ollama 模型選擇", ollama_models, index=default_idx)
                st.caption("提示：已自動偵測本機 Ollama 安裝的模型")
            else:
                st.warning("⚠️ 無法連線至本機 Ollama，請確認 Ollama 已啟動。")
                ollama_model_version = st.text_input("Ollama 模型名稱", value="llava-llama3")
        elif "partner" in model_selection:
            partner_api_url = st.text_input("廠商 API 端點 URL", value="http://192.168.0.184:8000/")
            partner_model_name = st.text_input("模型名稱 (選填)", value="default")
            
        st.markdown("---")
        
        # 從安全設定檔讀取 API Key
        api_key_input = ""
        try:
            if "GEMINI_API_KEY" in st.secrets:
                api_key_input = st.secrets["GEMINI_API_KEY"]
                st.success("🔒 API Key 已從安全設定檔中自動載入。")
            else:
                st.warning("⚠️ 未偵測到 API Key。請確保在 `.streamlit/secrets.toml` 中設定。")
        except Exception:
            st.warning("⚠️ 未建立 `.streamlit/secrets.toml` 設定檔。若您要使用 Gemini，請手動建立或在介面輸入 API Key（若介面有提供）。")
    
    st.title("🎬 分鏡稿自動生成系統")
    st.markdown("透過視覺 AI 分析影片，自動擷取關鍵動作、零件辨識，並產生標準工時比對的分鏡稿。")
    
    st.divider()

    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.subheader("📁 上傳檔案區")
        
        # 1. Video Upload (Required, Multi-files)
        video_files = st.file_uploader("上傳影片檔案 (必填，可多選)", type=["mp4", "avi", "mov", "mkv"], accept_multiple_files=True)
        
        # 2. Standard Hours (Optional)
        std_hours_file = st.file_uploader("上傳標準工時檔案 (選填)", type=["csv", "xlsx", "json"])
        
        # 3. SOP Document (Optional)
        sop_file = st.file_uploader("上傳 SOP 作業指導書 (選填)", type=["txt", "json", "pdf", "csv"])
        
        parse_mode_selection = "leonton"
        if sop_file and sop_file.name.lower().endswith(".pdf"):
            parse_mode_ui = st.selectbox(
                "SOP 解析模式",
                options=["[嚴格鎖定] 連易通專用格式", "[通用智慧] 廠商萬用格式"],
                help="若上傳的是連易通標準四欄位格式，請選 [嚴格鎖定] 以獲取 100% 精準度。若是外來廠商格式，請選 [通用智慧] 讓 AI 自行理解。"
            )
            parse_mode_selection = "leonton" if "嚴格鎖定" in parse_mode_ui else "general"
            
            if st.button("📄 預覽 PDF 萃取結果 (分析前 3 頁)", help="使用目前的 Vision AI 設定，試抓 PDF 前 3 頁的步驟與零件，方便您確認 AI 是否抓對。"):
                st.session_state.pdf_preview_requested = True
            
            pdf_preview_ui_container = st.container()
        
        # 4. Report Name (Optional)
        report_name_input = st.text_input("自訂分鏡稿報表名稱 (選填)", placeholder="若留空，將預設使用工時檔名")
        
        st.subheader("⚙️ 擷取設定")
        use_dynamic_clipping = st.checkbox("啟用目標式動態裁切 (前後 1.5 秒影片)", value=True, help="若上傳 SOP，系統會自動在精確秒數裁切出短片，而非單張靜態圖片。")
        
        if "pad_slider" not in st.session_state:
            st.session_state.pad_slider = 150
            st.session_state.pad_input = 150
        if "top_slider" not in st.session_state:
            st.session_state.top_slider = 25
            st.session_state.top_input = 25
        if "int_slider" not in st.session_state:
            st.session_state.int_slider = 1.0
            st.session_state.int_input = 1.0

        def sync_padding(source):
            if source == 'slider':
                st.session_state.pad_input = st.session_state.pad_slider
            else:
                st.session_state.pad_slider = st.session_state.pad_input
                
        def sync_top(source):
            if source == 'slider':
                st.session_state.top_input = st.session_state.top_slider
            else:
                st.session_state.top_slider = st.session_state.top_input
                
        def sync_interval(source):
            if source == 'slider':
                st.session_state.int_input = st.session_state.int_slider
            else:
                st.session_state.int_slider = st.session_state.int_input

        col_int1, col_int2 = st.columns([3, 1])
        with col_int1:
            st.slider("預設擷取精細度 (無 SOP 時生效)", min_value=0.25, max_value=5.00, step=0.25, format="%.2f", key="int_slider", on_change=sync_interval, args=('slider',))
        with col_int2:
            st.number_input("秒數 (0.25-5.00)", min_value=0.25, max_value=5.00, step=0.25, format="%.2f", key="int_input", on_change=sync_interval, args=('input',))
            
        interval_seconds = st.session_state.int_slider

        st.subheader("👐 手部追蹤邊界設定")

        col1, col2 = st.columns([3, 1])
        with col1:
            st.slider("雙手向外擴展範圍 (Padding Pixels)", min_value=0, max_value=500, step=10, key="pad_slider", on_change=sync_padding, args=('slider',), help="設定偵測到雙手後，向外擴展多少像素來包圍手中的零件。範圍越小 AI 越專注，但可能切到大零件。")
        with col2:
            st.number_input("數值 (0-500)", min_value=0, max_value=500, step=10, key="pad_input", on_change=sync_padding, args=('input',))

        col3, col4 = st.columns([3, 1])
        with col3:
            st.slider("上方排除區域 (%)", min_value=0, max_value=70, step=5, key="top_slider", on_change=sync_top, args=('slider',), help="忽略畫面上方多少比例的動態（用於排除背景同事走動或頭部動作）。預設 25%。")
        with col4:
            st.number_input("數值 (0-70)", min_value=0, max_value=70, step=5, key="top_input", on_change=sync_top, args=('input',))

        hand_crop_padding = st.session_state.pad_slider
        top_exclusion = st.session_state.top_slider
        
        if st.button("👁️ 預覽手部裁切範圍", help="掃描影片中間片段，找到手部後展示裁切框的位置。"):
            st.session_state.hand_crop_requested = True
            
        hand_crop_ui_container = st.container()

    with col_right:
        st.subheader("🎞️ 影片處理順序與預覽")
        
        # 將上傳的檔案同步到 session_state 進行排序管理
        if "uploaded_filenames" not in st.session_state or set(f.name for f in video_files) != st.session_state.uploaded_filenames:
            # 有新的檔案上傳或刪除，重新整理清單
            st.session_state.uploaded_filenames = set(f.name for f in video_files)
            # 將檔案存入暫存以供讀取封面
            st.session_state.video_list = []
            
            for f in video_files:
                temp_path = f"temp_{f.name}"
                f.seek(0) # 確保讀取指標在最前面，避免串流讀取到 0 byte
                with open(temp_path, "wb") as out:
                    out.write(f.read())
                st.session_state.video_list.append({
                    "name": f.name,
                    "path": temp_path,
                    "file_obj": f
                })

        if not st.session_state.video_list:
            st.info("尚未上傳影片。上傳後將顯示於此，供您預覽並調整順序。")
        else:
            from video_processor import VideoProcessor
            import base64
            
            for idx, v_item in enumerate(st.session_state.video_list):
                with st.container():
                    c1, c2, c3 = st.columns([2, 5, 2])
                    
                    # 取得封面
                    vp = VideoProcessor(v_item["path"])
                    cover_b64 = vp.get_video_cover()
                    
                    with c1:
                        if cover_b64:
                            # 改用原生 st.image 取代 HTML tag，避免被安全機制濾除
                            st.image(base64.b64decode(cover_b64), use_container_width=True)
                        else:
                            st.write("無封面")
                    
                    with c2:
                        st.markdown(f"**順序 {idx + 1}**: {v_item['name']}")
                    
                    with c3:
                        st.button("⬆️", key=f"up_{idx}", on_click=move_up, args=(idx,), disabled=(idx == 0))
                        st.button("⬇️", key=f"down_{idx}", on_click=move_down, args=(idx,), disabled=(idx == len(st.session_state.video_list)-1))
                    
                    st.divider()

    st.divider()
    
    # Submit Button
    if st.button("🚀 開始分析", type="primary", use_container_width=True):
        if not st.session_state.video_list:
            st.error("❌ 錯誤：影片檔案為必填項目！請先上傳影片。")
        else:
            st.success("檔案準備完畢！開始多部影片合併分析流程...")
            
            temp_std_path = None
            if std_hours_file:
                temp_std_path = f"temp_{std_hours_file.name}"
                with open(temp_std_path, "wb") as f:
                    f.write(std_hours_file.read())

            temp_sop_path = None
            if sop_file:
                temp_sop_path = f"temp_{sop_file.name}"
                with open(temp_sop_path, "wb") as f:
                    f.write(sop_file.read())

            progress_bar = st.progress(0, text="系統處理中，請稍候...")

            # 防呆機制：若選擇真實 AI 但未輸入 API Key，阻擋執行
            if "mock" not in model_selection and "ollama" not in model_selection and "partner" not in model_selection and not api_key_input:
                st.error("⚠️ 請確保已在 `.streamlit/secrets.toml` 中設定 API Key，或切換為「測試模擬器」/「Ollama地端模型」/「合作廠商地端API」。")
                return

            try:
                # 1. 初始化模型
                import models
                importlib.reload(models)
                from models import get_vision_model
                
                # 處理 model_selection 的字串
                if "mock" in model_selection:
                    model_type_parsed = "mock"
                elif "ollama" in model_selection:
                    model_type_parsed = "ollama"
                elif "partner" in model_selection:
                    model_type_parsed = "partner"
                else:
                    model_type_parsed = "gemini"
                
                # 確保 API Key 沒有夾帶換行或空白字元，避免 gRPC 發生 Illegal header value 錯誤
                safe_api_key = api_key_input.strip() if api_key_input else ""
                
                if model_type_parsed == "partner":
                    vision_model = get_vision_model(
                        model_type=model_type_parsed,
                        endpoint_url=partner_api_url,
                        model_name=partner_model_name
                    )
                else:
                    vision_model = get_vision_model(
                        model_type=model_type_parsed, 
                        api_key=safe_api_key,
                        model_name=gemini_model_version if model_type_parsed == "gemini" else ollama_model_version
                    )
                
                import analyzer as analyzer_mod
                importlib.reload(analyzer_mod)
                from analyzer import StoryboardAnalyzer
                analyzer = StoryboardAnalyzer(vision_model)
                
                # 準備 progress callback 讓使用者知道進度
                def analysis_progress(idx, total):
                    # 畫面分析進度從 50% 開始，到 90% 結束
                    percent_complete = 50 + int((idx / total) * 40)
                    progress_bar.progress(percent_complete, text=f"正在打包第 {idx+1}/{total} 張截圖... (為節省免費用戶額度，將採用「單次批次發送」)")

                # 3. 畫面分析 (全域分析 vs 工單驅動分析)
                import video_processor
                importlib.reload(video_processor)
                from video_processor import VideoProcessor
                import standard_hours
                importlib.reload(standard_hours)
                from standard_hours import StandardHoursIntegrator

                std_integrator = StandardHoursIntegrator(temp_std_path) if temp_std_path else None
                time_segments = std_integrator.get_time_segments() if std_integrator else []

                refined_storyboard = []
                all_keyframes = []

                if time_segments:
                    # ==========================================
                    # 新架構：工單驅動時間軸 (Standard Hours Driven Slicing)
                    # ==========================================
                    progress_bar.progress(20, text="正在建立全域時間軸對應表...")
                    
                    global_timeline = []
                    current_global_time = 0.0
                    for v_item in st.session_state.video_list:
                        vp = VideoProcessor(v_item["path"])
                        duration = vp.get_duration()
                        global_timeline.append({
                            "video_name": v_item["name"],
                            "video_path": v_item["path"],
                            "start_time": current_global_time,
                            "end_time": current_global_time + duration
                        })
                        current_global_time += duration
                    
                    keyframes_for_ai = []
                    for seg_idx, seg in enumerate(time_segments):
                        midpoint = (seg["start_time"] + seg["end_time"]) / 2.0
                        target_video = None
                        relative_time = 0.0
                        for timeline in global_timeline:
                            if timeline["start_time"] <= midpoint < timeline["end_time"]:
                                target_video = timeline
                                relative_time = midpoint - timeline["start_time"]
                                break
                        
                        if not target_video and global_timeline:
                            target_video = global_timeline[-1]
                            vp_temp = VideoProcessor(target_video["video_path"])
                            relative_time = max(0, vp_temp.get_duration() - 0.5)

                        if target_video:
                            progress_bar.progress(30 + int((seg_idx/len(time_segments))*20), text=f"正在抽取工單步驟「{seg['step_name']}」的代表影格(含手部智能裁切)...")
                            vp = VideoProcessor(target_video["video_path"])
                            frame_data = vp.extract_and_crop_hands(relative_time, padding=hand_crop_padding, top_exclusion_ratio=top_exclusion / 100.0)
                            if frame_data:
                                keyframes_for_ai.append({
                                    "time_sec": midpoint,
                                    "image_base64": frame_data["image_base64"],
                                    "source_video": target_video["video_name"],
                                    "step_name": seg["step_name"],
                                    "start_time": seg["start_time"],
                                    "end_time": seg["end_time"],
                                    "std_duration": seg["duration"]
                                })
                    
                    progress_bar.progress(60, text=f"正在呼叫 AI 進行精確驗證 (共 {len(keyframes_for_ai)} 張)...")
                    refined_storyboard = analyzer.analyze_time_driven_frames(keyframes_for_ai, progress_callback=analysis_progress)
                else:
                    # ==========================================
                    # 舊架構：盲抽分析 (Fallback)
                    # ==========================================
                    progress_bar.progress(50, text="AI 視覺模型全域分析準備中...")
                    current_time_offset = 0.0
                    total_videos = len(st.session_state.video_list)
                    for i, v_item in enumerate(st.session_state.video_list):
                        progress_text = f"正在擷取第 {i+1}/{total_videos} 部影片: {v_item['name']}"
                        progress_bar.progress(10 + int((i/total_videos)*30), text=progress_text)
                        
                        vp = VideoProcessor(v_item["path"])
                        frames = vp.extract_keyframes(interval_seconds=interval_seconds, time_offset=0.0)
                        
                        for f in frames:
                            f["source_video"] = v_item["name"]
                            
                        all_keyframes.extend(frames)

                    glossary = []
                    if temp_sop_path and os.path.exists(temp_sop_path):
                        progress_bar.progress(50, text="正在萃取 SOP 專業術語...")
                        import sop_task_planner
                        importlib.reload(sop_task_planner)
                        from sop_task_planner import SOPTaskPlanner
                        
                        planner = SOPTaskPlanner(vision_model=vision_model)
                        tasks = []
                        if temp_sop_path.lower().endswith('.pdf'):
                            tasks = planner.plan_tasks_from_pdf_vision(temp_sop_path, parse_mode=parse_mode_selection)
                        
                        if not tasks:
                            sop_text = planner.extract_text_content(temp_sop_path)
                            if not sop_text.startswith("錯誤"):
                                tasks = planner.plan_tasks_from_sop(sop_text)
                                
                        if tasks:
                            for t in tasks:
                                part = t.get("part_name", "").strip()
                                action = t.get("action_description", "").strip()
                                if part and part not in glossary:
                                    glossary.append(part)
                                if action and action not in glossary:
                                    glossary.append(action)
                        
                        if not glossary:
                            st.warning("⚠️ 無法萃取到 SOP 專有名詞，維持標準影像分析模式。")
                    
                    progress_bar.progress(60, text="正在進行影像分析...")
                    refined_storyboard = analyzer.analyze_video_frames(all_keyframes, progress_callback=analysis_progress, glossary=glossary if glossary else None)
                        
                # 執行影片動態裁切 (針對最終保留的分鏡)
                progress_bar.progress(80, text="正在產生影片片段...")
                from video_processor import VideoProcessor
                for i, frame in enumerate(refined_storyboard):
                    clip_path = None
                    src_vid = frame.get("source_video", "")
                    t_sec = frame.get("time_sec", 0)
                    if "start_time" in frame:
                        t_sec = frame["start_time"]
                        
                    if use_dynamic_clipping and src_vid:
                        vid_path = next((v["path"] for v in st.session_state.video_list if v["name"] == src_vid), None)
                        if vid_path:
                            clip_path = f"temp_clips/clip_task_{i+1}.mp4"
                            vp = VideoProcessor(vid_path)
                            vp.extract_video_clip(t_sec, clip_path, margin=1.5)
                    frame["video_clip_path"] = clip_path

                # 4. 標準工時對照 (若無檔案則略過)
                if temp_std_path and os.path.exists(temp_std_path):
                    progress_bar.progress(85, text="比對標準工時資料...")
                    from standard_hours import StandardHoursIntegrator
                    integrator = StandardHoursIntegrator(temp_std_path)
                    final_storyboard = integrator.compare_and_annotate(refined_storyboard)
                else:
                    progress_bar.progress(85, text="無標準工時檔案，略過比對...")
                    final_storyboard = refined_storyboard
                
                audit_result_json = None # 取消舊版事後稽核功能
                
                # 5. 生成 HTML
                progress_bar.progress(95, text="正在生成跨影片合併 HTML 報告...")
                
                from storyboard_generator import StoryboardGenerator
                
                generator = StoryboardGenerator()
                
                # 決定輸出檔名 (若使用者有填寫則使用，否則看有無工時檔案，最後預設 output_storyboard.html)
                output_html_name = f"{report_name_input}.html" if report_name_input else "output_storyboard.html"
                if not report_name_input and std_hours_file:
                    base_name = os.path.splitext(std_hours_file.name)[0]
                    output_html_name = f"{base_name}_分鏡稿.html"
                elif report_name_input and not output_html_name.endswith('.html'):
                    output_html_name += ".html"

                video_names = " + ".join([v['name'] for v in st.session_state.video_list])
                generator.generate_html(final_storyboard, video_names, output_html_name, audit_result_json=audit_result_json)
                
                progress_bar.progress(100, text="多影片合併分析完成！")
                st.toast('🎉 分鏡稿產生完畢！請點擊下方按鈕下載報告。', icon='✅')
                
                with open(output_html_name, "rb") as f:
                    st.download_button(
                        label=f"📄 下載合併版分鏡稿 HTML 報告 ({output_html_name})",
                        data=f,
                        file_name=output_html_name,
                        mime="text/html",
                        type="primary",
                        use_container_width=True
                    )
                    
            except Exception as e:
                st.error(f"分析過程發生錯誤: {e}")
            finally:
                if temp_std_path and os.path.exists(temp_std_path):
                    os.remove(temp_std_path)

    # === 延遲渲染的繁重處理區 (Deferred Heavy Processing) ===
    # 放置於 main 函式結尾，確保 col_left 與 col_right 都已完成版面渲染，避免 UI 消失
    
    # 1. 處理 PDF 預覽
    if st.session_state.get("pdf_preview_requested", False) and 'pdf_preview_ui_container' in locals():
        with pdf_preview_ui_container:
            if "mock" not in model_selection and "ollama" not in model_selection and "partner" not in model_selection and not api_key_input:
                st.error("請先在左側邊欄輸入 API Key！")
            elif "pdf_preview_tasks" not in st.session_state and "pdf_preview_error" not in st.session_state:
                with st.spinner("正在呼叫 Vision AI 分析 PDF 前 3 頁... (您的版面不會消失)"):
                    import tempfile
                    from models import get_vision_model
                    from sop_task_planner import SOPTaskPlanner
                    
                    if "mock" in model_selection:
                        m_type = "mock"
                    elif "ollama" in model_selection:
                        m_type = "ollama"
                    elif "partner" in model_selection:
                        m_type = "partner"
                    else:
                        m_type = "gemini"
                        
                    m_name = ""
                    if m_type == "gemini": m_name = gemini_model_version
                    elif m_type == "ollama": m_name = locals().get("ollama_model_version", "llava-llama3")
                    elif m_type == "partner": m_name = locals().get("partner_model_name", "default")
                        
                    if m_type == "partner":
                        vm = get_vision_model(model_type=m_type, endpoint_url=locals().get("partner_api_url", ""), model_name=m_name)
                    else:
                        vm = get_vision_model(model_type=m_type, api_key=api_key_input.strip() if api_key_input else "", model_name=m_name)

                    planner = SOPTaskPlanner(vision_model=vm)
                    
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(sop_file.getvalue())
                        tmp_path = tmp.name
                        
                    try:
                        tasks = planner.plan_tasks_from_pdf_vision(tmp_path, max_pages=3, parse_mode=parse_mode_selection)
                        st.session_state.pdf_preview_tasks = tasks
                    except Exception as e:
                        st.session_state.pdf_preview_error = str(e)
                    finally:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    st.rerun() # 重新渲染以顯示結果
            
            # 顯示預覽結果
            if "pdf_preview_error" in st.session_state:
                st.error(f"預覽發生錯誤: {st.session_state.pdf_preview_error}")
            elif "pdf_preview_tasks" in st.session_state:
                tasks = st.session_state.pdf_preview_tasks
                if tasks:
                    st.success(f"成功萃取 {len(tasks)} 個動作步驟！以下是從前 3 頁解析出來的結果：")
                    try:
                        st.dataframe(tasks, use_container_width=True)
                    except Exception as e:
                        st.warning("表格渲染失敗，改以原始資料呈現：")
                        st.json(tasks)
                else:
                    st.warning("無法從前 3 頁萃取出任何步驟。如果您的前 3 頁都是封面或目錄，這是正常的。")
            
            if st.button("❌ 關閉 PDF 預覽"):
                st.session_state.pdf_preview_requested = False
                if "pdf_preview_tasks" in st.session_state: del st.session_state.pdf_preview_tasks
                if "pdf_preview_error" in st.session_state: del st.session_state.pdf_preview_error
                st.rerun()

    # 2. 處理手部裁切預覽
    if st.session_state.get("hand_crop_requested", False) and 'hand_crop_ui_container' in locals():
        with hand_crop_ui_container:
            if "video_list" in st.session_state and st.session_state.video_list:
                if "hand_crop_preview_img" not in st.session_state or st.session_state.get("hand_crop_padding_used") != hand_crop_padding or st.session_state.get("hand_crop_top_used") != top_exclusion:
                    with st.spinner("正在掃描影片中間正負 3 秒尋找手部... (您的版面不會消失)"):
                        from video_processor import VideoProcessor
                        vp = VideoProcessor(st.session_state.video_list[0]["path"])
                        preview_img = vp.preview_hand_crop(padding=hand_crop_padding, top_exclusion_ratio=top_exclusion / 100.0)
                        st.session_state.hand_crop_preview_img = preview_img
                        st.session_state.hand_crop_padding_used = hand_crop_padding
                        st.session_state.hand_crop_top_used = top_exclusion
                        st.rerun() # 重新渲染以顯示結果

                # 顯示預覽圖
                preview_img = st.session_state.hand_crop_preview_img
                if isinstance(preview_img, str):
                    st.error(f"系統錯誤發生：\n{preview_img}")
                elif preview_img is not None:
                    st.image(preview_img, caption=f"Padding={st.session_state.hand_crop_padding_used} 預覽圖 (紅框: 裸手追蹤 / 綠框: 動態手套追蹤)", use_container_width=True)
                else:
                    st.warning("影片中間段 6 秒內未偵測到手部或任何動靜，無法提供裁切預覽。")
                    
                if st.button("❌ 關閉影片裁切預覽"):
                    st.session_state.hand_crop_requested = False
                    if "hand_crop_preview_img" in st.session_state: del st.session_state.hand_crop_preview_img
                    st.rerun()
            else:
                st.warning("請先上傳影片！")

if __name__ == "__main__":
    main()


