import threading, time, os, re, random, requests, json
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_req

# === CONFIGURATION ===
FIREBASE_URL = os.getenv("FIREBASE_URL", "").strip().rstrip('/')
MY_COOKIE = os.getenv("MY_COOKIE", "").strip()
MNIT_COOKIE = os.getenv("MNIT_COOKIE", "").strip()
MNIT_TOKEN = os.getenv("MNIT_TOKEN", "").strip()
MY_UA = os.getenv("MY_UA", "").strip()
TELE_TOKEN = os.getenv("TELE_TOKEN", "").strip()
TELE_CHAT_ID = os.getenv("TELE_CHAT_ID", "").strip()

# Cegah dobel proses ambil nomor
sudah_diproses = set()

def send_tele(text, msg_id=None):
    if not TELE_TOKEN or not TELE_CHAT_ID: return None
    try:
        method = "editMessageText" if msg_id else "sendMessage"
        url = f"https://api.telegram.org/bot{TELE_TOKEN}/{method}"
        payload = {'chat_id': TELE_CHAT_ID, 'text': text, 'parse_mode': 'HTML'}
        if msg_id: payload['message_id'] = msg_id
        res = requests.post(url, data=payload, timeout=10).json()
        return res.get('result', {}).get('message_id')
    except: return None

# ==========================================
# 1. MANAGER: AMBIL NOMOR (SINKRON NAMA)
# ==========================================
def run_manager():
    print("🚀 MANAGER: Antrian Active...")
    while True:
        try:
            r = requests.get(f"{FIREBASE_URL}/perintah_bot.json")
            cmds = r.json()
            if not cmds or not isinstance(cmds, dict):
                time.sleep(1); continue
            
            inv = requests.get(f"{FIREBASE_URL}/inventory.json").json()
            for cmd_id, val in cmds.items():
                if cmd_id in sudah_diproses: continue
                sudah_diproses.add(cmd_id)
                requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
                
                m_id = val.get('memberId', 'tester')
                m_name = val.get('memberName', 'User')
                inv_id = val.get('inventoryId')
                
                item = inv.get(inv_id) if inv else None
                if not item: continue

                nomor_hasil = None
                situs = "CallTime" if "PREFIX" not in str(item.get('type')).upper() else "x.mnitnetwork"
                
                if situs == "CallTime":
                    nums = item.get('stock') or item.get('stok') or []
                    if nums and len(nums) > 0:
                        nomor_hasil = nums.pop(0)
                        requests.put(f"{FIREBASE_URL}/inventory/{inv_id}/stock.json", json=nums)
                else:
                    target_range = item.get('prefixes') or item.get('prefix') or "2367261XXXX"
                    h = {'content-type':'application/json','cookie':MNIT_COOKIE,'mauthtoken':MNIT_TOKEN,'user-agent':MY_UA}
                    res = curl_req.post("https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/number", headers=h, json={"range":target_range}, impersonate="chrome", timeout=20)
                    if res.status_code == 200:
                        nomor_hasil = res.json().get('data', {}).get('copy')

                if nomor_hasil:
                    clean_n = re.sub(r'\D', '', str(nomor_hasil))
                    txt_start = (f"📞 <b>BERHASIL AMBIL NOMOR!</b>\n\n"
                                 f"👤 <b>Nama :</b> {m_name}\n"
                                 f"📱 <b>Nomor :</b> <code>{nomor_hasil}</code>\n"
                                 f"📌 <b>Situs :</b> {situs}\n"
                                 f"🌍 <b>Negara :</b> {item.get('serviceName') or item.get('name')}\n"
                                 f"💬 <b>Pesan :</b> menunggu sms . . .")
                    tele_id = send_tele(txt_start)

                    data_final = {
                        "number": str(nomor_hasil), "name": m_name, "country": item.get('serviceName') or item.get('name'),
                        "situs": situs, "tele_msg_id": tele_id, "timestamp": int(time.time() * 1000)
                    }
                    requests.patch(f"{FIREBASE_URL}/members/{m_id}/active_numbers/{clean_n}.json", json=data_final)
                    requests.patch(f"{FIREBASE_URL}/active_numbers_lookup/{clean_n}.json", json=data_final)
            
            if len(sudah_diproses) > 100: sudah_diproses.clear()
            time.sleep(1)
        except Exception as e:
            print(f"Error Manager: {e}"); time.sleep(5)

# ==========================================
# 2. GRABBER: SMS (FIX JALUR PREVIEW LO)
# ==========================================
def process_incoming_sms(num, full_msg):
    try:
        clean_num = re.sub(r'\D', '', str(num))
        owner = requests.get(f"{FIREBASE_URL}/active_numbers_lookup/{clean_num}.json").json()
        if owner:
            # Ambil OTP agar bisa diklik salin
            otp_match = re.search(r'\d{4,8}', full_msg)
            display_msg = full_msg
            if otp_match:
                otp_val = otp_match.group(0)
                display_msg = full_msg.replace(otp_val, f"<code>{otp_val}</code>")

            txt_sms = (f"📩 <b>SMS MASUK!</b>\n\n"
                       f"👤 <b>Nama :</b> {owner['name']}\n"
                       f"📱 <b>Nomor :</b> <code>{owner['number']}</code>\n"
                       f"📌 <b>Situs :</b> {owner['situs']}\n"
                       f"🌍 <b>Negara :</b> {owner['country']}\n"
                       f"💬 <b>Pesan :</b> {display_msg}")
            
            send_tele(txt_sms, owner.get('tele_msg_id'))
            requests.post(f"{FIREBASE_URL}/messages.json", json={"liveSms": owner['number'], "messageContent": full_msg, "timestamp": int(time.time() * 1000)})
            requests.delete(f"{FIREBASE_URL}/active_numbers_lookup/{clean_num}.json")
            print(f"✅ SMS {clean_num} Berhasil Grab!")
    except: pass

def run_grabber():
    print("📡 GRABBER: Scanning OTP...")
    done_ids = []
    headers_mnit = {'cookie': MNIT_COOKIE, 'mauthtoken': MNIT_TOKEN, 'user-agent': MY_UA, 'accept': 'application/json', 'x-requested-with': 'XMLHttpRequest'}
    
    while True:
        try:
            # --- 1. SCAN CALLTIME ---
            res_ct = requests.get(f"https://www.calltimepanel.com/yeni/SMS/?_={int(time.time()*1000)}", headers={'Cookie': MY_COOKIE}, timeout=15)
            soup = BeautifulSoup(res_ct.text, 'html.parser')
            for r in soup.select('table tr'):
                tds = r.find_all('td')
                if len(tds) < 4: continue
                n, m = tds[1].text.strip().split('-')[-1].strip(), tds[2].text.strip()
                if f"{n}_{m[:5]}" not in done_ids:
                    process_incoming_sms(n, m); done_ids.append(f"{n}_{m[:5]}")

            # --- 2. SCAN X-MNIT (SINKRON JALUR PREVIEW LO) ---
            tgl = time.strftime("%Y-%m-%d")
            url_mn = f"https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/info?date={tgl}&page=1&search=&status="
            res_mn = curl_req.get(url_mn, headers=headers_mnit, impersonate="chrome", timeout=15)
            
            if res_mn.status_code == 200:
                data_mnit = res_mn.json()
                # KUNCI: Sesuai gambar Preview lo jalurnya adalah data -> numbers
                items = data_mnit.get('data', {}).get('numbers', [])
                
                for it in items:
                    num = it.get('number') 
                    otp_text = it.get('otp')
                    
                    if num and otp_text and "Waiting" not in otp_text:
                        uid = f"{num}_{otp_text[:10]}"
                        if uid not in done_ids:
                            print(f"🔍 Dapet OTP MNIT: {num} -> {otp_text[:15]}")
                            process_incoming_sms(num, otp_text)
                            done_ids.append(uid)
            
            if len(done_ids) > 200: done_ids = done_ids[-100:]
            time.sleep(3)
        except Exception as e:
            print(f"Grab Error: {e}"); time.sleep(5)

if __name__ == "__main__":
    send_tele("🚀 <b>BOT ENGINE V-FINAL ONLINE!</b>\nSistem sinkron 24 jam. Selamat bekerja team!")
    threading.Thread(target=run_manager, daemon=True).start()
    threading.Thread(target=run_grabber, daemon=True).start()
    while True: time.sleep(10)
