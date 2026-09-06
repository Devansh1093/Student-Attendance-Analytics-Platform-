"""
Simple Attendance Generator
Profiles:
1. Perfect attendance
2. Few absent
3. Average attendance (~75-80%)
4. Good attendance (~85-95%)
5. Stops attending after first week
6. Few late classes
7. Mostly absent
8. Frequently late
"""

import csv
import json
import random
import time
from datetime import date, datetime, timedelta
from pathlib import Path
import os
from azure.storage.blob import BlobServiceClient

OUTPUT_DIR = Path("generated_attendance")
STATE_FILE = Path("generator_state.json")


START_DATE = date(2026, 7, 27)

# Number of seconds between simulated class days.
INTERVAL_SECONDS = 15
AZURE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_CONTAINER_NAME = "attendance-data"

STUDENTS = {
    1001: {"course_id": 101, "profile": "perfect"},
    1002: {"course_id": 102, "profile": "few_absent"},
    1003: {"course_id": 103, "profile": "average"},
    1004: {"course_id": 104, "profile": "good"},
    1005: {"course_id": 105, "profile": "stops_after_week"},
    1006: {"course_id": 101, "profile": "few_late"},
    1007: {"course_id": 102, "profile": "mostly_absent"},
    1009: {"course_id": 104, "profile": "good"},
    1010: {"course_id": 105, "profile": "average"},
    1011: {"course_id": 103, "profile": "frequently_late"},
}

HEADERS = [
    "ATTENDANCE_ID",
    "STUDENT_ID",
    "COURSE_ID",
    "ATTENDANCE_DATE",
    "CHECK_IN_TIME",
    "CHECK_OUT_TIME",
    "ATTENDANCE_STATUS",
    "ATTENDANCE_PERCENTAGE",
    "RECORDED_BY",
    "CREATED_TIMESTAMP",
]


def load_state():
    if STATE_FILE.exists():
        with STATE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)

    return {
        "next_attendance_id": 20001,
        "simulated_date": START_DATE.isoformat(),
        "attendance": {
            str(student_id): {"attended": 0, "classes": 0}
            for student_id in STUDENTS
        },
    }

def upload_to_azure(filename):
    if not AZURE_CONNECTION_STRING:
        raise RuntimeError(
            "AZURE_STORAGE_CONNECTION_STRING environment variable was not found."
        )

    blob_client = BlobServiceClient.from_connection_string(
        AZURE_CONNECTION_STRING
    )

    blob_client = blob_client.get_blob_client(
        container=AZURE_CONTAINER_NAME,
        blob=filename.name
    )

    with filename.open("rb") as data:
        blob_client.upload_blob(data, overwrite=True)

    print(f"Uploaded to Azure: {AZURE_CONTAINER_NAME}/{filename.name}")


def save_state(state):
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def choose_status(profile):
    
    r = random.random()

    if profile == "perfect":
        return "Present" if r < 0.99 else "Late"

    if profile == "few_absent":
        if r < 0.08:
            return "Absent"
        if r < 0.13:
            return "Late"
        return "Present"

    if profile == "average":
     
        if r < 0.23:
            return "Absent"
        if r < 0.31:
            return "Late"
        return "Present"

    if profile == "good":
        if r < 0.06:
            return "Absent" 
        if r < 0.14:
            return "Late"
        return "Present"

    if profile == "few_late":
        if r < 0.05:
            return "Absent"
        if r < 0.18:
            return "Late"
        return "Present"

    if profile == "mostly_absent":
        if r < 0.65:
            return "Absent"
        if r < 0.75:
            return "Late"
        return "Present"

    if profile == "frequently_late":
        if r < 0.08:
            return "Absent"
        if r < 0.50:
            return "Late"
        return "Present"

    return "Present"


def make_times(status, class_date):
    if status == "Absent":
        return "", ""

    # Class starts  at 09:00
    if status == "Late":
        minute = random.randint(8, 30)
    else:
        minute = random.randint(0, 5)

    check_in = datetime(
        class_date.year, 
        class_date.month, 
        class_date.day, 
        9,
        minute
    )
    check_out = datetime(
        class_date.year, class_date.month, class_date.day, 10, 0
    )

    return (
        check_in.strftime("%Y-%m-%d %H:%M:%S"),
        check_out.strftime("%Y-%m-%d %H:%M:%S"),
    )


def cumulative_percentage(student_state, status):
    student_state["classes"] += 1

    # Late counts as attended
    if status in ("Present", "Late"):
        student_state["attended"] += 1

    return round(
        student_state["attended"] / student_state["classes"] * 100, 2
    )


def generate_one_day(state):
    class_date = date.fromisoformat(state["simulated_date"])
    rows = []

    for student_id, info in STUDENTS.items():
        profile = info["profile"]

        # 1005 stops attending after the first week
        if profile == "stops_after_week" and class_date > START_DATE + timedelta(days=6):
            continue

        status = choose_status(profile)
        check_in, check_out = make_times(status, class_date)

        student_state = state["attendance"][str(student_id)]
        percentage = cumulative_percentage(student_state, status)

        attendance_id = state["next_attendance_id"]
        state["next_attendance_id"] += 1

        rows.append([
            attendance_id,
            student_id,
            info["course_id"],
            class_date.isoformat(),
            check_in,
            check_out,
            status,
            percentage,
            "Attendance_Generator",
            datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z"),
        ])

    if not rows:
        return class_date, None

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = OUTPUT_DIR / f"Attendance_{class_date.strftime('%Y%m%d')}_{state['next_attendance_id'] - len(rows)}.csv"

    with filename.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(HEADERS)
        writer.writerows(rows)

    next_date = class_date + timedelta(days=1)

    while next_date.weekday() >= 5:
        next_date += timedelta(days=1)

    state["simulated_date"] = next_date.isoformat()

    upload_to_azure(filename)
    save_state(state)

    return class_date, filename


def main():
    state = load_state()

    print("Attendance Generator started.")
    print(f"Output folder: {OUTPUT_DIR.resolve()}")
    print(f"Interval: {INTERVAL_SECONDS} seconds")
    print("Press Ctrl+C to stop.\n")

    while True:
        class_date, filename = generate_one_day(state)

        if filename:
            print(f"Generated: {filename.name}")
        else:
            print(f"No records generated for {class_date}")

        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
