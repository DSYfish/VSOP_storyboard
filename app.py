import streamlit as st
import time
import os
import pandas as pd
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

# 1. 處理 PDF 預覽 (使用 @st.dialog 漂浮視窗)
@st.dialog("📄 SOP 步驟萃取預覽與擷取 (漂浮視窗)", width="large")
def show_pdf_preview_modal():
    if "pdf_preview_error" in st.session_state:
        st.error(f"❌ 預覽發生錯誤：\n\n{st.session_state.pdf_preview_error}")
        st.info("💡 **除錯與優化建議**：\n"
                "1. **網路與服務檢查**：若您使用「合作廠商地端 API」或「本地 Ollama」，請確認該伺服器 IP (例如 192.168.x.x 或 127.0.0.1) 處於可連線狀態，且對應的 LLM 模型已正確啟動。\n"
                "2. **效能與記憶體優化**：我們已升級了 **智慧頁面過濾機制** (自動跳過封面、修改紀錄與純目錄頁) 並將 Ollama 記憶體配置優化為 `num_ctx=4096`，大幅降低 VRAM 負擔與超時機率。\n"
                "3. 若仍超時，建議檢查 GPU 顯存是否充足，或嘗試點擊「❌ 關閉視窗」後重試。")
    elif "pdf_preview_tasks" in st.session_state:
        tasks = st.session_state.pdf_preview_tasks
        if tasks:
            if "excel_export_msg" in st.session_state:
                st.success(st.session_state.excel_export_msg)
            
            if st.session_state.get("enable_video_alignment", False) and st.session_state.get("video_list"):
                st.success(f"🎬 已完成「SOP 步驟解析」！共萃取出 {len(tasks)} 個專屬步驟！")
            else:
                st.success(f"✅ 成功從全檔案中萃取出 {len(tasks)} 個標準動作步驟！")
            st.info("💡 請在下方勾選您確認影片有拍攝到的步驟！系統將會在分析時**精準強制擷取您勾選的這些步驟**！")
            try:
                # import pandas as pd
                df = pd.DataFrame(tasks)
                
                with st.form("pdf_selection_form", border=False):
                    edited_dfs = []
                    if "page_number" in df.columns:
                        # 依據頁碼分組
                        pages = df["page_number"].unique()
                        for page in sorted(pages):
                            page_df = df[df["page_number"] == page].copy()
                            
                            # 把每一頁第一項的動作敘述改成提取下一列
                            if len(page_df) > 1:
                                first_idx = page_df.index[0]
                                second_idx = page_df.index[1]
                                page_df.at[first_idx, "action_description"] = page_df.at[second_idx, "action_description"]
                                # 同步更新回原始 tasks 列表，以便後續生成時能使用正確的資料
                                for t in tasks:
                                    if t.get("page_number") == page and t.get("step_number") == page_df.at[first_idx, "step_number"]:
                                        t["action_description"] = page_df.at[first_idx, "action_description"]
                                        
                            # 從表格中徹底移除主標題 (不顯示也無法勾選)
                            page_df = page_df[page_df["step_number"].astype(str).str.contains("-")]
                            
                            # 重新排列欄位順序
                            cols = ["is_selected", "page_number", "step_number", "part_name", "action_description"]
                            cols = [c for c in cols if c in page_df.columns] + [c for c in page_df.columns if c not in cols]
                            page_df = page_df[cols]
                            
                            # 取得第一項的動作敘述作為標題摘要
                            first_action_desc = ""
                            if not page_df.empty:
                                first_idx_for_title = page_df.index[0]
                                first_action_desc = page_df.at[first_idx_for_title, "action_description"]
                            
                            col_chk, col_exp = st.columns([2, 8])
                            with col_chk:
                                st.write("") # 垂直對齊用
                                page_tasks = [t for t in st.session_state.pdf_preview_tasks if t.get("page_number") == page and "-" in str(t.get("step_number", ""))]
                                all_selected = all(t.get("is_selected", False) for t in page_tasks) if page_tasks else False
                                st.checkbox(f"☑ 全選第 {page} 頁", value=all_selected, key=f"chk_page_select_{page}")
                                
                            with col_exp:
                                with st.expander(f"第 {page} 頁 (共 {len(page_df)} 個步驟) - {first_action_desc}", expanded=False):
                                    edited_df = st.data_editor(
                                        page_df,
                                        use_container_width=True,
                                        hide_index=True,
                                        key=f"editor_page_{page}",
                                        column_config={
                                            "is_selected": st.column_config.CheckboxColumn("☑ 擷取", default=False, help="勾選表示此步驟會被帶入後續的影片分析中"),
                                            "page_number": st.column_config.NumberColumn("SOP 頁碼", format="%d 頁", width="small", disabled=True),
                                            "step_number": st.column_config.TextColumn("步驟編號", width="small", disabled=True),
                                            "part_name": st.column_config.TextColumn("零件/專有名詞", width="medium", disabled=True),
                                            "action_description": st.column_config.TextColumn("動作描述/工法", disabled=True)
                                        }
                                    )
                                    edited_dfs.append(("page", page, edited_df))
                    else:
                        # 若無頁碼資訊則維持原樣顯示
                        df = df[df["step_number"].astype(str).str.contains("-")]
                        
                        cols = ["is_selected", "step_number", "part_name", "action_description"]
                        cols = [c for c in cols if c in df.columns] + [c for c in df.columns if c not in cols]
                        df = df[cols]
                        
                        col_chk, col_exp = st.columns([2, 8])
                        with col_chk:
                            st.write("")
                            all_selected_nopage = all(t.get("is_selected", False) for t in st.session_state.pdf_preview_tasks if "-" in str(t.get("step_number", ""))) if st.session_state.pdf_preview_tasks else False
                            st.checkbox("☑ 全部選取", value=all_selected_nopage, key="chk_page_select_nopage")
                            
                        with col_exp:
                            edited_df = st.data_editor(
                                df,
                                use_container_width=True,
                                hide_index=True,
                                key="editor_no_page",
                                column_config={
                                    "is_selected": st.column_config.CheckboxColumn("☑ 擷取", default=False, help="勾選表示此步驟會被帶入後續的影片分析中"),
                                    "step_number": st.column_config.TextColumn("步驟編號", width="small", disabled=True),
                                    "part_name": st.column_config.TextColumn("零件/專有名詞", width="medium", disabled=True),
                                    "action_description": st.column_config.TextColumn("動作描述/工法", disabled=True)
                                }
                            )
                            edited_dfs.append(("nopage", None, edited_df))
                        
                    st.info("💡 **提示**：由於已啟用防卡頓機制，左側的「全選」核取方塊將會在您點擊最下方「✅ 確認選取」時一併結算生效。")
                    
                    if st.form_submit_button("✅ 確認選取 (完成並關閉此清單)", use_container_width=True):
                        # 批次處理所有被編輯的表格
                        for mode, page, edf in edited_dfs:
                            is_all_selected = st.session_state.get(f"chk_page_select_{page}" if mode == "page" else "chk_page_select_nopage", False)
                            for _, row in edf.iterrows():
                                for t in st.session_state.pdf_preview_tasks:
                                    if mode == "page":
                                        if t.get("page_number") == page and t.get("step_number") == row["step_number"]:
                                            if "-" in str(t.get("step_number", "")):
                                                t["is_selected"] = True if is_all_selected else row.get("is_selected", False)
                                            else:
                                                t["is_selected"] = False
                                    else:
                                        if t.get("step_number") == row["step_number"]:
                                            t["is_selected"] = True if is_all_selected else row.get("is_selected", False)
                                            
                        if "pdf_preview_error" in st.session_state:
                            del st.session_state.pdf_preview_error
                        st.rerun()
            except Exception as e:
                st.warning(f"表格渲染失敗: {e}，改以原始資料呈現：")
                st.json(tasks)
        else:
            st.warning("⚠️ 無法從文件中萃取出任何步驟。")
            st.info("💡 **智慧解析說明**：\n"
                    "系統已透過「智慧前置過濾」自動為您排除非步驟頁面（如封面、目錄大綱、設備清單等）。但在其餘頁面進行 AI 視覺推論時，未能正確擷取出符合格式的步驟任務。\n"
                    "👉 **建議步驟**：\n"
                    "1. 請確認選用的 AI 模型（如 gemma4:12b 或地端 API）是否具備足夠的圖片讀取與繁體中文 JSON 指令遵循能力。\n"
                    "2. 您可以嘗試切換左側的「SOP PDF 任務解析模式」（如切換至 **嚴格模式** 或 **標準模式**）後再次點擊預覽。")


# 1.5 處理純影片分析預覽
@st.dialog("👁️ 純影片 AI 解析預覽 (無 SOP 限制)", width="large")
def show_video_preview_modal():
    if "video_preview_error" in st.session_state:
        st.error(f"❌ 預覽發生錯誤：\n\n{st.session_state.video_preview_error}")
    elif "video_preview_all_results" in st.session_state:
        results = st.session_state.video_preview_all_results
        st.success("✅ 純視覺分析完成！以下是 AI 對每部影片獨立辨識出的操作過程敘述：")
        
        for res in results:
            st.markdown(f"#### 🎥 影片：`{res['video_name']}`")
            
            # 顯示敘述總結
            if res.get('narrative'):
                st.info(res['narrative'])
            
            # 將條列式時間軸藏在下拉選單中，避免干擾畫面
            with st.expander(f"🔍 檢視 {res['video_name']} 逐格詳細時間軸分析紀錄"):
                # import pandas as pd
                df = pd.DataFrame(res['storyboard'])
                cols = ["source_video", "time_sec", "part_name", "action_description"]
                df = df[[c for c in cols if c in df.columns]]
                
                st.dataframe(
                    df,
                    use_container_width=True,
                    hide_index=True,
                    height=250,
                    column_config={
                        "source_video": st.column_config.TextColumn("來源影片", width="small"),
                        "time_sec": st.column_config.NumberColumn("時間 (秒)", format="%.2f", width="small"),
                        "part_name": st.column_config.TextColumn("零件/操作物", width="medium"),
                        "action_description": st.column_config.TextColumn("動作描述", width="large")
                    }
                )
            st.divider()
            
        col_b1, col_b2 = st.columns([1, 4])
        with col_b1:
            if st.button("❌ 關閉視窗", key="close_video_modal"):
                if "video_preview_error" in st.session_state: del st.session_state.video_preview_error
                st.rerun()



@st.dialog("📋 從 SOP 步驟庫中指派", width="large")
def show_sop_picker_modal(target_id):
    st.info(f"👉 請點選下方清單中的某個步驟，將其直接指派給預覽表中的項目！")
    
    tasks = st.session_state.get("pdf_preview_tasks", [])
    if not tasks:
        st.warning("⚠️ 尚無解析完成的 SOP 步驟庫，請先上傳 PDF 並完成解析。")
        if st.button("關閉"):
            st.rerun()
        return
        
    import pandas as pd
    df = pd.DataFrame(tasks)
    if "step_number" in df.columns:
        df = df[df["step_number"].astype(str).str.contains("-")]
    
    cols = ["page_number", "step_number", "part_name", "action_description"]
    cols = [c for c in cols if c in df.columns]
    df = df[cols]
    
    event = st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        selection_mode="single-row",
        on_select="rerun",
        key="sop_picker_df",
        column_config={
            "page_number": st.column_config.NumberColumn("SOP 頁碼", format="%d 頁", width="small", disabled=True),
            "step_number": st.column_config.TextColumn("步驟編號", width="small", disabled=True),
            "part_name": st.column_config.TextColumn("零件/專有名詞", width="medium", disabled=True),
            "action_description": st.column_config.TextColumn("動作描述/工法", disabled=True)
        }
    )
    
    if event.selection.rows:
        idx = event.selection.rows[0]
        selected_row = df.iloc[idx]
        
        part_str = f"步驟 {selected_row.get('step_number', '')}: {selected_row.get('part_name', '')}"
        desc_str = selected_row.get('action_description', '')
        
        if st.button(f"✅ 確認指派: {part_str}", type="primary", use_container_width=True):
            st.session_state.preview_data[target_id]["part_name"] = part_str
            st.session_state.preview_data[target_id]["action_description"] = desc_str
            st.session_state.editor_key_counter = st.session_state.get("editor_key_counter", 0) + 1
            st.rerun()
            
    if st.button("❌ 取消並關閉"):
        st.rerun()

def main():

    if "workflow_stage" not in st.session_state:
        st.session_state.workflow_stage = "input"
    if "preview_data" not in st.session_state:
        st.session_state.preview_data = None
        
    # --- Sidebar 設定區 ---
    with st.sidebar:
        st.markdown("## 🎬 分鏡稿自動生成系統")
        st.header("🧭 快速導覽")
        st.markdown("""
        <style>
        .nav-pills .nav-link {
            background-color: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 0.5rem;
            padding: 0.6rem 1rem;
            margin-bottom: 0.5rem;
            display: block;
            text-decoration: none;
            color: #212529;
            transition: all 0.2s ease-in-out;
            font-weight: 500;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }
        .nav-pills .nav-link:hover {
            background-color: #e9ecef;
            border-color: #cdd3d8;
            color: #0d6efd;
            transform: translateX(4px);
        }
        @media (prefers-color-scheme: dark) {
            .nav-pills .nav-link {
                background-color: #2b2b36;
                border: 1px solid #4a4a5a;
                color: #e0e0e0;
                box-shadow: 0 1px 3px rgba(0,0,0,0.2);
            }
            .nav-pills .nav-link:hover {
                background-color: #3b3b4f;
                border-color: #5a5a6a;
                color: #6ea8fe;
            }
        }
        
        .anchor-offset {
            display: block;
            position: relative;
            top: -85px; 
            visibility: hidden;
        }
        </style>
        
        <div class="nav-pills">
            <a class="nav-link" href="#upload-section">📁 上傳檔案區</a>
            <a class="nav-link" href="#capture-section">⚙️ 擷取設定</a>
            <a class="nav-link" href="#hand-tracking-section">👐 手部追蹤邊界設定</a>
            <a class="nav-link" href="#video-preview-section">🎞️ 影片處理順序與預覽</a>
        </div>
        """, unsafe_allow_html=True)
        st.divider()
        
        st.header("⚙️ 系統設定")
        model_selection = st.selectbox("視覺模型選擇", ["ollama (地端模型)", "partner (合作廠商地端API)"])
        
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
                    if "gemma4" in m.lower():
                        default_idx = i
                        break
                    elif "minicpm-v" in m.lower() or "qwen2.5-vl" in m.lower():
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
        
        # 從安全設定檔讀取 API Key (地端與本地模型免用 Key)
        api_key_input = ""
        try:
            if "GEMINI_API_KEY" in st.secrets:
                api_key_input = st.secrets["GEMINI_API_KEY"]
        except Exception:
            pass
    
    st.title("🎬 分鏡稿自動生成系統")
    st.markdown("透過視覺 AI 分析影片，自動擷取關鍵動作、零件辨識，並產生標準工時比對的分鏡稿。")
    
    st.divider()

    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.markdown("<span id='upload-section' class='anchor-offset'></span>", unsafe_allow_html=True)
        st.subheader("📁 上傳檔案區")
        
        # 1. Video Upload (Required, Multi-files)
        video_files = st.file_uploader("上傳影片檔案 (必填，可多選)", type=["mp4", "avi", "mov", "mkv"], accept_multiple_files=True)
        
        # 2. Standard Hours (Optional)
        std_hours_file = st.file_uploader("上傳標準工時檔案 (暫不開放)", type=["csv", "xlsx", "json"], disabled=True, help="目前暫時鎖定此功能，無法匯入任何標準工時檔案。")
        
        # 3. SOP Document (Optional)
        sop_file = st.file_uploader("上傳 SOP 作業指導書 (選填)", type=["txt", "json", "pdf", "csv", "xlsx"])
        
        parse_mode_selection = "fast_text"
        st.session_state.enable_video_alignment = False
        
        if sop_file:
            if st.session_state.get("last_sop_file_name") != sop_file.name:
                st.session_state.last_sop_file_name = sop_file.name
                if "pdf_preview_tasks" in st.session_state: del st.session_state.pdf_preview_tasks
                if "pdf_preview_error" in st.session_state: del st.session_state.pdf_preview_error
                
            if sop_file.name.lower().endswith(".pdf"):
                enable_video_align_ui = st.checkbox(
                    "☑ 啟用影片-SOP物件對齊 (強制擷取您勾選的步驟)",
                    value=True,
                    help="當上傳作業影片與SOP同時存在時，系統將精確依照您勾選的步驟來切割影片，確保數量與內容完美對齊！"
                )
                st.session_state.enable_video_alignment = enable_video_align_ui
                
                if "pdf_preview_tasks" not in st.session_state:
                    if st.button("📄 產生 PDF 步驟預覽", help="使用極速模式讀取 PDF 表格，並擷取標準作業步驟。"):
                        st.session_state.run_pdf_analysis = True
                        if "pdf_preview_error" in st.session_state: del st.session_state.pdf_preview_error
                else:
                    col_pdf1, col_pdf2 = st.columns(2)
                    with col_pdf1:
                        if st.button("📄 預覽 PDF 步驟細項", use_container_width=True, help="查看並編輯剛剛解析完成的 SOP 步驟清單。"):
                            show_pdf_preview_modal()
                    with col_pdf2:
                        if st.button("🔄 重新解析 SOP", use_container_width=True, help="清除先前的解析結果，並重新執行 SOP 步驟萃取。"):
                            del st.session_state.pdf_preview_tasks
                            st.session_state.run_pdf_analysis = True
                            if "pdf_preview_error" in st.session_state: del st.session_state.pdf_preview_error
                            st.rerun()
            elif sop_file.name.lower().endswith(".xlsx") or sop_file.name.lower().endswith(".csv"):
                if "pdf_preview_tasks" not in st.session_state:
                    try:

                        if sop_file.name.lower().endswith(".xlsx"):
                            df = pd.read_excel(sop_file)
                        else:
                            df = pd.read_csv(sop_file)
                            
                        # ensure columns are correct and map to dict
                        tasks = df.to_dict('records')
                        for t in tasks:
                            if "is_selected" not in t:
                                t["is_selected"] = False
                        st.session_state.pdf_preview_tasks = tasks
                    except Exception as e:
                        st.error(f"讀取表格失敗: {e}")
                        
                enable_video_align_ui = st.checkbox(
                    "☑ 啟用影片-SOP物件對齊 (強制擷取您勾選的步驟)",
                    value=True,
                    help="當上傳作業影片與SOP同時存在時，系統將精確依照您勾選的步驟來切割影片，確保數量與內容完美對齊！"
                )
                st.session_state.enable_video_alignment = enable_video_align_ui
                
                if st.button("📄 預覽已載入的 SOP 步驟細項", use_container_width=True, help="查看並手動勾選從表格載入的 SOP 步驟清單。"):
                    show_pdf_preview_modal()
        else:
            # 清除快取，避免刪除檔案後預覽視窗仍異常彈出
            for key in ["last_sop_file_name", "pdf_preview_tasks", "pdf_preview_error"]:
                if key in st.session_state:
                    del st.session_state[key]
        
        # 4. Report Name (Optional)
        st.markdown("**自訂報表名稱 (選填)**")
        col_name1, col_name2 = st.columns([4, 1])
        with col_name1:
            report_name_input = st.text_input("名稱", label_visibility="collapsed", placeholder="若留空，預設為 [SOP檔名]")
        with col_name2:
            st.markdown("<div style='margin-top: 8px; font-weight: bold; color: #cbd5e1;'>分鏡稿</div>", unsafe_allow_html=True)        
        st.markdown("<span id='capture-section' class='anchor-offset'></span>", unsafe_allow_html=True)
        st.subheader("⚙️ 擷取設定")
        use_dynamic_clipping = st.checkbox("啟用目標式動態裁切 (前後 1.5 秒影片)", value=True, help="若上傳 SOP，系統會自動在精確秒數裁切出短片，而非單張靜態圖片。")
        
        if "pad_slider" not in st.session_state:
            st.session_state.pad_slider = 150
            st.session_state.pad_input = 150
        if "top_slider" not in st.session_state:
            st.session_state.top_slider = 25
            st.session_state.top_input = 25
        if "int_slider" not in st.session_state:
            st.session_state.int_slider = 2.0
            st.session_state.int_input = 2.0
        if "max_slider" not in st.session_state:
            st.session_state.max_slider = 25
            st.session_state.max_input = 25

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
                
        def sync_max(source):
            if source == 'slider':
                st.session_state.max_input = st.session_state.max_slider
            else:
                st.session_state.max_slider = st.session_state.max_input

        col_int1, col_int2 = st.columns([3, 1])
        with col_int1:
            st.slider("預設擷取間隔秒數 (越大速度越快)", min_value=0.50, max_value=5.00, step=0.25, format="%.2f", key="int_slider", on_change=sync_interval, args=('slider',), help="預設每 2.0 秒擷取一張畫面。數值越大、擷取張數越少，AI 推論速度越快！")
        with col_int2:
            st.number_input("秒數 (0.50-5.00)", min_value=0.50, max_value=5.00, step=0.25, format="%.2f", key="int_input", on_change=sync_interval, args=('input',))
            
        interval_seconds = st.session_state.int_slider
        
        col_max1, col_max2 = st.columns([3, 1])
        with col_max1:
            st.slider("單部影片最高上限張數 (限速保護)", min_value=10, max_value=100, step=5, key="max_slider", on_change=sync_max, args=('slider',), help="設定每部影片最多送給 AI 分析的影格張數。若影片過長，系統會自動均勻採樣至此上限，避免地端模型推論過久！")
        with col_max2:
            st.number_input("上限張數", min_value=10, max_value=100, step=5, key="max_input", on_change=sync_max, args=('input',))
            
        max_frames_limit = st.session_state.max_slider

        st.markdown("<span id='hand-tracking-section' class='anchor-offset'></span>", unsafe_allow_html=True)
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
        st.markdown("<span id='video-preview-section' class='anchor-offset'></span>", unsafe_allow_html=True)
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
    if st.session_state.workflow_stage == "input":
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if "video_preview_all_results" not in st.session_state:
                if st.button("👁️ 產生純影片 AI 解析預覽", use_container_width=True, help="在不提供 SOP 的情況下，單純測試 AI 是否能準確辨識影片中的動作。"):
                    if not st.session_state.video_list:
                        st.error("❌ 錯誤：請先上傳影片！")
                    else:
                        st.session_state.run_video_analysis = True
                        if "video_preview_error" in st.session_state:
                            del st.session_state.video_preview_error
            else:
                col_v1, col_v2 = st.columns(2)
                with col_v1:
                    if st.button("👁️ 預覽純視覺解析", use_container_width=True):
                        st.session_state.auto_open_video_modal = True
                with col_v2:
                    if st.button("🔄 重新解析影片", use_container_width=True):
                        if not st.session_state.video_list:
                            st.error("❌ 錯誤：請先上傳影片！")
                        else:
                            del st.session_state.video_preview_all_results
                            st.session_state.run_video_analysis = True
                            if "video_preview_error" in st.session_state:
                                del st.session_state.video_preview_error
                            st.rerun()
        
        with col_btn2:
            submit_clicked = st.button("🚀 開始分析 (套用 SOP 對齊)", type="primary", use_container_width=True)
            
        if submit_clicked or st.session_state.pop("trigger_auto_analysis", False):
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
                    if temp_std_path and os.path.exists(temp_std_path): os.remove(temp_std_path)
                    if temp_sop_path and os.path.exists(temp_sop_path): os.remove(temp_sop_path)
                    st.stop()

                try:
                    # 1. 初始化模型
                    import models
                    importlib.reload(models)
                    from models import get_vision_model
                    
                    if "mock" in model_selection:
                        model_type_parsed = "mock"
                    elif "ollama" in model_selection:
                        model_type_parsed = "ollama"
                    elif "partner" in model_selection:
                        model_type_parsed = "partner"
                    else:
                        model_type_parsed = "gemini"
                    
                    safe_api_key = api_key_input.strip() if api_key_input else ""
                    
                    if model_type_parsed == "partner":
                        vision_model = get_vision_model(model_type=model_type_parsed, endpoint_url=partner_api_url, model_name=partner_model_name)
                    else:
                        vision_model = get_vision_model(model_type=model_type_parsed, api_key=safe_api_key, model_name=gemini_model_version if model_type_parsed == "gemini" else ollama_model_version)
                    
                    import analyzer as analyzer_mod
                    importlib.reload(analyzer_mod)
                    from analyzer import StoryboardAnalyzer
                    analyzer = StoryboardAnalyzer(vision_model)
                    
                    def analysis_progress(idx, total):
                        percent_complete = 50 + int((idx / total) * 40)
                        progress_bar.progress(percent_complete, text=f"正在打包第 {idx+1}/{total} 張截圖... (為節省免費用戶額度，將採用「單次批次發送」)")

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
                        progress_bar.progress(20, text="正在建立全域時間軸對應表...")
                        global_timeline = []
                        import cv2
                        
                        import sop_task_planner
                        importlib.reload(sop_task_planner)
                        from sop_task_planner import SOPTaskPlanner
                        planner = SOPTaskPlanner(vision_model=vision_model)
                        
                        for vid in st.session_state.video_list:
                            v_name = vid["name"]
                            vid_path = vid["path"]
                            
                            vp = VideoProcessor(vid_path)
                            fps = vp.fps
                            
                            for seg in time_segments:
                                if seg.get("source_video") == v_name:
                                    t_start = seg.get("start_time", 0.0)
                                    t_end = seg.get("end_time", 0.0)
                                    mid_time = (t_start + t_end) / 2.0
                                    
                                    cap = cv2.VideoCapture(vid_path)
                                    cap.set(cv2.CAP_PROP_POS_MSEC, mid_time * 1000)
                                    ret, frame = cap.read()
                                    cap.release()
                                    
                                    if ret:
                                        _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                                        img_base64 = base64.b64encode(buffer).decode('utf-8')
                                        global_timeline.append({
                                            "time_sec": mid_time,
                                            "start_time": t_start,
                                            "end_time": t_end,
                                            "std_duration": seg.get("std_duration", 0.0),
                                            "source_video": v_name,
                                            "image_base64": img_base64,
                                            "step_name": seg.get("step_name", "未知步驟")
                                        })
                        
                        progress_bar.progress(50, text="正在分析全域代表影格...")
                        refined_storyboard = analyzer.analyze_time_driven_frames(global_timeline, progress_callback=analysis_progress)
                        all_keyframes = global_timeline
                        
                    else:
                        progress_bar.progress(20, text="準備進行單部影片獨立分析...")
                        
                        final_storyboard = []
                        
                        # 1. 取得 Master Tasks
                        if temp_sop_path and os.path.exists(temp_sop_path):
                            progress_bar.progress(30, text="正在解析 SOP 全文任務庫...")
                            import sop_task_planner
                            importlib.reload(sop_task_planner)
                            from sop_task_planner import SOPTaskPlanner
                            planner = SOPTaskPlanner(vision_model=vision_model)
                            def main_pdf_progress(c, t, msg): pass
                            
                            if "pdf_preview_tasks" in st.session_state and st.session_state.pdf_preview_tasks:
                                master_tasks = st.session_state.pdf_preview_tasks
                            else:
                                master_tasks = planner.plan_tasks_from_pdf_vision(
                                    temp_sop_path, max_pages=-1, parse_mode=parse_mode_selection, 
                                    progress_callback=main_pdf_progress
                                )
                                # 自動匯出 Excel
                                try:

                                    excel_filename = os.path.splitext(sop_file.name)[0] + ".xlsx"
                                    df_export = pd.DataFrame(master_tasks)
                                    df_export.rename(columns={
                                        "page_number": "SOP 頁碼",
                                        "step_number": "步驟編號",
                                        "part_name": "零件/專有名詞",
                                        "action_description": "動作描述/工法",
                                        "is_selected": "是否選取"
                                    }, inplace=True)
                                    df_export.to_excel(excel_filename, index=False)
                                except Exception: pass
                                
                                # 預設全部不勾選
                                for t in master_tasks:
                                    t["is_selected"] = False
                        else:
                            master_tasks = []
                            planner = None

                        # 2. 對每一部影片進行獨立迴圈處理
                        total_vids = len(st.session_state.video_list)
                        
                        # 先計算所有影片的總長度，以及全域的步驟分配
                        total_duration_all = 0.0
                        for vid in st.session_state.video_list:
                            import cv2
                            cap = cv2.VideoCapture(vid["path"])
                            fps = cap.get(cv2.CAP_PROP_FPS)
                            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                            vid["duration"] = frame_count / fps if fps > 0 else 0
                            cap.release()
                            total_duration_all += vid["duration"]
                            
                        global_vid_tasks = [t for t in master_tasks if t.get("is_selected", False) and "-" in str(t.get("step_number", ""))] if master_tasks else []
                        
                        # 檢查是否可以啟動「一頁對應一部影片」的智慧映射
                        unique_pages = []
                        for t in global_vid_tasks:
                            p = t.get("page_number", "")
                            if p not in unique_pages:
                                unique_pages.append(p)
                                
                        use_page_mapping = (len(unique_pages) == total_vids and total_vids > 0)
                        
                        global_step_duration = 0.0
                        global_task_idx = 0
                        
                        if not use_page_mapping:
                            global_step_duration = total_duration_all / max(1, len(global_vid_tasks)) if global_vid_tasks else 0
                        
                        current_offset = 0.0
                        
                        for idx, vid in enumerate(st.session_state.video_list):
                            base_prog = 30 + int((idx / total_vids) * 60)
                            progress_bar.progress(base_prog, text=f"🎬 正在處理影片 {idx+1}/{total_vids} ({vid['name']})...")
                            
                            # (A) 提取該影片的關鍵影格
                            processor = VideoProcessor(vid["path"])
                            vid_keyframes = processor.extract_keyframes(
                                use_scene_detection=False, time_offset=current_offset, 
                                interval_seconds=st.session_state.int_input, max_frames=st.session_state.max_input
                            )
                            for k in vid_keyframes:
                                k["source_video"] = vid["name"]
                                
                            vid_start_offset = current_offset
                            duration = vid["duration"]
                            current_offset += duration
                            
                            # (B) 若有啟用對齊，直接套用 Top-Down 均勻取幀法
                            if master_tasks and planner and st.session_state.get("enable_video_alignment", False):
                                vid_tasks_local = []
                                
                                if use_page_mapping:
                                    target_page = unique_pages[idx]
                                    progress_bar.progress(base_prog + 5, text=f"🔍 智慧對齊：影片 {idx+1} 精準對應 SOP 第 {target_page} 頁...")
                                    page_tasks = [t for t in global_vid_tasks if t.get("page_number") == target_page]
                                    
                                    if page_tasks:
                                        local_step_dur = duration / len(page_tasks)
                                        for i, task in enumerate(page_tasks):
                                            task["local_mid_time"] = (i + 0.5) * local_step_dur
                                            task["global_start"] = vid_start_offset + (i * local_step_dur)
                                            task["global_step_duration"] = local_step_dur
                                            vid_tasks_local.append(task)
                                else:
                                    progress_bar.progress(base_prog + 5, text=f"🔍 鎖定影片 {idx+1} 專屬 SOP 步驟 (套用全域時間軸分配)...")
                                    # 找出落入這部影片時間段的任務
                                    while global_task_idx < len(global_vid_tasks):
                                        g_mid = (global_task_idx + 0.5) * global_step_duration
                                        # 若是最後一部影片，則無條件吃下所有剩餘步驟，避免浮點數誤差
                                        if idx == total_vids - 1 or g_mid <= current_offset:
                                            task = global_vid_tasks[global_task_idx]
                                            task["local_mid_time"] = g_mid - vid_start_offset
                                            task["global_mid_time"] = g_mid
                                            task["global_start"] = global_task_idx * global_step_duration
                                            task["global_step_duration"] = global_step_duration
                                            vid_tasks_local.append(task)
                                            global_task_idx += 1
                                        else:
                                            break
                                        
                                if vid_tasks_local:
                                    num_steps = len(vid_tasks_local)
                                    progress_bar.progress(base_prog + 10, text=f"🧠 本影片分配到 {num_steps} 個步驟，正在擷取關鍵幀進行分析...")
                                    
                                    vid_timeline = []
                                    import base64
                                    vp_local = VideoProcessor(vid["path"])
                                    
                                    for task in vid_tasks_local:
                                        local_mid_time = task["local_mid_time"]
                                        # 確保擷取時間不超出影片實際長度
                                        local_mid_time = max(0, min(local_mid_time, duration))
                                        
                                        # 擷取對應秒數的畫面

                                        frame_data = vp_local.extract_and_crop_hands(local_mid_time, padding=150)
                                        if frame_data and "image_base64" in frame_data:
                                            img_base64 = frame_data["image_base64"]
                                        else:
                                            import cv2
                                            cap_temp = cv2.VideoCapture(vid["path"])
                                            cap_temp.set(cv2.CAP_PROP_POS_MSEC, local_mid_time * 1000)
                                            ret, frame_temp = cap_temp.read()
                                            if ret:
                                                _, buffer = cv2.imencode('.jpg', frame_temp, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                                                img_base64 = base64.b64encode(buffer).decode('utf-8')
                                            else:
                                                img_base64 = ""
                                            cap_temp.release()
                                            
                                        step_name_str = f"步驟 {task.get('step_number', '')}: {task.get('action_description', '')}"
                                        
                                        vid_timeline.append({
                                            "time_sec": local_mid_time,
                                            "start_time": task["global_start"],
                                            "end_time": task["global_start"] + task.get("global_step_duration", global_step_duration),
                                            "std_duration": task.get("global_step_duration", global_step_duration),
                                            "source_video": vid["name"],
                                            "image_base64": img_base64,
                                            "step_name": step_name_str,
                                            "page_number": task.get("page_number", ""),
                                            "part_name": task.get("part_name", "")
                                        })
                                        
                                    # 呼叫單幀上下文分析
                                    vid_storyboard = analyzer.analyze_time_driven_frames(vid_timeline, progress_callback=analysis_progress)
                                    
                                    # 舊有邏輯：直接判斷是否包含負面關鍵字並替換敘述 (註解保留以供後續參考)
                                    # valid_storyboard = []
                                    # for i, frame in enumerate(vid_storyboard):
                                    #     desc = frame.get("action_description", "")
                                    #     # 若 AI 判斷沒有符合的動作，則該敘述不必要，但為保持步驟數量一致，僅將敘述清空或標示
                                    #     negative_keywords = ["沒有人員", "沒有明顯", "沒有可見", "未看見", "沒有發現人員", "未發現人員", "沒有人員正在進行"]
                                    #     if any(k in desc for k in negative_keywords):
                                    #         desc = "未偵測到明顯動作"
                                    #         
                                    #     frame["page_number"] = vid_timeline[i]["page_number"]
                                    #     frame["action_description"] = f"{desc} (對應SOP: {vid_timeline[i]['step_name']})"
                                    #     
                                    #     clip_path = None
                                    #     if use_dynamic_clipping:
                                    #         clip_path = f"temp_clips/clip_task_v{idx+1}_{i+1}.mp4"
                                    #         # 使用該任務在此部影片中的相對秒數來裁剪 (確保秒數為正)
                                    #         clip_center = max(0, frame["time_sec"])
                                    #         vp_local.extract_video_clip(clip_center, clip_path, margin=1.5)
                                    #     frame["video_clip_path"] = clip_path
                                    #     valid_storyboard.append(frame)

                                    # 新邏輯：自適應重採樣機制 (Adaptive Re-sampling)
                                    valid_storyboard = []
                                    negative_keywords = ["沒有人員", "沒有明顯", "沒有可見", "未看見", "沒有發現人員", "未發現人員", "沒有人員正在進行"]
                                    
                                    for i, frame in enumerate(vid_storyboard):
                                        desc = frame.get("action_description", "")
                                        has_negative = any(k in desc for k in negative_keywords)
                                        
                                        # 如果中間點沒抓到，啟動 25% 和 75% 點的補償機制
                                        if has_negative and planner:
                                            progress_bar.progress(base_prog + 15, text=f"🔄 步驟 {i+1} 啟動智慧重採樣 (尋找遺漏動作)...")
                                            
                                            std_dur = vid_timeline[i]["std_duration"]
                                            base_local_time = vid_timeline[i]["time_sec"]
                                            # 推算出該步驟區間的起點
                                            block_start = base_local_time - 0.5 * std_dur
                                            
                                            retry_points = [0.25, 0.75]
                                            success = False
                                            
                                            for retry_ratio in retry_points:
                                                retry_time = block_start + retry_ratio * std_dur
                                                retry_time = max(0, min(retry_time, duration))
                                                
                                                # 抓取該時間點畫面
                                                frame_data_retry = vp_local.extract_and_crop_hands(retry_time, padding=150)
                                                if frame_data_retry and "image_base64" in frame_data_retry:
                                                    retry_img_b64 = frame_data_retry["image_base64"]
                                                else:
                                                    import cv2
                                                    cap_temp = cv2.VideoCapture(vid["path"])
                                                    cap_temp.set(cv2.CAP_PROP_POS_MSEC, retry_time * 1000)
                                                    ret, frame_temp = cap_temp.read()
                                                    if ret:
                                                        _, buffer = cv2.imencode('.jpg', frame_temp, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                                                        retry_img_b64 = base64.b64encode(buffer).decode('utf-8')
                                                    else:
                                                        retry_img_b64 = ""
                                                    cap_temp.release()
                                                    
                                                if retry_img_b64:
                                                    result_retry = analyzer.vision_model.analyze_single_frame_with_context(
                                                        image_base64=retry_img_b64,
                                                        step_name=vid_timeline[i]["step_name"]
                                                    )
                                                    desc_retry = result_retry.get("action_description", "")
                                                    if not any(k in desc_retry for k in negative_keywords):
                                                        # 成功找到了動作！覆寫原始失敗的結果
                                                        frame["time_sec"] = retry_time
                                                        frame["action_description"] = desc_retry
                                                        frame["part_name"] = result_retry.get("part_name", frame.get("part_name", ""))
                                                        desc = desc_retry
                                                        success = True
                                                        break
                                            
                                            if not success:
                                                # 若兩次補償點皆失敗，才保留未偵測提示
                                                desc = "未偵測到明顯動作"
                                        
                                        frame["page_number"] = vid_timeline[i]["page_number"]
                                        frame["action_description"] = desc
                                        frame["sop_step"] = vid_timeline[i]['step_name']
                                        frame["sop_page"] = vid_timeline[i]['page_number']
                                        frame["sop_file"] = st.session_state.get("last_sop_file_name", "SOP文件")
                                        
                                        clip_path = None
                                        if use_dynamic_clipping:
                                            clip_path = f"temp_clips/clip_task_v{idx+1}_{i+1}.mp4"
                                            # 使用該任務在此部影片中的相對秒數來裁剪 (確保秒數為正)
                                            clip_center = max(0, frame["time_sec"])
                                            vp_local.extract_video_clip(clip_center, clip_path, margin=1.5)
                                        frame["video_clip_path"] = clip_path
                                        valid_storyboard.append(frame)
                                        
                                    final_storyboard.extend(valid_storyboard)
                                    continue
                                else:
                                    st.info(f"⏭️ 影片 {idx+1} 沒有分配到 SOP 步驟，跳過 Top-Down 分析。")
                                    continue
                            
                            # (C) 降級：若無對齊，走純影像分析 (Bottom-Up)
                            progress_bar.progress(base_prog + 10, text=f"🧠 正在精準分析影片 {idx+1} (降級純影像模式)...")
                            vid_storyboard = analyzer.analyze_video_frames(
                                vid_keyframes, progress_callback=analysis_progress, glossary=None
                            )
                            
                            for i, frame in enumerate(vid_storyboard):
                                clip_path = None
                                t_sec = frame.get("start_time", frame.get("time_sec", 0))
                                if use_dynamic_clipping:
                                    clip_path = f"temp_clips/clip_task_v{idx+1}_{i+1}.mp4"
                                    vp = VideoProcessor(vid["path"])
                                    vp.extract_video_clip(t_sec, clip_path, margin=1.5)
                                frame["video_clip_path"] = clip_path
                                
                            final_storyboard.extend(vid_storyboard)
                            current_offset += duration

                        # 3. 處理工時比對
                        if temp_std_path and os.path.exists(temp_std_path):
                            progress_bar.progress(90, text="比對標準工時資料...")
                            from standard_hours import StandardHoursIntegrator
                            integrator = StandardHoursIntegrator(temp_std_path)
                            final_storyboard = integrator.compare_and_annotate(final_storyboard)
                        else:
                            progress_bar.progress(85, text="無標準工時檔案，略過比對...")

                    # 分析完成，寫入 preview_data 並切換狀態
                    st.session_state.preview_data = final_storyboard
                    st.session_state.workflow_stage = "preview"
                    st.rerun()

                except Exception as e:
                    st.error(f"分析過程發生錯誤: {e}")
                finally:
                    if temp_std_path and os.path.exists(temp_std_path): os.remove(temp_std_path)
                    if temp_sop_path and os.path.exists(temp_sop_path): os.remove(temp_sop_path)

    if st.session_state.workflow_stage == "preview":

        st.success("🎉 初步分析完成！請在此預覽並編輯分鏡資料，確認後即可產生最終報表。")
        
        df_data = []
        for i, item in enumerate(st.session_state.preview_data):
            df_data.append({
                "ID": i,
                "SOP 頁碼": item.get("page_number", ""),
                "時間 (秒)": item.get("time_sec", 0),
                "零件/步驟名稱": item.get("part_name", ""),
                "動作描述": item.get("action_description", ""),
                "來源影片": item.get("source_video", "")
            })
        
        df = pd.DataFrame(df_data)
        
        st.info("💡 **操作提示**：請在下方表格中「點擊任意橫列」，系統會立即在下方展開該步驟的畫面截圖，您可以直接對照圖片來指派正確的 SOP 步驟！")
        
        # 動態決定欄位類型
        if st.session_state.get("sop_glossary"):
            part_name_col = st.column_config.TextColumn("目前指派的 SOP 步驟 (點擊該列以修改)")
        else:
            part_name_col = st.column_config.TextColumn("零件/步驟名稱 (點擊該列以修改)")
            
        event = st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            key=f"preview_editor_{st.session_state.get('editor_key_counter', 0)}",
            column_config={
                "ID": st.column_config.NumberColumn(width="small"),
                "SOP 頁碼": st.column_config.NumberColumn(format="%d", width="small"),
                "時間 (秒)": st.column_config.NumberColumn(),
                "來源影片": st.column_config.TextColumn(),
                "零件/步驟名稱": part_name_col
            }
        )
        
        # 顯示選取橫列的預覽與編輯區塊
        st.markdown("---")
        selected_rows = event.selection.rows if hasattr(event, "selection") and event.selection.rows else []
        
        if selected_rows:
            # st.dataframe 支援 row selection，拿到的是 df 的 index
            selected_idx = selected_rows[0]
            if selected_idx < len(df):
                orig_id = int(df.iloc[selected_idx]["ID"])
                if orig_id < len(st.session_state.preview_data):
                    item = st.session_state.preview_data[orig_id]
                    
                    st.subheader(f"🔍 步驟細項預覽 (ID: {orig_id})")
                    col_img, col_info = st.columns([1, 1])
                    with col_img:
                        if item.get("image_base64"):
                            import base64
                            st.image(base64.b64decode(item["image_base64"]), caption=f"時間點: {item.get('time_sec', 0):.2f}s | 來源: {item.get('source_video', '')}", use_container_width=True)
                        else:
                            st.info("無影像資料")
                    with col_info:
                        safe_part = str(item.get('part_name', '無')).replace('~', '～')
                        safe_desc = str(item.get('action_description', '無')).replace('~', '～')
                        st.markdown(f"**AI 原始辨識物件**: `{safe_part}`")
                        st.markdown(f"**AI 原始動作描述**: {safe_desc}")
                        

                        st.markdown("### ✏️ 快速指派與編輯")
                        
                        current_part = item.get("part_name", "")
                        current_desc = item.get("action_description", "")
                        
                        col_sop1, col_sop2 = st.columns([3, 1])
                        with col_sop1:
                            new_part = st.text_input("零件/步驟名稱", value=current_part, key=f"edit_part_{orig_id}")
                        with col_sop2:
                            st.write("") # Vertical alignment
                            st.write("")
                            if st.button("🔍 從 SOP 步驟表選取", key=f"btn_pick_sop_{orig_id}", use_container_width=True):
                                show_sop_picker_modal(orig_id)
                                
                        new_desc = st.text_area("修改動作描述", value=current_desc, key=f"edit_desc_{orig_id}", height=100)
                        
                        col_btn1, col_btn2 = st.columns(2)
                        with col_btn1:
                            if st.button("💾 儲存修改", use_container_width=True, type="primary"):
                                st.session_state.preview_data[orig_id]["part_name"] = new_part
                                st.session_state.preview_data[orig_id]["action_description"] = new_desc
                                st.session_state.editor_key_counter = st.session_state.get("editor_key_counter", 0) + 1
                                st.rerun()
                        with col_btn2:
                            if st.button("🗑️ 刪除此步驟", use_container_width=True):
                                # 將此項目從 preview_data 移除
                                st.session_state.preview_data.pop(orig_id)
                                st.session_state.editor_key_counter = st.session_state.get("editor_key_counter", 0) + 1
                                st.rerun()
        else:
            st.info("👆 請在上方表格中點擊任意橫列來顯示此處的預覽畫面與編輯面板。")
            
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ 確認無誤，產生最終分鏡稿 HTML", type="primary", use_container_width=True):
                st.session_state.workflow_stage = "result"
                st.rerun()
                
        with col2:
            if st.button("🔄 捨棄編輯並重新執行分析", type="secondary", use_container_width=True, help="直接重新跑一次分析，不需要再按一次開始分析按鈕"):
                st.session_state.workflow_stage = "input"
                st.session_state.preview_data = None
                st.session_state.trigger_auto_analysis = True
                st.rerun()

    if st.session_state.workflow_stage == "result":
        st.success("🎉 分鏡稿產生完畢！請點擊下方按鈕下載報告。")
        
        from storyboard_generator import StoryboardGenerator
        generator = StoryboardGenerator()
        
        if report_name_input:
            output_html_name = f"{report_name_input}分鏡稿.html"
        else:
            sop_name = st.session_state.get("last_sop_file_name")
            if sop_name:
                base_sop_name = os.path.splitext(sop_name)[0]
                output_html_name = f"{base_sop_name}分鏡稿.html"
            elif std_hours_file:
                base_name = os.path.splitext(std_hours_file.name)[0]
                output_html_name = f"{base_name}分鏡稿.html"
            else:
                output_html_name = "分鏡稿報告.html"

        video_names = " + ".join([v['name'] for v in st.session_state.video_list])
        
        with st.spinner("正在打包 HTML 檔案..."):
            generator.generate_html(st.session_state.preview_data, video_names, output_html_name, audit_result_json=None)
            
        with open(output_html_name, "rb") as f:
            st.download_button(
                label=f"📄 下載合併版分鏡稿 HTML 報告 ({output_html_name})",
                data=f,
                file_name=output_html_name,
                mime="text/html",
                type="primary",
                use_container_width=True
            )
            
        if st.button("返回上一步修改", use_container_width=True):
            st.session_state.workflow_stage = "preview"
            st.rerun()
        
        if st.button("重啟新任務", type="secondary", use_container_width=True):
            st.session_state.workflow_stage = "input"
            st.session_state.preview_data = None
            st.session_state.video_list = []
            st.rerun()


    # === 延遲渲染的繁重處理區 (Deferred Heavy Processing) ===
    # 放置於 main 函式結尾，確保 col_left 與 col_right 都已完成版面渲染，避免 UI 消失
    
    if st.session_state.get("run_pdf_analysis", False):
        if parse_mode_selection != "fast_text" and "mock" not in model_selection and "ollama" not in model_selection and "partner" not in model_selection and not api_key_input:
            st.error("請先在左側邊欄輸入 API Key！")
            st.session_state.run_pdf_analysis = False
        else:
            with st.spinner("正在逐頁解析 PDF，請稍候..."):
                progress_bar = st.progress(0, text="準備分析 PDF 頁面...")
                def preview_progress(current, total, msg):
                    pct = min(100, int((current / max(1, total)) * 100))
                    progress_bar.progress(pct, text=msg)
                
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
                    master_tasks = planner.plan_tasks_from_pdf_vision(tmp_path, max_pages=-1, parse_mode=parse_mode_selection, progress_callback=preview_progress)
                    
                    # 自動匯出 Excel
                    try:
                        # import pandas as pd
                        excel_filename = os.path.splitext(sop_file.name)[0] + ".xlsx"
                        df_export = pd.DataFrame(master_tasks)
                        df_export.rename(columns={
                            "page_number": "SOP 頁碼",
                            "step_number": "步驟編號",
                            "part_name": "零件/專有名詞",
                            "action_description": "動作描述/工法",
                            "is_selected": "是否選取"
                        }, inplace=True)
                        df_export.to_excel(excel_filename, index=False)
                        st.session_state.excel_export_msg = f"✅ 已成功匯出/覆寫 Excel: {excel_filename}"
                    except Exception as e:
                        st.session_state.excel_export_msg = f"⚠️ Excel 匯出失敗: {e}"
                        
                    # 為每個任務加入是否勾選的預設狀態
                    for t in master_tasks:
                        t["is_selected"] = False
                        
                    tasks = master_tasks
                    progress_bar.progress(100, text="✅ 分析與影片物件對齊完成！")
                    st.session_state.pdf_preview_tasks = tasks
                    st.session_state.run_pdf_analysis = False
                    show_pdf_preview_modal()
                except Exception as e:
                    st.session_state.pdf_preview_error = str(e)
                    st.session_state.run_pdf_analysis = False
                    st.rerun()
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)

    if st.session_state.get("run_video_analysis", False):
        if "mock" not in model_selection and "ollama" not in model_selection and "partner" not in model_selection and not api_key_input:
            st.error("請先在左側邊欄輸入 API Key！")
            st.session_state.run_video_analysis = False
        else:
            with st.spinner("🚀 正在抽取影格並呼叫 AI 進行純視覺分析，請稍候... (約需 10~30 秒)"):
                try:
                    from models import get_vision_model
                    if "mock" in model_selection:
                        m_type = "mock"
                    elif "ollama" in model_selection:
                        m_type = "ollama"
                    elif "partner" in model_selection:
                        m_type = "partner"
                    else:
                        m_type = "gemini"
                        
                    # 臨時寫入 debug info
                    with open("temp_debug_mtype.txt", "w") as f:
                        f.write(f"model_selection: {model_selection}\nm_type: {m_type}\n")
                        
                    m_name = ""
                    if m_type == "gemini": m_name = gemini_model_version
                    elif m_type == "ollama": m_name = locals().get("ollama_model_version", "llava-llama3")
                    elif m_type == "partner": m_name = locals().get("partner_model_name", "default")
                        
                    if m_type == "partner":
                        vm = get_vision_model(model_type=m_type, endpoint_url=locals().get("partner_api_url", ""), model_name=m_name)
                    else:
                        vm = get_vision_model(model_type=m_type, api_key=api_key_input.strip() if api_key_input else "", model_name=m_name)
                    
                    from analyzer import StoryboardAnalyzer
                    analyzer = StoryboardAnalyzer(vision_model=vm)
                    
                    from video_processor import VideoProcessor
                    
                    all_results = []
                    for vid in st.session_state.video_list:
                        processor = VideoProcessor(vid["path"])
                        # 每部影片時間軸從 0 開始獨立計算
                        kf = processor.extract_keyframes(use_scene_detection=False, time_offset=0.0, interval_seconds=st.session_state.int_input, max_frames=st.session_state.max_input)
                        for k in kf:
                            k["source_video"] = vid["name"]
                        
                        # 單獨分析這部影片
                        raw_preview_storyboard = analyzer.analyze_video_frames(kf, glossary=None)
                        
                        # 單獨為這部影片生成敘述
                        summary_prompt = f"以下是從工廠作業影片「{vid['name']}」中，依時間順序擷取出的動作清單：\n\n"
                        for item in raw_preview_storyboard:
                            summary_prompt += f"- [時間 {item.get('time_sec', 0):.2f} 秒] 操作物件: {item.get('part_name', '')}, 動作: {item.get('action_description', '')}\n"
                        
                        summary_prompt += """
請根據上述動作清單，寫一段通順、連貫的敘述文字，描述整部影片的完整操作過程。
請不要使用條列式或時間軸，直接將過程整合成一段或數段完整的文章敘述。
請務必且強制使用「繁體中文 (Traditional Chinese)」回答。
"""
                        narrative_summary = vm.generate_text(summary_prompt, expect_json=False)
                        
                        all_results.append({
                            "video_name": vid["name"],
                            "storyboard": raw_preview_storyboard,
                            "narrative": narrative_summary
                        })
                        
                    st.session_state.video_preview_all_results = all_results
                    st.session_state.run_video_analysis = False
                    st.session_state.auto_open_video_modal = True
                except Exception as e:
                    st.session_state.video_preview_error = str(e)
                    st.session_state.run_video_analysis = False
                st.rerun()

    if st.session_state.pop("auto_open_video_modal", False):
        show_video_preview_modal()

    # 2. 處理手部裁切預覽
    if st.session_state.get("hand_crop_requested", False) and 'hand_crop_ui_container' in locals():
        with hand_crop_ui_container:
            if "video_list" in st.session_state and st.session_state.video_list:
                if "hand_crop_preview_img" not in st.session_state or st.session_state.get("hand_crop_padding_used") != hand_crop_padding or st.session_state.get("hand_crop_top_used") != top_exclusion:
                    with st.spinner("正在掃描「第一部影片」中間正負 3 秒尋找手部... (預覽裁切參數)"):
                        from video_processor import VideoProcessor
                        vp = VideoProcessor(st.session_state.video_list[0]["path"])
                        preview_img = vp.preview_hand_crop(padding=hand_crop_padding, top_exclusion_ratio=top_exclusion / 100.0)
                        st.session_state.hand_crop_preview_img = preview_img
                        st.session_state.hand_crop_padding_used = hand_crop_padding
                        st.session_state.hand_crop_top_used = top_exclusion
                        # 移除 st.rerun()，避免強制中斷腳本導致上傳檔案的快取被 Streamlit 清空

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
                    # 按鈕本身就會觸發重新執行，不需要再呼叫 st.rerun()
            else:
                st.warning("請先上傳影片！")

if __name__ == "__main__":
    main()


