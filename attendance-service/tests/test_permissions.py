from app.utils.permissions import Permissions


def test_permissions_constants_present():
    assert Permissions.ATTENDANCE_CHECK_IN
    assert Permissions.ATTENDANCE_VIEW_COMPANY
