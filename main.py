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

def send_tele(text):
    if not TELE_TOKEN or not TELE_CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
        requests.post(url, data={'chat_id': TELE_CHAT_ID, 'text': text, 'parse_mode': 'HTML'}, timeout=10)
    except: pass

# ==========================================
# 1. MANAGER: AMBIL NOMOR (ANTI-NYANGKUT)
# ==========================================
def run_manager():
    print("🚀 MANAGER: Antrian System Running...")
    while True:
        try:
            # Ambil antrian
            r = requests.get(f"{FIREBASE_URL}/perintah_bot.json")
            cmds = r.json()
            if not cmds or not isinstance(cmds, dict):
                time.sleep(1); continue
            
            inv = requests.get(f"{FIREBASE_URL}/inventory.json").json()
            for cmd_id, val in cmds.items():
                # Langsung hapus biar bisa klik lagi
                requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
                
                m_id = val.get('memberId', 'tester')
                m_name = val.get('memberName', 'User')
                inv_id = val.get('inventoryId')
                
                item = inv.get(inv_id) if inv else None
                if not item: continue

                nomor_hasil = None
                situs = "CallTime" if "PREFIX" not in str(item.get('type')).upper() else "x.mnitnetwork"
                
                # LOGIKA AMBIL STOK
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
                    clean_n = re.sub(r'\D', '', str(nomor_hasil))
                    data_final = {
                        "number": str(nomor_hasil), "name": m_name, "country": item.get('serviceName') or item.get('name'),
                        "situs": situs, "timestamp": int(time.time() * 1000)
                    }
                    # Push ke dashboard web anggota
                    requests.patch(f"{FIREBASE_URL}/members/{m_id}/active_numbers/{clean_n}.json", json=data_final)
                    # Simpan titipan untuk Grabber SMS (Lookup)
                    requests.patch(f"{FIREBASE_URL}/active_numbers_lookup/{clean_n}.json", json=data_final)
                    
                    send_tele(f"✅ <b>NOMOR DIDAPAT!</b>\n👤 Nama : {m_name}\n📱 Nomor : <code>{nomor_hasil}</code>\n🌍 Negara : {data_final['country']}\n💬 Pesan : menunggu sms . . .")
            time.sleep(1)
        except: time.sleep(5)

# ==========================================
# 2. GRABBER: SMS (BONGKAR PAKSA X-MNIT)
# ==========================================
def process_sms(num, msg):
    try:
        clean_num = re.sub(r'\D', '', str(num))
        owner = requests.get(f"{FIREBASE_URL}/active_numbers_lookup/{clean_num}.json").json()
        if owner:
            m_name = owner.get('name', 'User')
            c_name = owner.get('country', 'Unknown')
            # Hilangkan tag HTML jika ada di kode
            clean_code = re.sub('<[^<]+?>', '', str(msg)).replace("Your code is ", "").strip()
            
            # Format pesan final
            text = (f"📩 <b>SMS BARU!</b>\n\n"
                    f"👤 Nama : {m_name}\n"
                    f"📱 Nomor : <code>{owner['number']}</code>\n"
                    f"🌍 Negara : {c_name}\n"
                    f"💬 Pesan : <code>{clean_code}</code>")
            
            send_tele(text)
            # Masukin ke Firebase /messages biar Web Update
            requests.post(f"{FIREBASE_URL}/messages.json", json={"liveSms": owner['number'], "messageContent": msg, "timestamp": int(time.time() * 1000)})
            # Hapus lookup biar gak dobel grab
            requests.delete(f"{FIREBASE_URL}/active_numbers_lookup/{clean_num}.json")
            print(f"✅ OTP GRABBED: {clean_num}")
    except: pass

def run_grabber():
    print("📡 GRABBER: Scanning OTP...")
    done_ids = []
    headers_mnit = {
        'cookie': MNIT_COOKIE, 'mauthtoken': MNIT_TOKEN, 'user-agent': MY_UA,
        'accept': 'application/json', 'x-requested-with': 'XMLHttpRequest'
    }
    
    while True:
        try:
            # --- SCAN CALLTIME ---
            res_ct = requests.get(f"https://www.calltimepanel.com/yeni/SMS/?_={int(time.time()*1000)}", headers={'Cookie': MY_COOKIE}, timeout=15)
            soup = BeautifulSoup(res_ct.text, 'html.parser')
            for r in soup.select('table tr'):
                tds = r.find_all('td')
                if len(tds) < 4: continue
                n, m = tds[1].text.strip().split('-')[-1].strip(), tds[2].text.strip()
                if f"{n}_{m[:10]}" not in done_ids:
                    process_sms(n, m)
                    done_ids.append(f"{n}_{m[:10]}")

            # --- SCAN X-MNIT (LOGIKA DOUBLE DATA) ---
            tgl = time.strftime("%Y-%m-%d")
            url_mn = f"https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/info?date={tgl}&page=1&search=&status="
            res_mn = curl_req.get(url_mn, headers=headers_mnit, impersonate="chrome", timeout=15)
            
            if res_mn.status_code == 200:
                json_data = res_mn.json()
                # BONGKAR DATA MNIT
                items = json_data.get('data', [])
                if isinstance(items, dict): items = items.get('data', [])

                for it in items:
                    num, code = it.get('copy'), it.get('code')
                    if num and code:
                        # Bersihkan tag HTML ijo di kode
                        clean_c = re.sub('<[^<]+?>', '', str(code)).strip()
                        uid = f"{num}_{clean_c}"
                        if uid not in done_ids:
                            process_sms(num, f"Your code is {clean_c}")
                            done_ids.append(uid)
            
            if len(done_ids) > 500: done_ids = done_ids[-200:]
            time.sleep(3)
        except: time.sleep(5)

if __name__ == "__main__":
    send_tele("🚀 <b>BOT ENGINE V-FINAL AKTIF!</b>\nSemua panel standby. Silakan kerja.")
    threading.Thread(target=run_manager, daemon=True).start()
    threading.Thread(target=run_grabber, daemon=True).start()
    while True: time.sleep(10)
