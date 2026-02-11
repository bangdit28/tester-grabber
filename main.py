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

# Cegah dobel proses
sudah_diproses = set()

def send_or_edit_tele(text, msg_id=None):
    if not TELE_TOKEN or not TELE_CHAT_ID: return None
    try:
        url = f"https://api.telegram.org/bot{TELE_TOKEN}/{'editMessageText' if msg_id else 'sendMessage'}"
        payload = {'chat_id': TELE_CHAT_ID, 'text': text, 'parse_mode': 'HTML'}
        if msg_id: payload['message_id'] = msg_id
        res = requests.post(url, data=payload, timeout=10).json()
        return res.get('result', {}).get('message_id')
    except: return None

# ==========================================
# 1. MANAGER: AMBIL NOMOR (ANTI-DOBEL)
# ==========================================
def run_manager():
    print("🚀 MANAGER: Antrian Online...")
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
                
                # Hapus perintah duluan biar gak dobel ambil
                requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
                
                m_id = val.get('memberId', 'Unknown')
                m_name = val.get('memberName', 'Tester')
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
                    target_range = item.get('prefixes') or item.get('prefix')
                    h = {'content-type':'application/json','cookie':MNIT_COOKIE,'mauthtoken':MNIT_TOKEN,'user-agent':MY_UA}
                    res = curl_req.post("https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/number", headers=h, json={"range":target_range}, impersonate="chrome", timeout=20)
                    if res.status_code == 200:
                        nomor_hasil = res.json().get('data', {}).get('copy')

                if nomor_hasil:
                    # Bersihkan nomor (angka doang)
                    clean_n = re.sub(r'\D', '', str(nomor_hasil))
                    txt_start = (f"📞 <b>BERHASIL AMBIL NOMOR!</b>\n\n👤 <b>Nama :</b> {m_name}\n"
                                 f"📱 <b>Nomor :</b> <code>{nomor_hasil}</code>\n📌 <b>Situs :</b> {situs}\n"
                                 f"🌍 <b>Negara :</b> {item.get('serviceName') or item.get('name')}\n💬 <b>Pesan :</b> menunggu sms . . .")
                    tele_id = send_or_edit_tele(txt_start)

                    data_final = {
                        "number": str(nomor_hasil), "name": m_name, "country": item.get('serviceName') or item.get('name'),
                        "situs": situs, "tele_msg_id": tele_id, "timestamp": int(time.time() * 1000)
                    }
                    requests.patch(f"{FIREBASE_URL}/members/{m_id}/active_numbers/{clean_n}.json", json=data_final)
                    requests.patch(f"{FIREBASE_URL}/active_numbers_lookup/{clean_n}.json", json=data_final)
            
            if len(sudah_diproses) > 100: sudah_diproses.clear()
            time.sleep(1)
        except: time.sleep(5)

# ==========================================
# 2. GRABBER: SMS (BONGKAR PAKSA JSON MNIT)
# ==========================================
def process_incoming_sms(num, msg):
    try:
        clean_num = re.sub(r'\D', '', str(num))
        owner = requests.get(f"{FIREBASE_URL}/active_numbers_lookup/{clean_num}.json").json()
        if owner:
            # Cari OTP di dalam pesan
            otp = re.search(r'\d{4,8}', msg)
            clean_msg = msg.replace(otp.group(0), f"<code>{otp.group(0)}</code>") if otp else msg

            txt_sms = (f"📩 <b>SMS MASUK!</b>\n\n👤 <b>Nama :</b> {owner['name']}\n"
                       f"📱 <b>Nomor :</b> <code>{owner['number']}</code>\n📌 <b>Situs :</b> {owner['situs']}\n"
                       f"🌍 <b>Negara :</b> {owner['country']}\n💬 <b>Pesan :</b> {clean_msg}")
            
            send_or_edit_tele(txt_sms, owner.get('tele_msg_id'))
            requests.post(f"{FIREBASE_URL}/messages.json", json={"liveSms": owner['number'], "messageContent": msg, "timestamp": int(time.time() * 1000)})
            requests.delete(f"{FIREBASE_URL}/active_numbers_lookup/{clean_num}.json")
            print(f"✅ SMS Masuk: {clean_num}")
    except: pass

def run_grabber():
    print("📡 GRABBER: Scanning OTP...")
    done_ids = []
    # Header diperkuat biar gak dianggap bot
    headers_mnit = {
        'cookie': MNIT_COOKIE,
        'mauthtoken': MNIT_TOKEN,
        'user-agent': MY_UA,
        'accept': 'application/json, text/plain, */*',
        'referer': 'https://x.mnitnetwork.com/mdashboard/getnum',
        'x-requested-with': 'XMLHttpRequest'
    }
    
    while True:
        try:
            # --- GRAB CALLTIME ---
            res_ct = requests.get(f"https://www.calltimepanel.com/yeni/SMS/?_={int(time.time()*1000)}", headers={'Cookie': MY_COOKIE}, timeout=15)
            soup = BeautifulSoup(res_ct.text, 'html.parser')
            for r in soup.select('table tr'):
                tds = r.find_all('td')
                if len(tds) < 4: continue
                n, m = tds[1].text.strip().split('-')[-1].strip(), tds[2].text.strip()
                if f"{n}_{m[:5]}" not in done_ids:
                    process_incoming_sms(n, m); done_ids.append(f"{n}_{m[:5]}")

            # --- GRAB X-MNIT (LOGIKA BONGKAR PAKSA) ---
            tgl = time.strftime("%Y-%m-%d")
            url_mn = f"https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/info?date={tgl}&page=1&search=&status="
            res_mn = curl_req.get(url_mn, headers=headers_mnit, impersonate="chrome", timeout=15)
            
            if res_mn.status_code == 200:
                json_data = res_mn.json()
                # Coba cari data di semua kemungkinan folder MNIT
                items = []
                if isinstance(json_data.get('data'), list): 
                    items = json_data['data']
                elif isinstance(json_data.get('data'), dict) and isinstance(json_data['data'].get('data'), list):
                    items = json_data['data']['data']

                for it in items:
                    # Ambil nomor dan kode dengan berbagai kemungkinan nama field
                    num = it.get('copy') or it.get('number') or it.get('phone')
                    code = it.get('code') or it.get('otp') or it.get('sms')
                    
                    if num and code:
                        clean_c = re.sub('<[^<]+?>', '', str(code)).strip()
                        uid = f"{num}_{clean_c}"
                        if uid not in done_ids:
                            print(f"🔥 MNIT Dapet OTP: {num} -> {clean_c}")
                            process_incoming_sms(num, f"Your code is {clean_c}")
                            done_ids.append(uid)
            
            if len(done_ids) > 200: done_ids = done_ids[-100:]
            time.sleep(3)
        except Exception as e:
            print(f"Grabber Error: {e}"); time.sleep(5)

if __name__ == "__main__":
    send_or_edit_tele("🚀 <b>BOT ENGINE V-ULTIMATE ONLINE!</b>\nSistem sinkron 24 jam. Selamat bekerja team!")
    threading.Thread(target=run_manager, daemon=True).start()
    threading.Thread(target=run_grabber, daemon=True).start()
    while True: time.sleep(10)
