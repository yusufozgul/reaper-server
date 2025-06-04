import json
import logging
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime
import secrets
from flask import Flask, flash, g, jsonify, render_template, request, redirect, url_for

import reaper

logging.basicConfig(
  level=logging.INFO,
  format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
  handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("reaper")

app = Flask(__name__)
app.secret_key = secrets.token_hex()


def get_db():
  db = getattr(g, "_database", None)
  if db is None:
    db = g._database = sqlite3.connect("data.db")
    db.row_factory = sqlite3.Row
    init_db(db)
  return db


@app.teardown_appcontext
def close_connection(exception):
  db = getattr(g, "_database", None)
  if db is not None:
    db.close()


def init_db(conn):
  cursor = conn.cursor()

  cursor.execute("""
    CREATE TABLE IF NOT EXISTS report (
        report_id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_id TEXT NOT NULL,
        version TEXT NOT NULL,
        platform TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        metadata TEXT
    )
    """)

  cursor.execute("""
    CREATE TABLE IF NOT EXISTS observation (
        observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id INTEGER NOT NULL,
        token TEXT NOT NULL,
        FOREIGN KEY (report_id) REFERENCES report (report_id)
    )
    """)

  cursor.execute("""
    CREATE TABLE IF NOT EXISTS known (
        known_id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_id TEXT,
        version TEXT,
        platform TEXT,
        name TEXT NOT NULL,
        token TEXT NOT NULL
    )
    """)

  conn.commit()


@app.route("/")
def home():
  return render_template("index.html")


@app.route("/about")
def about():
  return render_template("about.html")


@app.route("/report", methods=["POST"])
def receive_report():
  """
  Endpoint to receive reports from Reaper iOS and Android SDK.

  Expected payload format:
  {
    "apiKey": "mykey",
    "seen": ["RvP1/Jw16IY=", ...],
    "platform": "android",
    "metadata": {
      "manufacturer": "Google",
      "model": "sdk_gphone64_arm64",
      "osVersion": "13",
      "reaperVersion": "1.0.2-SNAPSHOT"
    },
    "appId": "com.emergetools.hackernews",
    "shortVersionString": "1.0.2"
  }
  """
  data = request.get_json()

  if not data:
    return jsonify({"error": "No JSON data provided"}), 400

  app_id = data.get("appId")
  version = data.get("shortVersionString")
  platform = data.get("platform")
  seen = data.get("seen", [])
  metadata = data.get("metadata", {})

  db = get_db()
  cursor = db.cursor()

  timestamp = datetime.now().isoformat()
  metadata_json = json.dumps(metadata)

  cursor.execute(
    "INSERT INTO report (app_id, version, platform, timestamp, metadata) VALUES (?, ?, ?, ?, ?)",
    (app_id, version, platform, timestamp, metadata_json),
  )

  report_id = cursor.lastrowid

  for key in seen:
    cursor.execute("INSERT INTO observation (report_id, token) VALUES (?, ?)", (report_id, key))

  db.commit()

  logger.info(
    f"Received report for {app_id} v{version} on {platform} containing {len(seen)} observations"
  )
  return jsonify({"status": "success", "message": "Report received"}), 200


@app.route("/reaper/error", methods=["POST"])
def log_error():
  """Endpoint to receive error reports from Reaper SDK."""
  data = request.get_json()
  if not data:
    return jsonify({"error": "No JSON data provided"}), 400
  error = json.dumps(data)
  logger.error(f"Received error report from {error}")
  return jsonify({"error": error}), 200


@app.route("/analyze", methods=["GET"])
def analyze():
  """Simple page to view analysis of reports."""
  tab = request.args.get("tab", "summary")

  match tab:
    case "summary":
      return analyze_summary()
    case "reports":
      return analyze_reports()
    case "apps":
      return analyze_apps()
    case "dead":
      return analyze_dead()
    case _:
      return analyze_summary()


def analyze_summary():
  db = get_db()
  cursor = db.cursor()

  cursor.execute("SELECT COUNT(*) FROM report")
  total_reports = cursor.fetchone()[0]

  # Get app details with additional information
  cursor.execute("""
    SELECT
      r.app_id,
      COUNT(DISTINCT r.report_id) as report_count,
      MAX(r.version) as latest_version,
      COUNT(DISTINCT o.token) as reported_class_count,
      (SELECT COUNT(DISTINCT k.token) FROM known k WHERE k.app_id = r.app_id) as known_class_count
    FROM report r
    LEFT JOIN observation o ON r.report_id = o.report_id
    GROUP BY r.app_id
    ORDER BY report_count DESC
  """)

  app_details = []
  for row in cursor.fetchall():
    app_details.append(
      {
        "app_id": row[0],
        "report_count": row[1],
        "latest_version": row[2] or "Unknown",
        "reported_class_count": row[3],
        "known_class_count": row[4] or 0,
      }
    )

  unique_apps = [app["app_id"] for app in app_details]

  cursor.execute("SELECT DISTINCT token FROM observation")
  unique_observations = [row[0] for row in cursor.fetchall()]

  cursor.execute("SELECT COUNT(*) FROM known")
  total_known = cursor.fetchone()[0]

  cursor.execute("SELECT COUNT(DISTINCT token) FROM known")
  unique_known = cursor.fetchone()[0]

  cursor.execute("""
    SELECT COUNT(DISTINCT k.token) FROM known k
    LEFT OUTER JOIN observation o
    ON k.token = o.token
    WHERE o.token IS NULL;
  """)
  unique_dead = cursor.fetchone()[0]

  stats = {
    "total_reports": total_reports,
    "unique_apps": unique_apps,
    "unique_app_count": len(unique_apps),
    "unique_observations": len(unique_observations),
    "total_known": total_known,
    "unique_known": unique_known,
    "unique_dead": unique_dead,
  }

  return render_template("analyze_summary.html", stats=stats)

def analyze_reports():
  db = get_db()
  cursor = db.cursor()

  cursor.execute("""
      SELECT
        r.report_id,
        r.app_id,
        r.version,
        r.platform,
        r.timestamp,
        COUNT(o.observation_id) as observation_count
      FROM report r
      LEFT JOIN observation o ON r.report_id = o.report_id
      GROUP BY r.report_id
      ORDER BY r.timestamp DESC
      LIMIT 10
    """)

  sample_reports = []
  for row in cursor.fetchall():
    sample_reports.append(
      {
        "id": row[0],
        "app_id": row[1],
        "version": row[2],
        "platform": row[3],
        "timestamp": row[4],
        "class_count": row[5],
      }
    )

  stats = {
    "sample_reports": sample_reports,
  }

  return render_template("analyze_reports.html", stats=stats)


def analyze_apps():
  db = get_db()
  cursor = db.cursor()

  cursor.execute("SELECT COUNT(*) FROM report")
  total_reports = cursor.fetchone()[0]

  # Get app details with additional information
  cursor.execute("""
    SELECT
      r.app_id,
      COUNT(DISTINCT r.report_id) as report_count,
      MAX(r.version) as latest_version,
      COUNT(DISTINCT o.token) as reported_class_count,
      (SELECT COUNT(DISTINCT k.token) FROM known k WHERE k.app_id = r.app_id) as known_class_count
    FROM report r
    LEFT JOIN observation o ON r.report_id = o.report_id
    GROUP BY r.app_id
    ORDER BY report_count DESC
  """)

  app_details = []
  for row in cursor.fetchall():
    app_details.append(
      {
        "app_id": row[0],
        "report_count": row[1],
        "latest_version": row[2] or "Unknown",
        "reported_class_count": row[3],
        "known_class_count": row[4] or 0,
      }
    )

  unique_apps = [app["app_id"] for app in app_details]

  cursor.execute("SELECT DISTINCT token FROM observation")
  unique_observations = [row[0] for row in cursor.fetchall()]

  cursor.execute("SELECT COUNT(*) FROM known")
  total_known = cursor.fetchone()[0]

  cursor.execute("SELECT COUNT(DISTINCT token) FROM known")
  unique_known = cursor.fetchone()[0]

  cursor.execute("""
    SELECT COUNT(DISTINCT k.token) FROM known k
    LEFT OUTER JOIN observation o
    ON k.token = o.token
    WHERE o.token IS NULL;
  """)
  unique_dead = cursor.fetchone()[0]

  cursor.execute("""
      SELECT
        r.report_id,
        r.app_id,
        r.version,
        r.platform,
        r.timestamp,
        COUNT(o.observation_id) as observation_count
      FROM report r
      LEFT JOIN observation o ON r.report_id = o.report_id
      GROUP BY r.report_id
      ORDER BY r.timestamp DESC
      LIMIT 10
    """)

  sample_reports = []
  for row in cursor.fetchall():
    sample_reports.append(
      {
        "id": row[0],
        "app_id": row[1],
        "version": row[2],
        "platform": row[3],
        "timestamp": row[4],
        "class_count": row[5],
      }
    )

  stats = {
    "total_reports": total_reports,
    "unique_apps": unique_apps,
    "app_details": app_details,
    "unique_app_count": len(unique_apps),
    "unique_observations": len(unique_observations),
    "total_known": total_known,
    "unique_known": unique_known,
    "unique_dead": unique_dead,
  }

  return render_template("analyze_apps.html", stats=stats)

def analyze_dead():
  db = get_db()
  cursor = db.cursor()

  cursor.execute("""
    SELECT COUNT(DISTINCT k.token) FROM known k
    LEFT OUTER JOIN observation o
    ON k.token = o.token
    WHERE o.token IS NULL;
  """)
  unique_dead = cursor.fetchone()[0]

  cursor.execute("""
    SELECT
      k.name, k.token, k.app_id, k.version, k.platform
    FROM known k
    LEFT OUTER JOIN observation o
    ON k.token = o.token
    WHERE
      o.token IS NULL;
  """)
  dead_types = []
  for row in cursor.fetchall():
    dead_types.append(
      {
        "name": row[0],
        "token": row[1],
        "app_id": row[2],
        "version": row[3],
        "platform": row[4],
      }
    )


  print(unique_dead)
  stats = {
    "unique_dead": unique_dead,
    "dead_types": dead_types,
  }

  return render_template("analyze_dead.html", stats=stats)



@app.route("/upload", methods=["GET", "POST"])
def upload():
  """Upload app for static analysis."""

  if request.method == "POST":
    if "file" not in request.files:
      flash("No file provided")
      return render_template("upload_page.html")

    file = request.files["file"]

    if file.filename == "":
      flash("No file selected")
      return render_template("upload_page.html")

    db = get_db()
    cursor = db.cursor()
    count = 0

    if file.filename.endswith(".aab"):
      logger.info(f"Processing AAB file: {file.filename}")

      class_info_list = reaper.process_aab_file(file)

      if not class_info_list:
        flash("No classes found in the AAB file")
        return render_template("upload_page.html")

      for item in class_info_list:
        class_sig, sha256, base64_top_64, aab_app_id, aab_version = item
        app_id = aab_app_id if aab_app_id != "unknown" else None
        version = aab_version if aab_version != "unknown" else None
        platform = "android"

        cursor.execute(
          "INSERT INTO known (app_id, version, platform, name, token) VALUES (?, ?, ?, ?, ?)",
          (app_id, version, platform, class_sig, base64_top_64),
        )
        count += 1

      logger.info(f"Extracted {count} class signatures from AAB file")
    else:
      flash("Unsupported file type. Please upload an AAB")
      return render_template("upload_page.html")

    db.commit()

    flash(f"Successfully processed {count} classes from {file.filename}")
    return redirect(url_for("analyze"))

  return render_template("upload_page.html")


if __name__ == "__main__":
  app.run(debug=True)
