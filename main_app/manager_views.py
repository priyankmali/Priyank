import json
from django.contrib import messages
from django.core.files.storage import FileSystemStorage
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404,redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Count,Q
from django.db.models import Count,Q
from main_app.notification_badge import send_notification
from .forms import *
from .models import *
from asset_app.models import Notify_Manager,AssetsIssuance,Assets,LOCATION_CHOICES,AssetAssignmentHistory
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST
from asset_app.models import AssetIssue
from .models import CustomUser
from django.utils.timezone import localtime
from django.templatetags.static import static
import requests
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from datetime import datetime, time, timedelta
from django.core.paginator import Paginator
from django.forms.models import model_to_dict
from django.http import JsonResponse
from datetime import datetime
from django.template.loader import render_to_string
from asset_app.models import AssetCategory
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.core.paginator import Paginator, EmptyPage
from django.views.decorators.csrf import csrf_exempt
from .models import AttendanceRecord, Employee, Holiday, LeaveReportEmployee
from calendar import monthrange
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import transaction
from django.contrib.auth import update_session_auth_hash
import logging
from django.utils.text import get_valid_filename

LOCATION_CHOICES = (
    ("Main Room" , "Main Room"),
    ("Meeting Room", "Meeting Room"),
    ("Main Office", "Main Office"),
)

from django.utils.timezone import is_naive, make_aware

def make_aware_if_naive(dt):
    if dt and is_naive(dt):
        return make_aware(dt)
    return dt


@login_required   
def manager_home(request):
    manager = get_object_or_404(Manager, admin=request.user)
    
    today = date.today()
    current_time = timezone.now()

    predefined_names = ['Python Department', 'React JS Department', 'Node JS Department']
    all_departments = Department.objects.all()

    selected_department = request.GET.get('department', 'all').strip().lower()
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    employees = CustomUser.objects.filter(user_type=3)  
    normalized_predefined = [name.lower() for name in predefined_names]

    if selected_department != 'all':
        if selected_department == 'others':
            employees = employees.exclude(employee__department__name__in=predefined_names)
        else:
            employees = employees.filter(employee__department__name__iexact=selected_department.title())

    employee_ids = employees.values_list('id', flat=True)
    filtered_records = AttendanceRecord.objects.filter(user_id__in=employee_ids)
    
    on_break_now = Break.objects.filter(
        attendance_record__user__in=employee_ids,
        break_start__date=today,
        break_start__lte=current_time,
    ).filter(models.Q(break_end__isnull=True) | models.Q(break_end__gte=current_time)).distinct()

    total_on_break = on_break_now.count()

    if start_date and end_date:
        date_range = [parse_date(start_date), parse_date(end_date)]
        filtered_records = filtered_records.filter(date__range=date_range)

    time_history_data = []
    break_entries = []
    
    for employee in employees:
        emp_records = filtered_records.filter(user=employee)
        total_present = emp_records.filter(status='present').count()
        total_late = emp_records.filter(status='late').count()

        emp_leaves = LeaveReportEmployee.objects.filter(employee__admin=employee)
        if start_date and end_date:
            emp_leaves = emp_leaves.filter(
                start_date__lte=parse_date(end_date),
                end_date__gte=parse_date(start_date)
            )
        total_leave = emp_leaves.count()
    
        emp_breaks = Break.objects.filter(
            attendance_record__user=employee,
            break_start__date=today
        ).order_by('break_start')

        for b in emp_breaks:
            if b.break_end:
                duration = int((b.break_end - b.break_start).total_seconds() / 60)
            else:
                duration = 0 

            break_entries.append({
                'employee_id': employee.id,
                'employee_name': employee.get_full_name(),
                'department': employee.employee.department.name if hasattr(employee, 'employee') and employee.employee.department else '',
                'break_start': b.break_start.strftime('%H:%M'),
                'break_end': b.break_end.strftime('%H:%M') if b.break_end else 'Ongoing',
                'break_duration': duration,
            })

        # current record
        current_record = AttendanceRecord.objects.filter(
            user=request.user,
            clock_out__isnull=True,
            date=today
        ).first()

        # for break start end
        current_break = None
        if current_record:
            current_break = Break.objects.filter(
                attendance_record=current_record,
                break_end__isnull=True
            ).first()

        # Paginate break entries
        paginator = Paginator(break_entries, 10)  
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)

        # After the loop that appends to break_entries
        if break_entries:
            break_entries = sorted(break_entries, key=lambda x: x['break_start'], reverse=True)
            
            # Apply pagination to sorted entries
            paginator = Paginator(break_entries, 10)
            page_obj = paginator.get_page(page_number)
            break_entries = page_obj.object_list
        
        time_history_data.append({
            'employee_name': employee.get_full_name(),
            'department': employee.employee.department.name if hasattr(employee, 'employee') and employee.employee.department else '',
            'present': total_present,
            'late': total_late,
            'leave': total_leave,
            'working_days': total_present + total_late,
        })

    context = {
        'page_title': f"Manager Panel - {manager.admin.get_full_name().capitalize()}",
        'departments': all_departments,
        'time_history_data': time_history_data,
        'selected_department': selected_department,
        'start_date': start_date,
        'end_date': end_date,
        'total_employees': employees.count(),
        'total_attendance': filtered_records.count(),
        'total_leave': sum(item['leave'] for item in time_history_data),
        'total_department': all_departments.count(),
        'total_on_break' : total_on_break,
        'break_entries': break_entries,
        'page_obj': page_obj,
        'current_break' : current_break
    }
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string('manager_template/home_content.html', context, request=request)
        return HttpResponse(html)

    return render(request, 'manager_template/home_content.html', context)



@login_required
def manager_todays_attendance(request):
    manager = get_object_or_404(Manager, admin=request.user)
    today = timezone.now()
    
    team_members = Employee.objects.filter(team_lead=manager)
    employee_users = CustomUser.objects.filter(employee__in=team_members)
    
    today_attendances = AttendanceRecord.objects.filter(
        user__in=employee_users,
        date=today
    ).select_related('user__employee__department').order_by('-clock_in')

    # Pagination
    page = request.GET.get('page', 1)
    paginator = Paginator(today_attendances, 10)
    
    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    context = {
        'page_title': "Today's Clocked-In Employees",
        'page_obj': page_obj,
        'current_date': today.strftime("%Y-%m-%d"),
        'total_clocked_in': today_attendances.values('user').distinct().count()
    }
    return render(request, 'manager_template/todays_attendance.html', context)

@login_required   
def manager_take_attendance(request):
    manager = get_object_or_404(Manager, admin=request.user)
    print("manager",manager)
    departments = Department.objects.filter(division=manager.division)
    context = {
        'departments': departments,
        'page_title': 'Take Attendance',
    }
    return render(request, 'manager_template/manager_take_attendance.html', context)


@login_required   
@csrf_exempt
def get_employees(request):
    department_id = request.POST.get('department')
    try:
        if department_id == 'all':
            employees = Employee.objects.all()
        else:
            department = get_object_or_404(Department, id=department_id)
            employees = Employee.objects.filter(department=department)
        
        employee_data = []
        for employee in employees:
            data = {
                "id": employee.admin.id,
                "name": employee.admin.last_name + " " + employee.admin.first_name
            }
            employee_data.append(data)
        return JsonResponse(json.dumps(employee_data), content_type='application/json', safe=False)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required   
@csrf_exempt
def get_managers(request):
    print("sd fsdf","*"*20)
    department_id = request.POST.get('department')
    print(department_id,"*"*20)
    try:
        if department_id == 'all':
            managers = Manager.objects.all()
        else:
            department = get_object_or_404(Department, id=department_id)
            managers = Manager.objects.filter(department=department)
        manager_data = []
        for manager in managers:
            data = {
                "id": manager.admin.id,
                "name": manager.admin.last_name + " " + manager.admin.first_name
            }
            manager_data.append(data)
        return JsonResponse(json.dumps(manager_data), content_type='application/json', safe=False)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required   
@csrf_exempt
def save_attendance(request):
    employee_data = request.POST.get('employee_ids')
    date_str = request.POST.get('date')
    date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
    department_id = request.POST.get('department')
    half_full_day = request.POST.get('half_full_day')
    which_half = request.POST.get('which_half')
    today = date_obj.today()
    current_month = today.month
    current_year = today.year
    
    start_date = today.replace(day=1)
    if today.month == 12:
        next_month = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_month = today.replace(month=today.month + 1, day=1)

    end_date = next_month - timedelta(days=1)
    
    # Log incoming data for debugging
    print("$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$",request.user.id )
    print("start_date", start_date)
    print("end_date", end_date)
    print("Employee Data:", employee_data)
    print("half_full_day:", half_full_day)
    print("Date:", date_str)
    print("Department ID:", department_id)

    try:
        employees = json.loads(employee_data)
        
        department = get_object_or_404(Department, id=department_id)

        for emp in employees:
            if half_full_day:
                employee = CustomUser.objects.filter(id = int(emp)).first()
            else:
                employee = get_object_or_404(CustomUser, id=emp.get('id'))
            user = employee  # CustomUser linked
            # if half_full_day:
            status = 'present'
            # else:
            #     status = 'present' if emp.get('status') == 1 else 'late'

            # Only create if not already exists
            # created = False
            # try:
            #     attendance_record, created = AttendanceRecord.objects.get_or_create(
            #         user=user,
            #         date=date_obj,
            #         defaults={
            #             'clock_in': timezone.make_aware(datetime.combine(date_obj, datetime.min.time())),  # Make the datetime aware
            #             'status': status,
            #             'department': department,
            #             'is_primary_record': True,
            #         }
            #     )
            # except:
            #     pass
            # print("createdcreated",created)
            # if not created:
            #     # Update status if already exists
            #     attendance_record.status = status
            #     attendance_record.save()

            # Update the present day count in employee's dashboard
            # exist_data = AttendanceRecord.objects.filter( date__range=(start_date, end_date), department=department,user = employee.admin)
            # print("exist_data>>>>>>>>>>>>>>>>>>>>>>>>>>",exist_data)
            # LeaveReportEmployee.objects.filter(
            #     employee=employee,
            #     status=1,  # Approved leaves
            #     start_date__month=current_month,
            #     start_date__year=current_year
            # )
            # if exist_data:
            #     present_dates = exist_data.filter(
            #         status='present'
            #     ).values_list('date', flat=True).distinct().count()

            #     late_dates = exist_data.filter(
            #         status='late'
            #     ).values_list('date', flat=True).distinct().count()
            #     print("late_dates",late_dates)
            #     print("present_dates",present_dates)
            # if status == 'present':
            #     employee.present_days += 1
            # employee.save()
            
            if half_full_day == "full":
                leave_status = "Full-Day"
                total_work = 8*60*60
                status = "present"
                clock_in = datetime.combine(date_obj, time(14, 30, 0)) 
                clock_out = datetime.combine(date_obj, time(23, 30, 0)) 
            if half_full_day == "half":
                total_work = 4*60*60
                leave_status = "Half-Day"
                if which_half =="first":
                    # pass
                    status = "present"
                    clock_in = datetime.combine(date_obj, time(9, 00, 0)) 
                    clock_out = datetime.combine(date_obj, time(13, 00, 0))
                else:
                    status = "late"
                    clock_in = datetime.combine(date_obj, time(14, 00, 0)) 
                    clock_out = datetime.combine(date_obj, time(18, 00, 0)) 
            employee = Employee.objects.get(admin = employee)
            leave_record = LeaveReportEmployee.objects.create(
                employee = employee,
                leave_type = leave_status,
                start_date = date_obj,
                end_date = date_obj,
                message = f"Added From {request.user}",
                status = 1,
                created_at = today,
                updated_at = today
            )
            leave_record.save()
            user_id = int(emp)
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
            manager_id = request.user.id
            attendance = AttendanceRecord.objects.create(
                date=date_obj,
                clock_in=clock_in,
                clock_out=clock_out,  # or provide clock_out datetime
                status=status,
                total_worked=total_work,  # e.g., 8 hours in seconds
                regular_hours=0,
                overtime_hours=0,
                is_primary_record=True,
                requires_verification=False,
                is_verified=True,
                verification_time=None,
                created_at=timezone.now(),
                updated_at=timezone.now(),
                user_id=user_id,
                verified_by_id=manager_id,
                department_id=department_id
            )
            print(">>>>>>>>>>>>>>>>>>>INSERTION",user_id, manager_id)
            attendance.save()

    

        return HttpResponse("OK")
    except Exception as e:
        import traceback
        # Log the exception for debugging
        print("Error:", str(e))
        exc_type, exc_value, exc_tb = traceback.format_exc().splitlines()[-1], e, e.__traceback__
    
        # Print the error message
        print(f"Error: {exc_value}")
        
        # Print the line number and traceback details
        print("Traceback details:")
        print(f"File: {exc_tb.tb_frame.f_code.co_filename}, Line: {exc_tb.tb_lineno}")
        
        # Print the complete traceback for debugging
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=400)


# For displaying the update page
# def manager_update_attendance(request):
#     manager = get_object_or_404(Manager, admin=request.user)
#     # employees = Employee.objects.filter(department__in=departments)
#     departments = Department.objects.filter(division=manager.division)
#     context = {
#         'departments': departments,
#         # 'employees': employees,
#         'page_title': 'Update Attendance'
#     }
#     return render(request, 'manager_template/manager_update_attendance.html', context)

# from datetime import datetime


@login_required   
def manager_update_attendance(request):
    manager = get_object_or_404(Manager, admin=request.user)
    departments = Department.objects.filter(division=manager.division)
    employees = Employee.objects.filter(department__in=departments)
    context = {
        'departments': departments,
        'employees': employees,
        'page_title': 'View Attendance',
    }
    
    return render(request, 'manager_template/manager_update_attendance.html', context)



# For handling the AJAX updates
# @csrf_exempt
# def update_attendance(request):
#     if request.method == 'POST':
#         try:
#             employee_ids = json.loads(request.POST.get('employee_ids', '[]'))
#             date_str = request.POST.get('date')
#             half_full_day = request.POST.get('half_full_day')  # 'half' or 'full'
#             which_half = request.POST.get('which_half', '')  # 'first' or 'second'
            
#             if not employee_ids or not date_str:
#                 return JsonResponse({"error": "Employee IDs and date are required"}, status=400)
            
#             try:
#                 date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
#             except ValueError:
#                 return JsonResponse({"error": "Invalid date format. Use YYYY-MM-DD"}, status=400)
            
#             updated_count = 0
#             for emp_id in employee_ids:
#                 try:
#                     # Calculate times based on attendance type
#                     if half_full_day == 'full':
#                         # Full day timing (9:00 AM to 6:00 PM)
#                         status = 'present'
#                         clock_in = datetime.combine(date_obj, time(9, 0))  # 9:00 AM
#                         clock_out = datetime.combine(date_obj, time(18, 0))  # 6:00 PM
#                         total_work = 9 * 60 * 60  # 9 hours in seconds
#                     else:
#                         # Half day timing
#                         if which_half == 'first':
#                             # First half (9:00 AM to 1:30 PM)
#                             status = 'half_day_first'
#                             clock_in = datetime.combine(date_obj, time(9, 0))
#                             clock_out = datetime.combine(date_obj, time(13, 30))
#                             total_work = 4.5 * 60 * 60  # 4.5 hours
#                         else:
#                             # Second half (1:30 PM to 6:00 PM)
#                             status = 'half_day_second'
#                             clock_in = datetime.combine(date_obj, time(13, 30))
#                             clock_out = datetime.combine(date_obj, time(18, 0))
#                             total_work = 4.5 * 60 * 60  # 4.5 hours
                    
#                     # Update or create the attendance record
#                     record, created = AttendanceRecord.objects.update_or_create(
#                         user_id=emp_id,
#                         date=date_obj,
#                         defaults={
#                             'status': status,
#                             'clock_in': clock_in,
#                             'clock_out': clock_out,
#                             'total_worked': total_work,
#                             'is_primary_record': True,
#                             'requires_verification': False,
#                             'is_verified': True,
#                             'verified_by': request.user,
#                             'updated_at': timezone.now()
#                         }
#                     )
#                     updated_count += 1
                    
#                 except Exception as e:
#                     print(f"Error updating attendance for employee {emp_id}: {str(e)}")
#                     continue
            
#             return JsonResponse({
#                 "message": f"Attendance updated successfully for {updated_count} employees",
#                 "updated_count": updated_count
#             })
            
#         except Exception as e:
#             return JsonResponse({"error": str(e)}, status=400)
    
#     return JsonResponse({"error": "Invalid request method"}, status=400)
from django.forms.models import model_to_dict


@login_required   
@csrf_exempt
def update_attendance(request):
    if request.method == 'POST':
        try:
            employee_ids = json.loads(request.POST.get('employee_ids', '[]'))
            date_str = request.POST.get('date')
            half_full_day = request.POST.get('half_full_day')  # 'half' or 'full'
            which_half = request.POST.get('which_half', '')  # 'first' or 'second'
            
            if not employee_ids or not date_str:
                return JsonResponse({"error": "Employee IDs and date are required"}, status=400)
            
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                return JsonResponse({"error": "Invalid date format. Use YYYY-MM-DD"}, status=400)
            
            updated_count = 0
            for emp_id in employee_ids:
                try:
                    # Fetch the employee
                    employee = Employee.objects.get(employee_id=emp_id)

                    # Calculate times based on attendance type
                    if half_full_day == 'full':
                        # Full day timing (9:00 AM to 6:00 PM)
                        status = 'present'
                        clock_in = datetime.combine(date_obj, time(9, 0))  # 9:00 AM
                        clock_out = datetime.combine(date_obj, time(18, 0))  # 6:00 PM
                        total_work = 9 * 60 * 60  # 9 hours in seconds
                    else:
                        # Half day timing
                        if which_half == 'first':
                            # First half (9:00 AM to 1:30 PM)
                            status = 'half_day_first'
                            clock_in = datetime.combine(date_obj, time(9, 0))
                            clock_out = datetime.combine(date_obj, time(13, 30))
                            total_work = 4.5 * 60 * 60  # 4.5 hours
                        else:
                            # Second half (1:30 PM to 6:00 PM)
                            status = 'half_day_second'
                            clock_in = datetime.combine(date_obj, time(13, 30))
                            clock_out = datetime.combine(date_obj, time(18, 0))
                            total_work = 4.5 * 60 * 60  # 4.5 hours
                    
                    # Save previous record snapshot (optional)
                    old_record = AttendanceRecord.objects.filter(user=employee.admin, date=date_obj).first()
                    if old_record:
                        old_data = model_to_dict(old_record)
                        print("Previous record:", old_data)

                    # Update or create the attendance record
                    record, created = AttendanceRecord.objects.update_or_create(
                        user=employee.admin,  # Correct reference to employee's admin (CustomUser)
                        date=date_obj,
                        defaults={
                            'status': status,
                            'clock_in': clock_in,
                            'clock_out': clock_out,
                            'total_worked': total_work,
                            'is_primary_record': True,
                            'requires_verification': False,
                            'is_verified': True,
                            'verified_by': request.user,
                            'updated_at': timezone.now()
                        }
                    )

                    # Save updated record snapshot (optional)
                    print("Updated record:", model_to_dict(record))
                    updated_count += 1
                    
                except Exception as e:
                    print(f"Error updating attendance for employee {emp_id}: {str(e)}")
                    continue
            
            return JsonResponse({
                "message": f"Attendance updated successfully for {updated_count} employees",
                "updated_count": updated_count
            })
            
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
    
    return JsonResponse({"error": "Invalid request method"}, status=400)


@login_required
@csrf_exempt
def get_employee_attendance(request):
    if request.method == 'POST':
        try:
            # Retrieve POST parameters
            employee_id = request.POST.get('employee_id')
            department_id = request.POST.get('department_id')
            month = request.POST.get('month')
            year = request.POST.get('year')
            week = request.POST.get('week')
            from_date = request.POST.get('from_date')
            to_date = request.POST.get('to_date')
            page = int(request.POST.get('page', 1))
            per_page = request.POST.get('per_page', 5)
            try:
                per_page = int(per_page)
                # Cap per_page to prevent excessive memory usage
                per_page = min(per_page, 10000)
            except ValueError:
                per_page = 5

            # Validate required date inputs
            if not year and not (from_date and to_date):
                return JsonResponse({"error": "Year or date range is required"}, status=400)

            # Base queryset with related models
            queryset = AttendanceRecord.objects.select_related(
                'user__employee',
                'user__employee__department'
            ).prefetch_related('breaks').all()

            # Apply filters
            if employee_id and employee_id != 'all':
                try:
                    employee = Employee.objects.get(employee_id=employee_id)
                    queryset = queryset.filter(user__employee=employee)
                except Employee.DoesNotExist:
                    return JsonResponse({"error": "Employee not found"}, status=400)

            if department_id and department_id != 'all':
                queryset = queryset.filter(user__employee__department_id=department_id)

            # Date filtering
            holiday_dates = set()
            filtered_dates = None
            start_date = None
            end_date = None
            today = datetime.now().date()
            current_year = today.year
            current_month = today.month

            # Automatically set holidays for 2nd/4th Saturdays and Sundays
            def set_automatic_holidays(year, month):
                days_in_month = monthrange(year, month)[1]
                start_date = datetime(year, month, 1).date()
                end_date = min(today, datetime(year, month, days_in_month).date())
                existing_holidays = set(Holiday.objects.filter(
                    date__year=year,
                    date__month=month
                ).values_list('date', flat=True))

                saturdays = []
                current_date = start_date
                while current_date <= end_date:
                    if current_date.weekday() == 5:  # Saturday
                        week_number = (current_date.day - 1) // 7
                        if week_number in [1, 3]:  # 2nd or 4th Saturday
                            saturdays.append(current_date)
                    elif current_date.weekday() == 6:  # Sunday
                        if current_date not in existing_holidays:
                            Holiday.objects.get_or_create(
                                date=current_date,
                                defaults={'name': f'Sunday - {current_date.strftime("%B %d, %Y")}'}
                            )
                    current_date += timedelta(days=1)

                # Add 2nd and 4th Saturdays
                for saturday in saturdays:
                    if saturday not in existing_holidays:
                        Holiday.objects.get_or_create(
                            date=saturday,
                            defaults={'name': f'Saturday - {saturday.strftime("%B %d, %Y")}'}
                        )

            # Call to set holidays for current month
            set_automatic_holidays(current_year, current_month)

            # Calculate total working days and holiday count for the full current month
            full_month_start = datetime(current_year, current_month, 1).date()
            days_in_month = monthrange(current_year, current_month)[1]
            full_month_end = datetime(current_year, current_month, days_in_month).date()
            full_month_holidays = set(Holiday.objects.filter(
                date__year=current_year,
                date__month=current_month
            ).values_list('date', flat=True))
            total_working_days = 0
            holiday_count = 0
            current_date = full_month_start
            while current_date <= full_month_end:
                weekday = current_date.weekday()
                is_sunday = weekday == 6
                is_saturday = weekday == 5
                is_2nd_or_4th_saturday = is_saturday and ((current_date.day - 1) // 7) in [1, 3]
                is_holiday = current_date in full_month_holidays
                if is_sunday or is_2nd_or_4th_saturday or is_holiday:
                    if current_date <= today:
                        holiday_count += 1
                elif not (is_sunday or is_2nd_or_4th_saturday or is_holiday):
                    total_working_days += 1
                current_date += timedelta(days=1)

            if from_date and to_date:
                try:
                    start_date = datetime.strptime(from_date, '%Y-%m-%d').date()
                    end_date = datetime.strptime(to_date, '%Y-%m-%d').date()
                    queryset = queryset.filter(date__range=(start_date, end_date))
                    holiday_dates = set(Holiday.objects.filter(
                        date__range=(start_date, end_date)
                    ).values_list('date', flat=True))
                    filtered_dates = (start_date, end_date)
                except ValueError:
                    return JsonResponse({"error": "Invalid date format. Use YYYY-MM-DD"}, status=400)
            else:
                # Default to current month from 1st to today
                start_date = datetime(current_year, current_month, 1).date()
                end_date = today
                queryset = queryset.filter(date__range=(start_date, end_date))
                holiday_dates = set(Holiday.objects.filter(
                    date__range=(start_date, end_date)
                ).values_list('date', flat=True))
                filtered_dates = (start_date, end_date)

                if year:
                    year = int(year)
                    if week:
                        try:
                            week = int(week)
                            first_day_of_year = datetime(year, 1, 1).date()
                            start_date = first_day_of_year + timedelta(weeks=week - 1)
                            end_date = start_date + timedelta(days=6)
                            queryset = queryset.filter(date__range=(start_date, end_date))
                            holiday_dates = set(Holiday.objects.filter(
                                date__range=(start_date, end_date)
                            ).values_list('date', flat=True))
                            filtered_dates = (start_date, end_date)
                        except ValueError:
                            return JsonResponse({"error": "Invalid week number"}, status=400)
                    elif month:
                        try:
                            month = int(month)
                            start_date = datetime(year, month, 1).date()
                            days_in_month = monthrange(year, month)[1]
                            end_date = datetime(year, month, days_in_month).date()
                            if year == current_year and month == current_month:
                                end_date = today  # Limit to today for current month
                            queryset = queryset.filter(date__month=month, date__year=year)
                            holiday_dates = set(Holiday.objects.filter(
                                date__year=year,
                                date__month=month
                            ).values_list('date', flat=True))
                            filtered_dates = (start_date, end_date)
                            # Set holidays for the selected month if it's the current year
                            if year == current_year:
                                set_automatic_holidays(year, month)
                        except ValueError:
                            return JsonResponse({"error": "Invalid month number"}, status=400)

            # Ensure end_date doesn't exceed today
            if end_date > today:
                end_date = today

            # Order queryset by date
            queryset = queryset.order_by('-date')

            # Initialize attendance statistics
            present_days = 0
            late_days = 0
            half_days = 0
            absent_days = 0

            # Calculate attendance stats
            if start_date and end_date:
                current_date = start_date
                employee = Employee.objects.get(employee_id=employee_id) if employee_id and employee_id != 'all' else None
                
                # Create a dictionary to track all dates in the range and their status
                date_status_map = {}
                for record in queryset:
                    if record.date not in date_status_map:
                        date_status_map[record.date] = record.status

                # Track leaves for the employee
                leave_dates = set()
                half_day_leave_dates = set()
                if employee:
                    leaves = LeaveReportEmployee.objects.filter(
                        employee=employee,
                        status=1,
                        start_date__lte=end_date,
                        end_date__gte=start_date
                    )
                    for leave in leaves:
                        leave_start = max(leave.start_date, start_date)
                        leave_end = min(leave.end_date, end_date)
                        current_leave_date = leave_start
                        while current_leave_date <= leave_end:
                            if leave.leave_type == "Half-Day":
                                half_day_leave_dates.add(current_leave_date)
                            else:
                                leave_dates.add(current_leave_date)
                            current_leave_date += timedelta(days=1)

                while current_date <= end_date:
                    weekday = current_date.weekday()
                    is_sunday = weekday == 6
                    is_saturday = weekday == 5
                    is_2nd_or_4th_saturday = is_saturday and ((current_date.day - 1) // 7) in [1, 3]
                    is_holiday = current_date in holiday_dates

                    # Determine if this is a working day for attendance stats
                    if not (is_sunday or is_2nd_or_4th_saturday or is_holiday):
                        # Check attendance status
                        record_status = date_status_map.get(current_date)
                        
                        # Handle leaves
                        if current_date in half_day_leave_dates:
                            present_days += 1
                            half_days += 1
                            late_days += 1
                            absent_days += 0.5  # Count half-day leave as 0.5 absent day
                        elif current_date in leave_dates:
                            # Full day leave counts as present
                            present_days += 1
                        elif record_status == 'present':
                            present_days += 1
                        elif record_status == 'late':
                            present_days += 1
                            late_days += 1
                        elif record_status == 'half_day':
                            present_days += 1
                            half_days += 1
                            absent_days += 0.5  # Count half-day leave as 0.5 absent day
                        else:
                            absent_days += 1

                    current_date += timedelta(days=1)

            # Calculate attendance percentage
            filtered_working_days = total_working_days if filtered_dates[1] == full_month_end else sum(
                1 for d in [start_date + timedelta(days=x) for x in range((end_date - start_date).days + 1)]
                if not (d.weekday() == 6 or (d.weekday() == 5 and ((d.day - 1) // 7) in [1, 3]) or d in holiday_dates)
            )
            if filtered_working_days > 0:
                attendance_percentage = (present_days / filtered_working_days) * 100
                attendance_percentage = round(attendance_percentage, 1)
            else:
                attendance_percentage = 0

            # Process attendance records
            attendance_list = []
            attendance_dates = set(queryset.values_list('date', flat=True))

            for record in queryset:
                if hasattr(record.user, 'employee'):
                    user = record.user.employee
                    name = f"{user.admin.first_name} {user.admin.last_name}"
                    department = user.department.name if user.department else ""
                    user_type = "Employee"
                    user_id = user.employee_id

                    # Determine status - check if it's a holiday or weekend first
                    weekday = record.date.weekday()
                    is_sunday = weekday == 6
                    is_saturday = weekday == 5
                    is_2nd_or_4th_saturday = is_saturday and ((record.date.day - 1) // 7) in [1, 3]
                    is_holiday = record.date in holiday_dates

                    if is_holiday or is_sunday or is_2nd_or_4th_saturday:
                        status = "Holiday"
                    else:
                        status = record.status

                    # Calculate hours worked
                    hours = "0h 0m"
                    if record.total_worked:
                        total_seconds = record.total_worked.total_seconds()
                        hours_worked = int(total_seconds // 3600)
                        minutes_worked = int((total_seconds % 3600) // 60)
                        hours = f"{hours_worked}h {minutes_worked}m"

                    attendance_list.append({
                        "date": record.date.isoformat(),
                        "day": record.date.strftime('%a'),
                        "status": status,
                        "clock_in": record.clock_in.isoformat() if record.clock_in else None,
                        "clock_out": record.clock_out.isoformat() if record.clock_out else None,
                        "hours": hours,
                        "name": name,
                        "department": department,
                        "user_type": user_type,
                        "user_id": user_id,
                    })

            # Add missing holiday records
            current_date = start_date
            while current_date <= end_date:
                weekday = current_date.weekday()
                is_sunday = weekday == 6
                is_saturday = weekday == 5
                is_2nd_or_4th_saturday = is_saturday and ((current_date.day - 1) // 7) in [1, 3]
                is_holiday = current_date in holiday_dates

                if (is_sunday or is_2nd_or_4th_saturday or is_holiday) and current_date not in attendance_dates:
                    attendance_list.append({
                        "date": current_date.isoformat(),
                        "day": current_date.strftime('%a'),
                        "status": "Holiday",
                        "clock_in": None,
                        "clock_out": None,
                        "hours": "0h 0m",
                        "name": "",
                        "department": "",
                        "user_type": "",
                        "user_id": "",
                    })
                current_date += timedelta(days=1)

            # Sort attendance by date descending
            attendance_list = sorted(attendance_list, key=lambda x: x['date'], reverse=True)

            # Paginate results
            paginator = Paginator(attendance_list, per_page)
            try:
                page_obj = paginator.page(page)
            except EmptyPage:
                return JsonResponse({"error": "Invalid page number"}, status=400)

            # Prepare pagination data
            pagination_data = {
                "current_page": page_obj.number,
                "total_pages": paginator.num_pages,
                "total_records": paginator.count,
                "has_previous": page_obj.has_previous(),
                "has_next": page_obj.has_next(),
                "previous_page": page_obj.previous_page_number() if page_obj.has_previous() else None,
                "next_page": page_obj.next_page_number() if page_obj.has_next() else None,
                "start_index": page_obj.start_index(),
                "end_index": page_obj.end_index(),
            }

            # Prepare response
            response_data = {
                "data": page_obj.object_list,
                "pagination": pagination_data,
                "stats": {
                    "holidays": holiday_count,
                    "total_working_days": total_working_days,
                    "present_days": round(present_days, 1),
                    "late_days": late_days,
                    "half_days": half_days,
                    "absent_days": round(absent_days, 1),
                    "attendance_percentage": attendance_percentage,
                }
            }

            return JsonResponse(response_data, safe=False)

        except Exception as e:
            return JsonResponse({"error": f"Server error: {str(e)}"}, status=500)
    return JsonResponse({"error": "Invalid request method"}, status=405)


@login_required   
def manager_apply_leave(request):
    manager = get_object_or_404(Manager, admin_id=request.user.id)
    
    unread_ids = Notification.objects.filter(
        user=request.user,
        role="manager",
        is_read=False,
        notification_type="manager-leave-notification"
    ).values_list('leave_or_notification_id', flat=True)

    leave_list = LeaveReportManager.objects.filter(manager=manager).order_by('-created_at')
    paginator = Paginator(leave_list, 5)  

    page_number = request.GET.get('page')
    leave_page = paginator.get_page(page_number)

    if request.method == 'POST':
        leave_type_ = request.POST.get('leave_type')
        half_day_type_ = request.POST.get('half_day_type')
        start_date_ = request.POST.get('start_date')
        end_date_ = request.POST.get('end_date')
        message_ = request.POST.get('message')
        print(leave_type_, half_day_type_, start_date_, end_date_, message_)

        if not all([leave_type_, start_date_, message_]):
            messages.error(request, "All fields are required")
            return redirect(reverse('manager_apply_leave'))

        existing_leaves = LeaveReportManager.objects.filter(
            manager=manager,
            start_date__lte=end_date_ if end_date_ else start_date_,
            end_date__gte=start_date_,
            status__in=[0, 1]
        ).exists()

        if existing_leaves:
            messages.error(request, "You already applied or have approved leave for these dates.")
            return redirect(reverse('manager_apply_leave'))

        try:
            start_date = date.fromisoformat(start_date_)
            end_date = date.fromisoformat(end_date_ if end_date_ else start_date_)
            if end_date < start_date:
                messages.error(request, "End date cannot be before start date.")
                return redirect(reverse('manager_apply_leave'))  
        except ValueError:
            messages.error(request, "Invalid date format.")
            return redirect(reverse('manager_apply_leave'))

        try:
            leave_request = LeaveReportManager.objects.create(
                manager=manager,
                leave_type=leave_type_,
                half_day_type=half_day_type_ if half_day_type_ else None,
                start_date=start_date_,
                end_date=end_date_ if end_date_ else start_date_,
                message=message_
            )
            messages.success(request, "Your leave request has been submitted.")
            admin_users = CustomUser.objects.filter(is_superuser=True)
            if admin_users.exists():
                for admin_user in admin_users:
                    send_notification(admin_user, "Leave Applied", "leave-notification", leave_request.id, "ceo")
            
            return redirect(reverse('manager_apply_leave'))
        except Exception as e:
            messages.error(request, f"Error submitting leave: {str(e)}")
            return redirect(reverse('manager_apply_leave'))

    context = {
        'leave_page': leave_page,
        'unread_ids': list(unread_ids),
        'page_title': 'Apply for Leave',
    }
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string("manager_template/manager_apply_leave.html", context, request=request)
        return HttpResponse(html)

    return render(request, "manager_template/manager_apply_leave.html", context)


@login_required   
def manage_employee_by_manager(request):
    manager = get_object_or_404(Manager, admin=request.user)
    search_ = request.GET.get("search", '').strip()
    gender = request.GET.get("gender", '')
    department_id = request.GET.get("department", '')
    division_id = request.GET.get("division", '')
    page_number = request.GET.get('page', 1)

    # Get employees with asset count
    employees = Employee.objects.filter(team_lead=manager).annotate(
        asset_count=Count('admin__assetsissuance'),
    ).select_related('admin', 'department', 'division', 'team_lead')

    # Apply filters
    if search_:
        employees = employees.filter(
            Q(admin__first_name__icontains=search_) |
            Q(admin__last_name__icontains=search_) |
            Q(admin__email__icontains=search_)
        )
    
    if gender:
        employees = employees.filter(admin__gender=gender)
    
    if department_id:
        employees = employees.filter(department__id=department_id)
    
    if division_id:
        employees = employees.filter(division__id=division_id)

    # Get all departments and divisions for filter dropdowns
    departments = Department.objects.all()
    divisions = Division.objects.all()

    paginator = Paginator(employees, 10)
    page_obj = paginator.get_page(page_number)

    context = {
        'employees': page_obj,
        'page_title': 'Manage Employees',
        'location_choices': dict(LOCATION_CHOICES),
        'is_paginated': page_obj.has_other_pages(),
        'search': search_,
        'departments': departments,
        'divisions': divisions,
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string(
            "manager_template/manage_employee_by_manager.html",
            context,
            request=request
        )
        return HttpResponse(html)

    if not employees:
        messages.warning(request, "No employees found")
    return render(request, 'manager_template/manage_employee_by_manager.html', context)


@login_required   
@require_GET
def get_asset_categories(request):
    try:
        categories = AssetCategory.objects.all()
        categories_data = [{'id': category.id, 'name': category.category} for category in categories]
        return JsonResponse({'success': True, 'categories': categories_data})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required   
@require_GET
def get_available_assets(request):
    try:
        category_id_ = request.GET.get('category_id','')
        search_ = request.GET.get('search','')

        available_assets = Assets.objects.filter(
            is_asset_issued=False,
        ).select_related('asset_category')

        if category_id_:
            available_assets = available_assets.filter(asset_category_id=category_id_)
        
        if search_:
            available_assets = available_assets.filter(
                Q(asset_name__icontains=search_) |
                Q(asset_serial_number__icontains=search_) |
                Q(asset_brand__icontains=search_)
            )

        assets_data = [{
            'id': asset.id,
            'asset_name': asset.asset_name,
            'asset_serial_number': asset.asset_serial_number,
            'asset_category': asset.asset_category.category,
            'asset_brand': asset.asset_brand,
            'status': "Available"
        } for asset in available_assets]

        
        bundle_categories = ['Laptop', 'Keyboard', 'Mouse', 'Cooling Pad', 'Monitor']
        bundle_assets = []

        for category in bundle_categories:
            asset = Assets.objects.filter(
                is_asset_issued=False,
                asset_category__category=category.lower()
            ).select_related('asset_category').first()
            if asset:
                bundle_assets.append({
                    'id': asset.id,
                    'asset_name': asset.asset_name,
                    'asset_serial_number': asset.asset_serial_number,
                    'asset_category': asset.asset_category.category,
                    'asset_brand': asset.asset_brand,
                    'status': "Available"
                })
        
        return JsonResponse({'assets': assets_data,'bundle_assets': bundle_assets, 'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})



@login_required   
@require_GET
def get_assigned_assets(request):
    employee_id = request.GET.get('employee_id')
    try:
        employee = Employee.objects.get(admin_id=employee_id)
        assigned_assets = AssetsIssuance.objects.filter(
            asset_assignee=employee.admin,
        ).select_related('asset')


        assets_data = [{
            'id': issuance.asset.id,
            'asset_name': issuance.asset.asset_name,
            'asset_serial_number': issuance.asset.asset_serial_number,
            'issuance_id': issuance.id,
            'location': issuance.asset_location,
            'date_issued': issuance.date_issued.strftime('%Y-%m-%d')
        } for issuance in assigned_assets]
        
        return JsonResponse({'assets': assets_data, 'success': True})
    
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})



@login_required   
@csrf_exempt
@require_POST
def assign_assets(request):
    try:
        data = json.loads(request.body)
        employee_id = data.get('employee_id')
        asset_ids = data.get('asset_ids', [])
        location = data.get('location')

        if not employee_id:
            return JsonResponse({'success': False, 'error': 'Employee ID is required'})
        
        if not asset_ids:
            return JsonResponse({'success': False, 'error': 'Asset IDs are required'})

        employee = Employee.objects.get(admin_id=employee_id)

        assets = Assets.objects.filter(
            id__in=asset_ids, 
            is_asset_issued=False,
        )

        if not assets.exists():
            return JsonResponse({'success': False, 'error': 'No available assets found to assign'})

        created_issuances = []
        for asset in assets:
            issuance = AssetsIssuance.objects.create(
                asset=asset,
                asset_location=location,
                asset_assignee=employee.admin,
            )
            asset.is_asset_issued = True
            asset.save()

            created_issuances.append({
                'issuance_id': issuance.id,
                'asset_id': asset.id,
                'asset_name': asset.asset_name,
                'serial_number': asset.asset_serial_number
            })
        
        return JsonResponse({
            'success': True,
            'message': f'Successfully assigned {len(created_issuances)} asset(s)',
            'issuances': created_issuances
        })
        
    except Employee.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Employee not found'})
    
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})



@login_required   
@csrf_exempt
@require_POST
def remove_asset_assignment(request):
    try:
        data = json.loads(request.body)
        issuance_id = data.get('issuance_id')
        asset_id = data.get('asset_id')

        # Verify the asset belongs to this manager before removal
        asset = Assets.objects.get(
            id=asset_id,
        )
        
        issuance = AssetsIssuance.objects.select_for_update().get(
            id=issuance_id,
            asset=asset
        )

        asset.return_date = timezone.now()        
        asset.is_asset_issued = False
        asset.save()

        AssetAssignmentHistory.objects.create(
            asset = asset,
            assignee = issuance.asset_assignee,
            date_assigned = issuance.date_issued,
            date_returned = timezone.now(),
            location = issuance.asset_location,
            manager = request.user
        )

        issuance.delete()
        
        return JsonResponse({
            'success': True, 
            'message': 'Asset assignment removed successfully',
            'return_date': asset.return_date.strftime('%Y-%m-%d %H:%M:%S'),
            'asset_status': asset.status 
        })
    
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})



@login_required   
@csrf_exempt
@require_POST
def remove_selected_asset_assignment(request):
    try:
        data = json.loads(request.body)
        assets = data.get('assets',[])

        if not assets:
            return JsonResponse({"success":False , 'error' : 'No Assets Selected for Return'})

        returned_count = 0

        for asset in assets:
            issuance_id = asset.get('issuance_id')
            asset_id = asset.get('asset_id')

            asset = Assets.objects.get(id=asset_id)
            issuance = AssetsIssuance.objects.select_for_update().get(
                id=issuance_id,
                asset=asset
            )
            asset.return_date = timezone.now()
            asset.is_asset_issued = False
            asset.save()

            AssetAssignmentHistory.objects.create(
                asset=asset,
                assignee=issuance.asset_assignee,
                date_assigned=issuance.date_issued,
                date_returned=timezone.now(),
                location=issuance.asset_location,
                manager=request.user
            )

            issuance.delete()
            returned_count += 1
        
        return JsonResponse({
            'success': True,
            'message': f'Successfully returned {returned_count} asset(s)'
        })
    
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})



@login_required   
@csrf_exempt
@require_POST
def remove_all_asset_assignment(request):
    try:
        data = json.loads(request.body)
        employee_id = data.get('employee_id')

        if not employee_id:
            return JsonResponse({'success': False, 'error': 'Employee ID is required'})

        employee = Employee.objects.get(admin_id=employee_id)
        issuances = AssetsIssuance.objects.filter(asset_assignee=employee.admin).select_related('asset')

        if not issuances.exists():
            return JsonResponse({'success': False, 'error': 'No assets assigned to this employee'})

        returned_count = 0

        for issuance in issuances:
            asset = issuance.asset
            asset.return_date = timezone.now()
            asset.is_asset_issued = False
            asset.save()

            AssetAssignmentHistory.objects.create(
                asset=asset,
                assignee=issuance.asset_assignee,
                date_assigned=issuance.date_issued,
                date_returned=timezone.now(),
                location=issuance.asset_location,
                manager=request.user
            )

            issuance.delete()
            returned_count += 1
        
        return JsonResponse({
            'success': True,
            'message': f'Successfully returned {returned_count} asset(s)'
        })
    except Employee.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Employee not found'})
    
    except Exception as e:
        return JsonResponse({'success' : False,'error' : str(e)})


@login_required   
def add_employee_by_manager(request):
    # Only managers can add employees to their department
    manager = get_object_or_404(Manager, admin=request.user)

    # Form to add a new employee
    employee_form = EmployeeForm(request.POST or None, request.FILES or None)
    context = {'form': employee_form, 'page_title': 'Add Employee'}

    if request.method == 'POST':
        if employee_form.is_valid():
            first_name = employee_form.cleaned_data.get('first_name')
            last_name = employee_form.cleaned_data.get('last_name')
            address = employee_form.cleaned_data.get('address')
            email = employee_form.cleaned_data.get('email')
            gender = employee_form.cleaned_data.get('gender')
            password = employee_form.cleaned_data.get('password')
            division = employee_form.cleaned_data.get('division')
            designation = employee_form.cleaned_data.get('designation')
            phone_number = employee_form.cleaned_data.get('phone_number')
            department = employee_form.cleaned_data.get('department')

            passport_url = None

            if 'profile_pic' in request.FILES:
                passport = request.FILES['profile_pic']
                fs = FileSystemStorage()
                filename = fs.save(passport.name, passport)
                passport_url = fs.url(filename)

            try:
                # Create the user (employee)
                user = CustomUser.objects.create_user(
                    email=email, 
                    password=password, 
                    user_type=3, 
                    first_name=first_name, 
                    last_name=last_name, 
                    profile_pic=passport_url if passport_url else ""
                )
                user.gender = gender
                user.address = address
                user.save()

                employee = user.employee
                employee.division = division
                employee.department = department
                employee.team_lead = manager  # Assign manager as the team lead
                employee.phone_number = phone_number
                employee.designation = designation
                employee.save()

                messages.success(request, "Successfully Added Employee")
                return redirect(reverse('manage_employee_by_manager'))  # Redirect to employee management page
            except Exception as e:
                messages.error(request, "Could Not Add Employee: " + str(e))
        else:
            messages.error(request, "Please fill all the details correctly.")

    return render(request, 'manager_template/add_employee_by_manager.html', context)


@login_required   
def edit_employee_by_manager(request, employee_id):
    employee = get_object_or_404(Employee, id=employee_id)
    if employee.team_lead != request.user.manager:
        messages.error(request, "You do not have permission to edit this employee.")
        return redirect('manage_employee_by_manager')

    form = EmployeeForm(request.POST or None, instance=employee)
    context = {
        'form': form,
        'employee_id': employee_id,
        "user_object" : employee,
        'page_title': 'Edit Employee'
    }

    if request.method == 'POST':
        if form.is_valid():
            first_name = form.cleaned_data.get('first_name')
            last_name = form.cleaned_data.get('last_name')
            address = form.cleaned_data.get('address')
            username = form.cleaned_data.get('username')
            email = form.cleaned_data.get('email')
            gender = form.cleaned_data.get('gender')
            password = form.cleaned_data.get('password') or None
            division = form.cleaned_data.get('division')
            department = form.cleaned_data.get('department')
            passport = request.FILES.get('profile_pic') or None
            try:
                # Get the related CustomUser instance
                user = CustomUser.objects.get(id=employee.admin.id)

                # If a new passport image is uploaded, update the profile_pic
                if passport is not None:
                    fs = FileSystemStorage()
                    filename = fs.save(passport.name, passport)
                    passport_url = fs.url(filename)
                    user.profile_pic = passport_url

                # Update the CustomUser fields
                user.username = username
                user.email = email
                if password is not None:
                    user.set_password(password)  # Set the new password
                user.first_name = first_name
                user.last_name = last_name
                user.gender = gender
                user.address = address

                # Save the CustomUser instance
                user.save()

                # Update the Employee model fields
                employee.division = division
                employee.department = department
                employee.save()

                messages.success(request, "Employee information updated successfully.")
                return redirect(reverse('manage_employee_by_manager'))
            except Exception as e:
                messages.error(request, "Could not update employee: " + str(e))
        else:
            messages.error(request, "Please fill out the form correctly.")

    return render(request, 'manager_template/edit_employee_by_manager.html', context)


@login_required   
def delete_employee_by_manager(request, employee_id):
    # Get the employee object
    employee = get_object_or_404(Employee, id=employee_id)

    # Ensure that the logged-in manager is the team lead of the employee
    if employee.team_lead != request.user.manager:
        messages.error(request, "You do not have permission to delete this employee.")
        return redirect('manage_employee_by_manager')
   
    issuances = AssetsIssuance.objects.filter(asset_assignee=employee.admin)
    if issuances.exists():
        for issuance in issuances:
            asset = issuance.asset
            asset.is_asset_issued = False
            asset.return_date = timezone.now()
            asset.save()

            AssetAssignmentHistory.objects.create(
                asset=asset,
                assignee=issuance.asset_assignee,
                manager=request.user,
                date_assigned=issuance.date_issued,
                date_returned=timezone.now(),
                location=issuance.asset_location,
                notes="Automatically returned due to employee deletion"
            )
            # delete issuance record
            issuance.delete()

    # Delete the employee
    user = employee.admin
    employee.delete()
    if user:
        user.delete()

    messages.success(request, "Employee deleted successfully.")
    return redirect(reverse('manage_employee_by_manager'))


@login_required   
def manager_feedback(request):
    form = FeedbackManagerForm(request.POST or None)
    manager = get_object_or_404(Manager, admin_id=request.user.id)
    feedbacks_list = FeedbackManager.objects.filter(manager=manager).order_by('-created_at')
    paginator = Paginator(feedbacks_list, 5)  # 5 items per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    context = {
        'form': form,
        'page_obj': page_obj,
        'page_title': 'Add Feedback'
    }
    if request.method == 'POST':
        if form.is_valid():
            try:
                obj = form.save(commit=False)
                obj.manager = manager
                obj.save()
                messages.success(request, "Feedback submitted for review")
                return redirect(reverse('manager_feedback'))
            except Exception:
                messages.error(request, "Could not Submit!")
        else:
            messages.error(request, "Form has errors!")
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string(
            'manager_template/manager_feedback.html',
            context,
            request=request
        )
        return HttpResponse(html)
    
    return render(request, 'manager_template/manager_feedback.html', context)


@login_required
def manager_notify_employee(request):
    employee_list = CustomUser.objects.filter(user_type=3)
    
    paginator = Paginator(employee_list, 5)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_title': "Send Notifications To Employees",
        'employees': page_obj,
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string(
            "manager_template/employee_notification.html",
            context,
            request=request
        )
        return JsonResponse({'success': True, 'html': html})

    return render(request, "manager_template/employee_notification.html", context)


@login_required
@csrf_exempt
def manager_send_employee_notification(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)
    
    id = request.POST.get('id')
    message = request.POST.get('message', '').strip()
    
    if not message:
        return JsonResponse({'success': False, 'message': 'Message cannot be empty'}, status=400)
    
    try:
        # Retrieve CustomUser and corresponding Employee
        user = get_object_or_404(CustomUser, id=id, user_type=3)
        employee = get_object_or_404(Employee, admin=user)
        notification = NotificationEmployee(employee=employee, message=message, created_by=request.user)
        notification.save()
        
        # Assuming send_notification is a custom function; ensure it's defined
        try:
            send_notification(user, message, "notification-from-manager", notification.id, "employee")
        except Exception as e:
            print(f"send_notification failed: {str(e)}")
        
        return JsonResponse({'success': True, 'message': 'Notification sent successfully'})
    except Exception as e:
        print(f"Error: {str(e)}")
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@login_required
@csrf_exempt
def send_bulk_employee_notification_by_manager(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)
    
    message = request.POST.get('message', '').strip()
    
    if not message:
        return JsonResponse({'success': False, 'message': 'Message cannot be empty'}, status=400)
    
    try:
        employees = Employee.objects.all()
        if not employees.exists():
            return JsonResponse({'success': False, 'message': 'No employees found'}, status=400)
        
        for employee in employees:
            user = employee.admin
            notification = NotificationEmployee(employee=employee, message=message, created_by=request.user)
            notification.save()
            try:
                send_notification(user, message, "notification-from-manager", notification.id, "employee")
            except Exception as e:
                print(f"send_notification failed: {str(e)}")
        
        return JsonResponse({'success': True, 'message': 'Bulk notification sent successfully'})
    except Exception as e:
        print(f"Error: {str(e)}")
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@login_required
@csrf_exempt
def send_selected_employee_notification_by_manager(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)
    
    message = request.POST.get('message', '').strip()
    try:
        employee_ids = json.loads(request.POST.get('employee_ids', '[]'))
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid employee IDs format'}, status=400)
    
    if not message:
        return JsonResponse({'success': False, 'message': 'Message cannot be empty'}, status=400)
    
    if not employee_ids:
        return JsonResponse({'success': False, 'message': 'No employees selected'}, status=400)
    
    try:
        for emp_id in employee_ids:
            employee = get_object_or_404(Employee, admin_id=emp_id)
            user = employee.admin
            notification = NotificationEmployee(employee=employee, message=message, created_by=request.user)
            notification.save()

            try:
                send_notification(user, message, "notification-from-manager", notification.id, "employee")
            except Exception as e:
                print(f"send_notification failed: {str(e)}")
        
        return JsonResponse({'success': True, 'message': 'Notification sent to selected employees'})
    except Exception as e:
        print(f"Error: {str(e)}")
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


logger = logging.getLogger(__name__)

@login_required   
def manager_view_profile(request):
    manager = get_object_or_404(Manager, admin=request.user)
    form = ManagerEditForm(request.POST or None, request.FILES or None, instance=manager)
    context = {'form': form, 'page_title': 'View/Update Profile', 'user_object': manager.admin}
    
    if request.method == 'POST':
        try:
            if form.is_valid():
                first_name = form.cleaned_data.get('first_name')
                last_name = form.cleaned_data.get('last_name')
                email = form.cleaned_data.get('email')  # Added email field
                password = form.cleaned_data.get('password') or None
                address = form.cleaned_data.get('address')
                gender = form.cleaned_data.get('gender')
                passport = request.FILES.get('profile_pic') or None
                admin = manager.admin
                
                # Update email
                if email and email != admin.email:
                    admin.email = email
                    logger.info(f"Email updated for user {admin.username} to {email}")
                
                # Update password only if provided and non-empty
                if password and password.strip():
                    admin.set_password(password)
                    update_session_auth_hash(request, admin)  # Prevent session termination
                    logger.info(f"Password updated for user {admin.username}, session updated")
                
                if passport is not None:
                    fs = FileSystemStorage()
                    safe_filename = get_valid_filename(passport.name)
                    filename = fs.save(safe_filename, passport)
                    passport_url = fs.url(filename)
                    admin.profile_pic = passport_url
                    logger.info(f"Profile picture updated for user {admin.username}: {passport_url}")
                
                admin.first_name = first_name
                admin.last_name = last_name
                admin.address = address
                admin.gender = gender
                admin.save()
                manager.save()
                
                messages.success(request, "Profile updated successfully!")
                logger.info(f"Profile update successful for user {admin.username}")
                return redirect(reverse('manager_view_profile'))
            else:
                messages.error(request, "Invalid Data Provided")
                logger.warning(f"Invalid form data for user {request.user.username}")
                return render(request, "manager_template/manager_view_profile.html", context)
        except Exception as e:
            logger.error(f"Error updating profile for user {request.user.username}: {str(e)}")
            messages.error(request, "Error Occurred While Updating Profile: " + str(e))
            return render(request, "manager_template/manager_view_profile.html", context)

    return render(request, "manager_template/manager_view_profile.html", context)


@login_required   
@csrf_exempt
def manager_fcmtoken(request):
    token = request.POST.get('token')
    try:
        manager_user = get_object_or_404(CustomUser, id=request.user.id)
        manager_user.fcm_token = token
        manager_user.save()
        return HttpResponse("True")
    except Exception as e:
        return HttpResponse("False")



@login_required   
def manager_view_notification(request):
    manager = get_object_or_404(Manager, admin=request.user)

    # notification from admin
    notification_from_admin = NotificationManager.objects.filter(manager=manager).order_by('-created_at')

    # Get all unread notifications for manager
    unread_notifications = Notification.objects.filter(
        user=request.user,
        role="manager",
        is_read=False
    ).order_by('-timestamp')

    leave_request_from_employee_notification = unread_notifications.filter(notification_type='leave-notification')

    general_request_from_admin_notification = unread_notifications.filter(notification_type='general-notification',user=request.user)

    clockout_request_from_employee_notification = unread_notifications.filter(notification_type='clockout-notification')

    # Handle "Mark All as Read"
    if request.method == 'POST' and request.POST.get('mark_all_read'):
        with transaction.atomic():
            Notification.objects.filter(
                user=request.user,
                role="manager",
                notification_type="general-notification",
                is_read=False
            ).update(is_read=True)

    # Pending and history for early clock-out requests
    pending_early_clock_out_requests = EarylyClockOutRequest.objects.filter(status='pending').order_by('-submitted_at')
    early_clock_out_history = EarylyClockOutRequest.objects.filter(status__in=['approved', 'denied']).order_by('-reviewed_at')

    # Pending and history
    pending_leave_requests = LeaveReportEmployee.objects.filter(status=0).order_by('-created_at')
    leave_history = LeaveReportEmployee.objects.filter(status__in=[1, 2]).order_by('-updated_at')

    # Pagination
    notification_from_admin_paginator = Paginator(notification_from_admin, 3)
    leave_paginator = Paginator(leave_history, 3)
    early_clock_out_paginator = Paginator(early_clock_out_history, 3)
    early_clock_out_requests_paginator = Paginator(pending_early_clock_out_requests, 3)

    # Get page Numbers
    notification_from_admin_obj = request.GET.get('notification_from_admin_obj')
    leave_notification_page = request.GET.get('leave_notification_page')
    leave_page_number = request.GET.get('leave_history_page')
    early_clock_out_page_number = request.GET.get('early_clock_out_history_page')
    early_clock_out_requests_page = request.GET.get('early_clock_out_requests_page')

    # IDs for Highlighting
    leave_unread_ids = pending_leave_requests.values_list('id',flat=True)
    pending_early_clockout_ids = pending_early_clock_out_requests.values_list('id',flat=True)
    # notification_from_admin_ids = notification_from_admin.values_list('id',flat=True)

    notification_unread_ids = Notification.objects.filter(
        user=request.user,
        role="manager",
        notification_type="general-notification",
        is_read=False
    ).values_list('leave_or_notification_id', flat=True)

    context = {
        
        'notification_from_admin_obj' : notification_from_admin_paginator.get_page(notification_from_admin_obj),
        'pending_leave_requests': pending_leave_requests,
        'leave_history': leave_paginator.get_page(leave_page_number),
        'pending_early_clock_out_requests': early_clock_out_requests_paginator.get_page(early_clock_out_requests_page),
        'early_clock_out_history': early_clock_out_paginator.get_page(early_clock_out_page_number),
        'page_title': "View Notifications",
        'LOCATION_CHOICES': LOCATION_CHOICES,

        'leave_unread_ids' : list(leave_unread_ids),
        'pending_early_clockout_ids' : list(pending_early_clockout_ids),
        'notification_from_admin_ids' : list(notification_unread_ids),
    }

    return render(request, "manager_template/manager_view_notification.html", context)

@login_required
@csrf_exempt
def manager_view_by_employee_feedback_message(request):
    if request.method != 'POST':
        # Handle GET request to display feedback list
        feedback_list = FeedbackEmployee.objects.all().order_by('-id')
        page = request.GET.get('page', 1)
        paginator = Paginator(feedback_list, 10)
        try:
            feedbacks = paginator.page(page)
        except PageNotAnInteger:
            feedbacks = paginator.page(1)
        except EmptyPage:
            feedbacks = paginator.page(paginator.num_pages)

        unread_ids = list(
            Notification.objects.filter(
                user=request.user,
                is_read=False,
                notification_type='employee feedback'
            ).values_list('leave_or_notification_id', flat=True)
        )

        context = {
            'feedbacks': feedbacks,
            'page_title': 'Employee Feedback Messages',
            'unread_ids': unread_ids
        }

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            html = render_to_string(
                'manager_template/manager_view_by_employee_feedback_template.html',
                context,
                request=request
            )
            return JsonResponse({'success': True, 'html': html})

        return render(request, 'manager_template/manager_view_by_employee_feedback_template.html', context)

    # Handle POST request
    if request.POST.get('_method') == 'DELETE':
        feedback_ids = request.POST.getlist('ids[]')
        action = request.POST.get('action')

        try:
            if action == 'delete_all':
                FeedbackEmployee.objects.all().delete()
                Notification.objects.filter(
                    notification_type='employee feedback'
                ).delete()
                return JsonResponse({'success': True, 'message': 'All feedback deleted successfully'})
            elif feedback_ids:
                FeedbackEmployee.objects.filter(id__in=feedback_ids).delete()
                Notification.objects.filter(
                    leave_or_notification_id__in=feedback_ids,
                    notification_type='employee feedback'
                ).delete()
                return JsonResponse({'success': True, 'message': f'Deleted {len(feedback_ids)} feedback entries'})
            else:
                return JsonResponse({'success': False, 'message': 'No feedback IDs provided'}, status=400)
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)

    # Handle feedback reply
    feedback_id = request.POST.get('id')
    try:
        feedback = get_object_or_404(FeedbackEmployee, id=feedback_id)
        reply = request.POST.get('reply')
        feedback.reply = reply
        feedback.updated_at = timezone.now()
        feedback.save()
        
        notify = Notification.objects.filter(
            user=request.user,
            role="admin",
            is_read=False,
            leave_or_notification_id=feedback_id,
            notification_type='employee feedback'
        ).first()
        
        if notify:
            notify.is_read = True
            notify.save()
            
        return JsonResponse({
            'success': True,
            'message': 'Reply sent successfully',
            'reply': feedback.reply,
            'updated_at': feedback.updated_at.strftime('%b %d, %Y %H:%M')
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
    
@login_required
@csrf_exempt
def manager_view_by_employee_leave(request):
    if request.method != 'POST':
        all_leave = LeaveReportEmployee.objects.all().order_by('-created_at')
        paginator = Paginator(all_leave, 10)  
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)
        context = {
            'allLeave': page_obj,
            'page_title': 'Leave Applications From Employees'
        }

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            html = render_to_string(
                "manager_template/manager_view_by_employee_leave_view.html",
                context,
                request=request
            )
            return HttpResponse(html)

        return render(request, "manager_template/manager_view_by_employee_leave_view.html", context)
    else:
        id = request.POST.get('id')
        status = request.POST.get('status')
        status = 1 if status == '1' else -1
        try:
            leave = get_object_or_404(LeaveReportEmployee, id=id)
            leave.status = status
            leave.save()
            return HttpResponse("True")
        except Exception:
            return HttpResponse("False")


@login_required   
def manager_asset_view_notification(request):
    manager = get_object_or_404(Manager, admin=request.user)

    # Recently resolved recurring asset issues
    all_resolved_recurring = AssetIssue.objects.filter(
        status='resolved',
    ).order_by('-resolved_date')[:5]
    print(all_resolved_recurring)

    # Asset claim notifications pending approval
    pending_asset_notifications = Notify_Manager.objects.filter(
        manager=request.user,
        approved__isnull=True
    ).order_by('-timestamp')

    ## Asset claim notification history 
    asset_notification_history = Notify_Manager.objects.filter(
        manager = request.user,
    ).exclude(approved__isnull=True).order_by('-timestamp')

    # Asset issues with pending or in-progress status
    pending_asset_issues = AssetIssue.objects.filter(
        status__in=['pending', 'in_progress']
    ).order_by('-reported_date')

    # Pagination for asset claim notifications
    asset_notification_paginator = Paginator(pending_asset_notifications, 5)
    asset_notification_page_obj = asset_notification_paginator.get_page(request.GET.get('asset_page'))

    # Pagination for asset ckain notification history
    asset_history_claim_notication_paginator = Paginator(asset_notification_history,5)
    asset_history_claim_notication_obj = asset_history_claim_notication_paginator.get_page(request.GET.get('asset_claim_notification_history'))

    # Pagination for resolved recurring issues
    resolved_issues_paginator = Paginator(all_resolved_recurring, 5)
    resolved_issues_page_obj = resolved_issues_paginator.get_page(request.GET.get('resolved_page'))
    # IDs of unread notifications for potential frontend use
    manager_unread_ids = pending_asset_notifications.values_list('id', flat=True)

    # Count of unread asset-related notifications
    unread_asset_notification_count = pending_asset_notifications.count() + pending_asset_issues.count()

    context = {
        'asset_notifications': pending_asset_notifications,
        'asset_issue_notifications': pending_asset_issues,
        'pending_issue': pending_asset_issues.filter(status='pending'),
        'in_progress_issue': pending_asset_issues.filter(status='in_progress'),
        'all_resolved_recurring': all_resolved_recurring,
        'asset_notification_page_obj': asset_notification_page_obj,
        'resolved_issues_page_obj': resolved_issues_page_obj,
        'page_title': "Asset Notifications",
        'manager_unread_ids': manager_unread_ids,
        'LOCATION_CHOICES': LOCATION_CHOICES,
        'unread_asset_notification_count': unread_asset_notification_count,
        'unread_asset_request_count': pending_asset_notifications.count(),
        'unread_asset_issue_count': pending_asset_issues.count(),
        'asset_history_claim_notication_obj' : asset_history_claim_notication_obj
    }

    return render(request, "manager_template/manager_asset_view_notification.html", context)



@login_required   
def approve_assest_request(request, notification_id):
    if request.method == 'POST':
        asset_location_  = request.POST.get("asset_location" , "Main Room")
        notification = get_object_or_404(Notify_Manager, id=notification_id)

        if notification.approved is None or notification.approved is False:
            asset = notification.asset
            employee = notification.employee 
            try:
                AssetsIssuance.objects.create(
                    asset=asset,
                    asset_location=asset_location_,
                    asset_assignee=employee
                )
            
                my_asset = Assets.objects.get(id=asset.id)
                my_asset.manager = request.user
                my_asset.is_asset_issued = True
                my_asset.save()
                notification.approved = True
                notification.save()
                messages.success(request, "Asset request approved successfully.")
                notify = Notification.objects.filter(leave_or_notification_id=notification_id, user=request.user,role = "manager",notification_type = "notification").first()
                if notify:
                    notify.is_read = True
                    notify.save()
            except:
                messages.error(request,"This Asset is not Found in Inventry")

        else:
            messages.info(request, "This request was already approved.")

    return redirect('manager_asset_view_notification')

from django.db import transaction
@login_required   
def reject_assest_request(request, notification_id):
    notification = get_object_or_404(Notify_Manager, id=notification_id)
    if notification.approved is None or notification.approved is False:
        notification.approved = False
        notification.save()
        messages.success(request, "Asset request rejected successfully.")
        notify = Notification.objects.filter(leave_or_notification_id=notification_id, user=request.user,role = "manager",notification_type = "notification").first()
        if notify:
            notify.is_read = True
            notify.save()
        notification.save()
    else:
        messages.info(request, "This request was already approved or rejected.")

    return redirect('manager_asset_view_notification')




logger = logging.getLogger(__name__)

@login_required
def approve_leave_request(request, leave_id):
    if request.method == 'POST':
        try:
            leave = get_object_or_404(LeaveReportEmployee, id=leave_id)

            if leave.status != 0:  # 0 = Pending
                messages.info(request, "This leave request has already been processed.")
                return redirect('manager_view_notification')

            employee = leave.employee
            start_date = leave.start_date
            end_date = leave.end_date or start_date
            leave_amount = 0.5 if leave.leave_type == 'Half-Day' else 1.0

            # Process leave approval
            with transaction.atomic():
                current_date = start_date
                while current_date <= end_date:
                    # Deduct leave
                    success, remaining_leaves = LeaveBalance.deduct_leave(employee, current_date, leave.leave_type)
                    if not success:
                        logger.error(f"Failed to deduct leave for {current_date}")
                        messages.error(request, f"Failed to deduct leave for {current_date.strftime('%d-%m-%Y')}")
                        return redirect('manager_view_notification')

                    # Update or create attendance record
                    record, created = AttendanceRecord.objects.update_or_create(
                        user=employee.admin,
                        date=current_date,
                        defaults={
                            'status': 'half_day' if leave.leave_type == 'Half-Day' else 'leave',
                            'department': employee.department,
                            'clock_in': None,
                            'clock_out': None,
                            'total_worked': None,
                            'regular_hours': None,
                            'overtime_hours': None
                        }
                    )
                    current_date += timedelta(days=1)

                # Update leave status to Approved
                leave.status = 1
                leave.save()

                if leave.leave_type == 'Half-Day':
                    messages.success(request, "Half-Day leave approved.")
                else:
                    messages.success(request, "Full-Day leave approved.")
                msg = "Leave request Approved."

                # Update existing notifications for the employee to mark as read
                Notification.objects.filter(
                    notification_type = 'leave-notification',
                    leave_or_notification_id = leave.id,
                    role = 'manager'
                ).update(is_read=True)
                
                # Send notification to employee
                employee_user = leave.employee.admin
                Notification.objects.create(
                    user=employee_user,
                    message=msg,
                    notification_type="leave-notification",
                    leave_or_notification_id=leave_id,
                    role="employee"
                )

            return redirect('manager_view_notification')

        except Exception as e:
            logger.error(f"Error approving leave ID {leave_id}: {str(e)}")
            messages.error(request, "Error approving leave")
            return redirect('manager_view_notification')
        
    return redirect('manager_view_notification')
            

@login_required   
def reject_leave_request(request, leave_id):
    if request.method == 'POST':
        leave_request = get_object_or_404(LeaveReportEmployee, id=leave_id)
        
        if leave_request.status == 0:
            leave_request.status = 2
            leave_request.save()
            msg = "Leave request rejected."
            messages.warning(request, msg)

            # Update existing notifications for the employee to mark as read
            Notification.objects.filter(
                notification_type = 'leave-notification',
                leave_or_notification_id = leave_request.id,
                role = 'manager'
            ).update(is_read=True)

            # Send notification to employee
            employee_user = leave_request.employee.admin
            Notification.objects.create(
                user=employee_user,
                message=msg,
                notification_type="leave-notification",
                leave_or_notification_id=leave_id,
                role="employee"
            )
            
        else:
            messages.info(request, "This leave request has already been processed.")
    return redirect('manager_view_notification')


@login_required   
def manager_add_salary(request):
    manager = get_object_or_404(Manager, admin=request.user)
    departments = Department.objects.filter(division=manager.division)
    context = {
        'page_title': 'Salary Upload',
        'departments': departments
    }
    if request.method == 'POST':
        try:
            employee_id = request.POST.get('employee_list')
            department_id = request.POST.get('department')
            base = request.POST.get('base')
            ctc = request.POST.get('ctc')
            employee = get_object_or_404(Employee, id=employee_id)
            department = get_object_or_404(Department, id=department_id)
            try:
                data = EmployeeSalary.objects.get(
                    employee=employee, department=department)
                data.ctc = ctc
                data.base = base
                data.save()
                messages.success(request, "Scores Updated")
            except:
                salary = EmployeeSalary(employee=employee, department=department, base=base, ctc=ctc)
                salary.save()
                messages.success(request, "Scores Saved")
        except Exception as e:
            messages.warning(request, "Error Occured While Processing Form")
    return render(request, "manager_template/manager_add_salary.html", context)


@login_required   
def resolve_asset_issue(request,asset_issu_id):
    if request.method == "POST":
        issue_asset = get_object_or_404(AssetIssue,pk=asset_issu_id)
        issue_asset.status = request.POST.get('status')
        issue_asset.notes = request.POST.get('notes')
        issue_asset.resolution_method = request.POST.get('resolution_method')
        issue_asset.is_recurring = request.POST.get('is_recurring') == "on"
        issue_asset.resolved_date = datetime.now()
        issue_asset.save()

        if issue_asset.status == "resolved":
            notify = Notification.objects.filter(leave_or_notification_id=asset_issu_id, role = "manager",notification_type = "asset issue").first()
            if notify:
                notify.is_read = True
                notify.save()
        messages.success(request,f"Asset Issue {issue_asset.status}!!")
    
    return redirect('manager_asset_view_notification')


@login_required   
@csrf_exempt
def fetch_employee_salary(request):
    try:
        department_id = request.POST.get('department')
        employee_id = request.POST.get('employee')
        employee = get_object_or_404(Employee, id=employee_id)
        department = get_object_or_404(Department, id=department_id)
        salary = EmployeeSalary.objects.get(employee=employee, department=department)
        salary_data = {
            'ctc': salary.ctc,
            'base': salary.base
        }
        return HttpResponse(json.dumps(salary_data))
    except Exception as e:
        return HttpResponse('False')
    
    
    
