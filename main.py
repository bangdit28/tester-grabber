import threading
import time
import os
import re
import random
import requests
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_req

# === CONFIGURATION ===
FIREBASE_URL = os.getenv("FIREBASE_URL")
MY_COOKIE = os.getenv("MY_COOKIE")
MNIT_COOKIE = os.getenv("MNIT_COOKIE")
MNIT_TOKEN = os.getenv("MNIT_TOKEN")
MY_UA = os.getenv("MY_UA")
TELE_TOKEN = os.getenv("TELE_TOKEN")
TELE_CHAT_ID = os.getenv("TELE_CHAT_ID")

def kirim_tele_awal(pesan):
    """Fungsi tes koneksi bot"""
    if not TELE_TOKEN or not TELE_CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
        requests.post(url, data={'chat_id': TELE_CHAT_ID, 'text': pesan, 'parse_mode': 'HTML'}, timeout=10)
    except Exception as e:
        print(f"Gagal kirim tele: {e}")

def send_or_edit_tele(text, msg_id=None):
    try:
        if msg_id:
            url = f"https://api.telegram.org/bot{TELE_TOKEN}/editMessageText"
            data = {'chat_id': TELE_CHAT_ID, 'message_id': msg_id, 'text': text, 'parse_mode': 'HTML'}
        else:
            url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
            data = {'chat_id': TELE_CHAT_ID, 'text': text, 'parse_mode': 'HTML'}
        res = requests.post(url, data=data, timeout=10).json()
        return res.get('result', {}).get('message_id')
    except: return None

# ==========================================
# 1. MANAGER: PROSES AMBIL NOMOR
# ==========================================
def run_manager():
    print("🚀 Manager Running...")
    while True:
        try:
            # Ambil antrian
            r = requests.get(f"{FIREBASE_URL}/perintah_bot.json")
            cmds = r.json()
            if not cmds or not isinstance(cmds, dict):
                time.sleep(2); continue
            
            inv = requests.get(f"{FIREBASE_URL}/inventory.json").json()
            for cmd_id, val in cmds.items():
                if not isinstance(val, dict): continue
                
                m_id = val.get('memberId')
                m_name = val.get('memberName', 'Tester')
                inv_id = val.get('inventoryId')
                
                stok_item = inv.get(inv_id) if inv else None
                if not stok_item:
                    requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
                    continue

                nomor_hasil = None
                situs = "CallTime" if stok_item.get('type') == 'manual' else "x.mnitnetwork"
                
                if stok_item['type'] == 'manual':
                    nums = stok_item.get('stock', [])
                    if nums:
                        if isinstance(nums, list):
                            nomor_hasil = nums.pop(0)
                            requests.put(f"{FIREBASE_URL}/inventory/{inv_id}/stock.json", json=nums)
                        else:
                            key = list(nums.keys())[0]; nomor_hasil = nums[key]
                            requests.delete(f"{FIREBASE_URL}/inventory/{inv_id}/stock/{key}.json")
                
                elif stok_item['type'] == 'xmnit':
                    target = random.choice(stok_item.get('prefixes', ['2367261']))
                    h = {'content-type':'application/json','cookie':MNIT_COOKIE,'mauthtoken':MNIT_TOKEN,'user-agent':MY_UA}
                    res = curl_req.post("https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/number", headers=h, json={"range":target}, impersonate="chrome", timeout=20)
                    if res.status_code == 200:
                        nomor_hasil = res.json().get('data', {}).get('copy')

                if nomor_hasil:
                    # NOTIF TELE 1
                    txt_start = (f"📞 <b>BERHASIL AMBIL NOMOR!</b>\n\n👤 <b>Nama :</b> {m_name}\n"
                                 f"📱 <b>Nomor :</b> <code>{nomor_hasil}</code>\n📌 <b>Situs :</b> {situs}\n"
                                 f"🌍 <b>Negara :</b> {stok_item.get('name')}\n💬 <b>Pesan :</b> menunggu sms . . .")
                    tele_id = send_or_edit_tele(txt_start)

                    # SIMPAN KE FIREBASE
                    data_final = {
                        "number": str(nomor_hasil), "name": m_name, "country": stok_item.get('name'),
                        "situs": situs, "tele_msg_id": tele_id, "timestamp": int(time.time() * 1000)
                    }
                    requests.post(f"{FIREBASE_URL}/members/{m_id}/active_numbers.json", json=data_final)
                    requests.patch(f"{FIREBASE_URL}/active_numbers_lookup/{str(nomor_hasil).replace('+','')}.json", json=data_final)

                requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
            time.sleep(1)
        except Exception as e:
            print(f"Manager Error: {e}")
            time.sleep(5)

# ==========================================
# 2. GRABBER: SMS
# ==========================================
def run_grabber():
    print("📡 SMS Grabber Aktif...")
    done_ids = []
    while True:
        try:
            # Grab CallTime
            res_ct = requests.get(f"https://www.calltimepanel.com/yeni/SMS/?_={int(time.time()*1000)}", headers={'Cookie': MY_COOKIE}, timeout=15)
            soup = BeautifulSoup(res_ct.text, 'html.parser')
            for r in soup.select('table tr'):
                c = r.find_all('td')
                if len(c) < 4: continue
                n, m = c[1].text.strip().split('-')[-1].strip(), c[2].text.strip()
                uid = f"{n}_{m[:5]}"
                if uid not in done_ids:
                    # Cari pemilik & Edit Tele
                    clean_n = n.replace('+','')
                    owner = requests.get(f"{FIREBASE_URL}/active_numbers_lookup/{clean_n}.json").json()
                    if owner:
                        otp = re.search(r'\d{4,8}', m)
                        clean_m = m.replace(otp.group(0), f"<code>{otp.group(0)}</code>") if otp else m
                        txt_sms = (f"📩 <b>SMS MASUK!</b>\n\n👤 <b>Nama :</b> {owner['name']}\n"
                                   f"📱 <b>Nomor :</b> <code>{n}</code>\n📌 <b>Situs :</b> {owner['situs']}\n"
                                   f"🌍 <b>Negara :</b> {owner['country']}\n💬 <b>Pesan :</b> {clean_m}")
                        send_or_edit_tele(txt_sms, owner.get('tele_msg_id'))
                        requests.post(f"{FIREBASE_URL}/messages.json", json={"liveSms": n, "messageContent": m, "timestamp": int(time.time()*1000)})
                        requests.delete(f"{FIREBASE_URL}/active_numbers_lookup/{clean_n}.json")
                    done_ids.append(uid)
            time.sleep(4)
        except: time.sleep(5)

if __name__ == "__main__":
    # NOTIF TEST
    kirim_tele_awal("🚀 <b>Bot Tester Online!</b>\nFirebase: Connected\nSystem: Standby")
    
    threading.Thread(target=run_manager, daemon=True).start()
    threading.Thread(target=run_grabber, daemon=True).start()
    while True: time.sleep(10)
