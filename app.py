import os
import math
import json
import gspread
from flask import Flask, request, abort
from oauth2client.service_account import ServiceAccountCredentials
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# --- 初始化 ---
def init_line():
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    secret = os.environ.get("LINE_CHANNEL_SECRET")
    return LineBotApi(token) if token else None, WebhookHandler(secret) if secret else None

line_bot_api, handler = init_line()

EQUIPMENT_DATABASE = {
    "FXDB": {"name": "FXDB", "power": 780}, "ARDA": {"name": "ARDA", "power": 480},
    "FHDB": {"name": "FHDB", "power": 780}, "AHDB": {"name": "AHDB", "power": 410},
    "FXEB": {"name": "FXEB", "power": 915}, "FXED": {"name": "FXED", "power": 860},
    "FHEB": {"name": "FHEB", "power": 410}, "AHEB": {"name": "AHEB", "power": 410},
    "FHEL": {"name": "FHEL", "power": 350}, "FRHG": {"name": "FRHG", "power": 490},
    "AHHB": {"name": "AHHB", "power": 321}, "AZQG": {"name": "AZQG", "power": 720},
    "AZQI": {"name": "AZQI", "power": 520}, "AEQZ": {"name": "AEQZ", "power": 570},
    "AQQA": {"name": "AQQA", "power": 2095}, "AQQY": {"name": "AQQY", "power": 740},
    "AVQC": {"name": "AVQC", "power": 900}, "AVQL": {"name": "AVQL", "power": 380},
    "AHEGB": {"name": "AHEGB", "power": 1367}, "AHEGG": {"name": "AHEGG", "power": 410},
    "FW2EHB": {"name": "FW2EHB", "power": 210}, "FWHN": {"name": "FWHN", "power": 95},
    "AWHQE": {"name": "AWHQE", "power": 285}
}

USER_SESSIONS = {}

def get_site_data():
    try:
        creds_json = os.environ.get("GOOGLE_CREDS_JSON")
        if not creds_json: return []
        creds_dict = json.loads(creds_json)
        scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open("x5256123").sheet1
        return sheet.get_all_records()
    except Exception as e:
        print(f"DEBUG: Sheets 連線異常: {e}")
        return []

@app.route("/", methods=['GET'])
def home():
    return "Bot is running", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    if not line_bot_api: return
    uid = event.source.user_id
    msg = event.message.text.strip().upper()
    
    if msg in ["開始評估", "HELP", "0"]:
        USER_SESSIONS[uid] = {"step": "input_id", "equipments": {}}
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請輸入站號："))
        return
    
    session = USER_SESSIONS.get(uid, {"step": "input_id", "equipments": {}})
    
    if session["step"] == "input_id":
        data = get_site_data()
        msg_clean = msg.strip()
        
        # 暴力診斷：查看資料庫內到底有哪些台號
        all_db_ids = [str(r.get("台號", "")).strip() for r in data]
        print(f"DEBUG: 資料庫中的台號清單: {all_db_ids}") 
        
        results = [r for r in data if msg_clean == str(r.get("台號", "")).strip()]
        
        if not results:
            preview = ", ".join(all_db_ids[:3])
            error_msg = f"查無此站 '{msg_clean}'。\n\n資料庫共有 {len(all_db_ids)} 筆資料。\n前 3 筆台號為：\n{preview}\n\n請檢查 Google Sheet 第一列是否為『台號』。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=error_msg))
        else:
            process_selection(uid, event.reply_token, results[0])
            
    elif session["step"] == "input_equip":
        if msg == "計算":
            report = get_report(session["site_name"], session["equipments"], "1P3W")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(report))
        else:
            parts = msg.split()
            if len(parts) == 2 and parts[0] in EQUIPMENT_DATABASE:
                m, q = parts[0], int(parts[1])
                session["equipments"][m] = session["equipments"].get(m, 0) + q
                USER_SESSIONS[uid] = session
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"已追加 {m}，共 {session['equipments'][m]} 台。"))

def get_report(site_name, equipments, ac_phase):
    bbu_p = 400
    total_rf = sum(EQUIPMENT_DATABASE[m]["power"] * q for m, q in equipments.items() if m in EQUIPMENT_DATABASE)
    net_dc = bbu_p + total_rf
    ac_w = net_dc / 0.92
    ac_curr = ac_w / (220 * 0.9)
    nfb = max(30, min(100, (math.ceil((ac_curr * 1.25)/10)*10)))
    wire = "8.0 mm²" if nfb <= 30 else ("14 mm²" if nfb <= 50 else "22 mm²")
    details = "\n".join([f"• {EQUIPMENT_DATABASE[m]['name']} x {q}台" for m, q in equipments.items()])
    return f"🔍 【站台：{site_name}】\n供電：{ac_phase}\n\n設備清單：\n{details}\n-------------------\n總負載: {net_dc:.0f} W\n建議 NFB: {nfb} A\n建議線徑: {wire}\n\n輸入「0」返回，或「型號 數量」追加。"

def process_selection(uid, token, r):
    site_name = f"{r.get('台名', '未知')}-{r.get('(模組位置 / 光接點)', '未知')}"
    equipments = {}
    raw_model = str(r.get("模組型號", "")).upper()
    for db_model in EQUIPMENT_DATABASE:
        if db_model in raw_model:
            equipments[db_model] = equipments.get(db_model, 0) + 1
    USER_SESSIONS[uid] = {"step": "input_equip", "site_name": site_name, "equipments": equipments}
    line_bot_api.reply_message(token, TextSendMessage(text=f"已載入 {site_name}。\n共 {sum(equipments.values())} 台。\n輸入「計算」顯示報告，或「型號 數量」追加。"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
