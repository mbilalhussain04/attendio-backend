from app.models.attendance import AttendanceEntry, AttendanceBreak


def calculate_attendance_metrics(entry: AttendanceEntry, breaks: list[AttendanceBreak], policy) -> dict:
    gross_minutes = max(int((entry.check_out_at - entry.check_in_at).total_seconds() // 60), 0) if entry.check_in_at and entry.check_out_at else 0
    break_minutes = 0
    if entry.check_in_at and entry.check_out_at:
        for item in breaks:
            if not item.start_at or not item.end_at:
                continue
            start = max(item.start_at, entry.check_in_at)
            end = min(item.end_at, entry.check_out_at)
            break_minutes += max(int((end - start).total_seconds() // 60), 0)
    break_minutes = min(break_minutes, gross_minutes)
    worked_minutes = max(gross_minutes - break_minutes, 0)
    target_minutes = int(entry.target_work_minutes or float(policy.daily_target_hours) * 60)
    overtime_minutes = max(worked_minutes - target_minutes, 0)
    late_minutes = 0
    if entry.scheduled_start_at and entry.check_in_at:
        diff = int((entry.check_in_at - entry.scheduled_start_at).total_seconds() // 60)
        late_minutes = diff if diff > int(policy.late_grace_minutes) else 0
    early_departure_minutes = 0
    if entry.scheduled_end_at and entry.check_out_at:
        diff = int((entry.scheduled_end_at - entry.check_out_at).total_seconds() // 60)
        early_departure_minutes = max(diff - int(policy.daily_grace_early_departure_minutes or 0), 0)
    required_break = int(policy.break_after_9h_minutes) if worked_minutes > 9 * 60 else int(policy.break_after_6h_minutes) if worked_minutes > 6 * 60 else 0
    flags = []
    if late_minutes > 0:
        flags.append({'flag_type': 'late', 'severity': 'warning', 'message': f'Late by {late_minutes} minutes'})
    if early_departure_minutes > 0:
        flags.append({'flag_type': 'early_departure', 'severity': 'warning', 'message': f'Left early by {early_departure_minutes} minutes'})
    if overtime_minutes > 0:
        flags.append({'flag_type': 'overtime', 'severity': 'critical' if worked_minutes > float(policy.max_daily_hours) * 60 else 'info', 'message': f'Overtime {overtime_minutes} minutes'})
    if break_minutes < required_break:
        flags.append({'flag_type': 'break_violation', 'severity': 'critical', 'message': f'Break time below required minimum of {required_break} minutes'})
    if worked_minutes > float(policy.max_daily_hours) * 60:
        flags.append({'flag_type': 'daily_hours_violation', 'severity': 'critical', 'message': f'Exceeded max daily hours of {policy.max_daily_hours}'})
    if entry.check_in_at and entry.check_in_at.weekday() == 6 and policy.sunday_justification_required and not entry.notes:
        flags.append({'flag_type': 'sunday_work', 'severity': 'warning', 'message': 'Sunday work requires justification'})
    return {
        'worked_minutes': worked_minutes,
        'break_minutes': break_minutes,
        'overtime_minutes': overtime_minutes,
        'late_minutes': late_minutes,
        'early_departure_minutes': early_departure_minutes,
        'flags': flags,
    }


def rest_period_violation(previous_entry: AttendanceEntry | None, next_entry: AttendanceEntry, policy):
    if not previous_entry or not previous_entry.check_out_at or not next_entry.check_in_at:
        return None
    hours = (next_entry.check_in_at - previous_entry.check_out_at).total_seconds() / 3600
    if hours < float(policy.rest_period_hours):
        return {'flag_type': 'rest_violation', 'severity': 'critical', 'message': f'Rest period below {policy.rest_period_hours} hours'}
    return None
