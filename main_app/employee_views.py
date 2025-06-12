from datetime import datetime
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect, get_object_or_404,reverse
from django.utils import timezone
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from calendar import monthrange
from asset_app.models import Notify_Manager,LOCATION_CHOICES
from main_app.notification_badge import mark_notification_read, send_notification
from .forms import *
from .models import *
from django.db.models import Sum, F, DurationField, ExpressionWrapper
from django.db.models.functions import Coalesce
from datetime import timedelta
from asset_app.models import Notify_Manager,AssetIssue
from django.utils.timezone import localtime, make_aware
from datetime import timedelta, datetime, time
from django.core.paginator import Paginator
from datetime import date
from django.template.loader import render_to_string
from django.contrib.auth.decorators import login_required
import openpyxl
from openpyxl.styles import Font, Alignment
from io import BytesIO
from .context_processors import leave_balance_context
from zoneinfo import ZoneInfo
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, render
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db.models import Sum, F, ExpressionWrapper, DurationField
from django.db.models.functions import Coalesce
from django.utils import timezone
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, time
from calendar import monthrange
import logging
from django.utils.timezone import make_aware, now

logger = logging.getLogger(__name__)

@login_required
@transaction.atomic
def employee_home(request):
    today = timezone.now().date()
    current_time = timezone.now()
    employee = get_object_or_404(Employee, admin=request.user)
    
    logger.info(f"Employee {request.user.username} accessing dashboard on {today}")

    # Check for the first clock-in across all time
    first_clock_in = AttendanceRecord.objects.filter(
        user=request.user,
        status__in=['present', 'late', 'half_day']
    ).order_by('date').first()
    first_clock_in_date = first_clock_in.date if first_clock_in else None
    logger.debug(f"First clock-in date: {first_clock_in_date}")

    # Initialize leave balance variables
    balance = None
    total_available_leaves = 0.0

    if first_clock_in_date:
        # If there's a clock-in, initialize LeaveBalance records if not already done
        LeaveBalance.initialize_balances(employee, today)
        balance = LeaveBalance.get_balance(employee, today.year, today.month)
        if balance:
            logger.debug(f"Original Leave balance for {today.year}-{today.month}: Allocated={balance.allocated_leaves}, Carried Forward={balance.carried_forward}, Used={balance.used_leaves}, Available={balance.total_available_leaves()}")
        else:
            logger.warning(f"No LeaveBalance found for {today.year}-{today.month} after initialization")

    # Get filters from request
    date_filter = request.GET.get('date', "today")
    department_filter = request.GET.get('department')
    status_filter = request.GET.get('status')

    # Set date ranges for current month
    current_month = today.month
    current_year = today.year
    start_date = today.replace(day=1)
    if today.month == 12:
        next_month = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_month = today.replace(month=today.month + 1, day=1)
    end_date = next_month - timedelta(days=1)
    logger.debug(f"Date range for calculation: {start_date} to {end_date}")

    # Get attendance records with filters
    records = AttendanceRecord.objects.filter(user=request.user).select_related('department')
    
    # Apply date range filter if provided
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            if start_date > end_date:
                messages.warning(request, "End date must be after start date.")
                records = records.filter(date__month=current_month, date__year=current_year)
            else:
                records = records.filter(date__range=(start_date, end_date))
        except ValueError:
            messages.warning(request, "Invalid date format. Please use YYYY-MM-DD.")
            records = records.filter(date__month=current_month, date__year=current_year)
    else:
        records = records.filter(date__month=current_month, date__year=current_year)

    # Prepare detailed time entries for display
    detailed_time_entries = []
    for record in records.order_by('date', 'clock_in'):
        detailed_time_entries.append({
            'type': 'clock_in',
            'date': record.date,
            'start_time': record.clock_in,
            'end_time': record.clock_out if record.clock_out else None,
            'time': record.clock_in,
            'record': record,
            'status': 'Clocked In' if not record.clock_out else 'Clocked Out',
            'duration': record.clock_out - record.clock_in if record.clock_out else None
        })
        breaks = record.breaks.all().order_by('break_start')
        for brk in breaks:
            detailed_time_entries.append({
                'type': 'break',
                'date': record.date,
                'start_time': brk.break_start,
                'end_time': brk.break_end,
                'time': brk.break_start,
                'duration': brk.duration,
                'record': record,
                'status': 'Break End' if brk.break_end else 'Break Start'
            })
        if record.clock_out:
            detailed_time_entries.append({
                'type': 'clock_out',
                'date': record.date,
                'start_time': record.clock_in,
                'end_time': record.clock_out,
                'time': record.clock_out,
                'record': record,
                'status': 'Clocked Out',
                'duration': record.clock_out - record.clock_in
            })

    # Sort entries by date and time
    ist = ZoneInfo('Asia/Kolkata')
    min_datetime = datetime(1, 1, 1, tzinfo=ist)
    detailed_time_entries.sort(key=lambda x: (x['date'], x['time'] or min_datetime), reverse=True)

    # Pagination
    paginator = Paginator(detailed_time_entries, 10)
    page = request.GET.get('page', 1)
    try:
        paginated_entries = paginator.page(page)
    except PageNotAnInteger:
        paginated_entries = paginator.page(1)
    except EmptyPage:
        paginated_entries = paginator.page(paginator.num_pages)

    # Daily view with break time calculations
    daily_view = records.annotate(
        total_break_time=Coalesce(
            Sum('breaks__duration', output_field=DurationField()),
            timedelta()
        )
    ).annotate(
        net_worked_time=ExpressionWrapper(
            F('total_worked') - F('total_break_time'),
            output_field=DurationField()
        )
    ).order_by('-date')

    # Weekly and monthly views
    completed_records = records.filter(clock_out__isnull=False).annotate(
        total_break_time=Coalesce(
            Sum('breaks__duration', output_field=DurationField()),
            timedelta()
        )
    )

    # Weekly data aggregation
    weekly_data = {}
    for record in completed_records:
        week = record.date.isocalendar().week
        if week not in weekly_data:
            weekly_data[week] = {
                'total_hours': timedelta(),
                'regular_hours': timedelta(),
                'overtime_hours': timedelta(),
                'week_start': record.date - timedelta(days=record.date.weekday())
            }
        net_worked = record.total_worked - record.total_break_time
        weekly_data[week]['total_hours'] += net_worked
        weekly_data[week]['regular_hours'] += record.regular_hours
        weekly_data[week]['overtime_hours'] += record.overtime_hours

    weekly_view = [{
        'week': data['week_start'],
        'total_hours': data['total_hours'],
        'regular_hours': data['regular_hours'],
        'overtime_hours': data['overtime_hours']
    } for week, data in sorted(weekly_data.items(), reverse=True)]

    # Monthly data aggregation
    monthly_data = {}
    for record in completed_records:
        month_start_date = record.date.replace(day=1)
        if month_start_date not in monthly_data:
            monthly_data[month_start_date] = {
                'total_hours': timedelta(),
                'regular_hours': timedelta(),
                'overtime_hours': timedelta(),
                'present_days': 0,
                'late_days': 0,
                'half_days': 0
            }
        net_worked = record.total_worked - record.total_break_time
        monthly_data[month_start_date]['total_hours'] += net_worked
        monthly_data[month_start_date]['regular_hours'] += record.regular_hours
        monthly_data[month_start_date]['overtime_hours'] += record.overtime_hours
        if record.status == 'present':
            monthly_data[month_start_date]['present_days'] += 1
        elif record.status == 'late':
            monthly_data[month_start_date]['present_days'] += 1
            monthly_data[month_start_date]['late_days'] += 1
        elif record.status == 'half_day':
            monthly_data[month_start_date]['present_days'] += 1
            monthly_data[month_start_date]['half_days'] += 1
        elif record.status == 'leave':
            leave = LeaveReportEmployee.objects.filter(
                employee=employee,
                start_date__lte=record.date,
                end_date__gte=record.date,
                status=1
            ).first()
            if leave:
                leave_amount = 0.5 if leave.leave_type == 'Half-Day' else 1.0
                monthly_data[month_start_date]['present_days'] += leave_amount
                if leave.leave_type == 'Half-Day':
                    monthly_data[month_start_date]['half_days'] += 1
                logger.debug(f"Monthly view - Date {record.date}: Leave processed, Type={leave.leave_type}, Present Days={monthly_data[month_start_date]['present_days']}")

    monthly_view = [{
        'month': month,
        'total_hours': data['total_hours'],
        'regular_hours': data['regular_hours'],
        'overtime_hours': data['overtime_hours'],
        'present_days': data['present_days'],
        'late_days': data['late_days'],
        'half_days': data['half_days']
    } for month, data in sorted(monthly_data.items(), reverse=True)]

    # Get holidays for current month
    holidays = Holiday.objects.filter(
        date__month=current_month,
        date__year=current_year
    ).values_list('date', flat=True)
    logger.debug(f"Holidays in {current_month}/{current_year}: {list(holidays)}")

    # Calculate working days and attendance stats
    days_in_month = monthrange(current_year, current_month)[1]
    total_working_days = 0
    weekend_days_list = []
    absent_days = 0
    present_days = 0
    late_days = 0
    half_days = 0
    absent_dates = []

    logger.info(f"Calculating attendance stats for {current_month}/{current_year}")

    # Pre-fetch leaves and records for the month
    leaves = LeaveReportEmployee.objects.filter(
        employee=employee,
        status=1,  # Approved
        start_date__lte=end_date,
        end_date__gte=start_date
    ).order_by('start_date', 'id')
    logger.info(f"Found {leaves.count()} approved leaves: {[(l.id, l.start_date, l.end_date, l.leave_type) for l in leaves]}")

    # Fetch attendance records for the month
    month_records = AttendanceRecord.objects.filter(
        user=request.user,
        date__gte=start_date,
        date__lte=end_date
    ).select_related('department')
    logger.info(f"Found {month_records.count()} attendance records: {[(r.id, r.date, r.status) for r in month_records]}")

    # Get the joining date
    joining_date = employee.date_of_joining

    # First Pass: Calculate total working days for the entire month
    if not first_clock_in_date or today < first_clock_in_date:
        total_working_days = 0
        logger.debug("No clock-in yet or today is before first clock-in, setting Total Working Days to 0")
    elif joining_date.year > current_year or (joining_date.year == current_year and joining_date.month > current_month):
        total_working_days = 0
        logger.debug("Joining date is after the current month, setting Total Working Days to 0")
    else:
        start_day = 1  # Always start from the 1st of the month
        for day in range(start_day, days_in_month + 1):
            date = datetime(current_year, current_month, day).date()
            if date > end_date:
                break
            weekday = date.weekday()
            is_sunday = weekday == 6
            is_saturday = weekday == 5
            week_number = (day - 1) // 7  # 0-based week number (0 for days 1-7, 1 for days 8-14, etc.)
            is_2nd_or_4th_saturday = is_saturday and week_number in [1, 3]  # 2nd Saturday (week 1), 4th Saturday (week 3)

            if not is_sunday and not is_2nd_or_4th_saturday and date not in holidays:
                total_working_days += 1
                logger.debug(f"Working day: {date}, Total Working Days: {total_working_days}")
            else:
                weekend_days_list.append(str(date))
                logger.debug(f"Date {date} - Skipped (weekend/holiday)")

    # Second Pass: Calculate present and absent days
    if joining_date <= end_date:
        # Initialize leave balance tracking
        joining_year = joining_date.year
        joining_month = joining_date.month

        # Calculate initial available leaves at the start of the current month
        available_leaves = 0.0
        total_allocated = 0.0
        total_used_up_to_prev_month = 0.0

        # Sum allocated leaves and carried forward from joining month to previous month
        if current_year >= joining_year:
            start_month = joining_month if current_year == joining_year else 1
            for month in range(start_month, current_month):
                leave_balance = LeaveBalance.get_balance(employee, current_year, month)
                if leave_balance:
                    total_allocated += leave_balance.allocated_leaves
                    total_used_up_to_prev_month += leave_balance.used_leaves
            # Include current month's allocation but not its used leaves yet
            current_balance = LeaveBalance.get_balance(employee, current_year, current_month)
            if current_balance:
                total_allocated += current_balance.allocated_leaves
        available_leaves = total_allocated - total_used_up_to_prev_month
        logger.debug(f"Initial available leaves at start of {current_month}/{current_year}: Total Allocated={total_allocated}, Used up to prev month={total_used_up_to_prev_month}, Available={available_leaves}")

        # Process leaves in chronological order to reconstruct available leaves at each point
        leave_history = []
        for leave in leaves:
            start = max(leave.start_date, start_date)
            end = min(leave.end_date, end_date)
            leave_amount_per_day = 1.0 if leave.leave_type == 'Full-Day' else 0.5
            current_date = start
            while current_date <= end:
                if current_date.month == current_month:
                    # Check if the date is a working day
                    weekday = current_date.weekday()
                    is_sunday = weekday == 6
                    is_saturday = weekday == 5
                    week_number = (current_date.day - 1) // 7
                    is_2nd_or_4th_saturday = is_saturday and week_number in [1, 3]
                    if not is_sunday and not is_2nd_or_4th_saturday and current_date not in holidays:
                        leave_history.append({
                            'date': current_date,
                            'leave_amount': leave_amount_per_day,
                            'leave_id': leave.id,
                            'leave_type': leave.leave_type,
                        })
                current_date += timedelta(days=1)

        # Sort leave history by date to process in order
        leave_history.sort(key=lambda x: x['date'])
        logger.debug(f"Leave history to process: {[entry for entry in leave_history]}")

        # Track available leaves as we process each leave
        for entry in leave_history:
            date = entry['date']
            leave_amount = entry['leave_amount']
            leave_id = entry['leave_id']
            leave_type = entry['leave_type']

            logger.debug(f"Processing historical leave on {date} - Leave ID={leave_id}, Type={leave_type}, Amount={leave_amount}, Available Before={available_leaves}")

            if available_leaves >= leave_amount:
                # Sufficient leaves at the time of this leave
                available_leaves -= leave_amount
                entry['was_sufficient'] = True
                logger.debug(f"Leave on {date} - Sufficient leaves, Available After={available_leaves}")
            else:
                # Insufficient leaves
                available_leaves = max(0, available_leaves - leave_amount)
                entry['was_sufficient'] = False
                logger.debug(f"Leave on {date} - Insufficient leaves, Available After={available_leaves}")

        # Now calculate present and absent days, starting from joining_date
        start_day = joining_date.day if joining_date.year == current_year and joining_date.month == current_month else 1
        for day in range(1, days_in_month + 1):  # Loop through the entire month
            date = datetime(current_year, current_month, day).date()
            if date > end_date:
                break
            weekday = date.weekday()
            is_sunday = weekday == 6
            is_saturday = weekday == 5
            week_number = (day - 1) // 7
            is_2nd_or_4th_saturday = is_saturday and week_number in [1, 3]
            if is_sunday or is_2nd_or_4th_saturday or date in holidays:
                continue  # Skip weekends and holidays

            # Skip days before the joining date
            if date < joining_date:
                continue

            # Skip if today is before the first clock-in date or no clock-in exists
            if not first_clock_in_date or today < first_clock_in_date:
                continue

            # Check for attendance record
            record = month_records.filter(date=date).first()
            # Check for approved leave
            leave_entry = next((entry for entry in leave_history if entry['date'] == date), None)

            if record and record.status in ['present', 'late', 'half_day']:
                if record.status == 'present':
                    present_days += 1
                    logger.debug(f"Date {date} - Status={record.status}, Present Days={present_days}")
                elif record.status == 'late':
                    present_days += 1
                    late_days += 1
                    logger.debug(f"Date {date} - Status={record.status}, Present Days={present_days}, Late Days={late_days}")
                elif record.status == 'half_day':
                    present_days += 1
                    half_days += 1
                    logger.debug(f"Date {date} - Status={record.status}, Present Days={present_days}, Half Days={half_days}")
            elif leave_entry:
                leave_amount = leave_entry['leave_amount']
                leave_id = leave_entry['leave_id']
                was_sufficient = leave_entry['was_sufficient']
                
                if was_sufficient:
                    # Sufficient leaves at the time of application
                    present_days += leave_amount
                    if leave_entry['leave_type'] == 'Half-Day':
                        half_days += 0.5
                    logger.debug(f"Date {date} - Approved Leave ID={leave_id}, Type={leave_entry['leave_type']}, Sufficient Leaves, Present Days={present_days}")
                else:
                    # Insufficient leaves at the time of application
                    absent_days += 1
                    logger.debug(f"Date {date} - Approved Leave ID={leave_id}, Type={leave_entry['leave_type']}, Insufficient Leaves, Absent Days={absent_days}")
            elif date <= today:
                # If there's a first clock-in, mark as absent from joining_date to the day before first_clock_in_date
                if first_clock_in_date and date < first_clock_in_date:
                    absent_days += 1
                    absent_dates.append(date)
                    logger.debug(f"Date {date} - Marked as absent (before first clock-in), Absent Days={absent_days}")
                elif not record and not leave_entry:
                    # Mark as absent if no record or leave after first clock-in
                    absent_days += 1
                    absent_dates.append(date)
                    logger.debug(f"Date {date} - Marked as absent (no record or leave), Absent Days={absent_days}")

    # Update total available leaves for context
    if balance:
        total_available_leaves = balance.total_available_leaves()
        logger.debug(f"After adjustments - Leave balance for {today.year}-{today.month}: Allocated={balance.allocated_leaves}, Carried Forward={balance.carried_forward}, Used={balance.used_leaves}, Available={balance.total_available_leaves()}")

    # Get leave balance context after adjustments
    leave_context = leave_balance_context(request)
    yearly_leave_data = leave_context['yearly_leave_data']
    employee_name = leave_context.get('employee_name', employee.admin.get_full_name())
    department = leave_context.get('department', employee.department.name if employee.department else 'N/A')

    # Check current clock-in status
    current_record = AttendanceRecord.objects.filter(
        user=request.user,
        clock_out__isnull=True,
        date=today,
        status__in=['present', 'late', 'half_day']
    ).first()

    current_break = None
    if current_record:
        current_break = Break.objects.filter(
            attendance_record=current_record,
            break_end__isnull=True
        ).first()

    # Find the employee's schedule for today
    schedule = DailySchedule.objects.filter(
        employee=employee,
        date=today
    ).first()

    # Check if today's update has been submitted for the employee's schedule
    has_submitted_update = False
    if schedule:
        has_submitted_update = DailyUpdate.objects.filter(
            schedule=schedule,
            updated_at__date=today
        ).exists()
    logger.debug(f"Has submitted today's update: {has_submitted_update}")

    # Break statistics
    total_breaks_in_month = Break.objects.filter(
        attendance_record__date__month=current_month,
        attendance_record__date__year=current_year,
        attendance_record__user=request.user
    ).count()

    todays_breaks = Break.objects.filter(
        attendance_record__date=today,
        attendance_record__user=request.user
    ).count()

    logger.info(f"Final Attendance Stats - Total Working Days: {total_working_days}, Present Days: {present_days}, Late Days: {late_days}, Half Days: {half_days}, Absent Days: {absent_days}")

    # Calculate attendance percentage
    attendance_percentage = round((present_days / total_working_days * 100) if total_working_days > 0 else 0, 1)
    logger.debug(f"Attendance Percentage: {attendance_percentage}%")

    # Today's time tracking
    today_records = AttendanceRecord.objects.filter(
        user=request.user,
        date=today
    ).order_by('clock_in')

    today_total_worked = timedelta()
    today_status = 'Not Clocked In Today'
    today_late = False
    today_half_day = False
    today_duration_str = None
    today_clock_in_time = None
    today_clock_out_time = None
    today_current_duration_str = None
    today_late_duration_str = None
    lunch_taken = False
    on_break = False
    lunch_taken_time = None
    break_taken_time = None

    if today_records.exists():
        today_record = today_records.first()
        today_clock_in_time = today_record.clock_in
        last_clock_out_record = today_records.filter(clock_out__isnull=False).last()
        today_clock_out_time = last_clock_out_record.clock_out if last_clock_out_record else None

        clock_in_ist = today_record.clock_in.astimezone(ist) if today_record.clock_in else None
        office_start = datetime.combine(today, time(9, 0)).replace(tzinfo=ist) if clock_in_ist else None

        if current_record:
            today_status = 'Clocked In'
        elif today_clock_out_time:
            today_status = 'Clocked Out'
        else:
            today_status = 'Not Clocked In Today'

        today_late = today_record.status == 'late'
        today_half_day = today_record.status == 'half_day'

        # Calculate late duration if applicable
        if clock_in_ist and clock_in_ist > office_start:
            late_duration = clock_in_ist - office_start
            total_seconds = late_duration.total_seconds()
            hours = int(total_seconds // 3600)
            minutes = int((total_seconds % 3600) // 60)
            today_late_duration_str = f"{hours} hours {minutes} minutes" if total_seconds > 0 else "0 hours 0 minutes"
        else:
            today_late_duration_str = "0 hours 0 minutes"

        # Calculate worked duration
        first_clock_in = today_record.clock_in
        last_clock_out = today_clock_out_time

        if first_clock_in and last_clock_out:
            today_total_worked = last_clock_out - first_clock_in
            total_break_time = sum(
                (brk.duration for record in today_records for brk in record.breaks.all() if brk.duration),
                timedelta()
            )
            today_total_worked -= total_break_time
            total_seconds = today_total_worked.total_seconds()
            hours = int(total_seconds // 3600)
            minutes = int((total_seconds % 3600) // 60)
            today_duration_str = f"{hours} hours {minutes} minutes" if total_seconds > 0 else "0 hours 0 minutes"
        elif first_clock_in and not last_clock_out:
            current_duration = current_time - first_clock_in
            total_break_time = sum(
                (brk.duration for record in today_records for brk in record.breaks.all() if brk.duration),
                timedelta()
            )
            current_duration -= total_break_time
            total_seconds = current_duration.total_seconds()
            if total_seconds < 0:
                total_seconds = 0
            hours = int(total_seconds // 3600)
            minutes = int((total_seconds % 3600) // 60)
            today_current_duration_str = f"{hours} hours {minutes} minutes" if total_seconds > 0 else "0 hours 0 minutes"
            today_duration_str = today_current_duration_str
        else:
            today_duration_str = "0 hours 0 minutes"
            today_late_duration_str = "0 hours 0 minutes"

    # Check break status
    lunch_taken = Break.objects.filter(
        attendance_record__user=request.user,
        attendance_record__date=today,
        break_type='lunch'
    ).exists()

    on_break = current_break is not None

    lunch_break = Break.objects.filter(
        attendance_record__user=request.user,
        attendance_record__date=today,
        break_type='lunch'
    ).first()
    if lunch_break:
        lunch_taken_time = lunch_break.break_start

    recent_break = Break.objects.filter(
        attendance_record__user=request.user,
        attendance_record__date=today
    ).exclude(break_type='lunch').order_by('-break_start').first()
    if recent_break:
        break_taken_time = recent_break.break_start

    # Get recent activity
    recent_activities = ActivityFeed.objects.filter(
        user=request.user
    ).order_by('-timestamp').first()

    # Prepare context
    context = {
        'page_title': 'Employee Dashboard',
        'employee': employee,
        'employee_name': employee_name,
        'department': department,
        'today_total_worked': today_total_worked,
        'today_duration_str': today_duration_str,
        'today_current_duration_str': today_current_duration_str,
        'today_late_duration_str': today_late_duration_str,
        'today_status': today_status,
        'today_record': today_records.first() if today_records.exists() else None,
        'today_late': today_late,
        'today_half_day': today_half_day,
        'today_clock_in_time': today_clock_in_time,
        'today_clock_out_time': today_clock_out_time,
        'current_record': current_record,
        'current_break': current_break,
        'recent_activities': recent_activities,
        'lunch_taken': lunch_taken,
        'on_break': on_break,
        'lunch_taken_time': lunch_taken_time,
        'break_taken_time': break_taken_time,
        'has_submitted_update': has_submitted_update,
        'attendance_stats': {
            'total_days': total_working_days,
            'present_days': present_days,
            'late_days': late_days,
            'half_days': half_days,
            'absent_days': absent_days,
            'attendance_percentage': attendance_percentage,
            'total_breaks_in_month': total_breaks_in_month,
            'todays_total_breaks': todays_breaks,
        },
        'yearly_leave_data': yearly_leave_data,
        'total_available_leaves': round(total_available_leaves, 1),
        'detailed_time_entries': paginated_entries,
        'daily_view': daily_view,
        'weekly_view': weekly_view,
        'monthly_view': monthly_view,
        'current_filters': {
            'date': date_filter,
            'department': department_filter,
            'status': status_filter,
            'month': str(current_month),
            'year': str(current_year),
            'start_date': start_date_str,
            'end_date': end_date_str,
        },
        'status_choices': AttendanceRecord.STATUS_CHOICES,
    }

    # Handle AJAX requests
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' and request.method == 'GET':
        try:
            html = render_to_string('employee_template/home_content.html', context, request=request)
            return JsonResponse({
                'html': html,
                'current_page': paginated_entries.number,
                'num_pages': paginator.num_pages,
                'has_previous': paginated_entries.has_previous(),
                'has_next': paginated_entries.has_next(),
                'previous_page_number': paginated_entries.previous_page_number() if paginated_entries.has_previous() else None,
                'next_page_number': paginated_entries.next_page_number() if paginated_entries.has_next() else None,
            })
        except Exception as e:
            logger.error(f"Error rendering AJAX response for {request.user}: {str(e)}")
            return JsonResponse({'status': 'error', 'message': 'Error loading data.'}, status=500)

    logger.debug(f"Rendering dashboard with context: Present Days={present_days}, Absent Days={absent_days}")
    return render(request, 'employee_template/home_content.html', context)




@login_required
def leave_balance(request):
    employee = get_object_or_404(Employee, admin=request.user)
    today = get_ist_date()
    current_year = today.year
    current_month = today.month

    # Check for the first clock-in
    first_clock_in = AttendanceRecord.objects.filter(
        user=request.user,
        status__in=['present', 'late', 'half_day']
    ).order_by('date').first()

    yearly_leave_data = []
    total_available_leaves = 0.0
    yearly_total_allocated_leaves = 0.0

    if not first_clock_in:
        # Before first clock-in, show all values as 0.0 and an empty table
        context = {
            'page_title': 'Leave Balance',
            'employee': employee,
            'yearly_leave_data': yearly_leave_data,
            'total_available_leaves': round(total_available_leaves, 1),
            'yearly_total_allocated_leaves': round(yearly_total_allocated_leaves, 1),
        }
        return render(request, 'employee_template/leave_balance.html', context)

    # After first clock-in, proceed with actual calculations
    leave_balances = LeaveBalance.objects.filter(employee=employee, year=current_year).order_by('month')
    joining_date = employee.date_of_joining

    if joining_date:
        joining_year = joining_date.year
        joining_month = joining_date.month

        # Calculate yearly total allocated leaves (from joining month to December)
        if current_year >= joining_year:
            start_month = joining_month if current_year == joining_year else 1
            end_month = 12  # Always calculate until the end of the year
            # Number of months from start_month to end_month (inclusive)
            months_in_year = end_month - start_month + 1
            yearly_total_allocated_leaves = months_in_year * 1.0  # 1 leave per month

            # Adjust yearly total allocated leaves by subtracting available leaves for current month if fully used
            current_month_balance = leave_balances.filter(month=current_month).first()
            if current_month_balance and current_month_balance.total_available_leaves() == 0.0:
                yearly_total_allocated_leaves = max(0.0, yearly_total_allocated_leaves - (current_month_balance.allocated_leaves + current_month_balance.carried_forward))

        # Process monthly leave balances for display in the table
        for month in range(1, 13):
            if current_year < joining_year or (current_year == joining_year and month < joining_month):
                continue
            balance = leave_balances.filter(month=month).first()
            if not balance and month <= current_month:
                balance = LeaveBalance.get_balance(employee, current_year, month)
                if not balance:
                    balance = LeaveBalance.create_balance(employee, current_year, month)
            if balance:
                # Validate used_leaves for the current month
                if month == current_month:
                    max_used_leaves = balance.allocated_leaves + balance.carried_forward
                    if balance.used_leaves > max_used_leaves:
                        balance.used_leaves = max_used_leaves
                        balance.save()
                
                yearly_leave_data.append({
                    'month': datetime(current_year, month, 1).strftime('%B'),
                    'allocated_leaves': balance.allocated_leaves,
                    'carried_forward': balance.carried_forward,
                    'used_leaves': balance.used_leaves,
                    'available_leaves': balance.total_available_leaves()
                })
                if month == current_month:
                    total_available_leaves = balance.total_available_leaves()

    context = {
        'page_title': 'Leave Balance',
        'employee': employee,
        'yearly_leave_data': yearly_leave_data,
        'total_available_leaves': round(total_available_leaves, 1),
        'yearly_total_allocated_leaves': round(yearly_total_allocated_leaves, 1),
    }
    return render(request, 'employee_template/leave_balance.html', context)
    

@login_required
def employee_apply_leave(request):
    employee = get_object_or_404(Employee, admin=request.user)
    unread_ids = Notification.objects.filter(
        user=request.user,
        role="employee",
        is_read=False,
        notification_type="leave"
    ).values_list('leave_or_notification_id', flat=True)

    leave_list = LeaveReportEmployee.objects.filter(employee=employee).order_by('-created_at')
    paginator = Paginator(leave_list, 5)
    page_number = request.GET.get('page')
    leave_page = paginator.get_page(page_number)

    if request.method == 'POST':
        leave_type = request.POST.get('leave_type')
        half_day_type = request.POST.get('half_day_type') if leave_type == 'Half-Day' else None
        start_date_str = request.POST.get('start_date')
        end_date_str = request.POST.get('end_date')
        message = request.POST.get('message')

        if not all([leave_type, start_date_str, message]):
            messages.error(request, "All fields are required.")
            return redirect('employee_apply_leave')

        try:
            start_date = date.fromisoformat(start_date_str)
            end_date = date.fromisoformat(end_date_str) if end_date_str else start_date
            if end_date < start_date:
                messages.error(request, "End date cannot be before start date.")
                return redirect('employee_apply_leave')
        except ValueError:
            messages.error(request, "Invalid date format.")
            return redirect('employee_apply_leave')

        # Check for overlapping leaves
        existing_leaves = LeaveReportEmployee.objects.filter(
            employee=employee,
            start_date__lte=end_date,
            end_date__gte=start_date,
            status__in=[0, 1]  # Pending or Approved
        ).exists()
        if existing_leaves:
            messages.error(request, "You already have a leave request for these dates.")
            return redirect('employee_apply_leave')

        try:
            leave_request = LeaveReportEmployee.objects.create(
                employee=employee,
                leave_type=leave_type,
                half_day_type=half_day_type,
                start_date=start_date,
                end_date=end_date,
                message=message
            )
            messages.success(request, "Your leave request has been submitted.")
            user = CustomUser.objects.get(id=employee.team_lead.admin.id)
            send_notification(user, "Leave Applied", "leave-notification", leave_request.id, "manager")
            
            admin_users = CustomUser.objects.filter(is_superuser=True)
            if admin_users.exists():
                for admin_user in admin_users:
                    send_notification(admin_user, "Leave Applied", "employee-leave-notification", leave_request.id, "ceo")
            
            return redirect(reverse('employee_apply_leave'))
            
        except Exception as e:
            messages.error(request, f"Error submitting leave: {str(e)}")
            return redirect('employee_apply_leave')

    context = {
        'leave_page': leave_page,
        'unread_ids': list(unread_ids),
        'page_title': 'Apply for Leave',
    }
    return render(request, 'employee_template/employee_apply_leave.html', context)


@login_required   
def employee_feedback(request):
    employee = get_object_or_404(Employee, admin_id=request.user.id)
    form = FeedbackEmployeeForm(request.POST or None)
    
    # Paginate feedback list
    feedbacks_list = FeedbackEmployee.objects.filter(employee=employee).order_by('-created_at')
    paginator = Paginator(feedbacks_list, 5)  # 5 items per page
    page_number = request.GET.get('page')
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    context = {
        'form': form,
        'page_obj': page_obj,
        'page_title': 'Employee Feedback'
    }

    # mark_notification_read(request, 0, "feedback", "employee")

    if request.method == 'POST':
        if form.is_valid():
            try:
                obj = form.save(commit=False)
                obj.employee = employee
                obj.save()
                messages.success(request, "Feedback submitted for review")
                user = CustomUser.objects.get(id=employee.team_lead.admin.id)
                send_notification(user, f"Feedback submitted for review for {obj.id}", "employee feedback", obj.id, "admin")
                # For AJAX form submission, return JSON
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    html = render_to_string('employee_template/employee_feedback.html', context, request=request)
                    return JsonResponse({
                        'html': html,
                        'success': True,
                        'message': "Feedback submitted for review"
                    })
                return redirect(reverse('employee_feedback'))
            except Exception:
                messages.error(request, "Could not Submit!")
        else:
            messages.error(request, "Form has errors!")
        
        # Handle form errors for AJAX
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'message': "Form has errors!" if form.errors else "Could not Submit!",
                'errors': form.errors.as_json()
            })

    # Handle AJAX pagination
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' and request.method == 'GET':
        html = render_to_string('employee_template/employee_feedback.html', context, request=request)
        return JsonResponse({
            'html': html,
            'current_page': page_obj.number,
            'num_pages': paginator.num_pages,
            'has_previous': page_obj.has_previous(),
            'has_next': page_obj.has_next(),
            'previous_page_number': page_obj.previous_page_number() if page_obj.has_previous() else None,
            'next_page_number': page_obj.next_page_number() if page_obj.has_next() else None,
        })

    return render(request, "employee_template/employee_feedback.html", context)


@login_required   
def employee_view_profile(request):
    employee = get_object_or_404(Employee, admin=request.user)
    context = {'employee': employee,
               'page_title': 'Profile'
               }
    return render(request, "employee_template/employee_view_profile.html", context)


@login_required   
@csrf_exempt
def employee_fcmtoken(request):
    token = request.POST.get('token')
    employee_user = get_object_or_404(CustomUser, id=request.user.id)
    try:
        employee_user.fcm_token = token
        employee_user.save()
        return HttpResponse("True")
    except Exception as e:
        return HttpResponse("False")

logger = logging.getLogger(__name__)

@login_required
@csrf_exempt
def employee_view_attendance(request):
    try:
        employee = get_object_or_404(Employee, admin=request.user)
        
        if request.method == 'GET':
            division = get_object_or_404(Division, id=employee.division.id)
            context = {
                'departments': Department.objects.filter(division=division),
                'page_title': 'View Attendance',
                'default_start': (now() - timedelta(days=7)).strftime('%Y-%m-%d'),
                'default_end': now().strftime('%Y-%m-%d')  # Ensure today is included
            }
            return render(request, 'employee_template/employee_view_attendance.html', context)

        elif request.method == 'POST':
            start_date_str = request.POST.get('start_date')
            end_date_str = request.POST.get('end_date')
            page = request.POST.get('page', 1)

            logger.info(f"POST params: start_date={start_date_str}, end_date={end_date_str}, page={page}")

            if not all([start_date_str, end_date_str]):
                return JsonResponse({'error': 'Missing start_date or end_date'}, status=400)

            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            except ValueError:
                return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)

            if start_date > end_date:
                return JsonResponse({'error': 'Start date cannot be after end date'}, status=400)

            # Include records with clock_out=None for ongoing sessions
            all_records = AttendanceRecord.objects.filter(
                user=request.user,
                date__range=(start_date, end_date)
            ).exclude(clock_in=None).order_by('date', 'clock_in')

            logger.info(f"Records found: {all_records.count()}")

            daily_summaries = {}
            for record in all_records:
                date_str = record.date.strftime('%Y-%m-%d')
                if date_str not in daily_summaries:
                    daily_summaries[date_str] = {
                        'date': date_str,
                        'first_clock_in': make_aware(record.clock_in) if record.clock_in and not record.clock_in.tzinfo else record.clock_in,
                        'last_clock_out': make_aware(record.clock_out) if record.clock_out and not record.clock_out.tzinfo else record.clock_out,
                        'status': record.status,
                        'total_worked': record.total_worked or timedelta(),
                        'records_count': 1
                    }
                else:
                    day = daily_summaries[date_str]
                    if record.clock_in and (not day['first_clock_in'] or record.clock_in < day['first_clock_in']):
                        day['first_clock_in'] = make_aware(record.clock_in) if not record.clock_in.tzinfo else record.clock_in
                    if record.clock_out and (not day['last_clock_out'] or record.clock_out > day['last_clock_out']):
                        day['last_clock_out'] = make_aware(record.clock_out) if not record.clock_out.tzinfo else record.clock_out
                    if record.status == 'late':
                        day['status'] = 'late'
                    if record.total_worked:
                        day['total_worked'] += record.total_worked
                    day['records_count'] += 1

            json_data = []
            for date_str, day in sorted(daily_summaries.items(), reverse=True):
                lunch_start = make_aware(datetime.combine(datetime.strptime(date_str, '%Y-%m-%d'), time(13, 0)))
                lunch_end = make_aware(datetime.combine(datetime.strptime(date_str, '%Y-%m-%d'), time(13, 40)))

                # Adjust total_worked only for completed sessions
                if day['first_clock_in'] and day['last_clock_out'] and day['first_clock_in'] <= lunch_start and day['last_clock_out'] >= lunch_end:
                    day['total_worked'] -= timedelta(minutes=40)

                total_worked_str = '--'
                if day['total_worked'] and str(day['total_worked']) != '0:00:00':
                    total_seconds = int(day['total_worked'].total_seconds())
                    hours = total_seconds // 3600
                    minutes = (total_seconds % 3600) // 60
                    total_worked_str = f"{hours}h {minutes}m"
                elif not day['last_clock_out']:  # Ongoing session
                    current_time = make_aware(now())
                    if day['first_clock_in'] and current_time > day['first_clock_in']:
                        worked = current_time - day['first_clock_in']
                        if day['first_clock_in'] <= lunch_start and current_time >= lunch_end:
                            worked -= timedelta(minutes=40)
                        total_seconds = int(worked.total_seconds())
                        hours = total_seconds // 3600
                        minutes = (total_seconds % 3600) // 60
                        total_worked_str = f"{hours}h {minutes}m (ongoing)"

                json_data.append({
                    "date": date_str,
                    "status": day['status'],
                    "clock_in": day['first_clock_in'].strftime('%I:%M %p') if day['first_clock_in'] else '--',
                    "clock_out": day['last_clock_out'].strftime('%I:%M %p') if day['last_clock_out'] else 'Ongoing',
                    "total_worked": total_worked_str,
                    "records_count": day['records_count']
                })

            paginator = Paginator(json_data, 5)
            try:
                page_obj = paginator.page(page)
            except PageNotAnInteger:
                page_obj = paginator.page(1)
            except EmptyPage:
                page_obj = paginator.page(paginator.num_pages)

            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                context = {
                    'page_title': 'View Attendance',
                    'default_start': start_date_str,
                    'default_end': end_date_str,
                    'page_obj': page_obj,
                    'json_data': page_obj.object_list,
                }
                html = render_to_string('employee_template/employee_view_attendance.html', context, request=request)
                return JsonResponse({
                    'html': html,
                    'current_page': page_obj.number,
                    'num_pages': paginator.num_pages,
                    'has_previous': page_obj.has_previous(),
                    'has_next': page_obj.has_next(),
                    'previous_page_number': page_obj.previous_page_number() if page_obj.has_previous() else None,
                    'next_page_number': page_obj.next_page_number() if page_obj.has_next() else None,
                })

            return JsonResponse({'data': page_obj.object_list}, safe=False)

    except Exception as e:
        logger.error(f"Error in employee_view_attendance: {str(e)}", exc_info=True)
        return JsonResponse({'error': 'Internal server error. Please try again later.'}, status=500)

        
@login_required   
def employee_view_salary(request):
    employee = get_object_or_404(Employee, admin=request.user)
    salarys = EmployeeSalary.objects.filter(employee=employee)
    context = {
        'salarys': salarys,
        'page_title': "View Salary"
    }
    return render(request, "employee_template/employee_view_salary.html", context)


@login_required   
def employee_view_notification(request):
    employee = get_object_or_404(Employee, admin=request.user)
    
    all_notifications = NotificationEmployee.objects.filter(
        employee=employee
    ).order_by('-created_at')

    notification_from_admin = all_notifications.filter(
        created_by__is_superuser=True
    )
    
    notification_from_manager = all_notifications.filter(
        created_by__is_superuser=False
    )
    
    # get all unread notification 
    unread_notifications = Notification.objects.filter(
        user = request.user,
        role = 'employee',
        is_read=False,
    ).order_by('-timestamp')

    # notification from manager/admin(general-notification)
    general_notification = unread_notifications.filter(
        notification_type__in = ['notification-from-manager' , 'notification-from-admin']
    ).values_list('leave_or_notification_id', flat=True)

    # leave_request notification(is it approved/rejected ?)
    leave_notification = unread_notifications.filter(
        notification_type = 'leave-notification'
    )
    
    # unread_ids = list(notification_ids)
    admin_paginator = Paginator(notification_from_admin, 10)
    admin_page_number = request.GET.get('notification_page')
    notification_from_admin_obj = admin_paginator.get_page(admin_page_number)
    manager_paginator = Paginator(notification_from_manager, 10)
    manager_page_number = request.GET.get('manager_page')
    notification_from_manager_obj = manager_paginator.get_page(manager_page_number)
    
    context = {
        'notification_from_admin_obj': notification_from_admin_obj,
        'notification_from_manager_obj': notification_from_manager_obj,
        'total_notifications': notification_from_admin.count(),
        'total_manager_notifications': notification_from_manager.count(),
        'page_title': "View Notifications",
        # 'manager_unread_ids': unread_ids,
        'LOCATION_CHOICES': LOCATION_CHOICES,
        'general_notification' : general_notification,
        'leave_notification' : leave_notification
    }

    return render(request, "employee_template/employee_view_notification.html", context)


@login_required   
def employee_requests(request):
    try:
        employee = Employee.objects.get(admin=request.user)
    except Employee.DoesNotExist:
        messages.error(request, "Employee not found.")
        employee = None

    # Leave Requests Pagination
    leave_requests = LeaveReportEmployee.objects.filter(employee=employee).order_by('-created_at')
    leave_paginator = Paginator(leave_requests, 5)  
    leave_page_number = request.GET.get('leave_page')
    leave_requests_page = leave_paginator.get_page(leave_page_number)

    # Asset Claims Pagination
    asset_claims = Notify_Manager.objects.filter(employee=request.user).order_by('-timestamp')
    asset_paginator = Paginator(asset_claims, 5) 
    asset_page_number = request.GET.get('asset_page')
    asset_claims_page = asset_paginator.get_page(asset_page_number)

    # Asset Issues Pagination
    asset_issues = AssetIssue.objects.filter(reported_by=request.user).order_by('reported_date')
    issue_paginator = Paginator(asset_issues, 5)  
    issue_page_number = request.GET.get('issue_page')
    asset_issues_page = issue_paginator.get_page(issue_page_number)

    unread_notifications = Notification.objects.filter(
        user = request.user,
        is_read = False
    ).values_list('leave_or_notification_id' , flat=True)

    context = {
        'leave_requests': leave_requests_page,
        'asset_claims': asset_claims_page,
        'asset_issues': asset_issues_page,
        'page_title': 'My Requests',
        'unread_notifications' : list(unread_notifications)
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        # Render the entire template but client-side JS will extract relevant parts
        html = render_to_string('employee_template/employee_requests.html', context, request=request)
        return HttpResponse(html)

    return render(request, 'employee_template/employee_requests.html', context)



logger = logging.getLogger(__name__)

def get_ist_date():
    ist = pytz.timezone('Asia/Kolkata')
    return timezone.now().astimezone(ist).date()

def get_ist_datetime():
    return timezone.now().astimezone(pytz.timezone('Asia/Kolkata'))

@login_required
def daily_schedule(request):
    employee = get_object_or_404(Employee, admin=request.user)
    today = get_ist_date()
    now = get_ist_datetime()

    # Check if employee has clocked in today, redirect to home if not
    attendance_record = AttendanceRecord.objects.filter(
        user=request.user,
        date=today,
        clock_in__isnull=False,
        clock_out__isnull=True
    ).first()

    if not attendance_record:
        messages.error(request, "Please clock in first.")
        return redirect('employee_home')

    schedule = DailySchedule.objects.filter(employee=employee, date=today).first()

    # Check if editing is allowed (within 30 minutes of creation)
    allow_edit = True
    if schedule:
        # Ensure created_at is timezone-aware
        created_at_aware = schedule.created_at.astimezone(pytz.timezone('Asia/Kolkata')) if schedule.created_at.tzinfo is None else schedule.created_at
        edit_window = created_at_aware + timedelta(minutes=30)
        allow_edit = now <= edit_window

    if request.method == 'POST' and allow_edit:
        task_description = request.POST.get('task_description', '').strip()
        project = request.POST.get('project', '').strip()
        justification = request.POST.get('justification', '').strip()

        if not task_description:
            messages.error(request, "Please add at least one task.")
            return redirect('daily_schedule')
        
        tasks = [line.strip() for line in task_description.split("\n") if line.strip()]

        # Parse tasks and calculate total minutes
        total_minutes = 0
        for line in tasks:
            try:
                time_part = line.split('|')[1].strip().lower()
                if 'h' in time_part:
                    total_minutes += float(time_part.replace('h', '')) * 60
                elif 'm' in time_part:
                    total_minutes += float(time_part.replace('m', ''))
                elif 's' in time_part:
                    total_minutes += float(time_part.replace('s', '')) / 60
                else:
                    total_minutes += float(time_part)
            except (ValueError, IndexError):
                messages.error(request, f"Invalid time value in task: {line}")
                return redirect('daily_schedule')

        total_hours = total_minutes / 60

        # Check for justification if less than 8 hours
        if total_hours < 8 and not justification:
            messages.error(request, "Please provide justification for scheduling less than 8 hours.")
            return redirect('daily_schedule')

        if schedule:
            # Update existing schedule
            schedule.task_description = task_description
            schedule.project = project
            schedule.justification = justification
            schedule.total_hours = total_hours
            try:
                schedule.full_clean()
                schedule.save()
                messages.success(request, "Schedule updated successfully!")
            except ValidationError as e:
                messages.error(request, f"Error updating schedule: {e}")
        else:
            # Create new schedule
            schedule = DailySchedule(
                employee=employee,
                date=today,
                task_description=task_description,
                project=project,
                justification=justification,
                total_hours=total_hours
            )
            try:
                schedule.full_clean()
                schedule.save()

                time_since_clock_in = schedule.created_at - attendance_record.clock_in
                if time_since_clock_in > timedelta(minutes=30):
                    attendance_record.status = 'half_day'
                attendance_record.save()

                messages.success(request, f"Schedule created successfully.")

            except ValidationError as e:
                messages.error(request, f"Error creating schedule: {e}")

        return redirect('daily_schedule')

    show_form = False
    if request.GET.get('edit') == 'true' and allow_edit:
        show_form = True
    elif not schedule:
        show_form = True

    edit_tasks = []
    if schedule and schedule.task_description:
        for task in schedule.task_description.splitlines():
            parts = task.split('|')
            if len(parts) >= 2:
                edit_tasks.append({
                    'description' : parts[0].strip(),
                    'time' : parts[1].strip()
                })

    context = {
        'schedule': schedule,
        'today': today,
        'allow_edit': allow_edit,
        'now': now,
        'show_form': show_form,
        'edit_tasks': edit_tasks,
    }

    return render(request, 'employee_template/daily_schedule.html', context)
    
    
    
    
    
def get_ist_date():
    ist = timezone.get_current_timezone()
    return timezone.now().astimezone(ist).date()

@login_required
def todays_update(request):
    employee = get_object_or_404(Employee, admin=request.user)
    today = get_ist_date()
    schedule = DailySchedule.objects.filter(employee=employee, date=today).first()

    attendance_record = AttendanceRecord.objects.filter(
        user=request.user,
        date=today,
        clock_in__isnull=False,
        clock_out__isnull=False
    ).first()

    if attendance_record:
        messages.error(request,"Can't update record after clock-out.  Only can view in your All Schedules")
        return redirect('employee_home')
    
    if not schedule:
        messages.error(request, "Create a schedule first!")
        return redirect('daily_schedule')

    existing_update = schedule.updates.first()
    is_editable = not existing_update or existing_update.updated_at.date() == today

    if request.method == 'POST' and is_editable:
        update_description = request.POST.get('update_description', '')
        justification = request.POST.get('justification', '')
        
        # Validate updates
        updates = [line.strip() for line in update_description.split("\n") if line.strip()]
        invalid_updates = [u for u in updates if '|' not in u or len(u.split('|')) != 2]
        
        if invalid_updates:
            messages.error(request, "Each update must include description and time spent (e.g., 'Completed task|1.5h')")
            return render(request, 'employee_template/todays_update.html', {
                'schedule': schedule,
                'update': existing_update,
                'today': today,
                'is_editable': is_editable,
                'justification': justification,
            })

        # Calculate total time spent and validate time format
        total_minutes = 0
        for update in updates:
            try:
                desc, time_part = update.split('|')
                time_part = time_part.strip().lower()
                if 'h' in time_part:
                    total_minutes += float(time_part.replace('h', '')) * 60
                elif 'm' in time_part:
                    total_minutes += float(time_part.replace('m', ''))
                elif 's' in time_part:
                    total_minutes += float(time_part.replace('s', '')) / 60
                else:
                    raise ValueError
            except (ValueError, IndexError):
                messages.error(request, f"Invalid time format in update: {update}. Use format like 'Task|1.5h'")
                return render(request, 'employee_template/todays_update.html', {
                    'schedule': schedule,
                    'update': existing_update,
                    'today': today,
                    'is_editable': is_editable,
                    'justification': justification,
                })

        # Require justification if total time is less than 8 hours (480 minutes)
        if total_minutes < 480 and not justification.strip():
            messages.error(request, "Please provide justification for spending less than 8 hours.")
            return render(request, 'employee_template/todays_update.html', {
                'schedule': schedule,
                'update': existing_update,
                'today': today,
                'is_editable': is_editable,
                'justification': justification,
            })

        if existing_update:
            # Update existing
            existing_update.update_description = update_description
            existing_update.justification = justification
            try:
                existing_update.full_clean()
                existing_update.save()
                messages.success(request, "Update modified successfully!")
            except ValidationError as e:
                messages.error(request, f"Error updating: {e}")
                return render(request, 'employee_template/todays_update.html', {
                    'schedule': schedule,
                    'update': existing_update,
                    'today': today,
                    'is_editable': is_editable,
                    'justification': justification,
                })
        else:
            # Create new
            update = DailyUpdate(
                schedule=schedule,
                update_description=update_description,
                justification=justification,
            )
            try:
                update.full_clean()
                update.save()
                messages.success(request, "Update submitted successfully!")
            except ValidationError as e:
                messages.error(request, f"Error submitting: {e}")
                return render(request, 'employee_template/todays_update.html', {
                    'schedule': schedule,
                    'update': existing_update,
                    'today': today,
                    'is_editable': is_editable,
                    'justification': justification,
                })

        return redirect('todays_update')

    return render(request, 'employee_template/todays_update.html', {
        'schedule': schedule,
        'update': existing_update,
        'today': today,
        'is_editable': is_editable,
    })


def view_all_schedules(request):
    """View all schedules and their updates for the logged-in employee"""
    employee = get_object_or_404(Employee, admin=request.user)
    today = get_ist_date()

    schedules = DailySchedule.objects.filter(employee=employee).order_by('-date')

    # Get filter parameters
    filter_type = request.GET.get('filter_type', 'today')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    # Base queryset
    schedules = DailySchedule.objects.filter(employee=employee).order_by('-date')

    if filter_type == 'today':
        schedules = schedules.filter(date=today)
    elif filter_type == 'weekly':
        start = today - timedelta(days=6)  # last 7 days including today
        schedules = schedules.filter(date__gte=start, date__lte=today)
    elif filter_type == "monthly":
        start = today - timedelta(days=29)  
        schedules = schedules.filter(date__gte=start, date__lte=today)
    elif filter_type == 'custom' and start_date and end_date:
        try:
            from datetime import datetime
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            if start > end:
                messages.error(request, "Start date cannot be after end date.")
                start = end = today
            schedules = schedules.filter(date__gte=start, date__lte=end)
        except ValueError:
            messages.error(request, "Invalid date format. Using all schedules.")
            start_date = end_date = None

    if 'export' in request.GET:
        if not schedules:
            messages.error(request,"No Schedules Found for this date range")
        else:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Schedules and Updates"

            # Define headers
            headers = [
                "Schedule Date", "Project", "Tasks-Schedule", "Task-Updates"
            ]

            ws.append(headers)
            for cell in ws[1]:
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal='center', vertical='center')
            
            for schedule in schedules:
                tasks = schedule.task_description_lines
                updates = schedule.updates.all()
                if not updates:
                    # Schedule without updates
                    ws.append([
                        schedule.date.strftime('%Y-%m-%d'),
                        schedule.project or '',
                        '\n'.join(tasks) if tasks else 'No tasks',
                        '', '', ''
                    ])
                else:
                    for update in updates:
                        update_lines = update.update_description_lines
                        ws.append([
                            schedule.date.strftime('%Y-%m-%d'),
                            schedule.project or '',
                            '\n'.join(tasks) if tasks else 'No tasks',
                            '\n'.join(update_lines) if update_lines else 'No updates'
                        ])
            # Adjust column widths
            for col in ws.columns:
                max_length = 0
                column = col[0].column_letter
                for cell in col:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = (max_length + 2)
                ws.column_dimensions[column].width = adjusted_width
            
            # Create response
            output = BytesIO()
            wb.save(output)
            output.seek(0)
            response = HttpResponse(
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                content=output.getvalue()
            )
            response['Content-Disposition'] = f'attachment; filename=schedules_{today.strftime("%Y%m%d")}.xlsx'
            return response
    
    return render(request, 'employee_template/all_schedules.html', {
        'schedules': schedules,
        'today': today,
        'filter_type': filter_type,
        'start_date': start_date,
        'end_date': end_date
    })


@login_required
def others_schedule(request):
    employee = get_object_or_404(Employee, admin=request.user)
    if not employee.department:
        messages.error(request, "You are not assigned to a department.")
        return redirect('all_schedules')

    # Get filter parameters
    filter_type = request.GET.get('filter_type', 'today')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    employee_id = request.GET.get('employee_id')

    schedules = DailySchedule.objects.filter(
        employee__department=employee.department
    ).exclude(employee=employee).order_by('-date')

    # Apply date filters
    today = get_ist_date()
    if filter_type == 'today':
        schedules = schedules.filter(date=today)
    elif filter_type == 'weekly':
        start = today - timedelta(days=6)
        schedules = schedules.filter(date__gte=start, date__lte=today)
    elif filter_type == 'monthly':
        start = today - timedelta(days=29)
        schedules = schedules.filter(date__gte=start, date__lte=today)
    elif filter_type == 'custom' and start_date and end_date:
        try:
            from datetime import datetime
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            if start > end:
                messages.error(request, "Start date cannot be after end date.")
                start = end = today
            schedules = schedules.filter(date__gte=start, date__lte=end)
        except ValueError:
            messages.error(request, "Invalid date format. Using all schedules.")
            start_date = end_date = None
    
    if employee_id and employee_id != 'all':
        try:
            schedules = schedules.filter(employee__id=employee_id)
        except ValueError:
            messages.error(request, "Invalid employee selected.")

    # Get other employees in the department for the filter dropdown
    department_employees = Employee.objects.filter(
        department=employee.department
    ).exclude(id=employee.id).order_by('admin__first_name')

    return render(request, 'employee_template/others_schedules.html', {
        'schedules': schedules,
        'today': today,
        'filter_type': filter_type,
        'start_date': start_date,
        'end_date': end_date,
        'employee_id': employee_id,
        'department_employees': department_employees
    })


@login_required
def early_clock_out_request_page(request):
    context = {
        'has_active_attendance': False,
        'request_status': 'none',
        'request_message': '',
    }

    attendance_record = AttendanceRecord.objects.filter(
        user=request.user,
        date=timezone.now().date(),
        clock_out__isnull=True
    ).first()

    if attendance_record:
        context['has_active_attendance'] = True
        early_request = EarylyClockOutRequest.objects.filter(
            attendance_record=attendance_record
        ).order_by('-submitted_at').first()
        if early_request:
            context['request_status'] = early_request.status
            context['request_message'] = early_request.notes or ''

    return render(request, 'employee_template/early_clock_out_request.html', context)