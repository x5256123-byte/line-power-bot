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
        creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json), ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        client = gspread.authorize(creds)
        sheet = client.open_by_key("1GOPuTeocq6G0gj4AUMdPUiE84TicJhj0Qcwvn2Sjoe4").worksheet("工作表1")
        
        # 避開標題列問題的絕對位置讀取法
        all_values = sheet.get_all_values()
        data = []
        for r in all_values[2:]: # 從第3列開始
            if len(r) >= 6:
                data.append({"台號": str(r[0]).strip(), "台名": str(r[1]).strip(), "模組型號": str(r[3]).strip(), "(模組位置 / 光接點)": str(r[5]).strip()})
        return data
    except Exception as e:
        print(f"DEBUG: Sheets 連線異常: {e}")
        return []

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    handler.handle(request.get_data(as_text=True), signature)
    return 'OK'

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
        debug_list = [str(r.get("台號", "NULL")) for r in data[:3]]
        results = [r for r in data if msg.strip() == str(r.get("台號", "")).strip()]
        
        if not results:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"查無此站 '{msg}'。\n\n[除錯資訊]\n前3筆台號為：{debug_list}\n請檢查輸入格式。"))
        else:
            process_selection(uid, event.reply_token, results[0])
    elif session["step"] == "input_equip":
        if msg == "計算":
            line_bot_api.reply_message(event.reply_token, TextSendMessage(get_report(session["site_name"], session["equipments"])))
        elif len(msg.split()) == 2 and msg.split()[0] in EQUIPMENT_DATABASE:
            m, q = msg.split()[0], int(msg.split()[1])
            session["equipments"][m] = session["equipments"].get(m, 0) + q
            USER_SESSIONS[uid] = session
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"已追加 {m}，共 {session['equipments'][m]} 台。"))

def get_report(site_name, equipments):
    bbu_p = 400
    total_rf = sum(EQUIPMENT_DATABASE[m]["power"] * q for m, q in equipments.items())
    net_dc = bbu_p + total_rf
    nfb = max(30, min(100, (math.ceil(((net_dc / 0.92) / (220 * 0.9) * 1.25)/10)*10)))
    wire = "8.0 mm²" if nfb <= 30 else ("14 mm²" if nfb <= 50 else "22 mm²")
    details = "\n".join([f"• {EQUIPMENT_DATABASE[m]['name']} x {q}台" for m, q in equipments.items()])
    return f"🔍 【站台：{site_name}】\n總負載: {net_dc:.0f} W\n建議 NFB: {nfb} A\n建議線徑: {wire}\n\n輸入「0」返回，或「型號 數量」追加。"

def process_selection(uid, token, r):
    site_name = f"{r.get('台名', '未知')}-{r.get('(模組位置 / 光接點)', '未知')}"
    equipments = {m: 1 for m in EQUIPMENT_DATABASE if m in r.get("模組型號", "").upper()}
    USER_SESSIONS[uid] = {"step": "input_equip", "site_name": site_name, "equipments": equipments}
    line_bot_api.reply_message(token, TextSendMessage(text=f"已載入 {site_name}。\n輸入「計算」顯示報告。"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
