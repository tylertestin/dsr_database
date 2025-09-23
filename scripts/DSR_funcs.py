from datetime import datetime, timedelta
import pandas as pd
import os
import glob

import sqlite3

def calculate_status_start(data):
    # Ensure the data is sorted by vehicle_id and record_date
    data = data.sort_values(by=["BUNO", "report_date"])

    # Prepare the result list
    results = []

    # Iterate through each vehicle's data
    for vehicle_id, group in data.groupby("BUNO"):
        current_status = None
        current_streak_start = None
        previous_date = None

        for _, row in group.iterrows():
            record_date = datetime.strptime(row["report_date"].split()[0], "%Y-%m-%d")
            status = row["STATUS 1"]

            # Handle gaps: fill in missing days
            if previous_date and (record_date - previous_date).days > 1:
                gap_days = (record_date - previous_date).days - 1
                for _ in range(gap_days):
                    previous_date += timedelta(days=1)
                    if current_status == "PM":
                        continue  # Assume "PM" continues during gaps
            # Check status changes
            if status == "PM":
                if current_status != "PM":
                    current_streak_start = record_date  # Start a new streak
            else:
                current_streak_start = None  # Reset streak for non-PM status

            # Store the result
            results.append({
                "BUNO": vehicle_id,
                "report_date": row["report_date"],
                "STATUS 1": status,
                "streak_start": current_streak_start.strftime("%Y-%m-%d") if current_streak_start else None,
            })

            # Update tracking variables
            current_status = status
            previous_date = record_date

    return pd.DataFrame(results)                    

def import_excel_to_db(file_path, db_path="vehicle_data.db"):
    """
    Reads a single Excel file, extracts the date from row #0, 
    skips that row for actual data, then inserts into the database.
    """
    # --- A) Extract the date from the first row ---
    top_row = pd.read_excel(file_path, sheet_name="AC Status", header=None, nrows=1)
    report_date = top_row.iat[0,0]
    print(f"Extracted date from top row: {report_date}")

    # --- B) Read the actual data (skip row #0) ---
    df = pd.read_excel(file_path, sheet_name="AC Status", header=1, usecols="A:R")
    
    # --- C) Add a column for the date ---
    df['report_date'] = report_date

    # --- D) Insert into the database ---
    conn = sqlite3.connect(db_path)
    df.to_sql("VehicleHistory", conn, if_exists="append", index=False)
    conn.close()

    print(f"Inserted {len(df)} records from {os.path.basename(file_path)} into the database.")

def get_vehicle_status_history(db_path, vehicle_id):
    # Connect to the SQLite database
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Prepare the query
    query = """
    SELECT report_date, [STATUS 1]
    FROM VehicleHistory
    WHERE BUNO = ?
    ORDER BY report_date;
    """

    # Execute with the given vehicle_id as a parameter
    cur.execute(query, (vehicle_id,))

    # Fetch all matching records
    rows = cur.fetchall()

    # Close the DB connection
    conn.close()

    return rows

def main():

    excel_folder = r"c:\Users\TestinTyler(USSCA)\OneDrive - Boston Consulting Group, Federal\Desktop\AC_Status\data"  # DSRs
    excel_files = glob.glob(os.path.join(excel_folder, "*.xlsx"))

    print("Found Excel files:", excel_files)

    # Path to your database file (will be created if it doesn’t exist)
    db_path = r"c:\Users\TestinTyler(USSCA)\OneDrive - Boston Consulting Group, Federal\Desktop\AC_Status\vehicle_data.db"

    # 1. Remove the old database file
    if os.path.exists(db_path):
        os.remove(db_path)
        print("Old database removed.")

    if not excel_files:
        print("No Excel files found. Exiting.")
        return

    # Process each file
    for file_path in excel_files:
        import_excel_to_db(file_path, db_path=db_path)

    # For demo, let's pick an example 6-digit ID
    vehicle_id = "166243"  # Adjust to your actual ID

    status_history = get_vehicle_status_history(db_path, vehicle_id)

    if status_history:
        print(f"Date and Status for Vehicle ID {vehicle_id}:")
        for date_val, status_val in status_history:
            print(f"  {date_val}  |  {status_val}")
    else:
        print(f"No records found for Vehicle ID {vehicle_id}.")


if __name__ == "__main__":
    main()
