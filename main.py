import threading, time, os, re, random, requests
from curl_cffi import requests as curl_req

# === CONFIG ===
FIREBASE_URL = os.getenv("FIREBASE_URL", "").strip().rstrip('/')
TELE_TOKEN = os.getenv("TELE_TOKEN", "").strip()
TELE_CHAT_ID = os.getenv("TELE_CHAT_ID", "").strip()
MNIT_COOKIE = os.getenv("MNIT_COOKIE", "").strip()
MNIT_TOKEN = os.getenv("MNIT_TOKEN", "").strip()
MY_UA = os.getenv("MY_UA", "").strip()

def kirim_tele(pesan):
    if not TELE_TOKEN or not TELE_CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage"
        requests.post(url, data={'chat_id': TELE_CHAT_ID, 'text': pesan, 'parse_mode': 'HTML'}, timeout=10)
    except: pass

def run_manager():
    print(f"🛰️ MANAGER AKTIF. MENGARAH KE: {FIREBASE_URL}")
    while True:
        try:
            # 1. Ambil Antrian
            r = requests.get(f"{FIREBASE_URL}/perintah_bot.json")
            cmds = r.json()
            if not cmds or not isinstance(cmds, dict):
                time.sleep(1); continue
            
            # 2. Ambil Inventory
            inv = requests.get(f"{FIREBASE_URL}/inventory.json").json()
            
            for cmd_id, val in cmds.items():
                if not isinstance(val, dict):
                    requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
                    continue
                
                m_id = val.get('memberId', 'UnknownUser')
                inv_id = val.get('inventoryId')
                print(f"📥 REQUEST: {m_id} minta stok {inv_id}")

                if not inv or inv_id not in inv:
                    kirim_tele(f"❌ <b>ID STOK TIDAK DITEMUKAN!</b>\nID: {inv_id}")
                    requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
                    continue
                
                item = inv[inv_id]
                nomor_hasil = None
                
                # AMBIL NAMA (Cek semua kemungkinan nama variabel)
                nama_layanan = item.get('name') or item.get('nama') or item.get('service') or "Unknown Service"
                tipe = item.get('type') or item.get('tipe')

                # --- LOGIKA AMBIL NOMOR ---
                if tipe == 'manual':
                    # Cek field 'stock' atau 'stok'
                    nums = item.get('stock') or item.get('stok') or []
                    if nums:
                        if isinstance(nums, list):
                            nomor_hasil = nums.pop(0)
                            requests.put(f"{FIREBASE_URL}/inventory/{inv_id}/stock.json", json=nums)
                        elif isinstance(nums, dict):
                            key = list(nums.keys())[0]
                            nomor_hasil = nums[key]
                            requests.delete(f"{FIREBASE_URL}/inventory/{inv_id}/stock/{key}.json")
                
                elif tipe == 'xmnit':
                    # Cek field 'prefixes' atau 'prefix' atau 'range'
                    pref_data = item.get('prefixes') or item.get('prefix') or item.get('range') or []
                    
                    # Jika admin inputnya string dipisah koma, kita jadikan list
                    if isinstance(pref_data, str):
                        prefixes = [p.strip() for p in pref_data.split(',')]
                    else:
                        prefixes = pref_data

                    if prefixes:
                        target = random.choice(prefixes)
                        h = {'content-type':'application/json','cookie':MNIT_COOKIE,'mauthtoken':MNIT_TOKEN,'user-agent':MY_UA}
                        try:
                            res = curl_req.post("https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/number", headers=h, json={"range":target}, impersonate="chrome", timeout=20)
                            if res.status_code == 200:
                                nomor_hasil = res.json().get('data', {}).get('copy')
                        except: pass

                # --- HASIL ---
                if nomor_hasil:
                    data_final = {"number": str(nomor_hasil), "name": nama_layanan, "timestamp": int(time.time() * 1000)}
                    clean_num = str(nomor_hasil).replace('+', '').strip()
                    path_web = f"{FIREBASE_URL}/members/{m_id}/active_numbers/{clean_num}.json"
                    requests.patch(path_web, json=data_final)
                    
                    kirim_tele(f"✅ <b>NOMOR DIDAPAT!</b>\n👤 Anggota: <code>{m_id}</code>\n📱 Nomor: <code>{nomor_hasil}</code>\n📦 Layanan: {nama_layanan}")
                else:
                    kirim_tele(f"⚠️ <b>STOK HABIS / ERROR!</b>\nLayanan: {nama_layanan}\nAnggota: {m_id}\nTipe: {tipe}")

                requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
            
            time.sleep(1)
        except Exception as e:
            print(f"MANAGER ERROR: {e}")
            time.sleep(5)

if __name__ == "__main__":
    t1 = threading.Thread(target=run_manager, daemon=True)
    t1.start()
    while True: time.sleep(10)
