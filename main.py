import webview
from flask import Flask, request, jsonify, send_from_directory
import pandas as pd
import requests
import json
import threading
import logging
import datetime
import jwt  # PyJWT
import config

# ===== Logging Setup =====
logging.basicConfig(
    filename=config.LOG_FILE,
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s - %(levelname)s - %(message)s"
)

app = Flask(__name__, static_folder="web", template_folder="web")


def generate_jwt():
    payload = {
        "iss": config.API_KEY,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(minutes=5),
        "ver": 1  # Required version field
    }
    token = jwt.encode(payload, config.API_SECRET, algorithm="HS256")
    if isinstance(token, bytes):
        token = token.decode('utf-8')
    return token


def transform_record(record):
    addr_parts = [part.strip() for part in record.get("address", "").split(",")]
    addr_line = addr_parts[0] if len(addr_parts) > 0 else ""
    addr_city = addr_parts[1] if len(addr_parts) > 1 else ""
    addr_state = record.get("state", "")
    addr_zip = record.get("zip", "")

    visit_type_map = {
        "in_person": "N"
    }
    reason_map = {
        "Interested in inherited condition": "interested_in_inherited_condition",
        "Routine Check": "routine_check",
        "Annual Physical": "annual_physical",
    }
    test_code_map = {
        "COVID-19 PCR": "mS9ColoHealth",
        "Blood Panel": "blood_panel_code",
        "Flu Test": "flu_test_code",
        "Cholesterol": "cholesterol_test_code",
    }

    visit_type = visit_type_map.get(record.get("visitType", "").lower(), "N")
    reason_for_testing = reason_map.get(record.get("reasonForTesting", ""), "interested_in_inherited_condition")

    # Parse test types (semicolon-separated)
    test_names_raw = record.get("testTypes", "")
    test_names_list = [t.strip() for t in test_names_raw.split(";") if t.strip()]
    test_codes = [test_code_map.get(t, None) for t in test_names_list if test_code_map.get(t, None) is not None]
    test_names_list_final = [f"{code} - Test" for code in test_codes]

    payload = {
        "order": {
            "reference": str(record.get("pwnOrderId", "")),
            "bill_type": "1",
            "visit_type": visit_type,
            "take_tests_same_day": True,
            "account_number": record.get("accountNumber", ""),
            "confirmation_code": record.get("confirmationCode", ""),
            "test_types": test_codes,
            "test_names": test_names_list_final,
            "reason_for_testing": reason_for_testing,
            "customer": {
                "first_name": record.get("firstName", ""),
                "last_name": record.get("lastName", ""),
                "phone": record.get("homePhone", "18652996250"),  # fallback phone
                "birth_date": record.get("dob", ""),
                "gender": record.get("gender", ""),
                "email": record.get("email", ""),
                "address": {
                    "line": addr_line,
                    "city": addr_city,
                    "state": addr_state,
                    "zip": addr_zip,
                },
                "draw_location": {
                    "line": addr_line,
                    "city": addr_city,
                    "state": "TN",  # example hardcoded, change as needed
                    "zip": addr_zip,
                    "country": "USA"
                },
                "created_at": record.get("pwnCreatedAt", ""),
                "expires_at": record.get("pwnExpiresAt", ""),
                "status": record.get("pwnOrderStatus", "").lower(),
                "external_id": record.get("externalId", ""),
                "provider_id": record.get("providerId", ""),
            },
            "physician_review": {
                "name": record.get("pwnPhysicianName", "")
            },
            "links": {
                "ui_customer": record.get("pwnLink", "")
            }
        }
    }
    return payload


@app.route("/")
def index():
    return send_from_directory("web", "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("web", path)


@app.route("/upload", methods=["POST"])
def upload_csv():
    file = request.files.get("file")
    if not file:
        logging.warning("No file uploaded")
        return jsonify({"status": "error", "message": "No file uploaded"}), 400

    try:
        df = pd.read_csv(file, encoding=config.CSV_ENCODING)
        records = df.to_dict(orient="records")

        logging.info(f"CSV uploaded with {len(records)} rows")

        errors = []
        for i, record in enumerate(records, 1):
            payload = transform_record(record)
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {generate_jwt()}"
            }
            response = requests.post(config.API_URL, headers=headers, json=payload)
            if response.status_code != 200:
                error_msg = f"Row {i} upload failed: {response.status_code} - {response.text}"
                logging.error(error_msg)
                errors.append(error_msg)

        if errors:
            return jsonify({"status": "error", "message": "Some rows failed to upload", "details": errors}), 400
        else:
            return jsonify({"status": "success", "message": "All rows uploaded successfully!"})

    except Exception as e:
        logging.exception("Error while uploading CSV")
        return jsonify({"status": "error", "message": str(e)}), 500


def start_flask():
    app.run(host="127.0.0.1", port=5000)


if __name__ == "__main__":
    threading.Thread(target=start_flask).start()
    webview.create_window("PWNHealth CSV Uploader", "http://127.0.0.1:5000")
