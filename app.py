import os
import math
import csv
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# --- LINE API 設定 ---
line_bot_api = LineBotApi(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.environ.get("LINE_CHANNEL_SECRET"))
CSV_FILE_PATH = os.path.join(os.path.dirname(__file__), "pingtung_sites.csv")

# --- 設備資料庫 ---
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

def get_report(site_name, equipments, ac_phase):
    bbu_p = 400
    total_rf = sum(EQUIPMENT_DATABASE[m]["power"] * q for m, q in equipments.items() if m in EQUIPMENT_DATABASE)
    net_dc = bbu_p + total_rf
    ac_w = net_dc / 0.92
    ac_curr = ac_w / (220 * 0.9)
    nfb = max(30, min(100, (math.ceil((ac_curr * 1.25)/10)*10)))
    wire = "8.0 mm²" if nfb <= 30 else ("14 mm²" if nfb <= 50 else "22 mm²")
    
    details = "\n".join([f"• {EQUIPMENT_DATABASE[m]['name']} x {q}台" for m, q in equipments.items()])
    return (f"🔍 【站台：{site_name}】\n供電：{'單相三線' if ac_phase=='1P3W' else '三相四線'}\n\n設備清單：\n{details}\n"
            f"-------------------\n總負載: {net_dc:.0f} W\n建議 NFB: {nfb} A\n建議線徑: {wire}\n\n輸入「0」返回，或「型號 數量」追加。")

@app.route("/callback", methods=['POST'])
def callback():
    try:
        handler.handle(request.get_data(as_text=True), request.headers.get('X-Line-Signature'))
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    uid = event.source.user_id
    msg = event.message.text.strip().upper()
    
    if msg in ["開始評估", "HELP", "0"]:
        USER_SESSIONS[uid] = {"step": "input_id", "equipments": {}}
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請輸入站號，若為大站可加空格輸入位置（例：711524 泰隆）："))
        return

    session = USER_SESSIONS.get(uid, {"step": "input_id", "equipments": {}})

    if session["step"] == "input_id":
        parts = msg.split()
        sid_q = parts[0]
        loc_q = " ".join(parts[1:]).upper()
        results = []
        with open(CSV_FILE_PATH, encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                if sid_q in str(r.get("台號", "")):
                    loc_name = r.get("(模組位置 / 光接點)", "未知").split('/')[-1].strip().upper()
                    if not loc_q or loc_q in loc_name:
                        results.append({"name": f"{r.get('台名', '未知')}-{loc_name}", "equip": r.get("模組型號", "")})
        
        unique = {r['name']: r for r in results}.values()
        results = list(unique)

        if not results:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="查無此站，請確認站號。"))
        elif len(results) > 1:
            session["step"] = "select_site"
            session["options"] = results
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="找到多個位置，請輸入編號：\n" + "\n".join([f"{i+1}. {r['name']}" for i, r in enumerate(results[:9])])))
            USER_SESSIONS[uid] = session
        else:
            process_selection(uid, event.reply_token, results[0]['name'])

    elif session["step"] == "select_site":
        try:
            idx = int(msg) - 1
            if 0 <= idx < len(session["options"]):
                process_selection(uid, event.reply_token, session["options"][idx]['name'])
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="編號錯誤。"))
        except: line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請輸入數字編號。"))

    elif session["step"] == "input_equip":
        if msg == "計算":
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=get_report(session["site_name"], session["equipments"], "1P3W")))
        else:
            parts = msg.split()
            if len(parts) == 2 and parts[0] in EQUIPMENT_DATABASE:
                m, q = parts[0], int(parts[1])
                session["equipments"][m] = session["equipments"].get(m, 0) + q
                USER_SESSIONS[uid] = session
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"已更新 {m}，共 {session['equipments'][m]} 台。"))
            else: line_bot_api.reply_message(event.reply_token, TextSendMessage(text="格式錯誤，請輸入「型號 數量」。"))

def process_selection(uid, token, selected_name):
    equipments = {}
    with open(CSV_FILE_PATH, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            loc_name = r.get("(模組位置 / 光接點)", "未知").split('/')[-1].strip().upper()
            if f"{r.get('台名', '未知')}-{loc_name}" == selected_name:
                raw_model = r.get("模組型號", "").upper()
                for db_model in EQUIPMENT_DATABASE:
                    if db_model in raw_model:
                        equipments[db_model] = equipments.get(db_model, 0) + 1
    
    USER_SESSIONS[uid] = {"step": "input_equip", "site_name": selected_name, "equipments": equipments}
    line_bot_api.reply_message(token, TextSendMessage(text=f"已載入 {selected_name}，共 {sum(equipments.values())} 台。\n輸入「計算」顯示報告，或「型號 數量」追加。"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
