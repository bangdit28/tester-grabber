import threading, time, os, re, random, requests

FIREBASE_URL = os.getenv("FIREBASE_URL", "").strip().rstrip('/')
TELE_TOKEN = os.getenv("TELE_TOKEN", "").strip()
TELE_CHAT_ID = os.getenv("TELE_CHAT_ID", "").strip()

def kirim_tele(pesan):
    if not TELE_TOKEN: return
    try: requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage", 
                      data={'chat_id': TELE_CHAT_ID, 'text': pesan, 'parse_mode': 'HTML'}, timeout=10)
    except: pass

def run_manager():
    print(f"🛰️ MANAGER AKTIF. DATABASE: {FIREBASE_URL}")
    while True:
        try:
            # 1. CEK PERINTAH
            r = requests.get(f"{FIREBASE_URL}/perintah_bot.json")
            cmds = r.json()
            if not cmds or not isinstance(cmds, dict):
                time.sleep(1.5); continue
            
            # 2. AMBIL INVENTORY
            inv_res = requests.get(f"{FIREBASE_URL}/inventory.json")
            inv = inv_res.json() if inv_res.status_code == 200 else {}
            
            for cmd_id, val in cmds.items():
                if not isinstance(val, dict):
                    requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
                    continue
                
                m_id = val.get('memberId', 'tester')
                inv_id = val.get('inventoryId')
                
                print(f"📥 REQUEST MASUK: User {m_id} minta Stok ID {inv_id}")
                
                # CEK APAKAH STOK ADA?
                if not inv or inv_id not in inv:
                    print(f"❌ ERROR: Stok ID {inv_id} tidak ditemukan di Firebase.")
                    requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
                    continue
                
                item = inv[inv_id]
                nomor_hasil = None
                # Ambil nama dengan aman (pake .get biar gak error 'name')
                nama_layanan = item.get('name', 'Unknown Service')
                
                # LOGIKA AMBIL STOK MANUAL
                if item.get('type') == 'manual':
                    # Ambil list nomor
                    nums = item.get('stock', [])
                    if nums:
                        if isinstance(nums, list):
                            nomor_hasil = nums.pop(0)
                            requests.put(f"{FIREBASE_URL}/inventory/{inv_id}/stock.json", json=nums)
                        else: # Jika format object
                            key = list(nums.keys())[0]
                            nomor_hasil = nums[key]
                            requests.delete(f"{FIREBASE_URL}/inventory/{inv_id}/stock/{key}.json")
                
                if nomor_hasil:
                    # TULIS KE MEMBERS (Folder yang dibaca Web)
                    data_final = {
                        "number": str(nomor_hasil), 
                        "name": nama_layanan, 
                        "timestamp": int(time.time() * 1000)
                    }
                    path_member = f"{FIREBASE_URL}/members/{m_id}/active_numbers.json"
                    
                    res_post = requests.post(path_member, json=data_final)
                    if res_post.status_code == 200:
                        print(f"✅ SUKSES: {nomor_hasil} terkirim ke {m_id}")
                        kirim_tele(f"✅ <b>NOMOR DIDAPAT!</b>\n👤 User: <code>{m_id}</code>\n📱 Nomor: <code>{nomor_hasil}</code>\n📦 Layanan: {nama_layanan}")
                    else:
                        print(f"❌ GAGAL nulis ke Firebase.")

                # HAPUS ANTRIAN (Wajib agar Web berhenti muter)
                requests.delete(f"{FIREBASE_URL}/perintah_bot/{cmd_id}.json")
        except Exception as e:
            print(f"MANAGER ERROR: {e}")
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_manager, daemon=True).start()
    while True: time.sleep(10)
