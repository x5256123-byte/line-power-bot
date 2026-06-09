# ... (前面的 import 與初始化保持不變) ...

def get_site_data():
    try:
        creds_json = os.environ.get("GOOGLE_CREDS_JSON")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json), ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        client = gspread.authorize(creds)
        sheet = client.open_by_key("172To-4ENLnZutCsPP7qXCpXNANo4A5YNcyuRadHUGzg").worksheet("工作表1")
        
        all_values = sheet.get_all_values()
        data = []
        # 從第 3 列 (index 2) 開始，直到最後一列
        for r in all_values[2:]:
            # 確保列有足夠長度，並印出內容到 Log 以利除錯
            if len(r) >= 6:
                # 這裡我們將每一列資料都存起來
                data.append({
                    "台號": str(r[0]).strip(), 
                    "台名": str(r[1]).strip(), 
                    "模組型號": str(r[3]).strip(), 
                    "(模組位置 / 光接點)": str(r[5]).strip()
                })
        return data
    except Exception as e:
        print(f"DEBUG: 讀取失敗: {e}")
        return []

# --- 修改處：process_selection 改為接收該站所有結果 ---
def process_selection(uid, token, r_list):
    # 組合站台名稱
    site_name = f"{r_list[0].get('台名', '未知')}-{r_list[0].get('(模組位置 / 光接點)', '未知')}"
    
    # 自動統計所有設備
    equipments = {}
    for r in r_list:
        m = str(r.get("模組型號", "")).strip().upper()
        if m in EQUIPMENT_DATABASE:
            equipments[m] = equipments.get(m, 0) + 1
            
    USER_SESSIONS[uid] = {"step": "input_equip", "site_name": site_name, "equipments": equipments}
    
    summary = "\n".join([f"• {m} x {q}台" for m, q in equipments.items()])
    line_bot_api.reply_message(token, TextSendMessage(text=f"已載入 {site_name}。\n發現設備：\n{summary}\n\n輸入「計算」顯示報告。"))

# --- 修改處：handle_message 邏輯 ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    uid, msg = event.source.user_id, event.message.text.strip().upper()
    if msg in ["開始評估", "HELP", "0"]:
        USER_SESSIONS[uid] = {"step": "input_id", "equipments": {}}
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請輸入站號："))
        return
    
    session = USER_SESSIONS.get(uid, {"step": "input_id", "equipments": {}})
    if session["step"] == "input_id":
        data = get_site_data()
        # 關鍵修改：找出所有符合該站號的列，而不只是第一列
        results = [r for r in data if msg == str(r.get("台號", "")).strip()]
        
        if not results:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"查無此站 '{msg}'，請檢查 Excel 台號。"))
        else:
            # 傳入整個清單 (results) 而非單一項目
            process_selection(uid, event.reply_token, results)
# ... (其餘程式碼保持不變) ...
