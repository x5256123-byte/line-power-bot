import os
import math
import csv
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

# --- 本地 CSV 檔案路徑 ---
CSV_FILE_PATH = os.path.join(os.path.dirname(__file__), "pingtung_sites.csv")

# --- 🎯 射頻設備日常運轉基本功耗資料庫 ---
EQUIPMENT_DATABASE = {
    # 宏基站 (Macro Cell) 既存規格
    "FXDB": {"name": "FXDB", "power": 780},
    "ARDA": {"name": "ARDA", "power": 480},  
    "FHDB": {"name": "FHDB", "power": 780},
    "AHDB": {"name": "AHDB", "power": 410},
    "FXEB": {"name": "FXEB", "power": 915},  
    "FXED": {"name": "FXED", "power": 860},  
    "FHEB": {"name": "FHEB", "power": 410},  
    "AHEB": {"name": "AHEB", "power": 410},
    "FHEL": {"name": "FHEL", "power": 350},  
    "FRHG": {"name": "FRHG", "power": 490},  
    "AHHB": {"name": "AHHB", "power": 321},  
    "AZQG": {"name": "AZQG", "power": 720},
    "AZQI": {"name": "AZQI", "power": 520},
    "AEQZ": {"name": "AEQZ", "power": 570},
    "AQQA": {"name": "AQQA", "power": 2095},
    "AQQY": {"name": "AQQY", "power": 740},
    "AVQC": {"name": "AVQC", "power": 900},
    "AVQL": {"name": "AVQL", "power": 380},
    "AHEGB": {"name": "AHEGB", "power": 1367},
    "AHEGB+B3": {"name": "AHEGB+B3", "power": 2128},
    "AHEGG": {"name": "AHEGG", "power": 410},
    "AHEGG+B3": {"name": "AHEGG+B3", "power": 780},
    
    # 最新硬體常態瓦數精確版 (Small Cell 微細胞規格)
    "FW2EHB": {"name": "FW2EHB", "power": 210},  
    "FR2EB": {"name": "FR2EB", "power": 140},    
    "FWEA": {"name": "FWEA", "power": 84},      
    "AHEJ": {"name": "AHEJ", "power": 90},      
    "AWHQE": {"name": "AWHQE", "power": 285}, 
    "FWHN": {"name": "FWHN", "power": 95}        
}

USER_SESSIONS = {}

def search_csv_database_advanced(keyword):
    """進階多行揉合核心：直接比對全中文原始表格的「台號」與「台名」欄位"""
    if not os.path.exists(CSV_FILE_PATH):
        return 'NOT_FOUND', None
        
    keyword_up = keyword.upper().strip()
    matched_rows = []
    
    with open(CSV_FILE_PATH, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = str(row.get("台號", "")).strip().upper()
            sname = str(row.get("台名", "")).strip()
            sname_up = sname.upper()
            
            if sid == keyword_up or keyword_up in sname_up:
                raw_model = str(row.get("模組型號", "")).strip().upper()
                clean_model = raw_model.split('_')[0] if '_' in raw_model else raw_model
                
                cell_info = str(row.get("細胞(頻寬) / 細胞名稱", "")).upper()
                phase_type = "3P4W" if "3P" in cell_info else "1P3W"
                
                matched_rows.append({
                    "site_id": sid,
                    "site_name": sname,
                    "model": clean_model,
                    "ac_phase": phase_type
                })
                
    if not matched_rows:
        return 'NOT_FOUND', None
        
    unique_site_ids = list(set([item["site_id"] for item in matched_rows]))
    
    if len(unique_site_ids) == 1:
        target_id = unique_site_ids[0]
        site_allels = [item for item in matched_rows if item["site_id"] == target_id]
        
        merged_equipments = {}
        final_name = site_allels[0]["site_name"]
        final_phase = "1P3W"
        
        for item in site_allels:
            model = item["model"]
            if item["ac_phase"] == "3P4W":
                final_phase = "3P4W"
            if model in EQUIPMENT_DATABASE:
                merged_equipments[model] = merged_equipments.get(model, 0) + 1
                
        final_result = {
            "site_id": target_id,
            "site_name": final_name,
            "ac_phase": final_phase,
            "equipments": merged_equipments
        }
        return 'MATCH', final_result
        
    if len(unique_site_ids) > 1:
        multi_list = []
        seen = set()
        for item in matched_rows:
            if item["site_id"] not in seen:
                seen.add(item["site_id"])
                multi_list.append(item)
        return 'MULTI', multi_list

def calculate_current_report(site_id, site_name, ac_phase, equipments):
    """即時計算該站點目前的現況電氣報告"""
    bbu_p = 400
    total_rf_power = 0
    detail_list = []

    for model, qty in equipments.items():
        spec = EQUIPMENT_DATABASE[model]
        row_total = spec["power"] * qty
        total_rf_power += row_total
        detail_list.append(f"   • {spec['name']} x {qty}台 = {row_total} W")

    net_dc_load = bbu_p + total_rf_power
    smr_efficiency = 0.92
    pf = 0.90
    ac_total_w = net_dc_load / smr_efficiency
    
    phase_title = "單相三線 (1P3W 220V)" if ac_phase == "1P3W" else "三相四線 (3P4W -> 實務抓單相 RST+N)"
    ac_current = ac_total_w / (220 * pf)
    calculated_nfb = math.ceil(ac_current * 1.25)
    
    if calculated_nfb <= 30:
        suggested_nfb, suggested_wire = 30, "8.0 mm²"
    elif calculated_nfb <= 50:
        suggested_nfb, suggested_wire = 50, "14 mm²"
    elif calculated_nfb <= 60:
        suggested_nfb, suggested_wire = 60, "22 mm²"
    elif calculated_nfb <= 85:
        suggested_nfb = 75 if calculated_nfb <= 75 else 100
        suggested_wire = "38 mm²"
    else:
        suggested_nfb, suggested_wire = calculated_nfb, "50 mm² 或以上"

    ac_kwh_per_hour = ac_total_w / 1000.0
    ac_kwh_per_month = ac_kwh_per_hour * 24 * 30
    detail_str = "\n".join(detail_list) if detail_list else "   • 無既存或相符之射頻設備"

    report = (
        f"🔍 【資料庫檢索——站台歷史現況報告】\n"
