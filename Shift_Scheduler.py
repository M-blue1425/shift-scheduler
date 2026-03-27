import streamlit as st
import pandas as pd
import random
import io
import math

# === 1. KONFIGURASI HALAMAN ===
st.set_page_config(page_title="Shift Scheduler Ultimate", layout="wide")
st.title("HD ATMi Shifting Scheduler (Ultimate Rebuild)")

# === 2. SIDEBAR INPUT & UPLOAD ===
with st.sidebar:
    st.header("1. Upload Riwayat Bulan Lalu")
    st.info("Upload file Excel hasil jadwal bulan lalu agar jadwal Hari ke-1 bulan ini menyambung dengan akurat.")
    uploaded_file = st.file_uploader("Upload Excel (.xlsx)", type=['xlsx'])

    st.markdown("---")
    st.header("2. Konfigurasi Bulan Ini")
    default_team = "Reza\nGandhy\nFarhan\nJubel\nRudi\nRenjes\nKhenda\nKarel\nDwiki\nSyaiful\nFelix\nAdi\nAlfyn\nRobby"
    team_input = st.text_area("Team Members", default_team, height=150)

    num_days = st.slider("Jumlah Hari (Periode Bulan Ini)", min_value=7, max_value=31, value=31)

    st.subheader("Dompet Kuota & Batas")
    target_off_days = st.number_input("Target Libur (Off) per Karyawan", min_value=1, max_value=15, value=10)
    target_work_days = num_days - target_off_days

    # --- FITUR BARU: SLIDER BATAS KERJA ---
    max_consecutive_work = st.slider("Batas Maks. Kerja Beruntun", min_value=4, max_value=10, value=6)
    max_off_per_day = st.slider("Maksimal Karyawan Libur per Hari", min_value=2, max_value=10, value=5)

    st.success(
        f"**Dompet Kuota Terkunci:**\n💼 Target Kerja: **{target_work_days} Hari**\n🏖️ Target Libur: **{target_off_days} Hari**\n⚠️ Wajib Libur setelah: **{max_consecutive_work} Hari Kerja**")

    st.markdown("---")
    st.subheader("3. Request Libur & Cuti")
    st.info("Format: Nama, Dari, Sampai, Tipe (X/C)")
    request_input = st.text_area("Input Request", value="", height=150)

team_members = [name.strip() for name in team_input.strip().splitlines() if name.strip()]


# === 3. FUNGSI EKSTRAKSI (CARRY-OVER STATE) ===
def get_carry_over_state(file_upload, members):
    if file_upload is None: return None
    try:
        df_prev = pd.read_excel(file_upload, index_col=0)
        day_cols = [c for c in df_prev.columns if str(c).startswith('Day')]
        if not day_cols: return None

        state = {}
        for m in members:
            if m in df_prev.index:
                row_data = df_prev.loc[m, day_cols].values
                last_s = row_data[-1] if len(row_data) > 0 else None
                if pd.isna(last_s) or last_s == '-': last_s = None

                cw = 0
                for val in reversed(row_data):
                    if pd.isna(val) or val in ['Off', 'X', 'C', '-']:
                        break
                    cw += 1

                state[m] = {'last_shift': last_s, 'consecutive_work': cw}
        return state
    except Exception as e:
        st.sidebar.error(f"Gagal membaca file riwayat: {e}")
        return None


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


# === 4. LOGIKA UTAMA (REBUILD) ===
def generate_schedule_balanced(members, num_days, requests, target_work, target_off, max_off_daily, max_consec_work,
                               initial_state):
    special_team = ["Felix", "Adi", "Alfyn"]

    stats = {}
    for m in members:
        ls = None
        cw = 0
        if initial_state and m in initial_state:
            ls = initial_state[m]['last_shift']
            cw = initial_state[m]['consecutive_work']

        stats[m] = {
            'shifts': [], 'work_count': 0, 'off_count': 0, 'cuti_count': 0,
            'consecutive_work': cw, 'malam_count': 0, 'last_shift': ls,
            'owe_off': 0, 'restrict_pagi': False
        }

    for day_idx in range(num_days):
        day_num = day_idx + 1
        unassigned = members.copy()
        today_offs = 0

        # --- LANGKAH 1: REQUEST USER (Pasti Terkabul) ---
        for m in members:
            if (m, day_idx) in requests:
                req = requests[(m, day_idx)]
                stats[m]['shifts'].append(req)
                stats[m]['last_shift'] = req
                unassigned.remove(m)

                if req == 'C':
                    stats[m]['cuti_count'] += 1
                    stats[m]['consecutive_work'] = 0
                    today_offs += 1
                    stats[m]['restrict_pagi'] = False
                    if stats[m]['owe_off'] > 0: stats[m]['owe_off'] -= 1
                elif req in ['X', 'Off']:
                    stats[m]['off_count'] += 1
                    stats[m]['consecutive_work'] = 0
                    today_offs += 1
                    stats[m]['restrict_pagi'] = False
                    if stats[m]['owe_off'] > 0: stats[m]['owe_off'] -= 1

        # --- LANGKAH 2: SAFETY & DOMPET KUOTA ---
        for m in unassigned[:]:
            last_s = stats[m]['last_shift']
            force_off = False
            reason_off = ""
            just_added_owe = False

            # A. Cek Sensor Kelelahan (Menggunakan Slider Baru)
            if stats[m]['consecutive_work'] >= max_consec_work:
                force_off = True
                stats[m]['owe_off'] = 1
                just_added_owe = True

            # B. Cek Sensor Post-Malam
            if last_s == 'Malam':
                force_off = True
                reason_off = "Post-Malam"

            # C. Pembayaran Hutang Libur Hari ke-2
            elif stats[m]['owe_off'] > 0 and not just_added_owe:
                force_off = True
                stats[m]['owe_off'] -= 1

            # D. Penjaga Dompet Kuota Maksimal Kerja
            if (stats[m]['work_count'] + stats[m]['cuti_count']) >= target_work:
                force_off = True

            # E. Penjaga Dompet Kuota Maksimal Libur
            days_left = num_days - day_idx
            offs_needed = target_off - stats[m]['off_count']
            if offs_needed >= days_left: force_off = True

            if force_off:
                stats[m]['shifts'].append('Off')
                stats[m]['last_shift'] = 'Off'
                stats[m]['off_count'] += 1
                stats[m]['consecutive_work'] = 0
                today_offs += 1

                if reason_off == "Post-Malam":
                    stats[m]['restrict_pagi'] = True
                else:
                    stats[m]['restrict_pagi'] = False
                unassigned.remove(m)

        # --- LANGKAH 3: TIM SPESIAL (Flow Strict) ---
        for m in unassigned[:]:
            if m in special_team:
                last_s = stats[m]['last_shift']
                if last_s == 'Middle':
                    chosen = 'Siang'
                elif last_s == 'Siang':
                    chosen = 'Siang'
                else:
                    chosen = random.choice(['Siang', 'Middle'])

                stats[m]['shifts'].append(chosen)
                stats[m]['last_shift'] = chosen
                stats[m]['work_count'] += 1
                stats[m]['consecutive_work'] += 1
                stats[m]['restrict_pagi'] = False
                unassigned.remove(m)

        # --- LANGKAH 4: SHIFT MALAM (Rotasi Cerdas) ---
        eligible_malam = [m for m in unassigned if m not in special_team]

        def sort_malam(emp):
            ls = stats[emp]['last_shift']
            if ls == 'Sore':
                f_score = 1
            elif ls == 'Pagi':
                f_score = 2
            elif ls is None:
                f_score = 3
            else:
                f_score = 4
            return (stats[emp]['malam_count'], f_score, stats[emp]['work_count'])

        eligible_malam.sort(key=sort_malam)
        assigned_malam = 0
        for m in eligible_malam:
            if assigned_malam >= 2: break
            stats[m]['shifts'].append('Malam')
            stats[m]['last_shift'] = 'Malam'
            stats[m]['work_count'] += 1
            stats[m]['malam_count'] += 1
            stats[m]['consecutive_work'] += 1
            stats[m]['restrict_pagi'] = False
            unassigned.remove(m)
            assigned_malam += 1

        # --- LANGKAH 5: SHIFT PAGI/SORE TGL KHUSUS ---
        req_pagi_sore = 3 if day_num in [10, 11, 12, 25, 26, 27] else 0
        if req_pagi_sore > 0:
            eligible_pagi = [m for m in unassigned if
                             m not in special_team and not stats[m]['restrict_pagi'] and stats[m][
                                 'last_shift'] != 'Sore']
            eligible_pagi.sort(key=lambda x: stats[x]['work_count'])
            assigned_pagi = 0
            for m in eligible_pagi:
                if assigned_pagi >= req_pagi_sore: break
                stats[m]['shifts'].append('Pagi')
                stats[m]['last_shift'] = 'Pagi'
                stats[m]['work_count'] += 1
                stats[m]['consecutive_work'] += 1
                stats[m]['restrict_pagi'] = False
                unassigned.remove(m)
                assigned_pagi += 1

            eligible_sore = [m for m in unassigned if m not in special_team]
            eligible_sore.sort(key=lambda x: stats[x]['work_count'])
            assigned_sore = 0
            for m in eligible_sore:
                if assigned_sore >= req_pagi_sore: break
                stats[m]['shifts'].append('Sore')
                stats[m]['last_shift'] = 'Sore'
                stats[m]['work_count'] += 1
                stats[m]['consecutive_work'] += 1
                stats[m]['restrict_pagi'] = False
                unassigned.remove(m)
                assigned_sore += 1

        # --- LANGKAH 6: PEMERATAAN LIBUR ---
        if today_offs < max_off_daily:
            eligible_for_off = [m for m in unassigned if stats[m]['off_count'] < target_off]

            def sort_off(emp):
                consec = -stats[emp]['consecutive_work']
                ls = stats[emp]['last_shift']
                if ls == 'Sore':
                    f_score = 1
                elif ls == 'Pagi':
                    f_score = 2
                elif ls is None:
                    f_score = 3
                else:
                    f_score = 4
                return (consec, f_score)

            eligible_for_off.sort(key=sort_off)
            for m in eligible_for_off:
                if today_offs >= max_off_daily: break
                stats[m]['shifts'].append('Off')
                stats[m]['last_shift'] = 'Off'
                stats[m]['off_count'] += 1
                stats[m]['consecutive_work'] = 0
                stats[m]['restrict_pagi'] = False
                today_offs += 1
                unassigned.remove(m)

        # --- LANGKAH 7: PENYEIMBANG AKTIF PAGI/SORE ---
        unassigned_reguler = [m for m in unassigned]
        if unassigned_reguler:
            target_pagi = math.ceil(len(unassigned_reguler) / 2)

            def sort_pagi_priority(emp):
                last_s = stats[emp]['last_shift']
                if stats[emp]['restrict_pagi'] or last_s == 'Sore': return 99
                if last_s == 'Off': return 1
                if last_s is None: return 2
                if last_s == 'Pagi': return 3
                return 4

            unassigned_reguler.sort(key=sort_pagi_priority)
            assigned_pagi_count = 0

            for m in unassigned_reguler:
                stats[m]['temp_choice'] = 'Sore'

            for m in unassigned_reguler:
                if assigned_pagi_count < target_pagi and not stats[m]['restrict_pagi'] and stats[m][
                    'last_shift'] != 'Sore':
                    stats[m]['temp_choice'] = 'Pagi'
                    assigned_pagi_count += 1

            if assigned_pagi_count == 0 and len(unassigned_reguler) > 0:
                for m in reversed(unassigned_reguler):
                    if not stats[m]['restrict_pagi']:
                        stats[m]['temp_choice'] = 'Pagi'
                        assigned_pagi_count += 1
                        break

            for m in unassigned_reguler:
                chosen = stats[m]['temp_choice']
                stats[m]['shifts'].append(chosen)
                stats[m]['last_shift'] = chosen
                stats[m]['work_count'] += 1
                stats[m]['consecutive_work'] += 1
                stats[m]['restrict_pagi'] = False

    schedule = {m: stats[m]['shifts'] for m in members}
    return pd.DataFrame(schedule, index=[f"Day {i + 1}" for i in range(num_days)]).T


def generate_overtime_recommendations(schedule_df, days_count):
    day_columns = [f"Day {i + 1}" for i in range(days_count)]
    ot_df = pd.DataFrame("", index=schedule_df.index, columns=day_columns)
    for member in schedule_df.index:
        for col in day_columns:
            curr = schedule_df.at[member, col]
            if curr == 'Pagi':
                rek = "Sore, Malam"
            elif curr == 'Sore':
                rek = "Pagi, Malam"
            elif curr == 'Middle':
                rek = "Pagi, Sore"
            elif curr == 'Malam':
                rek = "Pagi (H+1)"
            else:
                rek = "-"
            ot_df.at[member, col] = rek
    return ot_df


# === 5. EKSEKUSI & TAMPILAN ===
user_requests = parse_requests_flexible(request_input)
initial_state = get_carry_over_state(uploaded_file, team_members)

if st.button("Generate Schedule"):
    with st.spinner("Menganalisis Algoritma Fatigue & Dompet Kuota..."):
        # Parameter max_consec_work dimasukkan ke pemanggilan fungsi di bawah ini
        df = generate_schedule_balanced(team_members, num_days, user_requests, target_work_days, target_off_days,
                                        max_off_per_day, max_consecutive_work, initial_state)

        st.write("### 🚨 Laporan Operasional Harian")
        daily_offs = (df.isin(['Off', 'X', 'C'])).sum()
        over_limit_days = daily_offs[daily_offs > max_off_per_day]

        if not over_limit_days.empty:
            st.warning(
                f"⚠️ Peringatan: Ada hari yang liburnya melewati batas maksimal ({max_off_per_day} orang) karena intervensi Aturan Kelelahan / Safety.")

            # --- TAMBAHAN: Menampilkan detail nama karyawan per hari ---
            for day in over_limit_days.index:
                # Filter nama karyawan yang statusnya Off, X, atau C pada hari tersebut
                off_employees = df[df[day].isin(['Off', 'X', 'C'])].index.tolist()

                # Gabungkan nama-nama tersebut menjadi satu string teks
                names_str = ", ".join(off_employees)

                # Tampilkan di layar dengan kotak warna merah/error agar jelas
                st.error(f"📅 **{day}** ({len(off_employees)} orang libur): {names_str}")
            # -----------------------------------------------------------

        else:
            st.success(f"✅ Aman! Tidak ada hari yang kekurangan personel jaga.")

        # --- HITUNGAN TOTAL ---
        df['Pagi'] = (df == 'Pagi').sum(axis=1)
        df['Siang'] = (df == 'Siang').sum(axis=1)
        df['Sore'] = (df == 'Sore').sum(axis=1)
        df['Malam'] = (df == 'Malam').sum(axis=1)
        df['Middle'] = (df == 'Middle').sum(axis=1)

        df['Total kerja'] = df[['Pagi', 'Siang', 'Sore', 'Malam', 'Middle']].sum(axis=1)
        df['Cuti (C)'] = (df == 'C').sum(axis=1)
        df['GRAND TOTAL KERJA'] = df['Total kerja'] + df['Cuti (C)']

        df['Req Libur (X)'] = (df == 'X').sum(axis=1)
        df['Libur Kerja'] = (df == 'Off').sum(axis=1)
        df['GRAND TOTAL LIBUR'] = df['Req Libur (X)'] + df['Libur Kerja']

        # --- GENERATE DATA LEMBUR ---
        df_lembur = generate_overtime_recommendations(df, num_days)


        # --- PEWARNAAN JADWAL ---
        def color_coding(val):
            if val == 'Off': return 'background-color: #e0e0e0; color: black'
            if val == 'Malam': return 'background-color: #2c3e50; color: white'
            if val == 'X': return 'background-color: #e74c3c; color: white'
            if val == 'C': return 'background-color: #f39c12; color: white'
            if val == 'Pagi': return 'background-color: #f1c40f; color: black'
            if val == 'Sore': return 'background-color: #27ae60; color: white'
            if val == 'Siang': return 'background-color : #FFD95F; color: black'
            if val == 'Middle': return 'background-color : #3498db; color: white'
            if isinstance(val, (int,
                                float)): return 'font-weight: bold; background-color: #f8f9fa; color: black; border-left: 1px solid #ccc'
            return ''


        # --- TAMPILAN DI WEB (STREAMLIT) ---
        st.subheader("📅 Jadwal Utama (Rebuild Edition)")
        st.dataframe(df.style.applymap(color_coding), use_container_width=True)

        st.subheader("💡 Rekomendasi Lembur (Overtime)")
        st.info(
            "Tabel ini menunjukkan rekomendasi shift lembur yang aman diambil oleh karyawan berdasarkan shift mereka hari itu.")
        st.dataframe(df_lembur, use_container_width=True)

        # --- EXPORT KE EXCEL (2 SHEET) ---
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Sheet 1: Jadwal Utama
            df.to_excel(writer, index=True, sheet_name='Summary_Schedule', startrow=0)
            worksheet = writer.sheets['Summary_Schedule']
            for column_cells in worksheet.columns:
                length = max(len(str(cell.value)) if cell.value else 0 for cell in column_cells)
                worksheet.column_dimensions[column_cells[0].column_letter].width = length + 2

            # Sheet 2: Rekomendasi Lembur
            df_lembur.to_excel(writer, index=True, sheet_name='Rekomendasi_Lembur', startrow=0)
            worksheet_ot = writer.sheets['Rekomendasi_Lembur']
            for column_cells in worksheet_ot.columns:
                length = max(len(str(cell.value)) if cell.value else 0 for cell in column_cells)
                worksheet_ot.column_dimensions[column_cells[0].column_letter].width = length + 2

        st.download_button("⬇️ Download Excel (Jadwal & Lembur)", output.getvalue(), 'jadwal_ultimate_rebuild.xlsx')
