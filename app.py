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

# --- Nokia AirScale 日常運轉基本功耗資料庫 ---
EQUIPMENT_DATABASE = {
    "FXDB": {"name": "FXDB", "power": 380},
    "FHDB": {"name": "FHDB", "power": 380},
    "AHDB": {"name": "AHDB", "power": 380},
    "FXEB": {"name": "FXEB", "power": 360},  
    "FHEB": {"name": "FHEB", "power": 400},
    "AHEB": {"name": "AHEB", "power": 400},
    "FHEL": {"name": "FHEL", "power": 430},  
    "FRHG": {"name": "FRHG", "power": 350},  
    "AHHB": {"name": "AHHB", "power": 510},  
    "AZQG": {"name": "AZQG", "power": 480},
    "AZQI": {"name": "AZQI", "power": 480},
    "AEQZ": {"name": "AEQZ", "power": 680},
    "AQQA": {"name": "AQQA", "power": 680},
    "AQQY": {"name": "AQQY", "power": 620},
    "AVQC": {"name": "AVQC", "power": 620},
    "AVQL": {"name": "AVQL", "power": 950},
    "AHEGB": {"name": "AHEGB", "power": 350},
    "AHEGB+B3": {"name": "AHEGB+B3", "power": 560},
    "AHEGG": {"name": "AHEGG", "power": 350},
    "AHEGG+B3": {"name": "AHEGG+B3", "power": 560}
}

# SMR 直流設備對照
SMR_DATABASE = {
    "1": {"name": "TYPE 1 (2.0 kW)", "capacity": 2000},
    "2": {"name": "SMR (5.0 kW)", "capacity": 5000},
    "3": {"name": "TYPE 3 (6.0 kW)", "capacity": 6000},
    "4": {"name": "SMR (7.5 kW)", "capacity": 7500}
}

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
    raw_msg = event.message.text.strip()
    user_msg = raw_msg.upper()  # 💡 強制全轉大寫，保證後續「計算」、「開始評估」不受大小寫影響

    if user_id not in USER_SESSIONS:
        USER_SESSIONS[user_id] = {
            "step": "input_site_name", 
            "site_name": "未命名站台", 
            "equipments": {}, 
            "ac_phase": "1P3W", 
            "chosen_smrs": []
        }

    session = USER_SESSIONS[user_id]

    if user_msg in ["開始評估", "HELP", "⚡ 新設基地台電力評估"]:
        USER_SESSIONS[user_id] = {"step": "input_site_name", "site_name": "未命名站台", "equipments": {}, "ac_phase": "1P3W", "chosen_smrs": []}
        reply_text = (
            "📱 【Nokia 電力估算助手 - 現場工法防呆版】\n\n"
            "【步驟 1：請輸入站台名稱】\n"
            "請直接回覆文字告知此站台名稱或編號（如：林園園區_01）。"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 階段零：設定站台名稱
    if session["step"] == "input_site_name":
        session["site_name"] = raw_msg  # 站台名稱保留使用者原始輸入的大小寫
        session["step"] = "input_equip"
        reply_text = (
            f"✅ 站台名稱：【 {raw_msg} 】\n\n"
            f"【步驟 2：輸入新設射頻】\n"
            f"請輸入型號與數量，格式為：【型號 數量】（大小寫皆可，如：avql 3）\n"
            f"確認好設備後，請輸入【計算】。"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    # 階段一：處理設備輸入 (完美支援大小寫)
    elif session["step"] == "input_equip":
        if user_msg == "計算":
            if not session["equipments"]:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 您的清單目前是空的，請先輸入設備。"))
                return
            
            session["step"] = "select_ac_phase"
            reply_text = (
                f"🏢 站台：{session['site_name']}\n\n"
                f"【步驟 3：請選擇現場交流供電相別】\n"
                f"請直接回覆代號數字【1 或 2】:\n"
                f"【1】 🔴 單相三線 (1P3W 220V) - 一般頂樓台/常規站\n"
                f"【2】 🔵 三相四線 (3P4W 380V) - 實務抓 RST 任一相配 N 相接法"
            )
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return

        try:
            parts = user_msg.split()  # 這裡使用已被 .upper() 轉為全大寫的字串來拆解
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
                        # 💡 修正：確保迴圈讀取出來的 Key (k) 在對照資料庫時能正確對應大寫名稱
                        for k, v in session["equipments"].items():
                            reply += f"• {EQUIPMENT_DATABASE[k]['name']}: {v}台\n"
                        reply += "\n輸入【計算】選擇供電相別。"
                    
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
                    return
        except ValueError:
            pass
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 請輸入「型號 數量」(如：avql 3)，或輸入「計算」。"))

    # 階段二：選擇 AC 供電相別
    elif session["step"] == "select_ac_phase":
        if user_msg in ["1", "2"]:
            session["ac_phase"] = "1P3W" if user_msg == "1" else "3P4W"
            
            bbu_p = 400  
            total_rf_power = 0
            detail_list = []

            for model, qty in session["equipments"].items():
                spec = EQUIPMENT_DATABASE[model]
                row_total = spec["power"] * qty
                total_rf_power += row_total
                detail_list.append(f"   • {spec['name']} x {qty}台 = {row_total} W")

            net_dc_load = bbu_p + total_rf_power
            total_dc_demand = net_dc_load 

            dc_kwh_per_hour = total_dc_demand / 1000.0
            dc_kwh_per_month = dc_kwh_per_hour * 24 * 30

            session["net_dc_load"] = net_dc_load
            session["total_dc_demand"] = total_dc_demand
            session["detail_str"] = "\n".join(detail_list)
            
            session["step"] = "select_smr"
            session["chosen_smrs"] = []

            phase_name = "單相三線 220V" if session["ac_phase"] == "1P3W" else "三相四線 (實務抓單相 RST+N 220V)"

            reply_text = (
                f"🏢 站台：{session['site_name']}\n"
                f"⚡ 供電相別：{phase_name}\n"
                f"🔋 【日常基本直流電量與度數統計】\n\n"
                f"設備常態直流明細：\n{session['detail_str']}\n"
                f" -----------------------------------\n"
                f" • 主設備直流負載總和: {net_dc_load:.0f} W\n"
                f" ⚡ 直流端總電量需求: {total_dc_demand:.0f} W ({total_dc_demand/1000:.2f} kW)\n"
                f" 📊 直流端每小時耗電: {dc_kwh_per_hour:.3f} 度電\n"
                f" 📊 直流端每月預估耗電: {dc_kwh_per_month:.1f} 度電\n"
                f" -----------------------------------\n\n"
                f"【步驟 4：請選填直流供電設備（支援多機累加）】\n"
                f"請直接回覆代號數字【1 ~ 4】:\n"
                f"【1】 TYPE 1 (2.0 kW)\n"
                f"【2】 SMR (5.0 kW)\n"
                f"【3】 TYPE 3 (6.0 kW)\n"
                f"【4】 SMR (7.5 kW)"
            )
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 請回覆 1 選擇單相三線，或回覆 2 選擇三相四線。"))

    # 階段三：手選直流設備 (多機累加與最終防呆報告)
    elif session["step"] == "select_smr":
        if user_msg in SMR_DATABASE:
            chosen_smr_spec = SMR_DATABASE[user_msg]
            session["chosen_smrs"].append(chosen_smr_spec)

            current_total_capacity = sum([smr["capacity"] for smr in session["chosen_smrs"]])
            total_dc_demand = session["total_dc_demand"]

            if current_total_capacity < total_dc_demand:
                remaining_w = total_dc_demand - current_total_capacity
                chosen_names = " + ".join([smr["name"] for smr in session["chosen_smrs"]])
                loop_reply = (
                    f"⚡ 【直流供電容量仍有不足！】\n\n"
                    f" • 目前已選配置: {chosen_names}\n"
                    f" 🔋 目前累計總供電容量: {current_total_capacity:.0f} W\n"
                    f" ⚠️ 缺額尚差: 🔴 【 {remaining_w:.0f} W 】\n"
                    f" -----------------------------------\n\n"
                    f"【請選擇再補一台直流設備（回覆 1 ~ 4）】"
                )
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=loop_reply))
                return

            net_dc_load = session["net_dc_load"]
            smr_efficiency = 0.92
            pf = 0.90
            ac_total_w = total_dc_demand / smr_efficiency

            if session["ac_phase"] == "1P3W":
                phase_title = "單相三線 (1P3W 220V)"
                nfb_poles = "2P"
            else:
                phase_title = "三相四線 (3P4W 380V -> 實務抓單相 RST+N 220V)"
                nfb_poles = "2P (RST單相配N)"
            
            ac_current = ac_total_w / (220 * pf)
            calculated_nfb = math.ceil(ac_current * 1.25)
            
            # 電工法規導線管內安培容量判定：
            if calculated_nfb <= 30:
                suggested_nfb = 30
                suggested_wire = "8.0 mm²"  
            elif calculated_nfb <= 50:
                suggested_nfb = 50          
                suggested_wire = "14 mm²"   
            elif calculated_nfb <= 60:
                suggested_nfb = 60
                suggested_wire = "22 mm²"   
            elif calculated_nfb <= 85:
                suggested_nfb = 75 if calculated_nfb <= 75 else 100
                suggested_wire = "38 mm²"   
            else:
                suggested_nfb = calculated_nfb
                suggested_wire = "50 mm² 或以上"

            ac_kwh_per_hour = ac_total_w / 1000.0
            ac_kwh_per_month = ac_kwh_per_hour * 24 * 30
            final_smr_config = " + ".join([smr["name"] for smr in session["chosen_smrs"]])

            report = (
                f"📋 【⚡ 基地台日常常態電力與度數報告】\n"
                f"🏢 站台名稱：{session['site_name']}\n\n"
                f" 🔹 1. 新設射頻清單：\n{session['detail_str']}\n"
                f" -----------------------------------\n"
                f" 🔋 2. 直流供電設備確認\n"
                f"   • 主設備基本直流負載: {net_dc_load:.0f} W\n"
                f"   • 直流端總電量需求: {total_dc_demand:.0f} W\n"
                f"   👉 最終多機配置: 【 {final_smr_config} 】\n"
                f"   👉 供電總瓦數能力: {current_total_capacity} W\n"
                f" -----------------------------------\n"
                f" ⚡ 3. 交流供電系統統計 ({phase_title})\n"
                f"   • SMR 常態交流側總功耗: {ac_total_w:.0f} W\n"
                f"   • 現場基本運轉線電流: {ac_current:.2f} A\n"
                f"   👉 建議 NFB 開關規格: {suggested_nfb} A {nfb_poles}\n"
                f"   👉 現場拉線進線線徑: {suggested_wire} (30A內保底8.0mm²，30A以上依法規以此類推)\n"
                f" -----------------------------------\n"
                f" 📊 4. 預估現場日常耗電度數 (台電計費基準)\n"
                f"   • 每小時基本用電: {ac_total_w:.0f} W ➡️ 【 {ac_kwh_per_hour:.3f} 度電 / 小時 】\n"
                f"   • 每月份預估總用電: 【 {ac_kwh_per_month:.1f} 度電 / 月 】\n\n"
                f"💡 輸入「開始評估」可開啟下一座台的電力計算。"
            )
            
            USER_SESSIONS[user_id] = {"step": "input_site_name", "site_name": "未命名站台", "equipments": {}, "ac_phase": "1P3W", "chosen_smrs": []}
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=report))
            return
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 請輸入正確的直流設備代號數字 (1、2、3 或 4)。"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
