import os

class StoryboardGenerator:
    def __init__(self, template_path: str = "storyboard_template.html"):
        self.template_path = template_path

    def format_time(self, seconds: float) -> str:
        """將秒數格式化為 MM:SS:ms，例如 01:05:500"""
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int(round((seconds - int(seconds)) * 1000))
        return f"{m:02d}:{s:02d}:{ms:03d}"

    def generate_html(self, storyboard_data: list, video_name: str, output_path: str = "output_storyboard.html", audit_result_json: dict = None):
        """
        將分鏡稿資料與 Base64 圖片注入 HTML 模板中，生成最終報表。
        """
        if not os.path.exists(self.template_path):
            print(f"[Generator] 找不到 HTML 模板: {self.template_path}")
            return False

        with open(self.template_path, 'r', encoding='utf-8') as f:
            template = f.read()

        table_rows_html = ""
        for idx, item in enumerate(storyboard_data, 1):
            start_str = self.format_time(item.get('start_time', 0))
            end_str = self.format_time(item.get('end_time', 0))
            
            action_desc = item.get('action_description', '')
            part_name = item.get('part_name', '')
            source_video = item.get('source_video', '')
            subtitle = item.get('subtitle', '')
            
            sop_badge_html = ""
            if item.get("sop_step"):
                sop_file = item.get("sop_file", "未提供")
                sop_page = item.get("sop_page", "")
                sop_step = item.get("sop_step", "").replace('"', '&quot;').replace("'", "&#39;")
                page_str = f"第 {sop_page} 頁" if sop_page else "未提供頁碼"
                tooltip_text = f"SOP 檔案：{sop_file}&#10;頁碼：{page_str}&#10;步驟內容：{sop_step}"
                sop_badge_html = f'<div style="display: inline-block; background: #eff6ff; color: #1d4ed8; padding: 4px 10px; border-radius: 6px; font-size: 0.85em; font-weight: bold; margin-bottom: 12px; margin-left: 8px; border: 1px solid #bfdbfe; box-shadow: 0 1px 2px rgba(0,0,0,0.05); cursor: help;" title="{tooltip_text}">📘 對照SOP</div>'
            
            # 若有標準工時異常，顯示紅色 Badge
            abnormal_badge = ""
            if item.get("is_abnormal", False):
                diff = item.get("duration_diff", 0)
                abnormal_badge = f'<span class="badge-abnormal">超時 {diff}s</span>'

            # 來源影片小標籤
            source_html = f'<div style="font-size: 0.8em; color: var(--text-muted); margin-top: 8px; text-align: center;">📁 來源: {source_video}</div>' if source_video else ''

            # 決定顯示圖片還是影片
            clip_path = item.get("video_clip_path")
            img_data = item.get("image_base64", "")
            
            if clip_path and os.path.exists(clip_path):
                import urllib.parse
                safe_path = urllib.parse.quote(clip_path)
                poster_attr = f'poster="data:image/jpeg;base64,{img_data}"' if img_data else ""
                # 使用 HTML5 video 標籤，並加入 poster 作為無影片時的保底截圖
                media_html = f'<video src="{safe_path}" {poster_attr} autoplay loop muted playsinline style="max-width: 100%; max-height: 250px; border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); cursor: pointer;" onclick="if(this.paused) this.play(); else this.pause();"></video>'
            else:
                if img_data:
                    media_html = f'<img src="data:image/jpeg;base64,{img_data}" alt="鏡頭 {idx}">'
                else:
                    media_html = f'<div style="width: 100%; height: 150px; display: flex; align-items: center; justify-content: center; background: #fef2f2; color: #ef4444; border-radius: 8px; font-weight: bold; border: 2px dashed #fca5a5;">無對應畫面</div>'

            # 組合 Table Row HTML
            row = f"""
            <tr class="storyboard-row">
                <td class="img-cell">
                    {media_html}
                    {source_html}
                </td>
                <td class="text-cell">
                    <div onclick="navigator.clipboard.writeText(this.innerText.replace(' 📋已複製', '').trim()); let el=document.createElement('span'); el.innerText=' 📋已複製'; el.style.color='#10b981'; el.style.fontSize='0.8em'; el.style.marginLeft='8px'; this.appendChild(el); setTimeout(()=>el.remove(), 1500);" style="font-weight: 600; color: var(--primary); margin-bottom: 12px; cursor: pointer;" title="點擊複製步驟標題" onmouseover="this.style.opacity='0.7'" onmouseout="this.style.opacity='1'">
                        {part_name}
                    </div>
                    <div style="display: inline-block; background: #f0fdf4; color: #166534; padding: 4px 10px; border-radius: 6px; font-size: 0.85em; font-weight: bold; margin-bottom: 12px; border: 1px solid #bbf7d0; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
                        ⏱️ {start_str} ~ {end_str} {abnormal_badge}
                    </div>
                    {sop_badge_html}
                    <div style="color: var(--text-main); line-height: 1.6; margin-bottom: 8px; text-indent: 2em;">
                        {action_desc}
                    </div>
                    {f'<div style="margin-top: 15px; padding: 10px; background: #f1f5f9; border-left: 4px solid var(--primary); font-style: italic; color: var(--text-main);">💬 旁白/字幕：{subtitle}</div>' if subtitle else ''}
                </td>
            </tr>
            """
            table_rows_html += row

        # 處理 SOP 稽核面板
        audit_panel_html = ""
        if audit_result_json and not "error" in audit_result_json:
            overall = audit_result_json.get("overall_conclusion", "")
            anchor = audit_result_json.get("anchor_step", "")
            missing = audit_result_json.get("missing_steps", [])
            
            missing_html = ""
            if missing:
                missing_html = f"<div style='color: #ef4444; font-weight: bold; margin-top: 10px;'>❌ 漏做步驟：{', '.join(missing)}</div>"
            else:
                missing_html = f"<div style='color: #22c55e; font-weight: bold; margin-top: 10px;'>✅ 步驟無遺漏</div>"
                
            audit_panel_html = f'''
            <div style="background: #ffffff; padding: 20px; border-radius: 12px; border: 2px solid #8b5cf6; margin-bottom: 30px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                <h2 style="color: #8b5cf6; margin-top: 0;">SOP 智能稽核報告</h2>
                <div style="margin-bottom: 10px;"><strong>📍 基準錨點定位：</strong> {anchor}</div>
                <div><strong>📝 總結報告：</strong> {overall}</div>
                {missing_html}
            </div>
            '''
        
        # 替換模板變數
        report_title_name = os.path.splitext(os.path.basename(output_path))[0]
        display_title = report_title_name
        if display_title.endswith("分鏡稿"):
            display_title = display_title[:-3]
        elif display_title.endswith("_storyboard"):
            display_title = display_title[:-11]
            
        html_content = template.replace("__REPORT_TITLE__", display_title)
        html_content = html_content.replace("__TABLE_ROWS_HTML__", table_rows_html)
        html_content = html_content.replace("__AUDIT_PANEL_HTML__", audit_panel_html)
        
        # 處理影片名稱清單 (以 + 號分隔)
        video_list = video_name.split(" + ")
        video_names_html = "".join([f"<li>{v}</li>" for v in video_list])
        html_content = html_content.replace("__VIDEO_NAMES_HTML__", video_names_html)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        print(f"[Generator] 成功生成分鏡稿報告: {output_path}")
        return True
