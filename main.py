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
    print(f"🛰️ MANAGER STANDBY. DATABASE: {FIREBASE_URL}")
    while True:
        try:
            # 1. Ambil Antrian Perintah
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
                
                m_id = val.get('memberId', 'Unknown')
                m_name = val.get('memberName') or m_id
                inv_id = val.get('inventoryId')
                
                print(f"📥 REQUEST: {m_name} minta stok {inv_id}")

                if not inv or inv_id not in inv:
                    requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
                    continue
                
                item = inv[inv_id]
                nomor_hasil = None
                
                # AMBIL NAMA LAYANAN (Cek semua kemungkinan field name)
                nama_layanan = item.get('serviceName') or item.get('name') or item.get('nama') or "Layanan"

                # --- STRATEGI 1: CEK APAKAH ADA STOK MANUAL? ---
                # (Bot bakal nyari di folder 'stock' atau 'stok' atau 'numbers')
                stok_manual = item.get('stock') or item.get('stok') or item.get('numbers')
                
                if stok_manual:
                    if isinstance(stok_manual, list) and len(stok_manual) > 0:
                        nomor_hasil = stok_manual.pop(0)
                        # Update sisa stok ke Firebase (Pake field aslinya)
                        field_name = 'stock' if item.get('stock') else ('stok' if item.get('stok') else 'numbers')
                        requests.put(f"{FIREBASE_URL}/inventory/{inv_id}/{field_name}.json", json=stok_manual)
                    elif isinstance(stok_manual, dict) and len(stok_manual) > 0:
                        key = list(stok_manual.keys())[0]
                        nomor_hasil = stok_manual[key]
                        field_name = 'stock' if item.get('stock') else ('stok' if item.get('stok') else 'numbers')
                        requests.delete(f"{FIREBASE_URL}/inventory/{inv_id}/{field_name}/{key}.json")

                # --- STRATEGI 2: JIKA STOK MANUAL KOSONG, CEK APAKAH ADA PREFIX X-MNIT? ---
                if not nomor_hasil:
                    raw_prefix = item.get('prefixes') or item.get('prefix')
                    if raw_prefix:
                        # Bersihkan XXXX biar jadi angka murni
                        target_range = re.sub(r'[xX]', '', str(raw_prefix)).strip()
                        print(f"🎯 Mencoba X-MNIT dengan Prefix: {target_range}")
                        
                        h = {'content-type':'application/json','cookie':MNIT_COOKIE,'mauthtoken':MNIT_TOKEN,'user-agent':MY_UA}
                        try:
                            api_url = "https://x.mnitnetwork.com/mapi/v1/mdashboard/getnum/number"
                            res = curl_req.post(api_url, headers=h, json={"range": target_range}, impersonate="chrome", timeout=20)
                            if res.status_code == 200:
                                nomor_hasil = res.json().get('data', {}).get('copy')
                        except: pass

                # --- HASIL AKHIR ---
                if nomor_hasil:
                    data_final = {
                        "number": str(nomor_hasil),
                        "name": nama_layanan,
                        "timestamp": int(time.time() * 1000)
                    }
                    # Simpan ke folder dashboard anggota (Web pasti nambah)
                    clean_num = str(nomor_hasil).replace('+', '').strip()
                    requests.patch(f"{FIREBASE_URL}/members/{m_id}/active_numbers/{clean_num}.json", json=data_final)
                    
                    # Notif Telegram
                    kirim_tele(f"✅ <b>NOMOR DIDAPAT!</b>\n👤 Anggota: <b>{m_name}</b>\n📱 Nomor: <code>{nomor_hasil}</code>\n📦 Layanan: {nama_layanan}")
                    print(f"✅ SUKSES: {nomor_hasil} dikirim ke {m_name}")
                else:
                    kirim_tele(f"⚠️ <b>STOK HABIS!</b>\nLayanan: {nama_layanan}\nAnggota: {m_name}")
                    print(f"❌ GAGAL: Tidak ada stok atau prefix valid untuk {inv_id}")

                # HAPUS ANTRIAN BIAR WEB BERHENTI MUTER
                requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
            
            time.sleep(1)
        except Exception as e:
            print(f"MANAGER ERROR: {e}")
            time.sleep(5)

if __name__ == "__main__":
    t1 = threading.Thread(target=run_manager, daemon=True)
    t1.start()
    print("🚀 BOT RUNNING - SEMOGA KALI INI SINKRON!")
    while True: time.sleep(10)
