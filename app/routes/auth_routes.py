from flask import Blueprint, render_template, request, redirect, url_for, session
from app.database import get_db_connection


auth = Blueprint("auth", __name__)


@auth.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        role = request.form.get("role")
        email = request.form.get("email")
        password = request.form.get("password")

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        query = """
            SELECT
                e.employee_id,
                e.employee_name,
                e.email,
                e.password_hash,
                r.role_name
            FROM Employee e
            JOIN Role r
                ON e.role_id = r.role_id
            WHERE e.email = %s
              AND r.role_name = %s
        """

        cursor.execute(query, (email, role))
        employee = cursor.fetchone()

        cursor.close()
        connection.close()

        if employee and employee["password_hash"] == password:

            session["employee_id"] = employee["employee_id"]
            session["employee_name"] = employee["employee_name"]
            session["role"] = employee["role_name"]

            if employee["role_name"] == "Employee":
                return redirect("/employee/dashboard")

            elif employee["role_name"] == "Manager":
                return redirect("/manager/dashboard")

            elif employee["role_name"] == "HR":
                return redirect("/hr/dashboard")

            elif employee["role_name"] == "Admin":
                return redirect("/admin/dashboard")

        return render_template(
            "login.html",
            error="Invalid email, password or role."
        )

    return render_template("login.html")


@auth.route("/employee/dashboard")
def employee_dashboard():

    if "employee_id" not in session:
        return redirect(url_for("auth.login"))

    employee_id = session["employee_id"]

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # Employee information
    employee_query = """
        SELECT
            e.employee_id,
            e.employee_code,
            e.employee_name,
            e.email,
            d.department_id,
            d.department_name,
            r.role_name,
            et.employment_type_name,
            es.status_name
        FROM Employee e
        LEFT JOIN Department d
            ON e.department_id = d.department_id
        LEFT JOIN Role r
            ON e.role_id = r.role_id
        LEFT JOIN Employment_Type et
            ON e.employment_type_id = et.employment_type_id
        LEFT JOIN Employee_Status es
            ON e.employee_status_id = es.employee_status_id
        WHERE e.employee_id = %s
    """

    cursor.execute(employee_query, (employee_id,))
    employee = cursor.fetchone()

    if not employee:
        cursor.close()
        connection.close()
        return "Employee not found", 404

    # Leave Balance
    leave_query = """
        SELECT COALESCE(SUM(remaining_days), 0) AS leave_balance
        FROM Leave_Balance
        WHERE employee_id = %s
    """

    cursor.execute(leave_query, (employee_id,))
    leave_data = cursor.fetchone()

    leave_balance = leave_data["leave_balance"]

    # Pending Leave Requests
    pending_query = """
        SELECT COUNT(*) AS pending_requests
        FROM Leave_Request lr
        JOIN Leave_Status ls
            ON lr.status_id = ls.status_id
        WHERE lr.employee_id = %s
          AND ls.status_name = 'Pending'
    """

    cursor.execute(pending_query, (employee_id,))
    pending_data = cursor.fetchone()

    pending_requests = pending_data["pending_requests"]

    # Attendance
    attendance_query = """
        SELECT
            COUNT(*) AS total_days,
            SUM(
                CASE
                    WHEN attendance_status = 'Present'
                    THEN 1
                    ELSE 0
                END
            ) AS present_days
        FROM Attendance
        WHERE employee_id = %s
    """

    cursor.execute(attendance_query, (employee_id,))
    attendance_data = cursor.fetchone()

    total_days = attendance_data["total_days"]
    present_days = attendance_data["present_days"] or 0

    if total_days > 0:
        attendance_percentage = round(
            (present_days / total_days) * 100, 2
        )
    else:
        attendance_percentage = 0

    cursor.close()
    connection.close()

    return render_template(
        "employee_dashboard.html",
        employee=employee,
        leave_balance=leave_balance,
        attendance_percentage=attendance_percentage,
        pending_requests=pending_requests
    )

@auth.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("auth.login"))


@auth.route("/employee/apply-leave", methods=["GET", "POST"])
def apply_leave():

    if "employee_id" not in session:
        return redirect(url_for("auth.login"))

    employee_id = session["employee_id"]

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # Get leave types
    cursor.execute("""
        SELECT
            leave_type_id,
            leave_type_name,
            description,
            max_days
        FROM Leave_Type
        ORDER BY leave_type_id
    """)

    leave_types = cursor.fetchall()

    if request.method == "POST":

        leave_type_id = request.form.get("leave_type_id")
        start_date = request.form.get("start_date")
        end_date = request.form.get("end_date")
        reason = request.form.get("reason")

        # Find Pending status
        cursor.execute("""
            SELECT status_id
            FROM Leave_Status
            WHERE status_name = 'Pending'
        """)

        status = cursor.fetchone()

        if not status:
            cursor.close()
            connection.close()
            return "Pending status not found", 500

        status_id = status["status_id"]

        # Insert leave request
        insert_query = """
            INSERT INTO Leave_Request
            (
                employee_id,
                leave_type_id,
                status_id,
                start_date,
                end_date,
                reason
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
        """

        cursor.execute(
            insert_query,
            (
                employee_id,
                leave_type_id,
                status_id,
                start_date,
                end_date,
                reason
            )
        )

        connection.commit()

        cursor.close()
        connection.close()

        return redirect("/employee/leave-requests")

    cursor.close()
    connection.close()

    return render_template(
        "employee/apply_leave.html",
        leave_types=leave_types
    )

@auth.route("/employee/leave-requests")
def leave_requests():

    if "employee_id" not in session:
        return redirect(url_for("auth.login"))

    employee_id = session["employee_id"]

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    query = """
        SELECT
            lr.leave_request_id,
            lt.leave_type_name,
            lr.start_date,
            lr.end_date,
            lr.reason,
            ls.status_name,
            lr.applied_at,

            a.approval_status,
            a.comments,
            a.approved_at,

            approver.employee_name AS approver_name

        FROM Leave_Request lr

        JOIN Leave_Type lt
            ON lr.leave_type_id = lt.leave_type_id

        JOIN Leave_Status ls
            ON lr.status_id = ls.status_id

        LEFT JOIN Approval a
            ON lr.leave_request_id = a.leave_request_id

        LEFT JOIN Employee approver
            ON a.approver_id = approver.employee_id

        WHERE lr.employee_id = %s

        ORDER BY lr.applied_at DESC
    """

    cursor.execute(query, (employee_id,))
    requests = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "employee/leave_requests.html",
        requests=requests
    )
@auth.route("/manager/dashboard")
def manager_dashboard():

    if "employee_id" not in session:
        return redirect(url_for("auth.login"))

    if session.get("role") != "Manager":
        return "Access Denied", 403

    manager_id = session["employee_id"]

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # Manager ki team
    team_query = """
        SELECT
            e.employee_id,
            e.employee_code,
            e.employee_name,
            e.email,
            d.department_name
        FROM Employee e
        LEFT JOIN Department d
            ON e.department_id = d.department_id
        WHERE e.manager_id = %s
    """

    cursor.execute(team_query, (manager_id,))
    team_members = cursor.fetchall()

    # Pending leave requests
    leave_query = """
        SELECT
            lr.leave_request_id,
            e.employee_name,
            lt.leave_type_name,
            lr.start_date,
            lr.end_date,
            lr.reason,
            ls.status_name
        FROM Leave_Request lr
        JOIN Employee e
            ON lr.employee_id = e.employee_id
        JOIN Leave_Type lt
            ON lr.leave_type_id = lt.leave_type_id
        JOIN Leave_Status ls
            ON lr.status_id = ls.status_id
        WHERE e.manager_id = %s
          AND ls.status_name = 'Pending'
        ORDER BY lr.applied_at DESC
    """

    cursor.execute(leave_query, (manager_id,))
    pending_requests = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "manager/dashboard.html",
        team_members=team_members,
        pending_requests=pending_requests
    )
@auth.route("/manager/leave/<int:request_id>/approve", methods=["POST"])
def approve_leave(request_id):

    if "employee_id" not in session:
        return redirect(url_for("auth.login"))

    if session.get("role") != "Manager":
        return "Access Denied", 403

    manager_id = session["employee_id"]

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # Check that this request belongs to manager's team
    query = """
        SELECT
            lr.leave_request_id,
            lr.employee_id,
            lr.leave_type_id,
            lr.start_date,
            lr.end_date
        FROM Leave_Request lr
        JOIN Employee e
            ON lr.employee_id = e.employee_id
        JOIN Leave_Status ls
            ON lr.status_id = ls.status_id
        WHERE lr.leave_request_id = %s
          AND e.manager_id = %s
          AND ls.status_name = 'Pending'
    """

    cursor.execute(query, (request_id, manager_id))
    leave_request = cursor.fetchone()

    if not leave_request:
        cursor.close()
        connection.close()
        return "Leave request not found or already processed", 404

    # Get Approved status
    cursor.execute("""
        SELECT status_id
        FROM Leave_Status
        WHERE status_name = 'Approved'
    """)

    approved_status = cursor.fetchone()

    if not approved_status:
        cursor.close()
        connection.close()
        return "Approved status not found", 500

    # Update leave request
    cursor.execute("""
        UPDATE Leave_Request
        SET status_id = %s
        WHERE leave_request_id = %s
    """, (approved_status["status_id"], request_id))

    # Calculate leave days
    leave_days = (
        leave_request["end_date"] - leave_request["start_date"]
    ).days + 1

    # Update leave balance
    cursor.execute("""
        UPDATE Leave_Balance
        SET
            used_days = used_days + %s,
            remaining_days = remaining_days - %s
        WHERE employee_id = %s
          AND leave_type_id = %s
    """, (
        leave_days,
        leave_days,
        leave_request["employee_id"],
        leave_request["leave_type_id"]
    ))

    # Save approval record
    cursor.execute("""
        INSERT INTO Approval
        (
            leave_request_id,
            approver_id,
            approval_status,
            comments,
            approved_at
        )
        VALUES
        (
            %s,
            %s,
            'Approved',
            'Leave approved by manager',
            NOW()
        )
    """, (
        request_id,
        manager_id
    ))
    cursor.execute("""
    INSERT INTO Notification
    (
        employee_id,
        title,
        message,
        notification_type
    )
    VALUES
    (
        %s,
        'Leave Request Approved',
        'Your leave request has been approved by your manager.',
        'Leave Approval'
    )
""", (
    leave_request["employee_id"],
))

    connection.commit()

    cursor.close()
    connection.close()
    

    return redirect("/manager/dashboard")

@auth.route("/employee/leave-balance")
def leave_balance():

    if "employee_id" not in session:
        return redirect(url_for("auth.login"))

    employee_id = session["employee_id"]

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    query = """
        SELECT
            lt.leave_type_name,
            lt.description,
            lb.allocated_days,
            lb.used_days,
            lb.remaining_days
        FROM Leave_Balance lb
        JOIN Leave_Type lt
            ON lb.leave_type_id = lt.leave_type_id
        WHERE lb.employee_id = %s
        ORDER BY lb.leave_type_id
    """

    cursor.execute(query, (employee_id,))
    leave_balances = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "employee/leave_balance.html",
        leave_balances=leave_balances
    )
@auth.route("/manager/leave/<int:request_id>/reject", methods=["POST"])
def reject_leave(request_id):

    if "employee_id" not in session:
        return redirect(url_for("auth.login"))

    if session.get("role") != "Manager":
        return "Access Denied", 403

    manager_id = session["employee_id"]

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # Check that the request belongs to this manager's team
    query = """
    SELECT
        lr.leave_request_id,
        lr.employee_id
    FROM Leave_Request lr
    JOIN Employee e
        ON lr.employee_id = e.employee_id
    JOIN Leave_Status ls
        ON lr.status_id = ls.status_id
    WHERE lr.leave_request_id = %s
      AND e.manager_id = %s
      AND ls.status_name = 'Pending'
    """

    cursor.execute(query, (request_id, manager_id))
    leave_request = cursor.fetchone()

    if not leave_request:
        cursor.close()
        connection.close()
        return "Leave request not found or already processed", 404

    # Get Rejected status
    cursor.execute("""
        SELECT status_id
        FROM Leave_Status
        WHERE status_name = 'Rejected'
    """)

    rejected_status = cursor.fetchone()

    if not rejected_status:
        cursor.close()
        connection.close()
        return "Rejected status not found", 500

    # Update leave request status
    cursor.execute("""
        UPDATE Leave_Request
        SET status_id = %s
        WHERE leave_request_id = %s
    """, (
        rejected_status["status_id"],
        request_id
    ))

    # Save rejection in Approval table
    cursor.execute("""
        INSERT INTO Approval
        (
            leave_request_id,
            approver_id,
            approval_status,
            comments,
            approved_at
        )
        VALUES
        (
            %s,
            %s,
            'Rejected',
            'Leave rejected by manager',
            NOW()
        )
    """, (
        request_id,
        manager_id
    ))
    cursor.execute("""
    INSERT INTO Notification
    (
        employee_id,
        title,
        message,
        notification_type
    )
    VALUES
    (
        %s,
        'Leave Request Rejected',
        'Your leave request has been rejected by your manager.',
        'Leave Rejection'
    )
""", (
    leave_request["employee_id"],
))

    connection.commit()

    cursor.close()
    connection.close()

    return redirect("/manager/dashboard")
@auth.route("/employee/leave-calendar")
def leave_calendar():

    if "employee_id" not in session:
        return redirect(url_for("auth.login"))

    employee_id = session["employee_id"]

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    query = """
        SELECT
            lr.leave_request_id,
            lt.leave_type_name,
            lr.start_date,
            lr.end_date,
            ls.status_name,
            lr.reason
        FROM Leave_Request lr
        JOIN Leave_Type lt
            ON lr.leave_type_id = lt.leave_type_id
        JOIN Leave_Status ls
            ON lr.status_id = ls.status_id
        WHERE lr.employee_id = %s
        ORDER BY lr.start_date
    """

    cursor.execute(query, (employee_id,))
    leaves = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "employee/leave_calendar.html",
        leaves=leaves
    )
@auth.route("/employee/attendance")
def attendance():
    if "employee_id" not in session:
        return redirect(url_for("auth.login"))

    employee_id = session["employee_id"]

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    # Attendance records
    query = """
        SELECT
            attendance_date,
            check_in,
            check_out,
            attendance_status
        FROM Attendance
        WHERE employee_id = %s
        ORDER BY attendance_date DESC
    """

    cursor.execute(query, (employee_id,))
    attendance_records = cursor.fetchall()

    # Attendance summary
    summary_query = """
        SELECT
            COUNT(*) AS total_days,
            SUM(
                CASE
                    WHEN attendance_status = 'Present'
                    THEN 1
                    ELSE 0
                END
            ) AS present_days,
            SUM(
                CASE
                    WHEN attendance_status = 'Absent'
                    THEN 1
                    ELSE 0
                END
            ) AS absent_days
        FROM Attendance
        WHERE employee_id = %s
    """

    cursor.execute(summary_query, (employee_id,))
    summary = cursor.fetchone()

    total_days = summary["total_days"] or 0
    present_days = summary["present_days"] or 0
    absent_days = summary["absent_days"] or 0

    if total_days > 0:
        attendance_percentage = round(
            (present_days / total_days) * 100, 2
        )
    else:
        attendance_percentage = 0

    cursor.close()
    connection.close()

    return render_template(
        "employee/attendance.html",
        attendance_records=attendance_records,
        total_days=total_days,
        present_days=present_days,
        absent_days=absent_days,
        attendance_percentage=attendance_percentage
    )
@auth.route("/employee/leave-history")
def leave_history():
    if "employee_id" not in session:
        return redirect(url_for("auth.login"))

    employee_id = session["employee_id"]

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    query = """
        SELECT
            lr.leave_request_id,
            lt.leave_type_name,
            lr.start_date,
            lr.end_date,
            lr.reason,
            ls.status_name,
            lr.applied_at
        FROM Leave_Request lr
        JOIN Leave_Type lt
            ON lr.leave_type_id = lt.leave_type_id
        JOIN Leave_Status ls
            ON lr.status_id = ls.status_id
        WHERE lr.employee_id = %s
        ORDER BY lr.applied_at DESC
    """

    cursor.execute(query, (employee_id,))
    history = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "employee/leave_history.html",
        history=history
    )
@auth.route("/employee/notifications")
def notifications():
    if "employee_id" not in session:
        return redirect(url_for("auth.login"))

    employee_id = session["employee_id"]

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    query = """
        SELECT
            notification_id,
            title,
            message,
            notification_type,
            is_read,
            created_at
        FROM Notification
        WHERE employee_id = %s
        ORDER BY created_at DESC
    """

    cursor.execute(query, (employee_id,))
    notifications = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "employee/notifications.html",
        notifications=notifications
    )
@auth.route("/manager/team")
def manager_team():
    if "employee_id" not in session:
        return redirect(url_for("auth.login"))

    if session.get("role") != "Manager":
        return "Access Denied", 403

    manager_id = session["employee_id"]

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    query = """
        SELECT
            e.employee_id,
            e.employee_code,
            e.employee_name,
            e.email,
            d.department_name,
            es.status_name
        FROM Employee e
        LEFT JOIN Department d
            ON e.department_id = d.department_id
        LEFT JOIN Employee_Status es
            ON e.employee_status_id = es.employee_status_id
        WHERE e.manager_id = %s
        ORDER BY e.employee_name
    """

    cursor.execute(query, (manager_id,))
    team_members = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "manager/team.html",
        team_members=team_members
    )
@auth.route("/manager/leave-requests")
def manager_leave_requests():
    if "employee_id" not in session:
        return redirect(url_for("auth.login"))

    if session.get("role") != "Manager":
        return "Access Denied", 403

    manager_id = session["employee_id"]

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    query = """
        SELECT
            lr.leave_request_id,
            e.employee_id,
            e.employee_name,
            e.employee_code,
            lt.leave_type_name,
            lr.start_date,
            lr.end_date,
            lr.reason,
            ls.status_name,
            lr.applied_at
        FROM Leave_Request lr

        JOIN Employee e
            ON lr.employee_id = e.employee_id

        JOIN Leave_Type lt
            ON lr.leave_type_id = lt.leave_type_id

        JOIN Leave_Status ls
            ON lr.status_id = ls.status_id

        WHERE e.manager_id = %s

        ORDER BY lr.applied_at DESC
    """

    cursor.execute(query, (manager_id,))
    leave_requests = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "manager/leave_requests.html",
        leave_requests=leave_requests
    )
    @auth.route("/manager/team-attendance")

    def manager_team_attendance():
        if "employee_id" not in session:
            return redirect(url_for("auth.login"))

    if session.get("role") != "Manager":
        return "Access Denied", 403

    manager_id = session["employee_id"]

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    query = """
        SELECT
            e.employee_id,
            e.employee_code,
            e.employee_name,
            d.department_name,
            a.attendance_date,
            a.check_in,
            a.check_out,
            a.attendance_status
        FROM Employee e

        LEFT JOIN Department d
            ON e.department_id = d.department_id

        LEFT JOIN Attendance a
            ON e.employee_id = a.employee_id

        WHERE e.manager_id = %s

        ORDER BY a.attendance_date DESC
    """

    cursor.execute(query, (manager_id,))
    attendance_records = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "manager/team_attendance.html",
        attendance_records=attendance_records
    )