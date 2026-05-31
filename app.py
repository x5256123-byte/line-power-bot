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

EQUIPMENT_DATABASE = {
    "FXDB": {"name": "FXDB", "power": 780}, "FHDB": {"name": "FHDB", "power": 780},
    "ARDA": {"name": "ARDA", "power": 480}, "FRHG": {"name": "FRHG", "power": 490},
    "FHEL": {"name": "FHEL", "power": 350}, "FWHN": {"name": "FWHN", "power": 95}
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
            f"-------------------\n總負載: {net_dc:.0f} W\n建議 NFB: {nfb} A\n建議線徑: {wire}\n\n輸入「0」返回。")

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
    uid = event.source.user_id
    msg = event.message.text.strip().upper()
    
    if msg in ["開始評估", "HELP", "0"]:
        USER_SESSIONS[uid] = {"step": "input_id"}
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請輸入站號（例如：711524）："))
        return

    session = USER_SESSIONS.get(uid, {"step": "input_id"})

    if session["step"] == "input_id":
        results = []
        try:
            with open(CSV_FILE_PATH, encoding='utf-8-sig') as f:
                for r in csv.DictReader(f):
                    if msg in str(r.get("台號", "")):
                        results.append({
                            "name": f"{r['台名']}-{r.get('(模組位置 / 光接點)', '未知位置')}",
                            "equip": r.get("模組型號", "").split('_')[0]
                        })
        except Exception as e:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"讀取錯誤: {str(e)}"))
            return
        
        if not results:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="查無此站，請重試。"))
        elif len(results) > 1:
            session["step"] = "select_site"
            session["options"] = results
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="找到多個站，請輸入編號：\n" + "\n".join([f"{i+1}. {r['name']}" for i, r in enumerate(results[:9])])))
            USER_SESSIONS[uid] = session
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=get_report(results[0]['name'], {results[0]['equip']: 1}, "1P3W")))

    elif session["step"] == "select_site":
        try:
            idx = int(msg) - 1
            if 0 <= idx < len(session["options"]):
                s = session["options"][idx]
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=get_report(s['name'], {s['equip']: 1}, "1P3W")))
                USER_SESSIONS[uid] = {"step": "input_id"}
        except:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="編號錯誤，請輸入正確數字。"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
