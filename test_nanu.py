#!/usr/bin/env python3
"""
Nanu Workflow Integration Test Suite
=====================================
Tests the full capture pipeline: webhook -> classification -> dedup -> merge -> Notion

Usage:
    python test_nanu.py                    # Run all phases
    python test_nanu.py --phase 1          # Run only Phase 1 (classification)
    python test_nanu.py --phase 2          # Run only Phase 2 (dedup/merge)
    python test_nanu.py --phase 3          # Run only Phase 3 (bug triggers)
    python test_nanu.py --phase 4          # Run only Phase 4 (edge cases)
    python test_nanu.py --cleanup          # Delete all test records from Notion
    python test_nanu.py --dry-run          # Show what would be sent without sending

Claude Code Usage:
    Save this file locally, then tell Claude Code:
    "Run test_nanu.py --phase 1, wait for it to finish, then show me the results"
    Or: "Run all phases of test_nanu.py sequentially and summarize the results"

    Claude Code can run the phases, read the output, and diagnose failures on the spot.

Prerequisites:
    pip install requests

IMPORTANT: Rotate your Notion API key after testing is complete.
"""

import requests
import time
import json
import argparse
import sys
from datetime import datetime, timezone

# ============================================================
# CONFIGURATION
# ============================================================
WEBHOOK_URL = "https://n8n.saltydalton.com/webhook/lauren-inbox"
NOTION_API_KEY = "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"

DATABASES = {
    "people":    "2f8b83d9-0e46-80f1-9694-e9129587fa6a",
    "projects":  "2f8b83d9-0e46-8072-93e6-cff6a8278de2",
    "ideas":     "2f8b83d9-0e46-80dc-bc5d-f00f6ef217d0",
    "admin":     "2f8b83d9-0e46-80f2-adaf-d3b4585f0950",
    "inbox_log": "2f8b83d9-0e46-806c-af24-c25c13727c01",
}

# Tag all test records so we can clean them up
TEST_TAG = "nanu-test"

# How long to wait for n8n to process each message (seconds)
PROCESSING_WAIT = 30

# How long to wait between messages in the same phase
MESSAGE_DELAY = 5

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}


# ============================================================
# NOTION HELPERS
# ============================================================

def notion_query(database_key, filter_obj=None):
    """Query a Notion database. Returns list of pages."""
    db_id = DATABASES[database_key]
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    body = {}
    if filter_obj:
        body["filter"] = filter_obj
    resp = requests.post(url, headers=NOTION_HEADERS, json=body)
    if resp.status_code != 200:
        print(f"  [ERROR] Notion query failed ({resp.status_code}): {resp.text[:200]}")
        return []
    return resp.json().get("results", [])


def notion_get_all(database_key):
    """Get all records from a database."""
    return notion_query(database_key)


def notion_archive_page(page_id):
    """Archive (soft-delete) a Notion page."""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    resp = requests.patch(url, headers=NOTION_HEADERS, json={"archived": True})
    return resp.status_code == 200


def get_page_property(page, prop_name, prop_type="rich_text"):
    """Extract a property value from a Notion page."""
    props = page.get("properties", {})
    prop = props.get(prop_name, {})

    if prop_type == "title":
        items = prop.get("title", [])
        return items[0]["plain_text"] if items else ""
    elif prop_type == "rich_text":
        items = prop.get("rich_text", [])
        return items[0]["plain_text"] if items else ""
    elif prop_type == "select":
        sel = prop.get("select")
        return sel["name"] if sel else ""
    elif prop_type == "date":
        d = prop.get("date")
        return d["start"] if d else ""
    elif prop_type == "multi_select":
        return [s["name"] for s in prop.get("multi_select", [])]
    elif prop_type == "url":
        return prop.get("url", "")
    return None


def count_records(database_key):
    """Count records in a database."""
    return len(notion_get_all(database_key))


def find_record_by_name(database_key, name_substring):
    """Find a record whose Name contains the given substring."""
    records = notion_get_all(database_key)
    for r in records:
        title = get_page_property(r, "Name", "title")
        if name_substring.lower() in title.lower():
            return r
    return None


# ============================================================
# WEBHOOK HELPER
# ============================================================

def send_message(text, message_id=None):
    """Send a message to the Nanu webhook, mimicking Discord bot payload."""
    if message_id is None:
        message_id = str(int(time.time() * 1000))

    payload = {
        "event_type": "message_create",
        "timestamp": int(time.time() * 1000),
        "content": {
            "text": text,
            "type": "message_create"
        },
        "author": {
            "id": "000000000000000000",
            "username": "test_runner",
            "discriminator": "0"
        },
        "channel": {
            "id": "1467567571074289705",
            "name": "lauren-inbox",
            "type": "text"
        },
        "guild": {
            "id": "1467107974207242345",
            "name": "Northern Lights"
        },
        "message_id": message_id,
        "original_message": {
            "channelId": "1467567571074289705",
            "guildId": "1467107974207242345",
            "id": message_id,
            "createdTimestamp": int(time.time() * 1000),
            "type": 0,
            "system": False,
            "content": text,
            "authorId": "000000000000000000",
            "pinned": False,
            "tts": False,
            "nonce": str(int(time.time() * 1000) - 1),
            "embeds": [],
            "components": [],
            "attachments": [],
            "stickers": [],
            "position": None,
            "roleSubscriptionData": None,
            "resolved": None,
            "editedTimestamp": None,
            "mentions": {
                "everyone": False,
                "users": [],
                "roles": [],
                "crosspostedChannels": [],
                "repliedUser": None,
                "members": [],
                "channels": []
            },
            "webhookId": None,
            "groupActivityApplicationId": None,
            "applicationId": None,
            "activity": None,
            "flags": 0,
            "reference": None,
            "interactionMetadata": None,
            "interaction": None,
            "poll": None,
            "messageSnapshots": [],
            "call": None,
            "cleanContent": text
        }
    }

    resp = requests.post(WEBHOOK_URL, json=payload)
    return resp.status_code, resp.text


# ============================================================
# TEST REPORTING
# ============================================================

class TestReport:
    def __init__(self):
        self.results = []
        self.phase = ""

    def set_phase(self, name):
        self.phase = name
        print(f"\n{'='*60}")
        print(f"  {name}")
        print(f"{'='*60}")

    def check(self, test_name, passed, expected="", actual="", detail=""):
        status = "PASS" if passed else "FAIL"
        icon = "+" if passed else "x"
        self.results.append({
            "phase": self.phase,
            "test": test_name,
            "passed": passed,
            "expected": expected,
            "actual": actual,
            "detail": detail,
        })
        print(f"  [{icon}] {test_name}")
        if not passed:
            if expected:
                print(f"      Expected: {expected}")
            if actual:
                print(f"      Actual:   {actual}")
            if detail:
                print(f"      Detail:   {detail}")

    def summary(self):
        total = len(self.results)
        passed = sum(1 for r in self.results if r["passed"])
        failed = total - passed

        print(f"\n{'='*60}")
        print(f"  SUMMARY: {passed}/{total} passed, {failed} failed")
        print(f"{'='*60}")

        if failed > 0:
            print(f"\n  Failed tests:")
            for r in self.results:
                if not r["passed"]:
                    print(f"    [x] [{r['phase']}] {r['test']}")
                    if r["expected"]:
                        print(f"        Expected: {r['expected']}")
                    if r["actual"]:
                        print(f"        Actual:   {r['actual']}")

        return failed == 0


# ============================================================
# PHASE 1: CLASSIFICATION & CREATION
# ============================================================

PHASE1_MESSAGES = [
    {
        "text": "person: Dr. Sarah Chen - my new dentist, office is on Main Street",
        "expect_db": "people",
        "expect_name_contains": "Sarah Chen",
        "expect_fields": {"Context": "dentist"},
    },
    {
        "text": "person: Uncle Rick - Lauren's uncle, lives in Tampa",
        "expect_db": "people",
        "expect_name_contains": "Uncle Rick",
        "expect_fields": {"Context": "Tampa"},
    },
    {
        "text": "project: Bathroom renovation - replacing tile and vanity, getting quotes this week",
        "expect_db": "projects",
        "expect_name_contains": "Bathroom",
        "expect_fields": {"Notes": "tile"},
    },
    {
        "text": "project: Lauren's birthday planning - surprise dinner, need to book restaurant",
        "expect_db": "projects",
        "expect_name_contains": "birthday",
        "expect_fields": {"Notes": "surprise"},
    },
    {
        "text": "idea: Start a YouTube channel reviewing DDR pads and rhythm game controllers",
        "expect_db": "ideas",
        "expect_name_contains": "YouTube",
        "expect_fields": {"One-Liner": "DDR"},
    },
    {
        "text": "idea: Build a Notion widget that shows daily Etsy sales on the home dashboard",
        "expect_db": "ideas",
        "expect_name_contains": "Notion widget",
        "expect_fields": {"Notes": "Etsy"},
    },
    {
        "text": "admin: Renew car registration by March 30",
        "expect_db": "admin",
        "expect_name_contains": "car registration",
        "expect_fields": {},
    },
    {
        "text": "admin: Schedule annual checkup with Dr. Patel",
        "expect_db": "admin",
        "expect_name_contains": "Dr. Patel",
        "expect_fields": {},
    },
]


def run_phase1(report, dry_run=False):
    report.set_phase("PHASE 1: Classification & Creation")

    # Snapshot record counts before
    counts_before = {db: count_records(db) for db in ["people", "projects", "ideas", "admin"]}
    print(f"\n  Record counts before: {counts_before}")

    for i, msg in enumerate(PHASE1_MESSAGES):
        print(f"\n  Sending [{i+1}/{len(PHASE1_MESSAGES)}]: {msg['text'][:60]}...")
        if dry_run:
            print(f"    [DRY RUN] Would send to {WEBHOOK_URL}")
            continue

        status, resp = send_message(msg["text"])
        report.check(
            f"Webhook accepted message {i+1}",
            status == 200,
            expected="200",
            actual=str(status),
        )
        time.sleep(MESSAGE_DELAY)

    if dry_run:
        print("\n  [DRY RUN] Skipping verification")
        return

    # Wait for all messages to process
    print(f"\n  Waiting {PROCESSING_WAIT}s for processing...")
    time.sleep(PROCESSING_WAIT)

    # Verify records were created
    counts_after = {db: count_records(db) for db in ["people", "projects", "ideas", "admin"]}
    print(f"  Record counts after: {counts_after}")

    for msg in PHASE1_MESSAGES:
        db = msg["expect_db"]
        name = msg["expect_name_contains"]

        record = find_record_by_name(db, name)
        report.check(
            f"'{name}' exists in {db}",
            record is not None,
            expected=f"Record in {db} containing '{name}'",
            actual="Not found" if not record else "Found",
        )

        if record and msg["expect_fields"]:
            for field, expected_substring in msg["expect_fields"].items():
                value = get_page_property(record, field, "rich_text")
                report.check(
                    f"'{name}' -> {field} contains '{expected_substring}'",
                    expected_substring.lower() in (value or "").lower(),
                    expected=f"'{expected_substring}' in {field}",
                    actual=f"'{value[:80]}'" if value else "(empty)",
                )

    # Verify inbox log entries
    inbox_entries = notion_get_all("inbox_log")
    new_entries = [e for e in inbox_entries
                   if get_page_property(e, "Status", "select") in ["Filed", "filed"]]
    report.check(
        f"Inbox Log has entries for filed messages",
        len(new_entries) >= len(PHASE1_MESSAGES),
        expected=f">= {len(PHASE1_MESSAGES)} filed entries",
        actual=f"{len(new_entries)} filed entries",
    )


# ============================================================
# PHASE 2: DEDUP & MERGE
# ============================================================

PHASE2_MESSAGES = [
    {
        "text": "Sarah Chen mentioned she's going on maternity leave in March",
        "expect_match": "Sarah Chen",
        "expect_db": "people",
        "expect_field": "Context",
        "expect_contains": "maternity",
        "expect_action": "merge",
    },
    {
        "text": "Bathroom reno update: went with the $3,200 quote from Mike's Contracting, starting March 15",
        "expect_match": "Bathroom",
        "expect_db": "projects",
        "expect_field": "Notes",
        "expect_contains": "Mike",
        "expect_action": "merge",
    },
    {
        "text": "YouTube channel idea - could also do stamina training tutorials, there's nothing good on YouTube for that",
        "expect_match": "YouTube",
        "expect_db": "ideas",
        "expect_field": "Notes",
        "expect_contains": "stamina",
        "expect_action": "merge",
    },
    {
        "text": "Car registration - found out I need an emissions test first, station on Route 6 is open Saturdays",
        "expect_match": "car registration",
        "expect_db": "admin",
        "expect_field": "Notes",
        "expect_contains": "emissions",
        "expect_action": "merge",
    },
]


def run_phase2(report, dry_run=False):
    report.set_phase("PHASE 2: Dedup & Merge")

    # Snapshot record counts and field values before
    snapshots = {}
    for msg in PHASE2_MESSAGES:
        record = find_record_by_name(msg["expect_db"], msg["expect_match"])
        if record:
            field_val = get_page_property(record, msg["expect_field"], "rich_text")
            snapshots[msg["expect_match"]] = {
                "record_count": count_records(msg["expect_db"]),
                "field_before": field_val,
                "page_id": record["id"],
            }
            print(f"  Before: '{msg['expect_match']}' {msg['expect_field']} = '{(field_val or '')[:60]}...'")
        else:
            print(f"  [WARN] Record '{msg['expect_match']}' not found in {msg['expect_db']}. Run Phase 1 first.")
            snapshots[msg["expect_match"]] = None

    for i, msg in enumerate(PHASE2_MESSAGES):
        print(f"\n  Sending [{i+1}/{len(PHASE2_MESSAGES)}]: {msg['text'][:60]}...")
        if dry_run:
            print(f"    [DRY RUN] Would send to {WEBHOOK_URL}")
            continue

        status, resp = send_message(msg["text"])
        report.check(
            f"Webhook accepted merge message {i+1}",
            status == 200,
            expected="200",
            actual=str(status),
        )
        time.sleep(MESSAGE_DELAY)

    if dry_run:
        print("\n  [DRY RUN] Skipping verification")
        return

    print(f"\n  Waiting {PROCESSING_WAIT}s for processing...")
    time.sleep(PROCESSING_WAIT)

    for msg in PHASE2_MESSAGES:
        name = msg["expect_match"]
        snap = snapshots.get(name)
        if not snap:
            report.check(f"'{name}' merge test", False, detail="Original record not found, skipped")
            continue

        # Check no duplicate was created
        new_count = count_records(msg["expect_db"])
        report.check(
            f"'{name}' - no duplicate created in {msg['expect_db']}",
            new_count == snap["record_count"],
            expected=f"{snap['record_count']} records",
            actual=f"{new_count} records",
        )

        # Check field was updated
        record = find_record_by_name(msg["expect_db"], name)
        if record:
            field_val = get_page_property(record, msg["expect_field"], "rich_text")
            report.check(
                f"'{name}' -> {msg['expect_field']} now contains '{msg['expect_contains']}'",
                msg["expect_contains"].lower() in (field_val or "").lower(),
                expected=f"'{msg['expect_contains']}' in {msg['expect_field']}",
                actual=f"'{(field_val or '')[:100]}'",
            )

            # Check field value actually changed
            report.check(
                f"'{name}' -> {msg['expect_field']} was actually updated (not same as before)",
                field_val != snap["field_before"],
                expected="Different from before",
                actual=f"Before: '{(snap['field_before'] or '')[:60]}' / After: '{(field_val or '')[:60]}'",
            )
        else:
            report.check(f"'{name}' still exists after merge", False, detail="Record not found")


# ============================================================
# PHASE 3: BUG TRIGGERS (wrong field names)
# ============================================================

PHASE3_MESSAGES = [
    {
        "text": "Here's a note about Sarah Chen: she recommended Dr. Yamamoto for Lauren's back pain",
        "trap": "AI sees 'note about' and may use 'Notes' instead of 'Context'",
        "expect_match": "Sarah Chen",
        "expect_db": "people",
        "valid_fields": ["Context", "Follow-ups"],
        "expect_data_contains": "Yamamoto",
    },
    {
        "text": "Follow up with the bathroom renovation: Mike needs us to pick tile by March 10",
        "trap": "AI sees 'follow up' and may use 'Follow-ups' instead of 'Next Action'",
        "expect_match": "Bathroom",
        "expect_db": "projects",
        "valid_fields": ["Notes", "Next Action"],
        "expect_data_contains": "tile",
    },
    {
        "text": "Next step for the YouTube channel idea: research what mic/camera setup other rhythm game YouTubers use",
        "trap": "AI sees 'next step' and may use 'Next Action' instead of 'Notes'",
        "expect_match": "YouTube",
        "expect_db": "ideas",
        "valid_fields": ["Notes", "One-Liner"],
        "expect_data_contains": "mic",
    },
    {
        "text": "One quick thought on the car registration: the emissions place also does inspections, could knock both out at once",
        "trap": "AI sees 'one quick thought' and may use 'One-Liner' instead of 'Notes'",
        "expect_match": "car registration",
        "expect_db": "admin",
        "valid_fields": ["Notes"],
        "expect_data_contains": "inspections",
    },
]

# Map of which fields exist per database for verification
DB_FIELDS = {
    "people":   ["Context", "Follow-ups"],
    "projects": ["Notes", "Next Action"],
    "ideas":    ["Notes", "One-Liner"],
    "admin":    ["Notes"],
}


def run_phase3(report, dry_run=False):
    report.set_phase("PHASE 3: Bug Triggers (wrong field names)")

    for i, msg in enumerate(PHASE3_MESSAGES):
        print(f"\n  Sending [{i+1}/{len(PHASE3_MESSAGES)}]: {msg['text'][:60]}...")
        print(f"  Trap: {msg['trap']}")
        if dry_run:
            print(f"    [DRY RUN] Would send to {WEBHOOK_URL}")
            continue

        status, resp = send_message(msg["text"])
        report.check(
            f"Webhook accepted bug trigger {i+1}",
            status == 200,
            expected="200",
            actual=str(status),
        )
        time.sleep(MESSAGE_DELAY)

    if dry_run:
        print("\n  [DRY RUN] Skipping verification")
        return

    print(f"\n  Waiting {PROCESSING_WAIT}s for processing...")
    time.sleep(PROCESSING_WAIT)

    for msg in PHASE3_MESSAGES:
        name = msg["expect_match"]
        record = find_record_by_name(msg["expect_db"], name)

        if not record:
            report.check(f"'{name}' bug trigger test", False, detail="Record not found")
            continue

        # Check that the new data landed SOMEWHERE in the valid fields
        data_found = False
        data_location = ""
        for field in msg["valid_fields"]:
            value = get_page_property(record, field, "rich_text")
            if msg["expect_data_contains"].lower() in (value or "").lower():
                data_found = True
                data_location = field
                break

        report.check(
            f"'{name}' - data '{msg['expect_data_contains']}' landed in a valid field",
            data_found,
            expected=f"'{msg['expect_data_contains']}' in one of {msg['valid_fields']}",
            actual=f"Found in '{data_location}'" if data_found else "Not found in any valid field",
        )

        # Also check it didn't create a duplicate
        all_records = notion_get_all(msg["expect_db"])
        matches = [r for r in all_records
                   if name.lower() in get_page_property(r, "Name", "title").lower()]
        report.check(
            f"'{name}' - no duplicate created",
            len(matches) == 1,
            expected="1 record",
            actual=f"{len(matches)} records",
        )


# ============================================================
# PHASE 4: EDGE CASES
# ============================================================

def run_phase4(report, dry_run=False):
    report.set_phase("PHASE 4: Edge Cases")

    # Test 1: Low confidence message should go to needs_review
    low_conf_msg = "maybe thing about later idk"
    print(f"\n  Sending low-confidence message: '{low_conf_msg}'")
    if not dry_run:
        status, resp = send_message(low_conf_msg)
        report.check("Webhook accepted low-confidence message", status == 200)
        time.sleep(MESSAGE_DELAY)

    # Test 2: Explicit prefix override
    prefix_msg = "admin: Sarah Chen's office needs the insurance forms faxed"
    print(f"  Sending prefix override (admin for person-sounding msg): '{prefix_msg[:60]}...'")
    if not dry_run:
        status, resp = send_message(prefix_msg)
        report.check("Webhook accepted prefix override message", status == 200)
        time.sleep(MESSAGE_DELAY)

    # Test 3: Exact duplicate (same message twice, no new info)
    exact_dup_msg = "Uncle Rick said he's selling his house and moving to Asheville"
    print(f"  Sending exact duplicate: '{exact_dup_msg[:60]}...'")
    if not dry_run:
        status, resp = send_message(exact_dup_msg)
        report.check("Webhook accepted exact duplicate message", status == 200)

    if dry_run:
        print("\n  [DRY RUN] Skipping verification")
        return

    print(f"\n  Waiting {PROCESSING_WAIT}s for processing...")
    time.sleep(PROCESSING_WAIT)

    # Verify low confidence -> needs_review in inbox log
    inbox = notion_get_all("inbox_log")
    needs_review = [e for e in inbox
                    if get_page_property(e, "Status", "select").lower() in ["needs review", "needs_review"]]
    report.check(
        "Low-confidence message logged as needs_review",
        len(needs_review) > 0,
        detail=f"Found {len(needs_review)} needs_review entries in Inbox Log",
    )

    # Verify prefix override -> admin (not people)
    admin_record = find_record_by_name("admin", "insurance forms")
    people_record = find_record_by_name("people", "insurance forms")
    report.check(
        "Prefix 'admin:' overrode person-sounding content",
        admin_record is not None,
        expected="Record in admin",
        actual="Found in admin" if admin_record else "Not found in admin",
    )
    report.check(
        "Prefix override did NOT create people record",
        people_record is None,
        expected="No record in people",
        actual="Found in people (bad!)" if people_record else "Not in people (good)",
    )

    # Verify exact duplicate didn't create a new Uncle Rick record
    people_records = notion_get_all("people")
    rick_records = [r for r in people_records
                    if "rick" in get_page_property(r, "Name", "title").lower()]
    report.check(
        "Exact duplicate 'Uncle Rick' did not create a second record",
        len(rick_records) == 1,
        expected="1 Uncle Rick record",
        actual=f"{len(rick_records)} Uncle Rick records",
    )


# ============================================================
# CLEANUP
# ============================================================

def run_cleanup():
    """Archive all records from test databases."""
    print("\n  CLEANUP: Archiving all test records...")
    print("  WARNING: This will archive ALL records in Lauren's databases.")
    confirm = input("  Type 'yes' to confirm: ")
    if confirm.strip().lower() != "yes":
        print("  Cleanup cancelled.")
        return

    for db_name in ["people", "projects", "ideas", "admin", "inbox_log"]:
        records = notion_get_all(db_name)
        print(f"  Archiving {len(records)} records from {db_name}...")
        for r in records:
            notion_archive_page(r["id"])
        print(f"    Done.")

    print("\n  Cleanup complete. All databases emptied.")


# ============================================================
# CONNECTIVITY CHECK
# ============================================================

def check_connectivity():
    """Verify we can reach the webhook and Notion API."""
    print("  Checking connectivity...")

    # Check Notion API
    url = f"https://api.notion.com/v1/databases/{DATABASES['people']}"
    try:
        resp = requests.get(url, headers=NOTION_HEADERS)
        if resp.status_code == 200:
            print("  [+] Notion API: OK")
        else:
            print(f"  [x] Notion API: Failed ({resp.status_code})")
            return False
    except Exception as e:
        print(f"  [x] Notion API: Connection error ({e})")
        return False

    # Check webhook (just a GET to see if it's reachable, expect 404 or similar)
    try:
        resp = requests.get(WEBHOOK_URL, timeout=10)
        # Webhook might reject GET but at least we know it's reachable
        print(f"  [+] Webhook: Reachable (status {resp.status_code})")
    except Exception as e:
        print(f"  [x] Webhook: Connection error ({e})")
        return False

    return True


# ============================================================
# MAIN
# ============================================================

def main():
    global PROCESSING_WAIT
    parser = argparse.ArgumentParser(description="Nanu Workflow Integration Tests")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3, 4], help="Run only this phase")
    parser.add_argument("--cleanup", action="store_true", help="Delete all test records")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without sending")
    parser.add_argument("--wait", type=int, default=PROCESSING_WAIT, help="Seconds to wait for processing")
    args = parser.parse_args()

    PROCESSING_WAIT = args.wait

    print(f"\n{'='*60}")
    print(f"  NANU WORKFLOW INTEGRATION TEST SUITE")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*60}")

    if args.cleanup:
        run_cleanup()
        return

    if not check_connectivity():
        print("\n  Connectivity check failed. Aborting.")
        sys.exit(1)

    report = TestReport()

    if args.phase is None or args.phase == 1:
        run_phase1(report, args.dry_run)

    if args.phase is None or args.phase == 2:
        run_phase2(report, args.dry_run)

    if args.phase is None or args.phase == 3:
        run_phase3(report, args.dry_run)

    if args.phase is None or args.phase == 4:
        run_phase4(report, args.dry_run)

    all_passed = report.summary()

    if not args.dry_run:
        print(f"\n  Reminder: Run 'python test_nanu.py --cleanup' to remove test data when done.")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
