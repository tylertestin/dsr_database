from scripts import DSR_funcs
import matplotlib
matplotlib.use("Agg")

from flask import Flask, render_template, request, url_for, redirect, flash
from datetime import datetime, timedelta
import sqlite3
import pandas as pd
import os, glob
import traceback
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import io
import base64
import re

# import openai
# openai.api_key = "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"

app = Flask(__name__)
app.secret_key = "supersecretkey"

DATABASE = "vehicle_data.db"  # Path to your SQLite file


_IDENTIFIER_CACHE = None


def _quote_identifier(identifier):
    return f'"{identifier.replace("\"", "\"\"")}"'


def _needs_quoting(identifier):
    return bool(re.search(r"[^A-Za-z0-9_]", identifier))


def _get_problematic_identifier_map(conn):
    global _IDENTIFIER_CACHE
    if _IDENTIFIER_CACHE is not None:
        return _IDENTIFIER_CACHE

    column_map = {}
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]

    for table_name in tables:
        if table_name.startswith("sqlite_"):
            continue

        pragma_query = f"PRAGMA table_info({_quote_identifier(table_name)})"
        for column in cursor.execute(pragma_query):
            column_name = column[1]
            if _needs_quoting(column_name):
                column_map[column_name.casefold()] = column_name

    _IDENTIFIER_CACHE = column_map
    return _IDENTIFIER_CACHE


def normalize_sql_query(query_text, conn):
    """Return a version of the query with string-literal identifiers corrected."""

    column_map = _get_problematic_identifier_map(conn)
    if not column_map:
        return query_text, {}

    replacements = {}

    def replace_literal(match):
        literal = match.group(1)
        canonical = column_map.get(literal.casefold())
        if canonical:
            replacements[literal] = canonical
            return f'"{canonical}"'
        return match.group(0)

    normalized_query = re.sub(r"'([^']+)'", replace_literal, query_text)
    return normalized_query, replacements


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def resolve_selected_sites(initial_sites=None, conn=None):
    """Return the list of sites to filter against.

    If the user hasn't selected any sites, fall back to all sites in the
    database. When there are no sites in the database, return an empty list so
    downstream queries can short-circuit gracefully.
    """

    selected = [site for site in (initial_sites or []) if site]
    if selected:
        return selected

    needs_close = False
    if conn is None:
        conn = get_db_connection()
        needs_close = True

    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT site FROM Vehicles ORDER BY site")
    sites = [row[0] for row in cursor.fetchall()]

    if needs_close:
        conn.close()

    return sites


def filter_unprocessed_files(excel_files, cursor):
    """Return files whose modified time differs from what is recorded in ProcessedFiles."""
    unprocessed = []
    skipped_count = 0

    for file_path in excel_files:
        try:
            last_modified = os.path.getmtime(file_path)
        except OSError:
            flash(f"Unable to access file: {os.path.basename(file_path)}")
            continue

        cursor.execute(
            "SELECT last_modified FROM ProcessedFiles WHERE file_path = ?",
            (file_path,),
        )
        row = cursor.fetchone()
        if row and row["last_modified"] == last_modified:
            skipped_count += 1
            continue

        unprocessed.append((file_path, last_modified))

    return unprocessed, skipped_count


# client = openai.OpenAI(api_key=openai.api_key)  # uses OPENAI_API_KEY env variable by default

def generate_sql_with_chatgpt(natural_language_prompt):
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant that writes valid SQLite queries. "
                    "Only return the SQL. Do not include explanations or markdown formatting."
                )
            },
            {
                "role": "user",
                "content": f"Convert this to SQL: {natural_language_prompt}"
            }
        ],
        temperature=0.2,
        max_tokens=200
    )

    return response.choices[0].message.content.strip()

@app.route("/")
def home():
    """
    Renders a simple homepage with a search form for Vehicle ID.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    selected_sites = resolve_selected_sites(request.args.getlist("site"), conn=conn)

    where_clause = ""
    params = []
    if selected_sites:
        placeholders = ", ".join(["?"] * len(selected_sites))
        where_clause = f"WHERE v.site IN ({placeholders})"
        params = selected_sites

    cursor.execute(f"""
        WITH LatestStatus AS (
            SELECT BUNO, [STATUS 1], MAX(report_date) as max_date
            FROM VehicleHistory
            WHERE BUNO IS NOT NULL
            GROUP BY BUNO
        )
        SELECT COALESCE(ls.[STATUS 1], 'Other') as status, COUNT(*) as count
        FROM LatestStatus ls
        JOIN Vehicles v ON ls.BUNO = v.BUNO
        {where_clause}
        GROUP BY COALESCE(ls.[STATUS 1], 'Other')
    """, params)
    data = cursor.fetchall()
    conn.close()

    # Extract data for the chart
    statuses = [row["status"] for row in data]
    counts = [row["count"] for row in data]

    # Desired X-axis order
    desired_order = ["FMC", "DET", "PM", "NMCM", "NMCS", "ACO", "Other"]

    # Reorder statuses and counts
    order_mapping = {status: i for i, status in enumerate(desired_order)}
    sorted_data = sorted(zip(statuses, counts), key=lambda x: order_mapping.get(x[0], float('inf')))
    statuses, counts = zip(*sorted_data)

    # Generate the customized Matplotlib chart
    fig, ax = plt.subplots(figsize=(10, 6), facecolor="none")  # Transparent background
    bars = ax.bar(statuses, counts, color="orange")

     # Set the font for x-axis labels
    ax.set_xticklabels(statuses, fontsize=14, fontname="Trebuchet MS", color="white")

    # Remove y-axis and grid
    ax.yaxis.set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["top"].set_visible(False)
    ax.spines["bottom"].set_color("white")  # Optional: White bottom spine

    # Add bar values on top of the bars
    for bar in bars:
        height = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,  # Center of bar
            height + 0.5,  # Slightly above the bar
            f"{height}",  # Value to display
            ha="center", va="bottom", color="white", fontsize=12, fontname="Trebuchet MS"
        )

    # Transparent background
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")

    # Save the chart as a PNG image
    img = io.BytesIO()
    plt.savefig(img, format="png", bbox_inches="tight", transparent=True)
    img.seek(0)
    chart_url = base64.b64encode(img.getvalue()).decode("utf8")
    plt.close(fig)

    # Render the home page with the chart URL
    return render_template("home.html", chart_url=chart_url, selected_sites=selected_sites)

@app.route("/search", methods=["POST"])
def search():
    """
    Receives the Vehicle ID from the form, queries the database,
    and displays the matching records.
    """
    vehicle_id = request.form.get("vehicle_id")

    selected_sites = resolve_selected_sites(request.args.getlist("site"))

    conn = get_db_connection()
    df = pd.read_sql_query("""
        SELECT 
            vh.BUNO,
            v.site,
            strftime('%Y-%m-%d', vh.report_date) AS report_date,
            vh.[STATUS 1],
            vh.[Status 2],
            vh.[REASON],
            vh.[LAST FLY DATE],
            vh.[NEXT DATE FLOWN],
            COUNT(bp.Part) AS ak0_count,
            GROUP_CONCAT(bp.Description || ' (' || bp.Part || ');  EDD: ' || COALESCE(NULLIF(strftime('%Y-%m-%d', bp.EDD), ''), 'Not Avail.'), '<br><br>') AS ak0_parts
        FROM VehicleHistory vh
        JOIN Vehicles v ON vh.BUNO = v.BUNO
        LEFT JOIN BackorderedParts bp 
            ON vh.BUNO = bp.BUNO 
            AND DATE(vh.report_date) = DATE(bp.report_date)
            AND bp.[Sub Priority] = 'AK0'
        WHERE CAST(vh.BUNO AS TEXT) = ?
        GROUP BY vh.BUNO, vh.report_date, vh.[STATUS 1], vh.[Status 2], vh.[REASON], vh.[LAST FLY DATE], vh.[NEXT DATE FLOWN]
        ORDER BY vh.report_date DESC;
    """, conn, params=[vehicle_id])
    conn.close()

    return render_template("results.html", rows=df.to_dict(orient="records"), vehicle_id=vehicle_id, selected_sites=selected_sites)

@app.route("/search/<vehicle_id>")
def search_id(vehicle_id):
    """
    GET-based route to fetch and display status history for a given vehicle ID.
    Allows direct links like /search/123456
    """
    selected_sites = resolve_selected_sites(request.args.getlist("site"))

    conn = get_db_connection()
    df = pd.read_sql_query("""
        SELECT 
            vh.BUNO,
            v.site,
            strftime('%Y-%m-%d', vh.report_date) AS report_date,
            vh.[STATUS 1],
            vh.[Status 2],
            vh.[REASON],
            vh.[LAST FLY DATE],
            vh.[NEXT DATE FLOWN],
            COUNT(bp.Part) AS ak0_count,
            GROUP_CONCAT(bp.Description || ' (' || bp.Part || ');  EDD: ' || COALESCE(NULLIF(strftime('%Y-%m-%d', bp.EDD), ''), 'Not Avail.'), '<br><br>') AS ak0_parts
        FROM VehicleHistory vh
        JOIN Vehicles v ON vh.BUNO = v.BUNO
        LEFT JOIN BackorderedParts bp 
            ON vh.BUNO = bp.BUNO 
            AND DATE(vh.report_date) = DATE(bp.report_date)
            AND bp.[Sub Priority] = 'AK0'
        WHERE CAST(vh.BUNO AS TEXT) = ?
        GROUP BY vh.BUNO, vh.report_date, vh.[STATUS 1], vh.[Status 2], vh.[REASON], vh.[LAST FLY DATE], vh.[NEXT DATE FLOWN]
        ORDER BY vh.report_date DESC;
    """, conn, params=[vehicle_id])
    conn.close()

    return render_template("results.html", rows=df.to_dict(orient="records"), vehicle_id=vehicle_id, selected_sites=selected_sites)

@app.route("/fleet")
def fleet():
    """
    Displays a table of all vehicles and their most recent status.
    Clicking on the status links to the full status history for that vehicle.
    """
    
    conn = get_db_connection()
    cur = conn.cursor()
    selected_sites = resolve_selected_sites(request.args.getlist("site"), conn=conn)

    rows = []
    if selected_sites:
        placeholders = ", ".join(["?"] * len(selected_sites))
        rows = cur.execute(f"""
        WITH LatestBackorderDate AS (
            SELECT BUNO, MAX(report_date) as max_date
            From BackorderedParts
        ),
        FilteredBackorders AS (
            SELECT bp.BUNO, bp.Description, bp.Part,
                COALESCE(NULLIF(bp.EDD, ''), 'Not Avail.') AS EDD,
                bp.report_date
            FROM BackorderedParts bp
            JOIN LatestBackorderDate lbd 
                ON bp.report_date = lbd.max_date 
            WHERE bp.[Sub Priority] = 'AK0' 
        )
        SELECT vh.BUNO, 
            v.site AS vehicle_site, 
            strftime('%Y-%m-%d', vh.report_date) AS report_date, 
            vh.[STATUS 1],
            COUNT(fb.Part) AS requisition_count,
            COALESCE(NULLIF(strftime('%Y-%m-%d', MAX(fb.EDD)), ''), 'Not Avail.') AS max_edd,
            GROUP_CONCAT(fb.Description || ' (' || fb.Part || ');  EDD: ' || COALESCE(NULLIF(strftime('%Y-%m-%d', fb.EDD), ''), 'Not Avail.'), '<br><br>') AS part_list
        FROM (
            SELECT vh.*
            FROM VehicleHistory vh
            JOIN (
                SELECT BUNO, MAX(report_date) AS max_date
                FROM VehicleHistory
                GROUP BY BUNO
            ) latest ON vh.BUNO = latest.BUNO AND vh.report_date = latest.max_date
        ) vh
        JOIN Vehicles v ON vh.BUNO = v.BUNO
        LEFT JOIN FilteredBackorders fb ON vh.BUNO = fb.BUNO
        WHERE v.site IN ({placeholders})
        GROUP BY vh.BUNO, vehicle_site, vh.report_date, vh.[STATUS 1]
        ORDER BY vh.BUNO;
    """, selected_sites).fetchall()

    conn.close()

    return render_template("fleet.html", rows=rows, selected_sites=selected_sites)

@app.route("/import_data", methods=["POST"])
def import_data():
    selected_sites = resolve_selected_sites(request.args.getlist("site"))
    directory_path = request.form.get("directory_path")
    if not directory_path or not os.path.isdir(directory_path):
        flash("Invalid directory path.")
        return redirect(url_for("home", site=selected_sites))

    # Gather all Excel files in the specified directory
    excel_files = glob.glob(os.path.join(directory_path, "*.xlsx"))
    if not excel_files:
        flash("No Excel files found in the directory.")
        return redirect(url_for("home", site=selected_sites))

    # Let's connect to our DB
    conn = get_db_connection()
    cur = conn.cursor()

    insert_sql = """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_vehicle_date
        ON VehicleHistory(BUNO, report_date);    
    """

    try:
        cur.execute(insert_sql)
    except:
        print("Creating new database")

    imported_count = 0

    for file_path in excel_files:
        # Read the Excel file into a DataFrame
        try:
            # --- A) Extract the date from the first row ---
            top_row = pd.read_excel(file_path, sheet_name="AC Status", header=None, nrows=1)
            report_date = top_row.iat[0,0]
            print(f"Extracted date from DSR: {report_date}")

            # --- B) Read the actual data (skip row #0) ---
            df = pd.read_excel(file_path, sheet_name="AC Status", header=1, usecols="A:R")
            df.columns = [col.strip() if isinstance(col, str) else col for col in df.columns]
            
            # --- C) Add a column for the date ---
            df['report_date'] = report_date

        except Exception as e:
            flash(f"Error reading {os.path.basename(file_path)}: {e}")
            continue  # Skip this file

        # Check that we have 'vehicle_id', 'record_date', 'status'
        required_cols = {"buno", "report_date", "status 1"}
        if not required_cols.issubset(df.columns.str.lower()):
            flash(f"{os.path.basename(file_path)} missing one of required columns: {required_cols}")
            continue

        try:
            df.to_sql("VehicleHistory", conn, if_exists="append", index=False)
        except:
            print("No new files detected")

        changes = conn.total_changes
        imported_count += changes

    conn.commit()
    conn.close()

    flash(f"Import complete. {imported_count} new records were added.")
    return redirect(url_for("home", site=selected_sites))

@app.route("/sharepoint_sync", methods=["POST"])
def sharepoint_sync():
    """
    Imports all Excel files from 3 fixed/hard-coded file paths
    (representing local SharePoint-synced folders).
    Skips duplicates using (vehicle_id, record_date) constraint.
    """
    selected_sites = resolve_selected_sites(request.args.getlist("site"))
    # Hard-coded file paths to SharePoint-synced folders
    sharepoint_paths = [
        r"C:\Users\TestinTyler(USSCA)\Boston Consulting Group, Federal\CNATRAJPPT - Documents\03 - Client data and briefs\DSRS NEW\NASWF DSRS NEW",
        r"C:\Users\TestinTyler(USSCA)\Boston Consulting Group, Federal\CNATRAJPPT - Documents\03 - Client data and briefs\DSRS NEW\NASCC DSRS NEW",
        r"C:\Users\TestinTyler(USSCA)\Boston Consulting Group, Federal\CNATRAJPPT - Documents\03 - Client data and briefs\DSRS NEW\NASP DSRS NEW"
    ]

    # Gather Excel files from each folder
    excel_files = []
    for sp_path in sharepoint_paths:
        if not os.path.isdir(sp_path):
            flash(f"Directory not found: {sp_path}")
            continue

        found = glob.glob(os.path.join(sp_path, "*.xlsx"))
        excel_files.extend(found)

    if not excel_files:
        flash("No Excel files found in any SharePoint paths.")
        return redirect(url_for("home", site=selected_sites))

    conn = get_db_connection()

    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ProcessedFiles (
            file_path TEXT PRIMARY KEY,
            last_modified REAL NOT NULL
        );
        """
    )

    total_changes_before = conn.total_changes

    skipped_files = 0

    unprocessed_files, skipped = filter_unprocessed_files(excel_files, cursor)
    skipped_files += skipped

    for file_path, last_modified in unprocessed_files:
        # Read the Excel file
        try:
            # --- A) Extract the date from the first row ---
            top_row = pd.read_excel(file_path, sheet_name="AC Status", header=None, nrows=1)
            report_date = top_row.iat[0,0]

            # --- B) Read the actual data (skip row #0) ---
            df = pd.read_excel(file_path, sheet_name="AC Status", header=1, usecols="A:R")
            df.columns = [col.strip() if isinstance(col, str) else col for col in df.columns]
            
            # --- C) Add a column for the date ---
            df['report_date'] = report_date

        except Exception as e:
            flash(f"Error reading {os.path.basename(file_path)}: {e}")
            continue  # Skip this file

        # Check that we have 'vehicle_id', 'record_date', 'status'
        required_cols = {"buno", "report_date", "status 1"}
        if not required_cols.issubset(df.columns.str.lower()):
            flash(f"{os.path.basename(file_path)} missing one of required columns: {required_cols}")
            continue

        try:
            df.to_sql("VehicleHistory", conn, if_exists="append", index=False)
        except Exception:
            continue

        cursor.execute(
            """
            INSERT INTO ProcessedFiles (file_path, last_modified)
            VALUES (?, ?)
            ON CONFLICT(file_path) DO UPDATE SET last_modified = excluded.last_modified
            """,
            (file_path, last_modified),
        )


    # Hard-coded file paths to SharePoint-synced folders
    sharepoint_paths = [
        r"C:\Users\TestinTyler(USSCA)\Boston Consulting Group, Federal\CNATRAJPPT - Documents\03 - Client data and briefs\A018",
    ]

    # Gather Excel files from each folder
    excel_files = []
    for sp_path in sharepoint_paths:
        if not os.path.isdir(sp_path):
            flash(f"Directory not found: {sp_path}")
            continue

        found = glob.glob(os.path.join(sp_path, "*.xlsx"))
        excel_files.extend(found)

    if not excel_files:
        flash("No Excel files found in any SharePoint paths.")
        return redirect(url_for("home"))
    
    unprocessed_files, skipped = filter_unprocessed_files(excel_files, cursor)
    skipped_files += skipped

    for file_path, last_modified in unprocessed_files:
        # Read the Excel file
        try:
            # --- A) Extract the date from the file name ---
            raw_text = os.path.basename(file_path)

            # Use regex to extract a date from the text
            match = re.search(r"(\d{1}-\d{1}-\d{4}|\d{1}-\d{2}-\d{4}|\d{2}-\d{1}-\d{4}|\d{2}-\d{2}-\d{4})", raw_text)

            if match:
                extracted_date = match.group(0)  # Extract matched date string
                report_date = pd.to_datetime(extracted_date, errors="coerce").strftime("%Y-%m-%d")  # Convert to standard format
            else:
                flash(f"Could not extract a valid date from the file: {os.path.basename(file_path)}")
                report_date = "1/1/1900"

            existing_count = 0
            try:
                cursor.execute("SELECT COUNT(*) FROM BackorderedParts WHERE report_date = ?", (report_date,))
                existing_count = cursor.fetchone()[0]
            except:
                print("Query Failed")

            if existing_count > 0:
                continue

            # --- B) Read the actual data (skip row #0) ---
            df = pd.read_excel(file_path, sheet_name="Outstanding Requisitions", header=0)
            df.columns = [col.strip() if isinstance(col, str) else col for col in df.columns]

            if "Vendor / Transfer From" not in df.columns:
                df["Vendor / Transfer From"] = None
            
            # --- C) Add a column for the date ---
            df['report_date'] = report_date
            df.rename(columns={"Tail No/Buno" : "BUNO"}, inplace=True)
            df.rename(columns={"Part Number" : "Part"}, inplace=True)
            df.fillna({"EDD": "No EDD"}, inplace=True)

        except Exception as e:
            flash(f"Error reading {os.path.basename(file_path)}: {e}")
            continue  # Skip this file

        try:
            df.to_sql("BackorderedParts", conn, if_exists="append", index=False)
        except Exception:
            continue

        cursor.execute(
            """
            INSERT INTO ProcessedFiles (file_path, last_modified)
            VALUES (?, ?)
            ON CONFLICT(file_path) DO UPDATE SET last_modified = excluded.last_modified
            """,
            (file_path, last_modified),
        )

    total_changes_after = conn.total_changes
    imported_count = total_changes_after - total_changes_before

    site_mapping_file = "20250203_AC_Sites.xlsx"

    # Load the Excel file
    try:
        df = pd.read_excel(site_mapping_file)
    except Exception as e:
        flash(f"Error reading site mapping file: {e}")
        return redirect(url_for("home"))

    # Ensure correct column names
    required_columns = {"BUNO", "site"}
    if not required_columns.issubset(df.columns):
        flash("Excel file is missing required columns: 'vehicle_id' and 'site'.")
        return redirect(url_for("home"))

    insert_sql = """
        CREATE TABLE IF NOT EXISTS Vehicles (
            BUNO TEXT PRIMARY KEY,
            site TEXT NOT NULL
        );   
    """

    cursor.execute(insert_sql)

    insert_sql = """
        CREATE TABLE IF NOT EXISTS VehicleHistory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            BUNO TEXT NOT NULL,
            [STATUS 1] TEXT NOT NULL,
            report_date DATE NOT NULL,
            [NEXT DATE FLOWN] DATE,
            [LAST FLY DATE] DATE,
            FOREIGN KEY (BUNO) REFERENCES Vehicles(BUNO)
        );
    """

    cursor.execute(insert_sql)

    # Insert or update vehicle site information
    for _, row in df.iterrows():
        vehicle_id = str(row["BUNO"]).strip()
        site = str(row["site"]).strip()

        cursor.execute("""
            INSERT INTO Vehicles (BUNO, site) 
            VALUES (?, ?) 
            ON CONFLICT(buno) DO UPDATE SET site = excluded.site
        """, (vehicle_id, site))

    conn.commit()
    conn.close()

    flash(
        f"SharePoint Sync complete. {imported_count} new records were added. "
        f"Skipped {skipped_files} previously imported files."
    )

    return redirect(url_for("home", site=selected_sites))

@app.route("/pm_summary")
def pm_summary():
    conn = get_db_connection()
    selected_sites = resolve_selected_sites(request.args.getlist("site"), conn=conn)

    placeholders = ""
    where_clause = ""
    params = []
    if selected_sites:
        placeholders = ", ".join(["?"] * len(selected_sites))
        where_clause = f"WHERE v.site IN ({placeholders})"
        params = selected_sites

    df = pd.read_sql_query(
        f"""
            SELECT vh.BUNO, v.site, vh.[STATUS 1], vh.report_date, vh.[NEXT DATE FLOWN], vh.[LAST FLY DATE]
            FROM VehicleHistory vh
            JOIN Vehicles v ON vh.BUNO = v.BUNO
            {where_clause}
            ORDER BY vh.BUNO, vh.report_date
        """,
        conn,
        params=params or None,
    )

    # Ensure proper data types
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
    df["NEXT DATE FLOWN"] = pd.to_datetime(df["NEXT DATE FLOWN"], errors="coerce")
    df["LAST FLY DATE"] = pd.to_datetime(df["LAST FLY DATE"], errors="coerce")

    # Initialize a list to store the summary
    summary = []
    today = pd.Timestamp.today().normalize()

    for vehicle_id, group in df.groupby("BUNO"):
        if group.empty:
            continue  # Skip this vehicle if no data exists
        
        group = group.sort_values(by="report_date", ascending=False)  # Sort by descending dates

        consecutive_dsrs_pm = 0
        for i, row in group.iterrows():
            if row["STATUS 1"] == "PM":
                consecutive_dsrs_pm += 1
            else:
                # If a non-"PM" status is encountered, break the streak
                break

        # Only include vehicles currently in "PM" status
        if group.iloc[0]["STATUS 1"] == "PM":
            # Calculate days to next fly date and days since last fly date
            next_fly_date = group.iloc[0]["NEXT DATE FLOWN"]
            last_fly_date = group.iloc[0]["LAST FLY DATE"]
            if consecutive_dsrs_pm < len(group):
                first_pm_date = group.iloc[consecutive_dsrs_pm]["report_date"]
            else:
                first_pm_date = group.iloc[-1]["report_date"]
            days_to_next_fly = (next_fly_date - today).days if pd.notnull(next_fly_date) else "N/A"
            days_since_last_fly = (today - last_fly_date).days if pd.notnull(last_fly_date) else "N/A"
            consecutive_days_pm = (today - first_pm_date).days if pd.notnull(first_pm_date) else "N/A"
            try:
                non_pm_days = days_since_last_fly-consecutive_days_pm
            except:
                non_pm_days = "N/A"

            # Append the summary information
            summary.append({
                "BUNO": vehicle_id,
                "Site": group.iloc[0]["site"],
                "next_fly_date": next_fly_date.strftime("%Y-%m-%d") if pd.notnull(next_fly_date) else "N/A",
                "days_to_next_fly": days_to_next_fly,
                "last_fly_date": last_fly_date.strftime("%Y-%m-%d") if pd.notnull(last_fly_date) else "N/A",
                "days_since_last_fly": days_since_last_fly,
                "consecutive_days_pm": consecutive_days_pm,
                "non_pm_days" : non_pm_days
            })

    # Render the table
    return render_template("pm_summary.html", pm_summary=summary, selected_sites=selected_sites)


@app.route("/p2p")
def p2p():
    selected_sites = resolve_selected_sites(request.args.getlist("site"))

    conn = get_db_connection()
    where_clause = ""
    params = []
    if selected_sites:
        placeholders = ", ".join(["?"] * len(selected_sites))
        where_clause = f"AND v.site IN ({placeholders})"
        params = selected_sites

    df = pd.read_sql_query(
        f"""
        SELECT vh.report_date, vh.[STATUS 1], vh.[STATUS 2]
        FROM VehicleHistory vh
        JOIN Vehicles v ON vh.BUNO = v.BUNO
        WHERE vh.[STATUS 1] IN ('FMC', 'DET')
          AND vh.[STATUS 2] IN ('UP', 'DET')
          {where_clause}
    """,
        conn,
        params=params or None,
    )
    conn.close()

    # Convert report_date to datetime
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
    df.dropna(subset=["report_date"], inplace=True)

    daily_counts = df.groupby(df["report_date"].dt.date).size().rename("count").reset_index()
    daily_counts.rename(columns={"report_date": "date"}, inplace=True)
    daily_counts["date"] = pd.to_datetime(daily_counts["date"])

    # Calculate 14-day rolling average from actual data (no 0 padding)
    daily_counts = daily_counts.sort_values("date")
    daily_counts["rolling_avg"] = daily_counts["count"].rolling(window=10).mean()

    # Generate plot
    fig, ax = plt.subplots(figsize=(10, 5), facecolor="#1e1e1e")
    fig.patch.set_facecolor("#1e1e1e")

    # Plot rolling average line
    ax.plot(
        daily_counts["date"], 
        daily_counts["rolling_avg"], 
        color="#00d1b2",  # Accent teal/cyan
        linewidth=2,
        label="2-week rolling avg"
    )

    # Titles and labels
    ax.set_ylabel("RFT", color="white", fontsize=12)

    # Tick styling
    ax.tick_params(axis='x', colors='white', labelrotation=45)
    ax.tick_params(axis='y', colors='white')

    # Date formatting (optional: monthly ticks or daily with rotation)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())

    # Grid styling
    ax.grid(True, which='major', linestyle='--', linewidth=0.5, color="#444444")

    # Background and spine cleanup
    ax.set_facecolor("#1e1e1e")
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Legend
    ax.legend(loc="upper left", facecolor="#1e1e1e", edgecolor="none", labelcolor='white')

    plt.tight_layout()

    # Save plot to base64
    img = io.BytesIO()
    plt.savefig(img, format="png")
    img.seek(0)
    plot_url = base64.b64encode(img.getvalue()).decode("utf8")
    plt.close()

    return render_template("p2p.html", plot_url=plot_url, selected_sites=selected_sites)


@app.route("/wf_p2p")
def wf_p2p():
    initial_sites = request.args.getlist("site")
    if not initial_sites:
        initial_sites = ["NASWF"]

    selected_sites = resolve_selected_sites(initial_sites)

    conn = get_db_connection()
    where_clause = ""
    params = []
    if selected_sites:
        placeholders = ", ".join(["?"] * len(selected_sites))
        where_clause = f"AND v.site IN ({placeholders})"
        params = selected_sites

    df = pd.read_sql_query(
        f"""
        SELECT vh.report_date
        FROM VehicleHistory vh
        JOIN Vehicles v ON vh.BUNO = v.BUNO
        WHERE vh.[STATUS 1] IN ('FMC', 'DET')
          AND vh.[Status 2] IN ('UP', 'DET')
          {where_clause}
    """,
        conn,
        params=params or None,
    )
    conn.close()

    # Convert report_date to datetime
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
    df.dropna(subset=["report_date"], inplace=True)

    daily_counts = df.groupby(df["report_date"].dt.date).size().rename("count").reset_index()
    daily_counts.rename(columns={"report_date": "date"}, inplace=True)
    daily_counts["date"] = pd.to_datetime(daily_counts["date"])

    # Calculate 14-day rolling average from actual data (no 0 padding)
    daily_counts = daily_counts.sort_values("date")
    daily_counts["rolling_avg"] = daily_counts["count"].rolling(window=10).mean()

    # Generate plot
    fig, ax = plt.subplots(figsize=(10, 5), facecolor="#1e1e1e")
    fig.patch.set_facecolor("#1e1e1e")

    # Plot rolling average line
    ax.plot(
        daily_counts["date"], 
        daily_counts["rolling_avg"], 
        color="#00d1b2",  # Accent teal/cyan
        linewidth=2,
        label="2-week rolling avg"
    )

    # Titles and labels
    ax.set_ylabel("RFT", color="white", fontsize=12)

    # Tick styling
    ax.tick_params(axis='x', colors='white', labelrotation=45)
    ax.tick_params(axis='y', colors='white')

    # Date formatting (optional: monthly ticks or daily with rotation)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())

    # Grid styling
    ax.grid(True, which='major', linestyle='--', linewidth=0.5, color="#444444")

    # Background and spine cleanup
    ax.set_facecolor("#1e1e1e")
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Legend
    ax.legend(loc="upper left", facecolor="#1e1e1e", edgecolor="none", labelcolor='white')

    plt.tight_layout()

    # Save plot to base64
    img = io.BytesIO()
    plt.savefig(img, format="png")
    img.seek(0)
    plot_url = base64.b64encode(img.getvalue()).decode("utf8")
    plt.close()

    return render_template("wf_p2p.html", plot_url=plot_url, selected_sites=selected_sites)

@app.route("/single_hits", methods=["GET"])
def single_hits():
    selected_date = request.args.get("date")
    if not selected_date:
        selected_date = datetime.today().strftime("%Y-%m-%d")

    selected_sites = resolve_selected_sites(request.args.getlist("site"))

    conn = get_db_connection()
    site_clause = ""
    params = [selected_date, selected_date]
    if selected_sites:
        placeholders = ", ".join(["?"] * len(selected_sites))
        site_clause = f"WHERE v.site IN ({placeholders})"
        params.extend(selected_sites)

    df = pd.read_sql_query(
        f"""
        WITH OneAK0Bunos AS (
            SELECT BUNO
            FROM BackorderedParts
            WHERE [Sub Priority] = 'AK0'
              AND DATE(report_date) = DATE(?)
            GROUP BY BUNO
            HAVING COUNT(*) = 1
        ),
        LatestHistory AS (
            SELECT vh.*
            FROM VehicleHistory vh
            JOIN (
                SELECT BUNO, MAX(report_date) AS max_date
                FROM VehicleHistory
                GROUP BY BUNO
            ) latest ON vh.BUNO = latest.BUNO AND vh.report_date = latest.max_date
        )
        SELECT 
            vh.BUNO,
            v.site,
            strftime('%Y-%m-%d', vh.report_date) AS report_date,
            vh.[STATUS 1],
            vh.[STATUS 2],
            vh.[LAST FLY DATE],
            vh.[NEXT DATE FLOWN],
            bp.Description || ' (' || bp.Part || ')' AS ak0_part,
            COALESCE(NULLIF(strftime('%Y-%m-%d', bp.EDD), ''), 'Not Avail.') AS ak0_edd
        FROM LatestHistory vh
        JOIN Vehicles v ON vh.BUNO = v.BUNO
        JOIN OneAK0Bunos a ON vh.BUNO = a.BUNO
        LEFT JOIN BackorderedParts bp
            ON bp.BUNO = vh.BUNO
            AND bp.[Sub Priority] = 'AK0'
            AND DATE(bp.report_date) = DATE(?)
        {site_clause}
        ORDER BY vh.BUNO
    """,
        conn,
        params=params,
    )
    conn.close()

    # Group parts for tooltip (one row per BUNO)
    grouped = df.groupby("BUNO").agg({
        "site": "first",
        "report_date": "first",
        "STATUS 1": "first",
        "STATUS 2": "first",
        "LAST FLY DATE": "first",
        "NEXT DATE FLOWN": "first",
        "ak0_part": lambda x: "<br><br>".join(x.dropna()),
        "ak0_edd": lambda x: "<br><br>".join(x.dropna())
    }).reset_index()

    # Combine part & EDD
    grouped["tooltip"] = grouped.apply(
        lambda row: f"{row['ak0_part']}; EDD: {row['ak0_edd']}" if row["ak0_part"] else "N/A", axis=1
    )

    return render_template(
        "single_hits.html",
        data=grouped.to_dict(orient="records"),
        selected_date=selected_date,
        selected_sites=selected_sites,
    )

@app.route("/quad")
def quad():
    selected_sites = resolve_selected_sites(request.args.getlist("site"))
    conn = get_db_connection()

    placeholders = ""
    site_where = ""
    site_and = ""
    params = []
    if selected_sites:
        placeholders = ", ".join(["?"] * len(selected_sites))
        site_where = f"WHERE v.site IN ({placeholders})"
        site_and = f"AND v.site IN ({placeholders})"
        params = selected_sites

    # Quadrant 1
    q1 = pd.read_sql_query(
        f"""
        WITH OrderedHistory AS (
            SELECT
                vh.BUNO,
                vh.report_date,
                vh.[STATUS 1],
                LAG(vh.[STATUS 1]) OVER (PARTITION BY vh.BUNO ORDER BY vh.report_date DESC) AS prev_status
            FROM VehicleHistory vh
            JOIN Vehicles v ON vh.BUNO = v.BUNO
            {site_where}
        )
        SELECT
            BUNO,
            strftime('%Y-%m-%d', report_date) AS report_date,
            [STATUS 1],
            prev_status
        FROM OrderedHistory
        WHERE [STATUS 1] = 'FMC'
          AND (prev_status IS NOT NULL AND prev_status <> 'FMC')
        ORDER BY report_date DESC;
    """,
        conn,
        params=params or None,
    )

    # Quadrant 2
    q2 = pd.read_sql_query(
        f"""
        WITH LatestHistory AS (
            SELECT vh.*
            FROM VehicleHistory vh
            JOIN (
                SELECT MAX(report_date) AS max_date
                FROM VehicleHistory
            ) latest ON vh.report_date = latest.max_date
            JOIN Vehicles v ON vh.BUNO = v.BUNO
            {site_where}
        )
        SELECT
            BUNO,
            strftime('%Y-%m-%d', report_date) AS report_date,
            strftime('%Y-%m-%d', [NEXT DATE FLOWN]) AS NFD
        FROM LatestHistory
        WHERE [NEXT DATE FLOWN] IS NOT NULL AND strftime('%Y-%m-%d', [NEXT DATE FLOWN]) = strftime('%Y-%m-%d', report_date)
        ORDER BY report_date DESC;
    """,
        conn,
        params=params or None,
    )

    # Quadrant 3
    q3 = pd.read_sql_query(
        f"""
        WITH OrderedParts AS (
            SELECT
                bp.BUNO,
                bp.Part,
                bp.Description,
                bp.EDD,
                bp.report_date,
                LAG(bp.EDD) OVER (PARTITION BY bp.BUNO, bp.Part ORDER BY bp.report_date DESC) AS prev_edd
            FROM BackorderedParts bp
            JOIN Vehicles v ON bp.BUNO = v.BUNO
            WHERE bp.[Sub Priority] = 'AK0'
            {site_and}
        )
        SELECT
            BUNO,
            Part,
            Description,
            strftime('%Y-%m-%d', COALESCE(NULLIF(EDD, ''), 'Not Avail.')) AS EDD,
            strftime('%Y-%m-%d', report_date) AS report_date,
            strftime('%Y-%m-%d', prev_edd) AS prev_edd
        FROM OrderedParts
        WHERE prev_edd IS NOT NULL
          AND EDD <> prev_edd
        ORDER BY report_date DESC;
    """,
        conn,
        params=params or None,
    )

    # Quadrant 4
    q4 = pd.read_sql_query(
        f"""
        WITH LatestBackorderDate AS (
            SELECT MAX(report_date) AS max_date
            FROM BackorderedParts
        ),
        LatestBackorderedParts AS (
            SELECT bp.*
            FROM BackorderedParts bp
            JOIN LatestBackorderDate lbd ON bp.report_date = lbd.max_date
            JOIN Vehicles v ON bp.BUNO = v.BUNO
            WHERE bp.[Sub Priority] = 'AK0'
            {site_and}
        )
        SELECT
            BUNO,
            Part,
            Description,
            strftime('%Y-%m-%d',COALESCE(NULLIF(EDD, ''), 'Not Avail.')) AS EDD,
            strftime('%Y-%m-%d', report_date) AS report_date
        FROM LatestBackorderedParts
        ORDER BY BUNO;
    """,
        conn,
        params=params or None,
    )
    
    conn.close()
    
    # Convert to dictionary lists for template rendering
    quad1 = q1.to_dict(orient="records")
    quad2 = q2.to_dict(orient="records")
    quad3 = q3.to_dict(orient="records")
    quad4 = q4.to_dict(orient="records")
    
    return render_template(
        "quad.html",
        quad1=quad1,
        quad2=quad2,
        quad3=quad3,
        quad4=quad4,
        selected_sites=selected_sites,
    )

@app.route("/sql_search", methods=["GET", "POST"])
def custom_sql():
    results = []
    columns = []
    query_text = ""
    error = None
    debug_details = None
    conn = None

    if request.method == "POST":
        query_text = request.form.get("sql_query", "").strip()
        if query_text:
            original_query = query_text
            normalization_details = {}
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                normalized_query, identifier_corrections = normalize_sql_query(query_text, conn)
                query_to_execute = normalized_query

                if identifier_corrections:
                    normalization_details["identifier_corrections"] = identifier_corrections
                if normalized_query != query_text:
                    normalization_details["normalized_query"] = normalized_query

                cursor.execute(query_to_execute)

                if query_to_execute.lstrip().lower().startswith("select"):
                    columns = [desc[0] for desc in cursor.description]
                    results = cursor.fetchall()
                    debug_details = dict(normalization_details)
                    debug_details["returned_rows"] = len(results)
                else:
                    conn.commit()
                    debug_details = dict(normalization_details)
                    debug_details["rowcount"] = cursor.rowcount
                    lastrowid = getattr(cursor, "lastrowid", None)
                    if lastrowid:
                        debug_details["lastrowid"] = lastrowid

                if "normalized_query" in normalization_details:
                    query_text = normalization_details["normalized_query"]
                debug_details = debug_details or None
            except Exception as e:
                error = {
                    "type": e.__class__.__name__,
                    "message": str(e),
                    "query": original_query,
                }
                if normalization_details.get("normalized_query"):
                    error["normalized_query"] = normalization_details["normalized_query"]
                debug_details = {
                    "traceback": traceback.format_exc(),
                    **normalization_details,
                }
            finally:
                if conn is not None:
                    conn.close()

    selected_sites = resolve_selected_sites(request.args.getlist("site"))

    return render_template(
        "custom_sql.html",
        query_text=query_text,
        results=results,
        columns=columns,
        error=error,
        debug_details=debug_details,
        selected_sites=selected_sites,
    )

if __name__ == "__main__":
    # For local dev usage
    app.run(debug=True)
