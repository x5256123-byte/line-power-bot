import os
import math
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# --- LINE API 金鑰設定 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- 中華電信現役 Nokia AirScale 設備直流功耗資料庫 ---
EQUIPMENT_DATABASE = {
    "FXDB": {"name": "FXDB (B8)", "power": 520},
    "FHDB": {"name": "FHDB (B8)", "power": 580},
    "AHDB": {"name": "AHDB (B8)", "power": 580},
    "FXEB": {"name": "FXEB (B3)", "power": 560},
    "FHEB": {"name": "FHEB (B3)", "power": 620},
    "AHEB": {"name": "AHEB (B3)", "power": 620},
    "FRHG": {"name": "FRHG (B7)", "power": 540},
    "AHHB": {"name": "AHHB (B7 8TR)", "power": 780},
    "AZQG": {"name": "AZQG (N35 8TR)", "power": 750},
    "AZQI": {"name": "AZQI (N35 8TR)", "power": 750},
    "AEQZ": {"name": "AEQZ (N35 32TR)", "power": 1050},
    "AQQA": {"name": "AQQA (N35 32TR)", "power": 1050},
    "AQQY": {"name": "AQQY (N35 32TR)", "power": 950},
    "AVQC": {"name": "AVQC (N35 32TR)", "power": 950},
    "AVQL": {"name": "AVQL (N35 64TR)", "power": 1450},
    "AHEGB": {"name": "AHEGB (N1 純5G)", "power": 350},
    "AHEGB+B3": {"name": "AHEGB (N1+B3 混模)", "power": 560},
    "AHEGG": {"name": "AHEGG (N1 純5G)", "power": 350},
    "AHEGG+B3": {"name": "AHEGG (N1+B3 混模)", "power": 560}
}

# SMR 規格與編號對照
SMR_DATABASE = {
    "1": {"name": "TYPE 1 (2.0 kW)", "capacity": 2000},
    "2": {"name": "SMR (5.0 kW)", "capacity": 5000},
    "3": {"name": "TYPE 3 (6.0 kW)", "capacity": 6000},
    "4": {"name": "SMR (7.5 kW)", "capacity": 7500}
}

# 記錄使用者暫存狀態
# 格式: { user_id: { "step": "input_equip", "equipments": {...}, "total_dc_demand": 0, "net_dc_load": 0, "detail_str": "" } }
USER_SESSIONS = {}

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_msg = event.message.text.strip().upper()

    # 初始化會話
    if user_id not in USER_SESSIONS:
        USER_SESSIONS[user_id] = {"step": "input_equip", "equipments": {}}

    session = USER_SESSIONS[user_id]

    # --- 強制重設指令 ---
    if user_msg in ["開始評估", "HELP", "⚡ 新設基地台電力評估"]:
        USER_SESSIONS[user_id] = {"step": "input_equip", "equipments": {}}
        reply_text = (
            "📱 【Nokia AirScale 電力估算助手】\n\n"
            "【步驟 1：輸入新設射頻】\n"
            "請輸入型號與數量，格式為：【型號 數量】\n"
            "範例：\n"
            "輸入「AVQL 3」代表 3片 64TR\n"
            "輸入「AHEGB+B3 3」代表 3台混模\n\n"
            "確認好所有新設設備後，請輸入【計算】觀看直流總瓦數。"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # --- 階段一：處理設備輸入與直流瓦數計算 ---
    if session["step"] == "input_equip":
        if user_msg == "計算":
            if not session["equipments"]:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 您的清單目前是空的，請先輸入設備（如：AVQL 3）。"))
                return

            bbu_p = 500  # 預設 BBU 500W
            total_rf_power = 0
            detail_list = []

            for model, qty in session["equipments"].items():
                spec = EQUIPMENT_DATABASE[model]
                row_total = spec["power"] * qty
                total_rf_power += row_total
                detail_list.append(f"   • {spec['name']} x {qty}台 = {row_total} W")

            net_dc_load = bbu_p + total_rf_power
            battery_charge_margin = net_dc_load * 0.15
            total_dc_demand = net_dc_load + battery_charge_margin

            # 暫存直流計算結果，留到下一步用
            session["net_dc_load"] = net_dc_load
            session["total_dc_demand"] = total_dc_demand
            session["detail_str"] = "\n".join(detail_list)
            
            # 切換到下一個階段：等待選擇直流設備
            session["step"] = "select_smr"

            # 判斷系統智慧推薦哪一款，做為提示
            smart_rec = "超出單組 7.5kW 容量！"
            for k, smr in SMR_DATABASE.items():
                if smr["capacity"] >= total_dc_demand:
                    smart_rec = smr["name"]
                    break

            reply_text = (
                f"🔋 【直流瓦數計算完畢】\n\n"
                f"新設設備直流明細：\n{session['detail_str']}\n"
                f" -----------------------------------\n"
                f" • 主設備純直流負載總和: {net_dc_load:.0f} W\n"
                f" • 預留蓄電池充電容量 (15%): {battery_charge_margin:.0f} W\n"
                f" ⚡ 直流端總電量需求: {total_dc_demand:.0f} W ({total_dc_demand/1000:.2f} kW)\n"
                f" 💡 (系統智慧推薦：{smart_rec})\n"
                f" -----------------------------------\n\n"
                f"【步驟 2：請選填現場要配置的直流設備】\n"
                f"請直接回覆【代號數字 1 ~ 4】:\n"
                f"【1】 TYPE 1 (2.0 kW)\n"
                f"【2】 SMR (5.0 kW)\n"
                f"【3】 TYPE 3 (6.0 kW)\n"
                f"【4】 SMR (7.5 kW)"
            )
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return

        # 處理日常的型號數量輸入 (如: AVQL 3)
        try:
            parts = user_msg.split()
            if len(parts) == 2:
                model, qty_str = parts[0], parts[1]
                if model in EQUIPMENT_DATABASE:
                    qty = int(qty_str)
                    if qty < 0: raise ValueError
                    
                    if qty == 0:
                        if model in session["equipments"]:
                            del session["equipments"][model]
                        reply = f"已從清單中移除 {model}。"
                    else:
                        session["equipments"][model] = qty
                        reply = f"✅ 已記錄：{EQUIPMENT_DATABASE[model]['name']} 共 {qty} 台。\n現有清單：\n"
                        for k, v in session["equipments"].items():
                            reply += f"• {EQUIPMENT_DATABASE[k]['name']}: {v}台\n"
                        reply += "\n繼續輸入其他設備，或輸入【計算】觀看直流瓦數並選擇SMR。"
                    
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
                    return
        except ValueError:
            pass

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 無法辨識。請輸入「型號 數量」(如：AVQL 3)，或輸入「計算」。"))

    # --- 階段二：處理同仁選填的直流設備並輸出最終交流統計 ---
    elif session["step"] == "select_smr":
        if user_msg in SMR_DATABASE:
            chosen_smr = SMR_DATABASE[user_msg]
            total_dc_demand = session["total_dc_demand"]
            net_dc_load = session["net_dc_load"]
            smr_efficiency = 0.92
            pf = 0.90

            # 安全容量檢查警告
            safety_warning = ""
            if chosen_smr["capacity"] < total_dc_demand:
                safety_warning = f"\n⚠️ 【工程警告】：您選的 {chosen_smr['name']} 容量小於直流總需求 ({total_dc_demand:.0f}W)，現場運轉有過載跳脫風險！\n"

            # 最終交流電統計 (單相三線式 220V)
            ac_total_w = total_dc_demand / smr_efficiency
            ac_current = ac_total_w / (220 * pf)
            suggested_nfb = math.ceil(ac_current * 1.25)

            if suggested_nfb <= 20: suggested_wire = "2.0 mm 或 3.5 mm²"
            elif suggested_nfb <= 30: suggested_wire = "5.5 mm²"
            elif suggested_nfb <= 50: suggested_wire = "8.0 mm² 或 14 mm²"
            else: suggested_wire = "22 mm² 或以上"

            report = (
                f"📋 【⚡ 基地台電力全系統統計報告】\n"
                f"{safety_warning}\n"
                f" 🔹 1. 新設射頻清單：\n{session['detail_str']}\n"
                f" -----------------------------------\n"
                f" 🔋 2. 直流供電設備確認\n"
                f"   • 主設備純直流負載: {net_dc_load:.0f} W\n"
                f"   • 直流端總電量需求: {total_dc_demand:.0f} W\n"
                f"   👉 現場配置設備: 【{chosen_smr['name']}】\n"
                f" -----------------------------------\n"
                f" ⚡ 3. 交流供電系統統計 (單相三線 220V)\n"
                f"   • SMR 換算交流側總功耗: {ac_total_w:.0f} W\n"
                f"   • 現場運轉線電流負載: {ac_current:.2f} A\n"
                f"   👉 建議 NFB 開關規格: {suggested_nfb} A 2P (已含1.25倍安全係數)\n"
                f"   👉 參考建議進線線徑: {suggested_wire}\n\n"
                f"💡 輸入「開始評估」可開啟下一座台的電力計算。"
            )
            
            # 計算完畢，將狀態回歸初始，方便下一次使用
            USER_SESSIONS[user_id] = {"step": "input_equip", "equipments": {}}
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=report))
            return
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 請輸入正確的直流設備代號數字 (1、2、3 或 4)。"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
