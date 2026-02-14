import streamlit as st
import pandas as pd
import random
import io

# === 1. KONFIGURASI HALAMAN ===
st.set_page_config(page_title="Shift Scheduler", layout="wide")
st.title("HD ATMi Shifting Scheduler)")

# === 2. SIDEBAR INPUT ===
with st.sidebar:
    st.header("Configuration")

    default_team = "Reza\nGandhy\nFarhan\nJubel\nRudi\nRenjes\nKhenda\nKarel\nDwiki\nSyaiful\nFelix\nAdi\nAlfyn"
    team_input = st.text_area("Team Members", default_team, height=150)

    # Note: Pilihan shift di sini hanya visual, logika coding akan meng-override berdasarkan nama member
    st.info("Logika Shift: Felix, Adi, Alfyn (Siang/Middle). Lainnya (Pagi/Sore/Malam).")

    num_days = st.slider("Number of Days", min_value=7, max_value=31, value=31)

    st.markdown("---")
    st.subheader("Request Libur & Cuti")
    st.info("Format: Nama, Dari, Sampai, Tipe (X/C)")

    placeholder_text = "Contoh:\nReza, 2, 3, X\nSyaiful, 5, C\nAdi, 10, 12, X"

    request_input = st.text_area(
        "Input Request",
        value="",  # <--- Dikosongkan
        height=200,
        placeholder=placeholder_text  # <--- Petunjuk bayangan (abu-abu)
    )

team_members = [name.strip() for name in team_input.strip().splitlines() if name.strip()]


# === 3. FUNGSI PARSE REQUEST ===
def parse_requests_flexible(request_text):
    requests = {}
    if not request_text.strip(): return requests

    for line in request_text.splitlines():
        if not line.strip(): continue
        try:
            parts = [p.strip() for p in line.split(',')]
            if len(parts) == 3:
                name, day, r_type = parts[0], int(parts[1]) - 1, parts[2].upper()
                requests[(name, day)] = r_type
            elif len(parts) == 4:
                name, d1, d2, r_type = parts[0], int(parts[1]), int(parts[2]), parts[3].upper()
                for day_idx in range(min(d1, d2) - 1, max(d1, d2)):
                    requests[(name, day_idx)] = r_type
        except:
            continue
    return requests


# === 4. LOGIKA PEMBUATAN JADWAL (UPDATED) ===
def generate_schedule_final(members, num_days, requests):
    schedule = {}

    # Kelompok Khusus (Logika No. 1)
    special_team = ["Felix", "Adi", "Alfyn"]

    for member in members:
        shifts = []

        # Variabel tracking pola kerja 5-2 (Logika No. 2)
        consecutive_work = 0
        owe_off_days = 0

        for i in range(num_days):
            # --- A. CEK REQUEST USER ---
            if (member, i) in requests:
                req_type = requests[(member, i)]
                shifts.append(req_type)

                # Update tracking kerja
                # Jika Request (X/C), berarti istirahat, reset streak kerja
                consecutive_work = 0
                # Jika kita punya hutang libur, request ini membayarnya
                if owe_off_days > 0:
                    owe_off_days -= 1
                continue

            prev_shift = shifts[i - 1] if i > 0 else None

            # --- B. TENTUKAN TIPE SHIFT (Logika No. 1) ---
            if member in special_team:
                allowed = ["Siang", "Middle"]
            else:
                allowed = ["Pagi", "Sore", "Malam"]

            # --- C. ATURAN CONSTRAINT ---
            force_off = False

            # 1. Aturan Malam Sebelumnya (Malam -> Off)
            if prev_shift == "Malam":
                force_off = True

            # 2. Aturan Sore -> Pagi (Dilarang)
            elif prev_shift == "Sore" and "Pagi" in allowed:
                allowed.remove("Pagi")

            # 3. Aturan Siang -> Middle (Logika No. 3)
            # Tidak bisa Middle jika sebelumnya Siang
            if prev_shift == "Siang" and "Middle" in allowed:
                allowed.remove("Middle")

            # 4. Limit Malam max 2x dalam 5 hari (Logika No. 4)
            # Hanya berlaku untuk tim non-spesial (karena spesial ga dpt malam)
            if member not in special_team and "Malam" in allowed:
                # Ambil 4 shift terakhir
                recent_shifts = shifts[-4:] if len(shifts) >= 4 else shifts
                if recent_shifts.count("Malam") >= 2:
                    allowed.remove("Malam")

            # --- D. LOGIKA 5 KERJA -> 2 LIBUR (Logika No. 2) ---
            # Cek status hari sebelumnya (apakah kerja atau libur)
            prev_was_work = prev_shift not in ['Off', 'X', 'C', None]

            if prev_was_work:
                consecutive_work += 1
            else:
                consecutive_work = 0  # Reset jika kemarin libur/cuti

            # Jika sudah kerja 5 hari berturut-turut, picu hutang libur 2 hari
            if consecutive_work >= 5:
                owe_off_days = 2
                consecutive_work = 0  # Reset counter agar trigger ulang nanti

            # Jika punya hutang libur, paksa Off
            if owe_off_days > 0:
                force_off = True

            # --- E. PENENTUAN FINAL ---
            final_shift = ""

            if force_off:
                final_shift = "Off"
                if owe_off_days > 0:
                    owe_off_days -= 1  # Bayar hutang libur
            else:
                # Random choice dari allowed
                # Kita beri sedikit kemungkinan 'Off' acak agar tidak terlalu padat
                # Tapi prioritas mengisi shift
                weight_off = ["Off"] if random.random() > 0.85 else []  # 15% chance random off
                final_shift = random.choice(allowed + weight_off)

                # Jika random kepilih Off, kurangi hutang jika ada (safety net)
                if final_shift == "Off" and owe_off_days > 0:
                    owe_off_days -= 1

            shifts.append(final_shift)

        schedule[member] = shifts
    return pd.DataFrame(schedule, index=[f"Day {i + 1}" for i in range(num_days)]).T

#Perhitungan rekomendasi Longshift
def generate_overtime_recommendations(schedule_df, days_count):
    # Buat copy kosong dengan index (nama member) yang sama
    # Kita hanya ambil kolom "Day 1" s/d "Day N", abaikan kolom Summary total
    day_columns = [f"Day {i + 1}" for i in range(days_count)]
    ot_df = pd.DataFrame("", index=schedule_df.index, columns=day_columns)

    for member in schedule_df.index:
        for col in day_columns:
            # Ambil shift saat ini dari tabel jadwal utama
            current_shift = schedule_df.at[member, col]

            rekomendasi = []

            # Rule 1: Pagi -> Sore atau Malam
            if current_shift == 'Pagi':
                rekomendasi = ["Sore", "Malam"]

            # Rule 2 & 5: Siang -> Malam atau Sore
            elif current_shift == 'Siang':
                rekomendasi = ["Sore", "Malam"]

            # Rule 4: Middle -> Pagi atau Sore
            elif current_shift == 'Middle':
                rekomendasi = ["Pagi", "Sore"]

            # Rule 3: Malam -> Pagi (Besok)
            elif current_shift == 'Malam':
                rekomendasi = ["Pagi (H+1)"]

            # Jika Off/Cuti/X, tidak ada rekomendasi
            else:
                rekomendasi = ["-"]

            # Masukkan ke tabel OT
            ot_df.at[member, col] = ", ".join(rekomendasi)

    return ot_df


# === 5. EKSEKUSI & SUMMARY ===
user_requests = parse_requests_flexible(request_input)

if st.button("Generate Schedule"):
    df = generate_schedule_final(team_members, num_days, user_requests)

    # --- SUMMARY CALCULATION ---
    # 1. Hitung Detail Shift
    df['Total Pagi'] = (df == 'Pagi').sum(axis=1)
    df['Total Siang'] = (df == 'Siang').sum(axis=1)
    df['Total Sore'] = (df == 'Sore').sum(axis=1)
    df['Total Malam'] = (df == 'Malam').sum(axis=1)
    df['Total Middle'] = (df == 'Middle').sum(axis=1)

    # 2. Hitung Libur & Cuti (BAGIAN YANG DIPERBAIKI)
    df['Total Cuti (C)'] = (df == 'C').sum(axis=1)
    df['Total Req Libur (X)'] = (df == 'X').sum(axis=1)  # <--- Baris ini yang sebelumnya hilang
    df['Total System Off'] = (df == 'Off').sum(axis=1)

    # 3. Hitung Grand Total (Sekarang aman karena variabel di atas sudah ada)
    df['GRAND TOTAL LIBUR'] = df['Total Req Libur (X)'] + df['Total System Off']

    # 4. Hitung Total Masuk
    work_shifts = ['Pagi', 'Sore', 'Malam', 'Siang', 'Middle']
    df['Total Masuk'] = df.isin(work_shifts).sum(axis=1)

    # 5. Generate Rekomendasi Lembur
    df_lembur = generate_overtime_recommendations(df, num_days)


    # --- TAMPILAN WEBSITE ---
    # Pewarnaan
    def color_coding(val):
        if val == 'Off': return 'background-color: #e0e0e0; color: black'
        if val == 'Malam': return 'background-color: #2c3e50; color: white'
        if val == 'X': return 'background-color: #e74c3c; color: white'
        if val == 'C': return 'background-color: #f39c12; color: white'
        if val == 'Pagi': return 'background-color: #f1c40f; color: black'
        if val == 'Sore': return 'background-color: #27ae60; color: white'
        if val == 'Siang': return 'background-color : #FFD95F; color: black'
        if val == 'Middle': return 'background-color : #3498db; color: white'
        if isinstance(val, (int, float)):
            return 'font-weight: bold; background-color: #f8f9fa; color: black; border-left: 1px solid #ccc'
        return ''


    st.success("Jadwal Berhasil Dibuat dengan Aturan Baru!")

    st.subheader("📅 Jadwal Utama")
    st.dataframe(df.style.applymap(color_coding), use_container_width=True)

    st.subheader("💪 Rekomendasi Lembur (Options)")
    st.dataframe(df_lembur, use_container_width=True)

    # --- DOWNLOAD EXCEL ---
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Tulis Tabel Utama
        df.to_excel(writer, index=True, sheet_name='Summary_Schedule', startrow=0)

        # Hitung posisi untuk tabel kedua (Beri jarak)
        start_row_ot = len(df) + 3

        # Tulis Judul Kecil
        worksheet = writer.sheets['Summary_Schedule']
        worksheet.cell(row=start_row_ot - 1, column=1, value="REKOMENDASI LEMBUR (OPTIONS)")

        # Tulis Tabel Lembur
        df_lembur.to_excel(writer, sheet_name='Summary_Schedule', startrow=start_row_ot, index=True)

        # Auto Adjust Column Width
        for column_cells in worksheet.columns:
            length = max(len(str(cell.value)) if cell.value else 0 for cell in column_cells)
            worksheet.column_dimensions[column_cells[0].column_letter].width = length + 2

    st.download_button("⬇️ Download Excel (Detailed Summary)", output.getvalue(), 'jadwal_detail_v3.xlsx')
