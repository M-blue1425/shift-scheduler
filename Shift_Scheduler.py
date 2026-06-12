import streamlit as st
import pandas as pd
import random
import io
import math
import plotly.express as px

# === 0. KONFIGURASI HALAMAN UTAMA (HARUS PALING ATAS) ===
st.set_page_config(page_title="omnira-atmi", layout="wide")


# ==========================================
# FUNGSI PEMBANTU (HELPER FUNCTIONS)
# ==========================================
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
        st.error(f"Gagal membaca file riwayat: {e}")
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


def generate_schedule_balanced(members, num_days, requests, target_work, target_off, max_off_daily, max_consec_work,
                               initial_state):
    special_team = ["Felix", "Adi", "Alfyn"]
    stats = {m: {'shifts': [], 'work_count': 0, 'off_count': 0, 'cuti_count': 0, 'consecutive_work': initial_state[m][
        'consecutive_work'] if initial_state and m in initial_state else 0, 'malam_count': 0,
                 'last_shift': initial_state[m]['last_shift'] if initial_state and m in initial_state else None,
                 'owe_off': 0, 'restrict_pagi': False} for m in members}

    for day_idx in range(num_days):
        day_num = day_idx + 1
        unassigned = members.copy()
        today_offs = 0

        for m in members:
            if (m, day_idx) in requests:
                req = requests[(m, day_idx)]
                stats[m]['shifts'].append(req)
                stats[m]['last_shift'] = req
                unassigned.remove(m)
                if req == 'C' or req in ['X', 'Off']:
                    if req == 'C':
                        stats[m]['cuti_count'] += 1
                    else:
                        stats[m]['off_count'] += 1
                    stats[m]['consecutive_work'] = 0
                    today_offs += 1
                    stats[m]['restrict_pagi'] = False
                    if stats[m]['owe_off'] > 0: stats[m]['owe_off'] -= 1

        for m in unassigned[:]:
            last_s = stats[m]['last_shift']
            force_off, reason_off, just_added_owe = False, "", False

            if stats[m]['consecutive_work'] >= max_consec_work:
                force_off, stats[m]['owe_off'], just_added_owe = True, 1, True
            if last_s == 'Malam':
                force_off, reason_off = True, "Post-Malam"
            elif stats[m]['owe_off'] > 0 and not just_added_owe:
                force_off, stats[m]['owe_off'] = True, stats[m]['owe_off'] - 1
            if (stats[m]['work_count'] + stats[m]['cuti_count']) >= target_work: force_off = True
            if (target_off - stats[m]['off_count']) >= (num_days - day_idx): force_off = True

            if force_off:
                stats[m]['shifts'].append('Off')
                stats[m]['last_shift'] = 'Off'
                stats[m]['off_count'] += 1
                stats[m]['consecutive_work'] = 0
                today_offs += 1
                stats[m]['restrict_pagi'] = (reason_off == "Post-Malam")
                unassigned.remove(m)

        # --- PERUBAHAN: TIM SPESIAL HANYA PAGI / SORE ---
        for m in unassigned[:]:
            if m in special_team:
                last_s = stats[m]['last_shift']
                # Logika Flow: Habis Sore dilarang Pagi
                if stats[m]['restrict_pagi'] or last_s == 'Sore':
                    chosen = 'Sore'
                elif last_s == 'Pagi':
                    chosen = 'Sore' # Flow natural Pagi ke Sore
                else: # Jika kemarin Off atau hari pertama
                    chosen = 'Pagi'
                
                stats[m]['shifts'].append(chosen)
                stats[m]['last_shift'] = chosen
                stats[m]['work_count'] += 1
                stats[m]['consecutive_work'] += 1
                stats[m]['restrict_pagi'] = False
                unassigned.remove(m)

        # Tim Reguler untuk Malam (Tim Spesial tetap dikecualikan dari Malam)
        eligible_malam = [m for m in unassigned if m not in special_team]
        eligible_malam.sort(key=lambda emp: (stats[emp]['malam_count'],
                                             1 if stats[emp]['last_shift'] == 'Sore' else 2 if stats[emp][
                                                                                                   'last_shift'] == 'Pagi' else 3 if
                                             stats[emp]['last_shift'] is None else 4, stats[emp]['work_count']))
        for m in eligible_malam[:2]:
            stats[m]['shifts'].append('Malam')
            stats[m]['last_shift'] = 'Malam'
            stats[m]['work_count'] += 1
            stats[m]['malam_count'] += 1
            stats[m]['consecutive_work'] += 1
            unassigned.remove(m)

        req_pagi_sore = 3 if day_num in [10, 11, 12, 25, 26, 27] else 0
        if req_pagi_sore > 0:
            for s_type in ['Pagi', 'Sore']:
                elig = [m for m in unassigned if m not in special_team and (
                            s_type == 'Sore' or (not stats[m]['restrict_pagi'] and stats[m]['last_shift'] != 'Sore'))]
                elig.sort(key=lambda x: stats[x]['work_count'])
                for m in elig[:req_pagi_sore]:
                    if m in unassigned:
                        stats[m]['shifts'].append(s_type)
                        stats[m]['last_shift'] = s_type
                        stats[m]['work_count'] += 1
                        stats[m]['consecutive_work'] += 1
                        unassigned.remove(m)

        if today_offs < max_off_daily:
            eligible_for_off = [m for m in unassigned if stats[m]['off_count'] < target_off]
            eligible_for_off.sort(key=lambda emp: (-stats[emp]['consecutive_work'],
                                                   1 if stats[emp]['last_shift'] == 'Sore' else 2 if stats[emp][
                                                                                                         'last_shift'] == 'Pagi' else 3 if
                                                   stats[emp]['last_shift'] is None else 4))
            for m in eligible_for_off:
                if today_offs >= max_off_daily: break
                stats[m]['shifts'].append('Off')
                stats[m]['last_shift'] = 'Off'
                stats[m]['off_count'] += 1
                stats[m]['consecutive_work'] = 0
                today_offs += 1
                unassigned.remove(m)

        unassigned_reguler = [m for m in unassigned]
        if unassigned_reguler:
            target_pagi = math.ceil(len(unassigned_reguler) / 2)
            unassigned_reguler.sort(
                key=lambda emp: 99 if stats[emp]['restrict_pagi'] or stats[emp]['last_shift'] == 'Sore' else 1 if
                stats[emp]['last_shift'] == 'Off' else 2 if stats[emp]['last_shift'] is None else 3 if stats[emp][
                                                                                                           'last_shift'] == 'Pagi' else 4)
            assigned_pagi_count = 0
            for m in unassigned_reguler: stats[m]['temp_choice'] = 'Sore'
            for m in unassigned_reguler:
                if assigned_pagi_count < target_pagi and not stats[m]['restrict_pagi'] and stats[m][
                    'last_shift'] != 'Sore':
                    stats[m]['temp_choice'] = 'Pagi'
                    assigned_pagi_count += 1
            if assigned_pagi_count == 0 and len(unassigned_reguler) > 0:
                for m in reversed(unassigned_reguler):
                    if not stats[m]['restrict_pagi']:
                        stats[m]['temp_choice'] = 'Pagi'
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


def categorize_date(day):
    if 1 <= day <= 5:
        return "Tgl 1-5"
    elif 6 <= day <= 10:
        return "Tgl 6-10"
    elif 11 <= day <= 15:
        return "Tgl 11-15"
    elif 16 <= day <= 20:
        return "Tgl 16-20"
    elif 21 <= day <= 25:
        return "Tgl 21-25"
    else:
        return "Tgl 26-31"


def color_coding(val):
    if val == 'Off': return 'background-color: #e0e0e0; color: black'
    if val == 'Malam': return 'background-color: #2c3e50; color: white'
    if val == 'X': return 'background-color: #e74c3c; color: white'
    if val == 'C': return 'background-color: #f39c12; color: white'
    if val == 'Pagi': return 'background-color: #f1c40f; color: black'
    if val == 'Sore': return 'background-color: #27ae60; color: white'
    if val == 'Siang': return 'background-color : #FFD95F; color: black'
    if val == 'Middle': return 'background-color : #3498db; color: white'
    if isinstance(val, (int, float)): return 'font-weight: bold; background-color: #f8f9fa; color: black; border-left: 1px solid #ccc'
    return ''


# ==========================================
# 1. PROGRAM JADWAL SHIFT
# ==========================================
def aplikasi_jadwal_shift():
    st.title("🗓️ HD ATMi Shifting Scheduler Ultimate")

    # --- UI DI TENGAH (Menggunakan kolom agar tidak makan tempat) ---
    st.write("Silakan lengkapi form di bawah ini untuk membuat jadwal shift bulan ini.")

    col1, col2 = st.columns(2)

    with col1:
        st.header("1. Upload Riwayat Bulan Lalu")
        uploaded_file = st.file_uploader("Upload Excel (.xlsx)", type=['xlsx'])

        st.header("3. Request Libur & Cuti")
        st.info("Format: Nama, Dari, Sampai, Tipe (X/C)")
        request_input = st.text_area("Input Request", value="", height=150)

    with col2:
        st.header("2. Konfigurasi Karyawan")
        default_team = "Reza\nGandhy\nFarhan\nJubel\nRudi\nRenjes\nKhenda\nKarel\nDwiki\nSyaiful\nFelix\nAdi\nAlfyn\nRobby"
        team_input = st.text_area("Team Members", default_team, height=150)

    st.divider()

    st.header("⚙️ Konfigurasi Aturan")
    col3, col4, col5 = st.columns(3)
    with col3:
        num_days = st.slider("Jumlah Hari Bulan Ini", min_value=7, max_value=31, value=31)
        target_off_days = st.number_input("Hari Libur per Karyawan", min_value=1, max_value=15, value=10)
    with col4:
        max_consecutive_work = st.slider("Batas Maks. Kerja Berturut-turut", min_value=4, max_value=10, value=6)
    with col5:
        max_off_per_day = st.slider("Maks. Karyawan Libur per Hari", min_value=2, max_value=10, value=5)

    target_work_days = num_days - target_off_days
    team_members = [name.strip() for name in team_input.strip().splitlines() if name.strip()]

    # Eksekusi Jadwal
    if st.button("🚀 Generate Schedule", use_container_width=True, type="primary"):
        user_requests = parse_requests_flexible(request_input)
        initial_state = get_carry_over_state(uploaded_file, team_members)

        with st.spinner("Menganalisis Algoritma Kelelahan Karyawan & Saldo Libur..."):
            df = generate_schedule_balanced(team_members, num_days, user_requests, target_work_days, target_off_days,
                                            max_off_per_day, max_consecutive_work, initial_state)

            st.divider()
            st.write("### 🚨 Laporan Operasional Harian")
            daily_offs = (df.isin(['Off', 'X', 'C'])).sum()
            over_limit_days = daily_offs[daily_offs > max_off_per_day]

            if not over_limit_days.empty:
                st.warning(
                    f"⚠️ Peringatan: Ada hari yang liburnya melewati batas maksimal ({max_off_per_day} orang) karena Aturan Kelelahan.")
                for day in over_limit_days.index:
                    off_employees = df[df[day].isin(['Off', 'X', 'C'])].index.tolist()
                    st.error(f"📅 **{day}** ({len(off_employees)} orang libur): {', '.join(off_employees)}")
            else:
                st.success(f"✅ Aman! Tidak ada hari yang kekurangan personel jaga.")

            # Summary Kerja & Libur
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

            df_lembur = generate_overtime_recommendations(df, num_days)

            st.subheader("📅 Jadwal Utama")
            st.dataframe(df.style.applymap(color_coding), use_container_width=True)

            st.subheader("💡 Rekomendasi Lembur (Overtime)")
            st.dataframe(df_lembur, use_container_width=True)

            # Ekspor File Excel
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=True, sheet_name='Summary_Schedule')
                df_lembur.to_excel(writer, index=True, sheet_name='Rekomendasi_Lembur')

            st.download_button("⬇️ Download Excel (Jadwal & Lembur)", output.getvalue(), 'jadwal_ultimate_rebuild.xlsx')


# ==========================================
# 2. PROGRAM ANALISIS DATA ATM (OMNIRA-ATMI)
# ==========================================
def aplikasi_analisis_atm():
    st.title("🏦 Dashboard Analisis Transaksi & ATM Tertelan")
    
    if "df_atm" not in st.session_state:
        st.session_state.df_atm = None

    # --- 1. MENU UPLOAD ---
    if st.session_state.df_atm is None:
        st.header("📂 Upload Data")
        st.write("Upload data bulan Januari, Februari, Maret, dst. sekaligus di bawah ini.")
        uploaded_files = st.file_uploader(
            "Upload file CSV/Excel Data Keluhan", type=['csv', 'xlsx'], accept_multiple_files=True
        )

        if uploaded_files:
            all_data = []
            for file in uploaded_files:
                if file.name.endswith('.csv'):
                    df_upload = pd.read_csv(file, skiprows=2)
                else:
                    df_upload = pd.read_excel(file, skiprows=2)
                all_data.append(df_upload)

            st.session_state.df_atm = pd.concat(all_data, ignore_index=True)
            st.rerun()

    # --- 2. DASHBOARD UTAMA ---
    else:
        if st.button("🔄 Upload Data Baru"):
            st.session_state.df_atm = None
            st.rerun()

        st.divider()
        df = st.session_state.df_atm.copy()

        # --- A. PREPROCESSING DATA ---
        # 1. Tanggal & Waktu
        df['Tanggal Transaksi'] = pd.to_datetime(df['Tanggal Transaksi'], format='%d/%m/%Y', errors='coerce')
        df = df.dropna(subset=['Tanggal Transaksi'])
        df['Bulan'] = df['Tanggal Transaksi'].dt.strftime('%Y-%m')
        df['Hari'] = df['Tanggal Transaksi'].dt.day
        df['Periode 5 Harian'] = df['Hari'].apply(categorize_date)
        
        df['Jam_H'] = pd.to_datetime(df['Jam Transaksi'], format='%H:%M:%S', errors='coerce').dt.hour
        def categorize_hour(h):
            if 0 <= h < 6: return "Dini Hari (00-06)"
            elif 6 <= h < 12: return "Pagi (06-12)"
            elif 12 <= h < 18: return "Siang (12-18)"
            else: return "Malam (18-00)"
        df['Waktu Hari'] = df['Jam_H'].apply(categorize_hour)

        # 2. Nominal Uang
        if 'Size' in df.columns:
            df['Size'] = pd.to_numeric(df['Size'], errors='coerce').fillna(0)

        # 3. SLA (Days on stage Solved)
        if 'Days on stage Solved' in df.columns:
            df['SLA_Days'] = df['Days on stage Solved'].str.extract('(\d+)').astype(float).fillna(0)

        # 4. Filter Kategori (DITAMBAHKAN UTLE)
        df['Kategori Laporan'] = 'Lainnya'
        df.loc[df['Jenis Pengaduan'].str.contains('Tarik Tunai', case=False, na=False), 'Kategori Laporan'] = 'Tarik Tunai'
        df.loc[df['Jenis Pengaduan'].str.contains('Tertelan', case=False, na=False), 'Kategori Laporan'] = 'ATM Tertelan'
        df.loc[df['Jenis Pengaduan'].str.contains('UTLE', case=False, na=False), 'Kategori Laporan'] = 'UTLE' # Tangkap UTLE
        
        # Filter hanya Tarik Tunai, ATM Tertelan, dan UTLE
        df_filtered = df[df['Kategori Laporan'].isin(['Tarik Tunai', 'ATM Tertelan', 'UTLE'])]

        # --- B. TAMPILAN TAB ---
        tab1, tab2 = st.tabs(["📊 Analisis Per Bulan", "📈 Management Control Tower (Komparasi & BI)"])

        with tab1:
            st.header("Analisis 5-Harian per Bulan")
            bulan_pilih = st.selectbox("Pilih Bulan:", sorted(df['Bulan'].unique(), reverse=True))
            df_m = df_filtered[df_filtered['Bulan'] == bulan_pilih]

            if not df_m.empty:
                df_g = df_m.groupby(['Periode 5 Harian', 'Kategori Laporan']).size().reset_index(name='Jumlah')
                total_p = df_g.groupby('Periode 5 Harian')['Jumlah'].transform('sum')
                df_g['Persentase'] = (df_g['Jumlah'] / total_p * 100).round(2)

                fig = px.bar(df_g, x='Periode 5 Harian', y='Jumlah', color='Kategori Laporan', text='Persentase', barmode='group',
                             category_orders={"Periode 5 Harian": ["Tgl 1-5", "Tgl 6-10", "Tgl 11-15", "Tgl 16-20", "Tgl 21-25", "Tgl 26-31"]})
                fig.update_traces(texttemplate='<b>%{y}</b><br>(%{text}%)', textposition='outside')
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("Data tidak tersedia untuk bulan ini.")

        with tab2:
            st.header("📈 Analisis Komprehensif Antar Bulan")
            
            # --- 1. TREN KRONOLOGIS ---
            trend_df = df_filtered.groupby(['Bulan', 'Periode 5 Harian', 'Kategori Laporan']).size().reset_index(name='Jumlah')
            p_order = ["Tgl 1-5", "Tgl 6-10", "Tgl 11-15", "Tgl 16-20", "Tgl 21-25", "Tgl 26-31"]
            trend_df['Periode 5 Harian'] = pd.Categorical(trend_df['Periode 5 Harian'], categories=p_order, ordered=True)
            trend_df = trend_df.sort_values(['Bulan', 'Periode 5 Harian'])
            trend_df['Timeline'] = trend_df['Bulan'] + " (" + trend_df['Periode 5 Harian'].astype(str) + ")"

            fig_t = px.line(trend_df, x='Timeline', y='Jumlah', color='Kategori Laporan', markers=True, text='Jumlah', title="Tren Keluhan per 5 Hari")
            fig_t.update_traces(textposition='top center')
            st.plotly_chart(fig_t, use_container_width=True)

            st.divider()

            # --- 2. SUMMARY TOP 5 BANK (VOLUME & NOMINAL) ---
            col_v1, col_v2 = st.columns(2)
            with col_v1:
                st.subheader("🚨 Top 5 Bank: Kasus Tertelan")
                st.dataframe(df_filtered[df_filtered['Kategori Laporan'] == 'ATM Tertelan'].groupby('Bank').size().reset_index(name='Kasus').sort_values('Kasus', ascending=False).head(5), hide_index=True, use_container_width=True)
            with col_v2:
                st.subheader("💸 Top 5 Bank: Kasus Tarik Tunai")
                st.dataframe(df_filtered[df_filtered['Kategori Laporan'] == 'Tarik Tunai'].groupby('Bank').size().reset_index(name='Kasus').sort_values('Kasus', ascending=False).head(5), hide_index=True, use_container_width=True)

            # FINANCIAL IMPACT
            st.subheader("💰 Financial Impact: Total Nominal Sengketa")
            df_fin = df_filtered[df_filtered['Kategori Laporan'] == 'Tarik Tunai'].groupby('Bank')['Size'].sum().reset_index(name='Total (Rp)').sort_values('Total (Rp)', ascending=False)
            fig_f = px.bar(df_fin.head(10), x='Bank', y='Total (Rp)', color='Total (Rp)', color_continuous_scale='Reds', text_auto='.2s')
            st.plotly_chart(fig_f, use_container_width=True)

            st.divider()

            # --- 3. ANALISIS PEAK HOUR & CHANNEL ---
            col_p1, col_p2 = st.columns(2)
            with col_p1:
                st.subheader("🕒 Analisis Jam Sibuk (Peak Hour)")
                hour_df = df_filtered.groupby('Waktu Hari').size().reset_index(name='Jumlah')
                fig_h = px.bar(hour_df, x='Waktu Hari', y='Jumlah', color='Waktu Hari', title="Kapan Nasabah Paling Banyak Komplain?")
                st.plotly_chart(fig_h, use_container_width=True)
            with col_p2:
                st.subheader("📱 Kanal Laporan (Source)")
                src_df = df_filtered.groupby('Source').size().reset_index(name='Jumlah')
                fig_s = px.pie(src_df, values='Jumlah', names='Source', hole=0.4, title="Dari Mana Laporan Masuk?")
                st.plotly_chart(fig_s, use_container_width=True)

            st.divider()

            # --- 4. ANALISIS HASIL & SLA ---
            col_a1, col_a2 = st.columns(2)
            with col_a1:
                st.subheader("✅ Distribusi Hasil Analisis")
                res_df = df_filtered.groupby('Hasil Analis').size().reset_index(name='Jumlah').sort_values('Jumlah', ascending=False).head(8)
                fig_res = px.pie(res_df, values='Jumlah', names='Hasil Analis', title="Hasil Akhir Penanganan Tiket")
                st.plotly_chart(fig_res, use_container_width=True)
            with col_a2:
                st.subheader("⏱️ Performa SLA (Rata-rata Hari Solusi)")
                if 'SLA_Days' in df.columns:
                    sla_df = df_filtered.groupby('Bulan')['SLA_Days'].mean().reset_index(name='Rata-rata Hari')
                    fig_sla = px.line(sla_df, x='Bulan', y='Rata-rata Hari', markers=True, title="Trend Kecepatan Penyelesaian Kasus")
                    st.plotly_chart(fig_sla, use_container_width=True)

            st.divider()

            # --- 5. TOP 10 ATM BERMASALAH (BREAKDOWN PIVOT BULANAN) ---
            st.subheader("📟 Top 10 ID ATM Paling Sering Bermasalah (Breakdown Per Bulan)")
            st.info("Tabel ini membongkar rincian masalah per bulan untuk 10 mesin ATM dengan kasus terbanyak (Tarik Tunai, Tertelan, & UTLE).")
            
            # 1. Cari 10 ATM paling bermasalah secara keseluruhan
            top_atms = df_filtered.groupby(['ID ATM', 'Bank']).size().reset_index(name='Total Keseluruhan')
            top_atms = top_atms.sort_values('Total Keseluruhan', ascending=False).head(10)
            top_atm_ids = top_atms['ID ATM'].tolist()

            # 2. Ambil data mentah hanya untuk ke-10 ATM tersebut
            df_top10 = df_filtered[df_filtered['ID ATM'].isin(top_atm_ids)]

            if not df_top10.empty:
                # 3. Buat Pivot Table dinamis (Baris: ATM, Kolom: Bulan + Kategori, Nilai: Jumlah Kasus)
                pivot_atm = pd.pivot_table(
                    df_top10,
                    index=['ID ATM', 'Bank'],
                    columns=['Bulan', 'Kategori Laporan'],
                    aggfunc='size',
                    fill_value=0
                )
                
                # 4. Merapikan nama kolom (Gabungkan Nama Bulan dan Kategori)
                # Contoh: Kolom '2026-01' dan 'Tarik Tunai' menjadi '2026-01 (Tarik Tunai)'
                pivot_atm.columns = [f"{col[0]} ({col[1]})" for col in pivot_atm.columns]
                pivot_atm = pivot_atm.reset_index()

                # 5. Gabungkan kembali dengan kolom Total Keseluruhan agar bisa diurutkan
                pivot_atm = pivot_atm.merge(top_atms[['ID ATM', 'Total Keseluruhan']], on='ID ATM')
                pivot_atm = pivot_atm.sort_values('Total Keseluruhan', ascending=False)

                # Tampilkan sebagai dataframe agar bisa discroll ke kanan (karena kolomnya akan banyak jika bulannya banyak)
                st.dataframe(pivot_atm, hide_index=True, use_container_width=True)
            else:
                st.warning("Belum ada data masalah ATM yang tercatat.")


# ==========================================
# 3. MENU NAVIGASI UTAMA (SIDEBAR)
# ==========================================
def main():
    st.sidebar.title("🧭 Navigasi Utama")
    st.sidebar.markdown("Silakan pilih aplikasi yang ingin digunakan:")

    pilihan_menu = st.sidebar.radio(
        "Menu:",
        ("🗓️ Jadwal Shift", "🏦 Analisis ATM")
    )

    st.sidebar.divider()
    st.sidebar.info("Aplikasi ini merupakan One-Stop Solution untuk mempermudah operasional harian Anda.")

    if pilihan_menu == "🗓️ Jadwal Shift":
        aplikasi_jadwal_shift()
    elif pilihan_menu == "🏦 Analisis ATM":
        aplikasi_analisis_atm()


if __name__ == "__main__":
    main()
