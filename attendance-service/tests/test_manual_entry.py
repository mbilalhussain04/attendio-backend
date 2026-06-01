from datetime import datetime, timezone
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.db.session import SessionLocal
from app.models.attendance import AttendanceCorrectionRequest, AttendanceEntry, ShiftAssignment
from app.services import attendance_service
from app.utils.date import today_date


def test_self_manual_entry_with_break_is_recorded_without_approval():
    db = SessionLocal()
    company_id = uuid4()
    user_id = uuid4()
    try:
        row = attendance_service.submit_self_entry(
            db,
            company_id=company_id,
            user_id=user_id,
            employee_code="EMP-MANUAL",
            branch_id=None,
            check_in_at=datetime(2026, 5, 18, 9, 0),
            check_out_at=datetime(2026, 5, 18, 17, 0),
            scheduled_start_at=None,
            scheduled_end_at=None,
            reason="Remote work",
            actor_user_id=user_id,
            notes=None,
            break_minutes=30,
        )

        assert row.status == "corrected"
        assert row.worked_minutes == 450
        assert row.break_minutes == 30
        assert len(row.breaks) == 1
        assert not row.approvals
    finally:
        db.query(AttendanceEntry).filter(AttendanceEntry.company_id == company_id).delete()
        db.commit()
        db.close()


def test_clocked_day_uses_employee_expected_hours_target():
    db = SessionLocal()
    company_id = uuid4()
    user_id = uuid4()
    try:
        attendance_service.check_in(
            db,
            company_id=company_id,
            user_id=user_id,
            employee_code="EMP-PART",
            branch_id=None,
            scheduled_start_at=None,
            scheduled_end_at=None,
            source="web",
            actor_user_id=user_id,
            latitude=None,
            longitude=None,
            ip_address=None,
            notes=None,
            check_in_at=datetime(2026, 5, 20, 8, 0),
            profile={"user": {"expected_hours_period": "weekly", "expected_hours": 20}},
        )

        row = attendance_service.check_out(
            db,
            company_id=company_id,
            user_id=user_id,
            actor_user_id=user_id,
            latitude=None,
            longitude=None,
            ip_address=None,
            check_out_at=datetime(2026, 5, 20, 12, 30),
        )

        assert row.target_work_minutes == 240
        assert row.worked_minutes == 270
        assert row.overtime_minutes == 30
    finally:
        db.query(AttendanceEntry).filter(AttendanceEntry.company_id == company_id).delete()
        db.commit()
        db.close()


def test_clocked_day_uses_assigned_shift_schedule_and_target():
    db = SessionLocal()
    company_id = uuid4()
    user_id = uuid4()
    try:
        db.add(ShiftAssignment(
            company_id=company_id,
            user_id=user_id,
            employee_code="EMP-SHIFT",
            name="Morning",
            start_at=datetime(2026, 5, 21, 8, 0),
            end_at=datetime(2026, 5, 21, 16, 30),
            break_minutes=30,
        ))
        db.commit()

        entry = attendance_service.check_in(
            db,
            company_id=company_id,
            user_id=user_id,
            employee_code="EMP-SHIFT",
            branch_id=None,
            scheduled_start_at=None,
            scheduled_end_at=None,
            source="web",
            actor_user_id=user_id,
            latitude=None,
            longitude=None,
            ip_address=None,
            notes=None,
            check_in_at=datetime(2026, 5, 21, 8, 5),
            profile={"user": {"expected_hours_period": "weekly", "expected_hours": 20}},
        )

        assert entry.scheduled_start_at == datetime(2026, 5, 21, 8, 0)
        assert entry.scheduled_end_at == datetime(2026, 5, 21, 16, 30)
        assert entry.target_work_minutes == 480
    finally:
        db.query(AttendanceEntry).filter(AttendanceEntry.company_id == company_id).delete()
        db.query(ShiftAssignment).filter(ShiftAssignment.company_id == company_id).delete()
        db.commit()
        db.close()


def test_self_manual_entry_accepts_late_local_day_as_utc_payload():
    db = SessionLocal()
    company_id = uuid4()
    user_id = uuid4()
    try:
        row = attendance_service.submit_self_entry(
            db,
            company_id=company_id,
            user_id=user_id,
            employee_code="EMP-TZ",
            branch_id=None,
            check_in_at=datetime(2026, 5, 14, 7, 30, tzinfo=timezone.utc),
            check_out_at=datetime(2026, 5, 14, 20, 15, tzinfo=timezone.utc),
            scheduled_start_at=None,
            scheduled_end_at=None,
            reason="Remote work",
            actor_user_id=user_id,
            notes=None,
            break_minutes=30,
        )

        assert str(row.date) == "2026-05-14"
        assert row.worked_minutes == 735
        assert row.check_in_at.tzinfo is None
        assert row.check_in_at.hour == 7
        assert row.check_out_at.hour == 20
    finally:
        db.query(AttendanceEntry).filter(AttendanceEntry.company_id == company_id).delete()
        db.commit()
        db.close()


def test_self_manual_entry_keeps_gross_break_and_worked_separate():
    db = SessionLocal()
    company_id = uuid4()
    user_id = uuid4()
    try:
        row = attendance_service.submit_self_entry(
            db,
            company_id=company_id,
            user_id=user_id,
            employee_code="EMP-CALC",
            branch_id=None,
            check_in_at=datetime(2026, 5, 14, 8, 0, tzinfo=timezone.utc),  # 10:00 Europe/Berlin
            check_out_at=datetime(2026, 5, 14, 13, 0, tzinfo=timezone.utc),  # 15:00 Europe/Berlin
            scheduled_start_at=None,
            scheduled_end_at=None,
            reason="Remote work",
            actor_user_id=user_id,
            notes=None,
            break_minutes=30,
        )

        gross_minutes = int((row.check_out_at - row.check_in_at).total_seconds() // 60)
        assert gross_minutes == 300
        assert row.break_minutes == 30
        assert row.worked_minutes == 270
    finally:
        db.query(AttendanceEntry).filter(AttendanceEntry.company_id == company_id).delete()
        db.commit()
        db.close()


def test_self_manual_entry_duplicate_date_returns_conflict():
    db = SessionLocal()
    company_id = uuid4()
    user_id = uuid4()
    try:
        payload = dict(
            db=db,
            company_id=company_id,
            user_id=user_id,
            employee_code="EMP-DUP",
            branch_id=None,
            check_in_at=datetime(2026, 5, 19, 9, 0),
            check_out_at=datetime(2026, 5, 19, 17, 0),
            scheduled_start_at=None,
            scheduled_end_at=None,
            reason="Remote work",
            actor_user_id=user_id,
            notes=None,
            break_minutes=30,
        )
        attendance_service.submit_self_entry(**payload)

        with pytest.raises(HTTPException) as exc:
            attendance_service.submit_self_entry(**payload)
        assert exc.value.status_code == 409
    finally:
        db.query(AttendanceEntry).filter(AttendanceEntry.company_id == company_id).delete()
        db.commit()
        db.close()


def test_self_manual_entry_future_date_returns_validation_error():
    db = SessionLocal()
    company_id = uuid4()
    user_id = uuid4()
    future_day = today_date() + timedelta(days=1)
    try:
        with pytest.raises(HTTPException) as exc:
            attendance_service.submit_self_entry(
                db=db,
                company_id=company_id,
                user_id=user_id,
                employee_code="EMP-FUTURE",
                branch_id=None,
                check_in_at=datetime(future_day.year, future_day.month, future_day.day, 9, 0),
                check_out_at=datetime(future_day.year, future_day.month, future_day.day, 17, 0),
                scheduled_start_at=None,
                scheduled_end_at=None,
                reason="Future work",
                actor_user_id=user_id,
                notes=None,
                break_minutes=30,
            )
        assert exc.value.status_code == 400
    finally:
        db.query(AttendanceEntry).filter(AttendanceEntry.company_id == company_id).delete()
        db.commit()
        db.close()


def test_reset_self_date_deletes_existing_entry():
    db = SessionLocal()
    company_id = uuid4()
    user_id = uuid4()
    try:
        row = attendance_service.submit_self_entry(
            db=db,
            company_id=company_id,
            user_id=user_id,
            employee_code="EMP-RESET",
            branch_id=None,
            check_in_at=datetime(2026, 5, 18, 9, 0),
            check_out_at=datetime(2026, 5, 18, 17, 0),
            scheduled_start_at=None,
            scheduled_end_at=None,
            reason="Reset test",
            actor_user_id=user_id,
            notes=None,
            break_minutes=30,
        )

        result = attendance_service.reset_self_date(
            db,
            company_id=company_id,
            user_id=user_id,
            target_date=row.date,
            actor_user_id=user_id,
        )

        assert result["deleted_count"] == 1
        assert db.query(AttendanceEntry).filter(AttendanceEntry.id == row.id).first() is None
    finally:
        db.query(AttendanceEntry).filter(AttendanceEntry.company_id == company_id).delete()
        db.commit()
        db.close()


def test_pending_correction_blocks_duplicate_request():
    db = SessionLocal()
    company_id = uuid4()
    user_id = uuid4()
    try:
        row = attendance_service.submit_self_entry(
            db=db,
            company_id=company_id,
            user_id=user_id,
            employee_code="EMP-CORR",
            branch_id=None,
            check_in_at=datetime(2026, 5, 18, 9, 0),
            check_out_at=datetime(2026, 5, 18, 17, 0),
            scheduled_start_at=None,
            scheduled_end_at=None,
            reason="Correction test",
            actor_user_id=user_id,
            notes=None,
            break_minutes=30,
        )
        attendance_service.request_correction(
            db,
            company_id=company_id,
            requested_by_user_id=user_id,
            attendance_entry_id=str(row.id),
            reason="Forgot checkout",
            requested_check_in_at=None,
            requested_check_out_at=datetime(2026, 5, 18, 17, 30),
            requested_break_minutes=None,
        )

        with pytest.raises(HTTPException) as exc:
            attendance_service.request_correction(
                db,
                company_id=company_id,
                requested_by_user_id=user_id,
                attendance_entry_id=str(row.id),
                reason="Second request",
                requested_check_in_at=datetime(2026, 5, 18, 8, 45),
                requested_check_out_at=None,
                requested_break_minutes=None,
            )
        assert exc.value.status_code == 409
    finally:
        db.query(AttendanceEntry).filter(AttendanceEntry.company_id == company_id).delete()
        db.commit()
        db.close()


def test_correction_keeps_original_snapshot_after_approval():
    db = SessionLocal()
    company_id = uuid4()
    user_id = uuid4()
    try:
        row = attendance_service.submit_self_entry(
            db=db,
            company_id=company_id,
            user_id=user_id,
            employee_code="EMP-SNAPSHOT",
            branch_id=None,
            check_in_at=datetime(2026, 5, 18, 9, 0),
            check_out_at=datetime(2026, 5, 18, 17, 0),
            scheduled_start_at=None,
            scheduled_end_at=None,
            reason="Snapshot test",
            actor_user_id=user_id,
            notes=None,
            break_minutes=30,
        )
        correction = attendance_service.request_correction(
            db,
            company_id=company_id,
            requested_by_user_id=user_id,
            attendance_entry_id=str(row.id),
            reason="Worked longer",
            requested_check_in_at=None,
            requested_check_out_at=datetime(2026, 5, 18, 17, 30),
            requested_break_minutes=45,
        )

        assert correction.original_check_in_at == datetime(2026, 5, 18, 9, 0)
        assert correction.original_check_out_at == datetime(2026, 5, 18, 17, 0)
        assert correction.original_break_minutes == 30
        assert str(correction.entry_date) == "2026-05-18"

        attendance_service.review_correction(
            db,
            company_id=company_id,
            correction_request_id=str(correction.id),
            approver_user_id=str(user_id),
            status="approved",
            decision_reason=None,
        )
        refreshed = db.query(AttendanceCorrectionRequest).filter(AttendanceCorrectionRequest.id == correction.id).first()
        updated_entry = db.query(AttendanceEntry).filter(AttendanceEntry.id == row.id).first()

        assert refreshed.original_check_out_at == datetime(2026, 5, 18, 17, 0)
        assert refreshed.original_break_minutes == 30
        assert updated_entry.check_out_at == datetime(2026, 5, 18, 17, 30)
        assert updated_entry.break_minutes == 45
        assert updated_entry.worked_minutes == 465
    finally:
        db.query(AttendanceEntry).filter(AttendanceEntry.company_id == company_id).delete()
        db.commit()
        db.close()
