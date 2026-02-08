import streamlit as st
import pandas as pd
import random
import io

# === 1. KONFIGURASI HALAMAN ===
st.set_page_config(page_title="Shift Scheduler Pro v2", layout="wide")
st.title("Team Shift Scheduler (Detailed Summary)")

# === 2. SIDEBAR INPUT ===
with st.sidebar:
    st.header("Configuration")

    default_team = "Reza\nGandhy\nFarhan\nJubel\nRudi\nRenjes\nKhenda\nKarel\nDwiki\nSyaiful"
    team_input = st.text_area("Team Members", default_team, height=150)

    shift_types = st.multiselect("Shift Types", ["Morning", "Afternoon", "Night"],
                                 default=["Morning", "Afternoon", "Night"])
    num_days = st.slider("Number of Days", min_value=7, max_value=35, value=31)

    st.markdown("---")
    st.subheader("Request Libur & Cuti")
    st.info("Format: Nama, Dari, Sampai, Tipe (X/C)")

    default_req = """Reza, 2, 3, X
Farhan, 1, 2, X
Syaiful, 3, 4, X
Syaiful, 5, 6, C
Gandhy, 17, 18, X
Jubel, 18, 19, X
Rudi, 24, 25, X
Dwiki, 27, 28, X
Khenda, 24, 22, X
Karel, 21, 23, C
Karel, 22, X
Reza, 30, 31, C"""

    request_input = st.text_area("Input Request", default_req, height=200)

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


# === 4. LOGIKA PEMBUATAN JADWAL ===
def generate_schedule_final(members, num_days, requests):
    schedule = {}
    for member in members:
        shifts = []
        regular_off_count = 0
        for i in range(num_days):
            day_in_week = i % 7
            if day_in_week == 0: regular_off_count = 0

            if (member, i) in requests:
                shifts.append(requests[(member, i)])
                continue

            prev_shift = shifts[i - 1] if i > 0 else None
            allowed = shift_types.copy()
            force_off = False

            if prev_shift == "Night":
                force_off = True
            elif prev_shift == "Afternoon" and "Morning" in allowed:
                allowed.remove("Morning")

            days_remaining = 7 - day_in_week
            must_take_off = (2 - regular_off_count) >= days_remaining
            prev_was_req = prev_shift in ['X', 'C']
            can_take_off = True

            if prev_was_req and not force_off: can_take_off = False
            if regular_off_count >= 2 and not force_off: can_take_off = False

            if force_off or must_take_off:
                final_shift = "Off"
            elif can_take_off:
                final_shift = random.choice(allowed + ["Off"])
            else:
                final_shift = random.choice(allowed)

            if final_shift == "Off": regular_off_count += 1
            shifts.append(final_shift)
        schedule[member] = shifts
    return pd.DataFrame(schedule, index=[f"Day {i + 1}" for i in range(num_days)]).T


# === 5. EKSEKUSI & SUMMARY ===
user_requests = parse_requests_flexible(request_input)

if st.button("Generate Schedule"):
    df = generate_schedule_final(team_members, num_days, user_requests)

    # --- PERUBAHAN DI SINI: PEMISAHAN TOTAL ---
    df['Total Cuti (C)'] = (df == 'C').sum(axis=1)
    df['Total Req Libur (X)'] = (df == 'X').sum(axis=1)
    df['Total System Off'] = (df == 'Off').sum(axis=1)
    df['GRAND TOTAL LIBUR'] = df['Total Req Libur (X)'] + df['Total System Off']


    # Pewarnaan
    def color_coding(val):
        if val == 'Off': return 'background-color: #e0e0e0; color: black'
        if val == 'Night': return 'background-color: #2c3e50; color: white'
        if val == 'X': return 'background-color: #e74c3c; color: white'
        if val == 'C': return 'background-color: #f39c12; color: white'
        if val == 'Morning': return 'background-color: #f1c40f; color: black'
        if val == 'Afternoon': return 'background-color: #27ae60; color: white'
        if isinstance(val, (int, float)):
            return 'font-weight: bold; background-color: #f8f9fa; color: black; border-left: 1px solid #ccc'
        return ''


    st.success("Jadwal Berhasil Dibuat!")
    st.dataframe(df.style.applymap(color_coding), use_container_width=True)

    # Download
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=True, sheet_name='Summary_Schedule')

    st.download_button("⬇️ Download Excel (Detailed Summary)", output.getvalue(), 'jadwal_detail.xlsx')