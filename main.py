import threading, time, os, re, random, requests, json
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_req

# === CONFIG ===
FIREBASE_URL = os.getenv("FIREBASE_URL", "").strip().rstrip('/')
MY_COOKIE = os.getenv("MY_COOKIE", "").strip()
MNIT_COOKIE = os.getenv("MNIT_COOKIE", "").strip()
MNIT_TOKEN = os.getenv("MNIT_TOKEN", "").strip()
MY_UA = os.getenv("MY_UA", "").strip()
TELE_TOKEN = os.getenv("TELE_TOKEN", "").strip()
TELE_CHAT_ID = os.getenv("TELE_CHAT_ID", "").strip()

# Variabel buat cegah dobel proses
sudah_diproses = set()

def send_or_edit_tele(text, msg_id=None):
    if not TELE_TOKEN or not TELE_CHAT_ID: return None
    try:
        if msg_id:
            url = f"https://api.telegram.org/bot{TELE_TOKEN}/editMessageText"
            payload = {'chat_id': TELE_CHAT_ID, 'message_id': msg_id, 'text': text, 'parse_mode': 'HTML'}
        else:
            url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
            payload = {'chat_id': TELE_CHAT_ID, 'text': text, 'parse_mode': 'HTML'}
        res = requests.post(url, data=payload, timeout=10).json()
        return res.get('result', {}).get('message_id')
    except: return None

# ==========================================
# 1. MANAGER: PENGAMBIL NOMOR (ANTI DOBEL)
# ==========================================
def run_manager():
    print("🚀 MANAGER: Antrian System Active...")
    while True:
        try:
            r = requests.get(f"{FIREBASE_URL}/perintah_bot.json")
            cmds = r.json()
            if not cmds or not isinstance(cmds, dict):
                time.sleep(1); continue
            
            inv = requests.get(f"{FIREBASE_URL}/inventory.json").json()
            for cmd_id, val in cmds.items():
                # CEK APAKAH SUDAH DIPROSES? (Cegah Ambil 2-3 Nomor)
                if cmd_id in sudah_diproses: continue
                sudah_diproses.add(cmd_id)

                # HAPUS PERINTAH DULUAN (Biar loop berikutnya gak baca lagi)
                requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
                
                m_id = val.get('memberId', 'Unknown')
                m_name = val.get('memberName', 'Tester')
                inv_id = val.get('inventoryId')
                
                item = inv.get(inv_id) if inv else None
                if not item: continue

                nomor_hasil = None
                situs = "CallTime" if "PREFIX" not in str(item.get('type')).upper() else "x.mnitnetwork"
                
                # --- PROSES AMBIL ---
                if situs == "CallTime":
                    nums = item.get('stock') or item.get('stok') or []
                    if nums:
                        if isinstance(nums, list):
                            nomor_hasil = nums.pop(0)
                            requests.put(f"{FIREBASE_URL}/inventory/{inv_id}/stock.json", json=nums)
                        else:
                            key = list(nums.keys())[0]; nomor_hasil = nums[key]
                            requests.delete(f"{FIREBASE_URL}/inventory/{inv_id}/stock/{key}.json")
                else:
                    target_range = item.get('prefixes') or item.get('prefix')
                    h = {'content-type':'application/json','cookie':MNIT_COOKIE,'mauthtoken':MNIT_TOKEN,'user-agent':MY_UA}
                    res = curl_req.post("https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/number", headers=h, json={"range":target_range}, impersonate="chrome", timeout=20)
                    if res.status_code == 200:
                        nomor_hasil = res.json().get('data', {}).get('copy')

                if nomor_hasil:
                    # Notif Telegram 1
                    txt_start = (f"📞 <b>BERHASIL AMBIL NOMOR!</b>\n\n👤 <b>Nama :</b> {m_name}\n"
                                 f"📱 <b>Nomor :</b> <code>{nomor_hasil}</code>\n📌 <b>Situs :</b> {situs}\n"
                                 f"🌍 <b>Negara :</b> {item.get('serviceName') or item.get('name')}\n💬 <b>Pesan :</b> menunggu sms . . .")
                    tele_id = send_or_edit_tele(txt_start)

                    # Save to Firebase
                    clean_n = re.sub(r'\D', '', str(nomor_hasil)) 
                    data_final = {
                        "number": str(nomor_hasil), "name": m_name, "country": item.get('serviceName') or item.get('name'),
                        "situs": situs, "tele_msg_id": tele_id, "timestamp": int(time.time() * 1000)
                    }
                    requests.patch(f"{FIREBASE_URL}/members/{m_id}/active_numbers/{clean_n}.json", json=data_final)
                    requests.patch(f"{FIREBASE_URL}/active_numbers_lookup/{clean_n}.json", json=data_final)
            
            # Bersihkan cache proses tiap 10 detik
            if len(sudah_diproses) > 50: sudah_diproses.clear()
            time.sleep(1)
        except: time.sleep(5)

# ==========================================
# 2. GRABBER: SMS (FIX JALUR MNIT CONSOLE)
# ==========================================
def process_incoming_sms(num, msg):
    try:
        clean_num = re.sub(r'\D', '', str(num))
        owner = requests.get(f"{FIREBASE_URL}/active_numbers_lookup/{clean_num}.json").json()
        if owner:
            # Format OTP monospaced
            otp = re.search(r'\d{4,8}', msg)
            clean_msg = msg.replace(otp.group(0), f"<code>{otp.group(0)}</code>") if otp else msg

            txt_sms = (f"📩 <b>SMS MASUK!</b>\n\n👤 <b>Nama :</b> {owner['name']}\n"
                       f"📱 <b>Nomor :</b> <code>{owner['number']}</code>\n📌 <b>Situs :</b> {owner['situs']}\n"
                       f"🌍 <b>Negara :</b> {owner['country']}\n💬 <b>Pesan :</b> {clean_msg}")
            
            send_or_edit_tele(txt_sms, owner.get('tele_msg_id'))
            requests.post(f"{FIREBASE_URL}/messages.json", json={"liveSms": owner['number'], "messageContent": msg, "timestamp": int(time.time() * 1000)})
            requests.delete(f"{FIREBASE_URL}/active_numbers_lookup/{clean_num}.json")
    except: pass

def run_grabber():
    print("📡 GRABBER: Scanning OTP...")
    done_ids = []
    headers_mnit = {'cookie': MNIT_COOKIE,'mauthtoken': MNIT_TOKEN,'user-agent': MY_UA,'accept': 'application/json','x-requested-with': 'XMLHttpRequest'}
    
    while True:
        try:
            # --- SCAN CALLTIME ---
            res_ct = requests.get(f"https://www.calltimepanel.com/yeni/SMS/?_={int(time.time()*1000)}", headers={'Cookie': MY_COOKIE}, timeout=15)
            soup = BeautifulSoup(res_ct.text, 'html.parser')
            for r in soup.select('table tr'):
                tds = r.find_all('td')
                if len(tds) < 4: continue
                n, m = tds[1].text.strip().split('-')[-1].strip(), tds[2].text.strip()
                if f"{n}_{m[:5]}" not in done_ids:
                    process_incoming_sms(n, m); done_ids.append(f"{n}_{m[:5]}")

            # --- SCAN X-MNIT (JALUR CONSOLE & INFO) ---
            tgl = time.strftime("%Y-%m-%d")
            # Jalur 1: Jalur Console (Biasanya paling baru)
            # Jalur 2: Jalur Info (History)
            endpoints = [
                f"https://x.mnitnetwork.com/mapi/v1/mdashboard/console?page=1",
                f"https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/info?date={tgl}&page=1&search=&status="
            ]

            for url in endpoints:
                res_mn = curl_req.get(url, headers=headers_mnit, impersonate="chrome", timeout=15)
                if res_mn.status_code == 200:
                    items = res_mn.json().get('data', {}).get('data', [])
                    for it in items:
                        num, code = it.get('copy'), it.get('code')
                        if num and code:
                            c_code = re.sub('<[^<]+?>', '', str(code)).strip()
                            if f"{num}_{c_code}" not in done_ids:
                                process_incoming_sms(num, f"Your code is {c_code}")
                                done_ids.append(f"{num}_{c_code}")
            
            if len(done_ids) > 200: done_ids = done_ids[-100:]
            time.sleep(3)
        except: time.sleep(5)

if __name__ == "__main__":
    send_or_edit_tele("🚀 <b>BOT ENGINE V-FINAL ONLINE!</b>\nSistem sinkron 24 jam. Selamat bekerja team!")
    threading.Thread(target=run_manager, daemon=True).start()
    threading.Thread(target=run_grabber, daemon=True).start()
    while True: time.sleep(10)
