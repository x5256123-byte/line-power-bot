import os
import math
import re
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# ---------- 動態讀取 Render 後台的環境變數 ----------
CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '')
CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', '')

print(f"【系統啟動檢查】")
print(f"-> TOKEN 讀取狀態: {'❌ 失敗(None)' if not CHANNEL_ACCESS_TOKEN else f'✅ 成功(長度:{len(CHANNEL_ACCESS_TOKEN)})'}")
print(f"-> SECRET 讀取狀態: {'❌ 失敗(None)' if not CHANNEL_SECRET else f'✅ 成功(長度:{len(CHANNEL_SECRET)})'}")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# ---------- 📊 設備資料庫 (已完成全型號校正，無括號方便輸入) ----------
EQUIPMENT_DATABASE = {
    "FXDB": {"type": "normal", "power": 260},
    "FHDB": {"type": "normal", "power": 300},
    "AHDB": {"type": "normal", "power": 300},
    "FXEB": {"type": "normal", "power": 340},
    "FHEB": {"type": "normal", "power": 340},
    "FHEL": {"type": "normal", "power": 350},
    "AHEB": {"type": "normal", "power": 420},
    "FRHG": {"type": "normal", "power": 360},
    "AHHB": {"type": "normal", "power": 580},
    "AZQG": {"type": "normal", "power": 750},
    "AZQI": {"type": "normal", "power": 750},
    "AEQZ": {"type": "normal", "power": 1050},
    "AQQA": {"type": "normal", "power": 1050},
    "AQQY": {"type": "normal", "power": 950},
    "AVQC": {"type": "normal", "power": 950},
    "AVQL": {"type": "normal", "power": 1450},
    "AHEGB": {"type": "dual", "N1_Only": 350, "N1_With_B3": 560},
    "AHEGG": {"type": "dual", "N1_Only": 350, "N1_With_B3": 560}
}

SMR_DATABASE = [
    {"name": "TYPE 1 (2.0 kW)", "capacity": 2000},
    {"name": "SMR (5.0 kW)", "capacity": 5000},
    {"name": "TYPE 3 (6.0 kW)", "capacity": 6000},
    {"name": "SMR (7.5 kW)", "capacity": 7500}
]
BATTERY_MARGIN = 0.15
PF = 0.90
AC_VOLTAGE = 220
CB_SAFETY = 1.25

def calculate_power(bbu_watt, efficiency_percent, devices):
    if not devices:
        return None
    eff = efficiency_percent / 100.0
    total_rf = 0
    details = []
    for model, qty, b3 in devices:
        spec = EQUIPMENT_DATABASE.get(model)
        if not spec:
            continue
        if spec["type"] == "dual":
            unit_power = spec["N1_With_B3"] if b3 else spec["N1_Only"]
            tag = " (含B3)" if b3 else " (純N1)"
        else:
            unit_power = spec["power"]
            tag = ""
        row_power = unit_power * qty
        total_rf += row_power
        details.append(f"{model}{tag} x{qty}台 = {row_power}W")
    net_dc = bbu_watt + total_rf
    battery_margin = net_dc * BATTERY_MARGIN
    total_dc = net_dc + battery_margin
    selected_smr = "⚠️ 超出 7.5kW"
    for smr in SMR_DATABASE:
        if smr["capacity"] >= total_dc:
            selected_smr = smr["name"]
            break
    ac_power = total_dc / eff
    ac_current = ac_power / (AC_VOLTAGE * PF)
    nfb = math.ceil(ac_current * CB_SAFETY)
    
    # 💡 修正重點：配合一線實務，總電流 (NFB) 30A 以下一律改成 8 平方 (8.0mm²)
    if nfb <= 30:
        wire = "8.0mm² (實務安全特規)"
    elif nfb <= 50:
        wire = "14mm²"
    else:
        wire = "22mm² 以上"
        
    return {
        "details": details,
        "net_dc": net_dc,
        "total_dc": total_dc,
        "selected_smr": selected_smr,
        "ac_power": ac_power,
        "ac_current": ac_current,
        "nfb": nfb,
        "wire": wire,
        "efficiency": efficiency_percent
    }

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    
    if '"events":[]' in body or not signature:
        print("【安全通關】偵測到 LINE 測試用空事件封包，直接 Bypass 回傳 200！")
        return 'OK', 200

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("【驗證失敗】數位簽章不符！請確認 Render 後台環境變數。")
        abort(400)
    except Exception as e:
        print(f"【未知例外】已安全防護處理，原因: {e}")
        return 'OK', 200
        
    return 'OK', 200

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text.strip()
    if user_text == "幫助" or user_text == "help":
        reply = "請輸入設備格式：\n型號 數量 [含B3]\n多行輸入多個設備，最後一行輸入 BBU功耗 效率%\n範例：\nFRHG 2\nAHEGB 1 含B3\n500 92"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return
    # 解析輸入
    lines = user_text.split('\n')
    devices = []
    bbu = 500
    eff = 92
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 判斷是否為 BBU 效率行
        parts = line.split()
        if len(parts) == 2 and parts[0].replace('.','',1).isdigit() and parts[1].replace('.','',1).isdigit():
            bbu = float(parts[0])
            eff = float(parts[1])
            continue
        # 解析設備行
        match = re.match(r'^(.+?)\s+(\d+)\s*(含B3|B3)?', line)
        if match:
            model = match.group(1).strip()
            qty = int(match.group(2))
            b3 = match.group(3) is not None
            if model in EQUIPMENT_DATABASE:
                devices.append((model, qty, b3))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"未知型號: {model}"))
                return
        else:
            if line in EQUIPMENT_DATABASE:
                devices.append((line, 1, False))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"無法辨識: {line}"))
                return
    if not devices:
        reply = "未偵測到設備，請輸入如：\nFRHG 2\nAHEGB 1 含B3\n最後一行加上 500 92"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return
    result = calculate_power(bbu, eff, devices)
    if not result:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="計算失敗"))
        return
    msg = f"📊 基地台電力報告\n"
    msg += "\n".join(result["details"]) + "\n"
    msg += f"直流總負載: {result['net_dc']:.0f} W\n"
    msg += f"含15%充電: {result['total_dc']:.0f} W\n"
    msg += f"建議SMR: {result['selected_smr']}\n"
    msg += f"交流總功耗: {result['ac_power']:.0f} W (效率{result['efficiency']}%)\n"
    msg += f"220V電流: {result['ac_current']:.2f} A\n"
    msg += f"建議NFB: {result['nfb']} A 2P\n"
    msg += f"建議線徑: {result['wire']}"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
