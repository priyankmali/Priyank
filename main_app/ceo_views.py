from django.contrib import messages
from django.core.files.storage import FileSystemStorage
from django.http import HttpResponse, JsonResponse
from django.shortcuts import (HttpResponse,get_object_or_404, redirect, render)
import requests,json
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from .forms import *
from .models import *
from collections import defaultdict
from calendar import monthrange
from datetime import datetime,timedelta
from decimal import Decimal
from django.template.loader import get_template
from django.contrib.auth.decorators import login_required
from asset_app.models import AssetIssue,AssetsIssuance,AssetAssignmentHistory
from django.db.models import Count,Q
from django.core.paginator import Paginator,EmptyPage,PageNotAnInteger
from main_app.notification_badge import send_notification
from django.template.loader import render_to_string
from django.core.paginator import Paginator
from .models import AttendanceRecord, Holiday, Employee, Manager
from xhtml2pdf import pisa
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.core.paginator import Paginator
from datetime import date, datetime, timedelta
from django.utils import timezone
from dateutil.parser import parse
from django.contrib.auth import update_session_auth_hash
import logging
from django.utils.text import get_valid_filename
from django.contrib.auth import get_user_model 
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile


LOCATION_CHOICES = (
    ("Main Room" , "Main Room"),
    ("Meeting Room", "Meeting Room"),
    ("Main Office", "Main Office"),
)

@login_required
def admin_home(request):
    # Count totals
    total_managers = Manager.objects.all().count()
    total_employees = Employee.objects.all().count()
    departments = Department.objects.all()
    total_department = departments.count()
    total_division = Division.objects.all().count()
    manager_applied_leave = LeaveReportManager.objects.filter(status=0).count()
    employee_applied_leave = LeaveReportEmployee.objects.filter(status=0).count()
    
    today = date.today()
    current_time = timezone.now()

    selected_department = request.GET.get('department', 'all').strip().lower()
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    # Date parsing and validation
    try:
        start_date = parse(start_date_str).date() if start_date_str else today
        end_date = parse(end_date_str).date() if end_date_str else today
        if start_date > end_date:
            start_date, end_date = end_date, start_date
    except (ValueError, TypeError):
        start_date = end_date = today

    employees = CustomUser.objects.filter(user_type=3)  # Employees
    managers = CustomUser.objects.filter(user_type=2)   # Managers
    
    if selected_department != 'all':
        try:
            employees = employees.filter(employee__department__name__iexact=selected_department)
            managers = managers.filter(manager__department__name__iexact=selected_department)
        except Department.DoesNotExist:
            employees = CustomUser.objects.none()
            managers = CustomUser.objects.none()

    employee_ids = employees.values_list('id', flat=True)
    manager_ids = managers.values_list('id', flat=True)
    all_user_ids = list(employee_ids) + list(manager_ids)

    # Filter breaks within the date range and active/ongoing breaks
    employee_breaks_today = Break.objects.filter(
        attendance_record__user_id__in=employee_ids,
        break_start__date__gte=start_date,
        break_start__date__lte=end_date,
        break_end__isnull=True  # Only ongoing breaks
        
    ).distinct()
    
    manager_breaks_today = Break.objects.filter(
        attendance_record__user_id__in=manager_ids,
        break_start__date__gte=start_date,
        break_start__date__lte=end_date,
        break_end__isnull=True  # Only ongoing breaks
    ).distinct()
    
    total_employee_on_break = employee_breaks_today.count()
    total_manager_on_break = manager_breaks_today.count()

    break_entries = []
    break_queryset = Break.objects.filter(
        attendance_record__user_id__in=all_user_ids,
        break_start__date__gte=start_date,
        break_start__date__lte=end_date
    ).select_related('attendance_record__user').order_by('-break_start')
    
    for b in break_queryset:
        user = b.attendance_record.user 
        user_type = 'Employee' if user.user_type == '3' else 'Manager' if user.user_type == '2' else 'Unknown'
        
        department = 'N/A'
        try:
            if user_type == 'Employee':
                employee = Employee.objects.get(admin=user)
                department = employee.department.name if employee.department else 'N/A'
            elif user_type == 'Manager':
                manager = Manager.objects.get(admin=user)
                department = manager.department.name if manager.department else 'N/A'
        except (Employee.DoesNotExist, Manager.DoesNotExist):
            department = 'N/A'
            
        duration = 0
        if b.break_end:
            duration = int((b.break_end - b.break_start).total_seconds() / 60)
        else:
            duration = int((current_time - b.break_start).total_seconds() / 60)
            
        break_entries.append({
            'user_id': user.id,
            'user_name': user.get_full_name() or user.username,
            'user_type': user_type,
            'department': department,
            'break_start': b.break_start.strftime('%H:%M'),
            'break_end': b.break_end.strftime('%H:%M') if b.break_end else 'Ongoing',
            'break_duration': duration,
        })

    paginator = Paginator(break_entries, 10)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        'page_title': "Administrative Dashboard",
        'total_employees': total_employees,
        'total_managers': total_managers,
        'total_department': total_department,
        'total_division': total_division,
        'employee_applied_leave': employee_applied_leave,
        'manager_applied_leave': manager_applied_leave,
        'total_employee_on_break': total_employee_on_break,
        'total_manager_on_break': total_manager_on_break,
        'break_entries': page_obj.object_list,
        'page_obj': page_obj,
        'departments': departments,
        'selected_department': selected_department,
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
    }
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        try:
            html = render_to_string('ceo_template/home_content.html', context, request=request)
            return HttpResponse(html)
        except Exception as e:
            return HttpResponse(f'<div class="text-center py-4 text-danger">Error loading data: {str(e)}</div>', status=500)
    
    return render(request, 'ceo_template/home_content.html', context)


@login_required
def add_manager(request):
    form = ManagerForm(request.POST or None, request.FILES or None)
    context = {'form': form, 'page_title': 'Add Manager'}

    if request.method == 'POST':
        if form.is_valid():
            first_name = form.cleaned_data.get('first_name')
            last_name = form.cleaned_data.get('last_name')
            address = form.cleaned_data.get('address')
            email = form.cleaned_data.get('email')
            gender = form.cleaned_data.get('gender')
            password = form.cleaned_data.get('password')
            division = form.cleaned_data.get('division')
            department = form.cleaned_data.get('department')
            date_of_joining = form.cleaned_data.get('date_of_joining')
            emergency_name = form.cleaned_data.get('emergency_name')
            emergency_relationship = form.cleaned_data.get('emergency_relationship')
            emergency_phone = form.cleaned_data.get('emergency_phone')
            emergency_address = form.cleaned_data.get('emergency_address')

            passport_url = None
            if 'profile_pic' in request.FILES:
                passport = request.FILES['profile_pic']
                fs = FileSystemStorage()
                filename = fs.save(passport.name, passport)
                passport_url = fs.url(filename)

            try:
                user = CustomUser.objects.create_user(
                    email=email,
                    password=password,
                    user_type=2,  # Manager
                    first_name=first_name,
                    last_name=last_name,
                    profile_pic=passport_url if passport_url else ""
                )
                user.gender = gender
                user.address = address
                user.save()

                manager = user.manager
                manager.division = division
                manager.department = department
                manager.date_of_joining = date_of_joining
                manager.emergency_contact = {
                    'name': emergency_name,
                    'relationship': emergency_relationship,
                    'phone': emergency_phone,
                    'address': emergency_address
                }
                manager.save()

                messages.success(request, "Successfully Added")
                return redirect(reverse('manage_manager'))

            except Exception as e:
                messages.error(request, "Could Not Add: " + str(e))
        else:
            messages.error(request, "Please fill all the details correctly.")

    return render(request, 'ceo_template/add_manager_template.html', context)



@login_required
def add_employee(request):
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
            department = employee_form.cleaned_data.get('department')
            designation = employee_form.cleaned_data.get('designation')
            phone_number = employee_form.cleaned_data.get('phone_number')
            team_lead = employee_form.cleaned_data.get('team_lead')
            date_of_joining = employee_form.cleaned_data.get('date_of_joining')
            emergency_name = employee_form.cleaned_data.get('emergency_name')
            emergency_relationship = employee_form.cleaned_data.get('emergency_relationship')
            emergency_phone = employee_form.cleaned_data.get('emergency_phone')
            emergency_address = employee_form.cleaned_data.get('emergency_address')

            passport_url = None
            if 'profile_pic' in request.FILES:
                passport = request.FILES['profile_pic']
                fs = FileSystemStorage()
                filename = fs.save(passport.name, passport)
                passport_url = fs.url(filename)

            try:
                user = CustomUser.objects.create_user(
                    email=email,
                    password=password,
                    user_type=3,  # Employee
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
                employee.phone_number = phone_number
                employee.designation = designation
                employee.date_of_joining = date_of_joining
                if team_lead:
                    employee.team_lead = team_lead

                employee.emergency_contact = {
                    'name': emergency_name,
                    'relationship': emergency_relationship,
                    'phone': emergency_phone,
                    'address': emergency_address
                }

                employee.save()

                messages.success(request, "Successfully Added")
                return redirect(reverse('manage_employee'))
            except Exception as e:
                messages.error(request, "Could Not Add: " + str(e))
        else:
            messages.error(request, "Please fill all the details correctly.")

    return render(request, 'ceo_template/add_employee_template.html', context)



logger = logging.getLogger(__name__)

@login_required
def admin_view_profile(request):
    admin = get_object_or_404(Admin, admin=request.user)
    form = AdminForm(request.POST or None, request.FILES or None, instance=admin)
    context = {'form': form, 'page_title': 'View/Update Profile', 'user_object': admin.admin}
    
    if request.method == 'POST':
        try:
            if form.is_valid():
                first_name = form.cleaned_data.get('first_name')
                last_name = form.cleaned_data.get('last_name')
                email = form.cleaned_data.get('email')
                password = form.cleaned_data.get('password') or None
                address = form.cleaned_data.get('address')
                gender = form.cleaned_data.get('gender')
                profile_pic = request.FILES.get('profile_pic') or None
                user = admin.admin
                
                # Track if any changes were made
                changes_made = False
                
                # Update email
                if email and email != user.email:
                    user.email = email.lower()
                    logger.info(f"Email updated for user {user.username} to {email}")
                    changes_made = True
                
                # Update password only if provided and non-empty
                if password and password.strip():
                    user.set_password(password)
                    update_session_auth_hash(request, user)
                    logger.info(f"Password updated for user {user.username}, session updated")
                    changes_made = True
                
                if profile_pic is not None:
                    safe_filename = get_valid_filename(profile_pic.name)
                    filename = default_storage.save(safe_filename, ContentFile(profile_pic.read()))
                    profile_pic_url = default_storage.url(filename)
                    user.profile_pic = profile_pic_url
                    logger.info(f"Profile picture updated for user {user.username}: {profile_pic_url}")
                    changes_made = True
                
                # Update other fields if changed
                if user.first_name != first_name:
                    user.first_name = first_name
                    changes_made = True
                if user.last_name != last_name:
                    user.last_name = last_name
                    changes_made = True
                if user.address != address:
                    user.address = address
                    changes_made = True
                if user.gender != gender:
                    user.gender = gender
                    changes_made = True
                
                # Save only if changes were made
                if changes_made:
                    user.save()
                    admin.save()
                    messages.success(request, "Profile updated successfully!")
                    logger.info(f"Profile update successful for user {user.username}")
                    return redirect(reverse('admin_view_profile'))
                else:
                    
                    logger.info(f"No changes made for user {user.username}")
                    return redirect(reverse('admin_view_profile'))
            else:
                messages.error(request, "Invalid Data Provided")
                logger.warning(f"Invalid form data for user {request.user.username}")
                return render(request, "ceo_template/admin_view_profile.html", context)
        except Exception as e:
            logger.error(f"Error updating profile for user {request.user.username}: {str(e)}")
            messages.error(request, "Error Occurred While Updating Profile: " + str(e))
            return render(request, "ceo_template/admin_view_profile.html", context)

    return render(request, "ceo_template/admin_view_profile.html", context)
    


@login_required
def add_division(request):
    form = DivisionForm(request.POST or None)
    context = {
        'form': form,
        'page_title': 'Add Division'
    }
    if request.method == 'POST':
        if form.is_valid():
            name = form.cleaned_data.get('name')
            
            if Division.objects.filter(name__iexact=name).exists():
                messages.error(request, "This department already exist")
            else:
                try:
                    division = Division()
                    division.name = name
                    division.save()
                    messages.success(request, "Successfully Added")
                    return redirect(reverse('manage_division'))
                except:
                    messages.error(request, "Could Not Add")
        else:
            messages.error(request, "Could Not Add")
    return render(request, 'ceo_template/add_division_template.html', context)


@login_required
def add_department(request):
    form = DepartmentForm(request.POST or None)
    context = {
        'form': form,
        'page_title': 'Add Department'
    }
    if request.method == 'POST':
        if form.is_valid():
            name = form.cleaned_data.get('name')
            division = form.cleaned_data.get('division')
            if Department.objects.filter(name__iexact=name, division=division):
                messages.error(request, "This division already exist") 
            else:
                try:
                    department = Department()
                    department.name = name
                    department.division = division
                    department.save()
                    messages.success(request, "Successfully Added")
                    return redirect(reverse('manage_department'))

                except Exception as e:
                    messages.error(request, "Could Not Add " + str(e))
        else:
            messages.error(request, "Fill Form Properly")

    return render(request, 'ceo_template/add_department_template.html', context)


@login_required
def manage_manager(request):
    manager_list = CustomUser.objects.filter(user_type=2)
    
    paginator = Paginator(manager_list, 5)
    page_number = request.GET.get('page', 1)
    
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    manager_list = CustomUser.objects.filter(user_type=2)
    
    paginator = Paginator(manager_list, 5)
    page_number = request.GET.get('page', 1)
    
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    context = {
        'allManager': page_obj.object_list,
        'page_obj': page_obj,
        'page_title': 'Manage Manager'
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string(
            "ceo_template/manage_manager.html",
            context,
            request=request
        )
        return HttpResponse(html)

    return render(request, "ceo_template/manage_manager.html", context)


@login_required
def view_manager(request, manager_id):
    manager = get_object_or_404(Manager, id=manager_id)
    context = {
        'manager': manager,
        'page_title': f'Profile - {manager}'
    }
    print("iiiiiiiiiiiiii",manager)
    return render(request, 'ceo_template/view_manager.html', context)


@login_required
def manage_employee(request):
    search_ = request.GET.get("search", '').strip()
    gender = request.GET.get("gender", '')
    department_id = request.GET.get("department", '')
    division_id = request.GET.get("division", '')
    page_number = request.GET.get('page', 1)

    # Get employees with asset count
    employees = CustomUser.objects.filter(
        user_type=3,
        employee__isnull=False
    ).annotate(
        asset_count=Count('assetsissuance'),
    ).select_related('employee', 'employee__department', 'employee__division', 'employee__team_lead')

    # Apply filters
    if search_:
        employees = employees.filter(
            Q(first_name__icontains=search_) |
            Q(last_name__icontains=search_) |
            Q(email__icontains=search_)
        )
    
    if gender:
        employees = employees.filter(gender=gender)
    
    if department_id:
        employees = employees.filter(employee__department__id=department_id)
    
    if division_id:
        employees = employees.filter(employee__division__id=division_id)

    # Get all departments and divisions for filter dropdowns
    departments = Department.objects.all()
    divisions = Division.objects.all()

    paginator = Paginator(employees, 5)
    page_obj = paginator.get_page(page_number)

    context = {
        'employees': page_obj.object_list,
        'page_obj': page_obj,
        'page_title': 'Manage Employees',
        'location_choices': dict(LOCATION_CHOICES),
        'search': search_,
        'departments': departments,
        'divisions': divisions,
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string(
            "ceo_template/manage_employee.html",
            context,
            request=request
        )
        return HttpResponse(html)

    if not employees:
        messages.warning(request, "No employees found")
    return render(request, "ceo_template/manage_employee.html", context)


@login_required
def view_employee(request, employee_id):
    employee = get_object_or_404(Employee, id=employee_id)
    context = {
        'employee': employee,
        'page_title': f'Profile - {employee}'
    }
    return render(request, 'ceo_template/view_employee.html', context)


@login_required
def manage_division(request):
    divisions = Division.objects.all()
    page = request.GET.get('page', 1)
    
    paginator = Paginator(divisions, 10)  
    try:
        divisions = paginator.page(page)
    except PageNotAnInteger:
        divisions = paginator.page(1)
    except EmptyPage:
        divisions = paginator.page(paginator.num_pages)

    context = {
        'divisions': divisions,
        'page_title': 'Manage Divisions'
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string(
            "ceo_template/manage_division.html",
            context,
            request=request
        )
        return HttpResponse(html)

    return render(request, "ceo_template/manage_division.html", context)


@login_required
def manage_department(request):
    department_list = Department.objects.all()
    page = request.GET.get('page', 10)
    
    paginator = Paginator(department_list, 10)  # 1 item per page
    try:
        departments = paginator.page(page)
    except PageNotAnInteger:
        departments = paginator.page(1)
    except EmptyPage:
        departments = paginator.page(paginator.num_pages)
    
    context = {
        'departments': departments,  # Note: This is the paginated object
        'page_title': 'Manage Departments'
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string(
            "ceo_template/manage_department.html",
            context,
            request=request
        )
        return HttpResponse(html)

    return render(request, "ceo_template/manage_department.html", context)


@login_required
def edit_manager(request, manager_id):
    manager = get_object_or_404(Manager, id=manager_id)
    form = ManagerForm(request.POST or None, request.FILES or None, instance=manager)

    context = {
        'form': form,
        'manager_id': manager_id,
        'user_object': manager,
        'page_title': 'Edit Manager'
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

            emergency_name = form.cleaned_data.get('emergency_name')
            emergency_relationship = form.cleaned_data.get('emergency_relationship')
            emergency_phone = form.cleaned_data.get('emergency_phone')
            emergency_address = form.cleaned_data.get('emergency_address')

            try:
                if emergency_phone and (not emergency_phone.isdigit() or len(emergency_phone) != 10):
                    raise ValidationError("Emergency phone number must be exactly 10 digits.")

                user = manager.admin
                user.username = username
                user.email = email
                if password:
                    user.set_password(password)
                user.first_name = first_name
                user.last_name = last_name
                user.gender = gender
                user.address = address

                if passport:
                    fs = FileSystemStorage()
                    filename = fs.save(passport.name, passport)
                    passport_url = fs.url(filename)
                    user.profile_pic = passport_url

                user.save()

                manager.division = division
                manager.department = department
                manager.emergency_contact = {
                    'name': emergency_name or "Not provided",
                    'relationship': emergency_relationship or "Not provided",
                    'phone': emergency_phone or "Not provided",
                    'address': emergency_address or "Not provided"
                }

                manager.save()

                messages.success(request, "Manager information updated successfully.")
                return redirect(reverse('manage_manager'))

            except Exception as e:
                messages.error(request, "Could Not Update: " + str(e))
        else:
            messages.error(request, "Please fill all fields properly.")

    return render(request, "ceo_template/edit_manager_template.html", context)

    
@login_required
def edit_employee(request, employee_id):
    employee = get_object_or_404(Employee, id=employee_id)
    form = EmployeeForm(request.POST or None, instance=employee)
    
    context = {
        'form': form,
        'employee_id': employee_id,
        'user_object': employee,
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
            designation = form.cleaned_data.get('designation')
            phone_number = form.cleaned_data.get('phone_number')
            team_lead = form.cleaned_data.get('team_lead')
            passport = request.FILES.get('profile_pic') or None

            emergency_name = form.cleaned_data.get('emergency_name')
            emergency_relationship = form.cleaned_data.get('emergency_relationship')
            emergency_phone = form.cleaned_data.get('emergency_phone')
            emergency_address = form.cleaned_data.get('emergency_address')

            try:
                if emergency_phone and (not emergency_phone.isdigit() or len(emergency_phone) != 10):
                    raise ValidationError("Emergency phone number must be exactly 10 digits.")

                user = employee.admin
                user.username = username
                user.email = email
                if password:
                    user.set_password(password)
                user.first_name = first_name
                user.last_name = last_name
                user.gender = gender
                user.address = address

                if passport:
                    fs = FileSystemStorage()
                    filename = fs.save(passport.name, passport)
                    passport_url = fs.url(filename)
                    user.profile_pic = passport_url

                user.save()

                employee.division = division
                employee.department = department
                employee.designation = designation
                employee.phone_number = phone_number
                employee.team_lead = team_lead

                employee.emergency_contact = {
                    'name': emergency_name or "Not provided",
                    'relationship': emergency_relationship or "Not provided",
                    'phone': emergency_phone or "Not provided",
                    'address': emergency_address or "Not provided"
                }

                employee.save()

                messages.success(request, "Employee information updated successfully.")
                return redirect(reverse('manage_employee'))

            except Exception as e:
                messages.error(request, "Could Not Update: " + str(e))
        else:
            messages.error(request, "Please fill all fields properly.")

    return render(request, "ceo_template/edit_employee_template.html", context)


@login_required
def edit_division(request, division_id):
    instance = get_object_or_404(Division, id=division_id)
    form = DivisionForm(request.POST or None, instance=instance)
    context = {
        'form': form,
        'division_id': division_id,
        'page_title': 'Edit Division'
    }
    if request.method == 'POST':
        if form.is_valid():
            name = form.cleaned_data.get('name')
            try:
                division = Division.objects.get(id=division_id)
                division.name = name
                division.save()
                messages.success(request, "Successfully Updated")
                return redirect(reverse('manage_division'))
            except:
                messages.error(request, "Could Not Update")
        else:
            messages.error(request, "Could Not Update")

    return render(request, 'ceo_template/edit_division_template.html', context)


@login_required
def edit_department(request, department_id):
    instance = get_object_or_404(Department, id=department_id)
    form = DepartmentForm(request.POST or None, instance=instance)
    context = {
        'form': form,
        'department_id': department_id,
        'page_title': 'Edit Department'
    }
    if request.method == 'POST':
        if form.is_valid():
            name = form.cleaned_data.get('name')
            division = form.cleaned_data.get('division')
            try:
                department = Department.objects.get(id=department_id)
                department.name = name
                department.division = division
                department.save()
                messages.success(request, "Successfully Updated")
                return redirect(reverse('manage_department'))
            except Exception as e:
                messages.error(request, "Could Not Add " + str(e))
        else:
            messages.error(request, "Fill Form Properly")
    return render(request, 'ceo_template/edit_department_template.html', context)


@csrf_exempt
def check_email_availability(request):
    email = request.POST.get("email")
    try:
        user = CustomUser.objects.filter(email=email).exists()
        if user:
            return HttpResponse(True)
        return HttpResponse(False)
    except Exception as e:
        return HttpResponse(False)


@login_required
@csrf_exempt
def employee_feedback_message(request):
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
                'ceo_template/employee_feedback_template.html',
                context,
                request=request
            )
            return JsonResponse({'success': True, 'html': html})

        return render(request, 'ceo_template/employee_feedback_template.html', context)

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
def manager_feedback_message(request):
    if request.method != 'POST':
        # Handle GET request to display feedback list
        feedback_list = FeedbackManager.objects.all().order_by('-id')
        page = request.GET.get('page', 1)
        paginator = Paginator(feedback_list, 10)
        try:
            feedbacks = paginator.page(page)
        except PageNotAnInteger:
            feedbacks = paginator.page(1)
        except EmptyPage:
            feedbacks = paginator.page(paginator.num_pages)

        context = {
            'feedbacks': feedbacks,
            'page_title': 'Manager Feedback Messages'
        }

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            html = render_to_string(
                'ceo_template/manager_feedback_template.html',
                context,
                request=request
            )
            return JsonResponse({'success': True, 'html': html})

        return render(request, 'ceo_template/manager_feedback_template.html', context)

    # Handle POST request
    if request.POST.get('_method') == 'DELETE':
        feedback_ids = request.POST.getlist('ids[]')
        action = request.POST.get('action')

        try:
            if action == 'delete_all':
                FeedbackManager.objects.all().delete()
                return JsonResponse({'success': True, 'message': 'All feedback deleted successfully'})
            elif feedback_ids:
                FeedbackManager.objects.filter(id__in=feedback_ids).delete()
                return JsonResponse({'success': True, 'message': f'Deleted {len(feedback_ids)} feedback entries'})
            else:
                return JsonResponse({'success': False, 'message': 'No feedback IDs provided'}, status=400)
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)

    # Handle feedback reply
    feedback_id = request.POST.get('id')
    try:
        feedback = get_object_or_404(FeedbackManager, id=feedback_id)
        reply = request.POST.get('reply').strip()
        if not reply:
            return JsonResponse({'success': False, 'message': 'Reply cannot be empty'}, status=400)
        feedback.reply = reply
        feedback.updated_at = timezone.now()
        feedback.save()
        
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
def view_manager_leave(request):
    if request.method != 'POST':
        allLeaveList = LeaveReportManager.objects.all().order_by('-created_at')
        paginator = Paginator(allLeaveList, 10) 
        page_number = request.GET.get('page')
        allLeave = paginator.get_page(page_number)

        unread_notification_ids = Notification.objects.filter(
            user = request.user,
            role = 'ceo',
            is_read = False
        ).values_list('leave_or_notification_id' , flat=True)

        context = {
            'allLeave': allLeave,
            'unread_notification_ids' : list(unread_notification_ids),
            'page_title': 'Leave Applications From Manager'
        }

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            html = render_to_string(
                "ceo_template/manager_leave_view.html",
                context,
                request=request
            )
            return HttpResponse(html)

        return render(request, "ceo_template/manager_leave_view.html", context)
    else:
        id = request.POST.get('id')
        status = request.POST.get('status')
        status = 1 if status == '1' else -1
        try:
            leave = get_object_or_404(LeaveReportManager, id=id)
            if leave.status == 0:
                if status == -1: # Rejected

                    # Update existing notification to mark as read
                    Notification.objects.filter(
                        leave_or_notification_id = leave.id,
                        role = 'ceo',
                        is_read = False,
                        notification_type = 'manager-leave-notification',
                    ).update(is_read = True)

                    # Send notification to manager
                    Notification.objects.create(
                        user = leave.manager.admin,
                        role = 'manager',
                        notification_type = 'manager-leave-notification',
                        leave_or_notification_id = leave.id,
                        message = "Leave Request Rejected"
                    )

                    leave.status = status
                    leave.save()
                    return HttpResponse(True)
                
                if status == 1: # Approved

                    # Update existing notification to mark as read
                    Notification.objects.filter(
                        leave_or_notification_id = leave.id,
                        role = 'ceo',
                        is_read = False,
                        notification_type = 'manager-leave-notification'
                    ).update(is_read = True)

                    # Send notification to manager
                    Notification.objects.create(
                        user = leave.manager.admin,
                        role = 'manager',
                        notification_type = 'manager-leave-notification',
                        leave_or_notification_id = leave.id,
                        message = "Leave Request Approved"
                    )

                    leave.status = status
                    leave.save()
                    return HttpResponse(True)
                
        except Exception:
            return HttpResponse(False)


@login_required
@csrf_exempt
def view_employee_leave(request):
    if request.method != 'POST':
        all_leave = LeaveReportEmployee.objects.all().order_by('-created_at')
        paginator = Paginator(all_leave, 10)  
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)
        unread_ids = Notification.objects.filter(
            user = request.user , 
            role = 'ceo' ,
            is_read = False
        ).values_list('leave_or_notification_id' , flat=True)
        context = {
            'allLeave': page_obj,
            'unread_ids' : list(unread_ids),
            'page_title': 'Leave Applications From Employees'
        }

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            html = render_to_string(
                "ceo_template/employee_leave_view.html",
                context,
                request=request
            )
            return HttpResponse(html)

        return render(request, "ceo_template/employee_leave_view.html", context)
    else:
        id = request.POST.get('id')
        status = request.POST.get('status')
        status = 1 if status == '1' else -1
        try:
            leave = get_object_or_404(LeaveReportEmployee, id=id)
            if leave.status == 0:  # 0  Pending
                if status == -1: # Rejected
                    # Update existing notifications to mark as read
                    Notification.objects.filter(
                        notification_type__in = ['leave-notification' , 'employee-leave-notification'],
                        leave_or_notification_id = leave.id,
                        is_read = False
                    ).update(is_read=True)
                    
                    # Send notification to employee
                    Notification.objects.create(
                        user=leave.employee.admin,
                        message="Leave Request Rejected",
                        notification_type="leave-notification",
                        leave_or_notification_id=id,
                        role="employee"
                    )

                    # Update leave status
                    leave.status = status
                    leave.save()
                    return HttpResponse("True")

                if status == 1:  # Approved
                    employee = leave.employee
                    start_date = leave.start_date
                    end_date = leave.end_date or start_date
                    leave_amount = 0.5 if leave.leave_type == 'Half-Day' else 1.0

                    # Process leave approval
                    current_date = start_date
                    while current_date <= end_date:
                        # Deduct leave
                        success, remaining_leaves = LeaveBalance.deduct_leave(employee, current_date, leave.leave_type)
                        if not success:
                            return HttpResponse("False")

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

                    # Prepare notification message
                    if leave.leave_type == 'Half-Day':
                        msg = "Half-Day leave approved by Admin."
                    else:
                        msg = "Full-Day leave approved by Admin."

                    # Update existing notifications to mark as read
                    Notification.objects.filter(
                        notification_type__in = ['leave-notification' , 'employee-leave-notification'],
                        leave_or_notification_id = leave.id,
                        is_read = False
                    ).update(is_read=True)
                    
                    # Send notification to employee
                    employee_user = leave.employee.admin
                    Notification.objects.create(
                        user=employee_user,
                        message=msg,
                        notification_type="leave-notification",
                        leave_or_notification_id=id,
                        role="employee"
                    )

                    # Update leave status
                    leave.status = status
                    leave.save()
                    return HttpResponse("True")

        except Exception as e:
            return HttpResponse("False")


@login_required
@csrf_exempt
def get_admin_attendance(request):
    department_id = request.POST.get('department')
    attendance_date_id = request.POST.get('attendance_date_id')
    try:
        department = get_object_or_404(Department, id=department_id)
        attendance = get_object_or_404(AttendanceRecord, id=attendance_date_id)
        attendance_reports = AttendanceRecord.objects.filter(attendance=attendance)
        json_data = []
        for report in attendance_reports:
            data = {
                "status": str(report.status),
                "name": str(report.employee)
            }
            json_data.append(data)
        return JsonResponse(json.dumps(json_data), safe=False)
    except Exception as e:
        return None


@login_required
def admin_notify_manager(request):
    manager_list = CustomUser.objects.filter(user_type=2).order_by('last_name', 'first_name')
    
    page = request.GET.get('page', 1)
    paginator = Paginator(manager_list, 5)
    
    try:
        managers = paginator.page(page)
    except PageNotAnInteger:
        managers = paginator.page(1)
    except EmptyPage:
        managers = paginator.page(paginator.num_pages)
    
    context = {
        'page_title': "Send Notifications To Manager",
        'allManager': managers,
        'page_obj': managers
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string(
            "ceo_template/manager_notification.html",
            context,
            request=request
        )
        return JsonResponse({'success': True, 'html': html})

    return render(request, "ceo_template/manager_notification.html", context)



@login_required
@csrf_exempt
def send_manager_notification(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)
    
    id = request.POST.get('id')
    message = request.POST.get('message', '').strip()
    
    if not message:
        return JsonResponse({'success': False, 'message': 'Message cannot be empty'}, status=400)
    
    try:
        manager = get_object_or_404(Manager, admin_id=id)
        
        # Create NotificationManager entry
        notification = NotificationManager(manager=manager, message=message)
        notification.save()
        user = CustomUser.objects.get(id=manager.admin.id)
        send_notification(user, message, "general-notification", notification.id, "manager")
        
        return JsonResponse({'success': True, 'message': 'Notification sent successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
    

@login_required
@csrf_exempt
def send_bulk_manager_notification(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)
    
    message = request.POST.get('message', '').strip()
    
    if not message:
        return JsonResponse({'success': False, 'message': 'Message cannot be empty'}, status=400)
    
    try:
        managers = Manager.objects.all()
        if not managers.exists():
            return JsonResponse({'success': False, 'message': 'No managers found'}, status=400)
        
        for manager in managers:
            # FCM notification (uncommented as in original)
            if manager.admin.fcm_token:
                url = "https://fcm.googleapis.com/fcm/send"
                body = {
                    'notification': {
                        'title': "KoliInfoTech",
                        'body': message,
                        'click_action': reverse('manager_view_notification'),
                        'icon': static('dist/img/AdminLTELogo.png')
                    },
                    'to': manager.admin.fcm_token
                }
                headers = {
                    'Authorization': 'key=AAAA3Bm8j_M:APA91bElZlOLetwV696SoEtgzpJr2qbxBfxVBfDWFiopBWzfCfzQp2nRyC7_A2mlukZEHV4g1AmyC6P_HonvSkY2YyliKt5tT3fe_1lrKod2Daigzhb2xnYQMxUWjCAIQcUexAMPZePB',
                    'Content-Type': 'application/json'
                }
                requests.post(url, data=json.dumps(body), headers=headers)
            
            # Save notification to database
            notification = NotificationManager(manager=manager, message=message)
            notification.save()
        
        return JsonResponse({'success': True, 'message': 'Bulk notification sent successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
    
    

@login_required
@csrf_exempt
def send_selected_manager_notification(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)
    
    message = request.POST.get('message', '').strip()
    try:
        manager_ids = json.loads(request.POST.get('manager_ids', '[]'))
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid manager IDs format'}, status=400)
    
    if not message:
        return JsonResponse({'success': False, 'message': 'Message cannot be empty'}, status=400)
    
    if not manager_ids:
        return JsonResponse({'success': False, 'message': 'No managers selected'}, status=400)
    
    try:
        for manager_id in manager_ids:
            manager = get_object_or_404(Manager, admin_id=manager_id)
            if manager.admin.fcm_token:
                url = "https://fcm.googleapis.com/fcm/send"
                body = {
                    'notification': {
                        'title': "KoliInfoTech",
                        'body': message,
                        'click_action': reverse('manager_view_notification'),
                        'icon': static('dist/img/AdminLTELogo.png')
                    },
                    'to': manager.admin.fcm_token
                }
                headers = {
                    'Authorization': 'key=AAAA3Bm8j_M:APA91bElZlOLetwV696SoEtgzpJr2qbxBfxVBfDWFiopBWzfCfzQp2nRyC7_A2mlukZEHV4g1AmyC6P_HonvSkY2YyliKt5tT3fe_1lrKod2Daigzhb2xnYQMxUWjCAIQcUexAMPZePB',
                    'Content-Type': 'application/json'
                }
                requests.post(url, data=json.dumps(body), headers=headers)
            
            # Save notification to database
            notification = NotificationManager(manager=manager, message=message)
            notification.save()
        
        return JsonResponse({'success': True, 'message': 'Notification sent to selected managers'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)



@login_required
def admin_notify_employee(request):
    employee_list = CustomUser.objects.filter(user_type=3).order_by('last_name', 'first_name')    
    page = request.GET.get('page', 1)
    paginator = Paginator(employee_list, 10)
    
    try:
        employees = paginator.page(page)
    except PageNotAnInteger:
        employees = paginator.page(1)
    except EmptyPage:
        employees = paginator.page(paginator.num_pages)
    
    context = {
        'page_title': "Send Notifications To Employees",
        'employees': employees,
        'page_obj': employees
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string(
            "ceo_template/employee_notification.html",
            context,
            request=request
        )
        return JsonResponse({'success': True, 'html': html})

    return render(request, "ceo_template/employee_notification.html", context)



@login_required
@csrf_exempt
def send_employee_notification(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)
    
    id = request.POST.get('id')
    message = request.POST.get('message', '').strip()
    
    if not message:
        return JsonResponse({'success': False, 'message': 'Message cannot be empty'}, status=400)
    
    try:
        employee = get_object_or_404(Employee, admin_id=id)
        user = employee.admin
        notification = NotificationEmployee(employee=employee, message=message, created_by=request.user)
        notification.save()

        try:
            send_notification(user, message, "notification-from-admin", notification.id, "employee")
        except Exception as e:
            print(f"send_notification failed: {str(e)}")
        
        return JsonResponse({'success': True, 'message': 'Notification sent successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
    

@login_required
@csrf_exempt
def send_bulk_employee_notification(request):
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
                send_notification(user, message, "notification-from-admin", notification.id, "employee")
            except Exception as e:
                print(f"send_notification failed: {str(e)}")
        
        return JsonResponse({'success': True, 'message': 'Bulk notification sent successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
    

@login_required
@csrf_exempt
def send_selected_employee_notification(request):
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
                send_notification(user, message, "notification-from-admin", notification.id, "employee")
            except Exception as e:
                print(f"send_notification failed: {str(e)}")
                
        return JsonResponse({'success': True, 'message': 'Notification sent to selected employees'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)



@login_required
def delete_manager(request, manager_id):
    manager = get_object_or_404(CustomUser, manager__id=manager_id)
    try:
        manager.delete()
        messages.success(request, "Manager deleted successfully!")
    except Exception as e:
        messages.error(request,"Sorry, failed to delete manager.")
    return redirect(reverse('manage_manager'))


@login_required
def delete_employee(request, employee_id):
    employee = get_object_or_404(CustomUser, employee__id=employee_id)
    try:
        issuances = AssetsIssuance.objects.filter(asset_assignee=employee)
        if issuances.exists():
            for issuance in issuances:
                asset = issuance.asset
                asset.is_asset_issued = False
                asset.return_date = timezone.now()
                asset.save()

                # Log the return in AssetAssignmentHistory
                AssetAssignmentHistory.objects.create(
                    asset=asset,
                    assignee=employee,
                    manager=request.user,
                    date_assigned=issuance.date_issued,
                    date_returned=timezone.now(),
                    location=issuance.asset_location,
                    notes="Automatically returned due to employee deletion by admin"
                )

                # Delete the issuance record
                issuance.delete()

        employee.delete()
        messages.success(request, "Employee deleted successfully!")
    except Exception:
        messages.error(request,"Sorry, failed to delete employee.")
    return redirect(reverse('manage_employee'))


@login_required
def delete_division(request, division_id):
    division = get_object_or_404(Division, id=division_id)
    try:
        division.delete()
        messages.success(request, "Division deleted successfully!")
    except Exception:
        messages.error(
            request, "Sorry, some employees are assigned to this division already. Kindly change the affected employee division and try again")
    return redirect(reverse('manage_division'))


@login_required
def delete_department(request, department_id):
    try:
        department = get_object_or_404(Department, id=department_id)
        department.delete()
        messages.success(request, "Department deleted successfully!")
        return redirect(reverse('manage_department'))
    except Exception:
        messages.error(
            request, "Sorry, some employees are assigned to this department already. Kindly change the affected employee division and try again")
    return redirect(reverse('manage_department'))


@require_POST
@login_required
def get_department_data(request):
    if request.method == "POST":
        department_id = request.POST.get('department')

        data = {
            'employees' : [],
            'managers' : [],
            'status' : 'success'
        }
        try:
            if department_id and department_id != 'all':
                employees = Employee.objects.filter(department_id=department_id).select_related('admin')
                managers = Manager.objects.filter(department_id=department_id).select_related('admin')
                
                data['employees'] = [{
                    'id' : emp.admin.id,
                    'name' : f'{emp.admin.get_full_name()}'
                } for emp in employees]

                data['managers'] = [{
                    'id' : mag.admin.id,
                    'name' : f"{mag.admin.get_full_name()}"
                } for mag in managers]

            return JsonResponse(data)

        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=400)


@login_required
def generate_performance_report(request):
    departments = Department.objects.all()
    
    if request.method == 'POST':
        employee_ids = request.POST.getlist('employee')
        manager_ids = request.POST.getlist('manager')
        month = request.POST.get('month')
        year = request.POST.get('year')
        department_id = request.POST.get('department')

        if not month or not year:
            messages.error(request, "Month and Year are required fields")
            return redirect('generate_performance_report')
            
        if not department_id and not employee_ids and not manager_ids:
            messages.error(request, "Please select at least one filter (Department, Employee or Manager)")
            return redirect('generate_performance_report')
        
        try:
            year = int(year)
            month = int(month)
            
            # Get employees and managers based on selection
            employees = Employee.objects.all()
            managers = Manager.objects.all()

            if department_id and department_id != 'all':
                employees = employees.filter(department_id=department_id)
                managers = managers.filter(department_id=department_id)
            if employee_ids:
                employees = employees.filter(admin__id__in=employee_ids)
            if manager_ids:
                managers = managers.filter(admin__id__in=manager_ids)
            
            # Process each employee and manager
            all_reports = []
            
            # Process employees
            for employee in employees:
                report = generate_individual_report(employee.admin, year, month)
                all_reports.append(report)
            
            # Process managers
            for manager in managers:
                report = generate_individual_report(manager.admin, year, month)
                all_reports.append(report)
            
            # For HTML preview
            if 'generate_html' in request.POST:
                if len(all_reports) == 1:
                    return render(request, 'ceo_template/attendance_report_pdf.html', all_reports[0])
                else:
                    return render(request, 'ceo_template/multi_employee_report.html', {
                        'all_reports': all_reports,
                        'month_name': datetime(year, month, 1).strftime('%B'),
                        'year': year,
                    })
            
            # For PDF generation
            if 'generate_pdf' in request.POST:
                if len(all_reports) == 1:
                    template = get_template('ceo_template/attendance_report_pdf.html')
                    filename = f"attendance_report_{all_reports[0]['employee'].admin.get_full_name()}_{month}_{year}.pdf"
                    context = all_reports[0]
                else:
                    template = get_template('ceo_template/multi_employee_report.html')
                    filename = f"attendance_report_{month}_{year}.pdf"
                    context = {
                        'all_reports': all_reports,
                        'month_name': datetime(year, month, 1).strftime('%B'),
                        'year': year,
                    }
                
                html = template.render(context)
                
                response = HttpResponse(content_type='application/pdf')
                response['Content-Disposition'] = f'attachment; filename="{filename}"'
                
                pisa_status = pisa.CreatePDF(html, dest=response)
                if pisa_status.err:
                    messages.error(request, 'Error generating PDF')
                    return redirect('generate_performance_report')
                return response
            
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
            return redirect('generate_performance_report')
    
    # GET request handling
    all_months = [
        (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
        (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
        (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December')
    ]
    current_month = datetime.now().month
    months = all_months[current_month-1:] + all_months[:current_month-1]
    
    context = {
        'departments': departments,
        "page_title": 'Generate Report',
        'months': months,
        'years': range(datetime.now().year, datetime.now().year - 6, -1),
    }
    return render(request, 'ceo_template/generate_report.html', context)

def generate_individual_report(user, year, month):
    """Helper function to generate report for a single user (employee or manager)"""
    # Get the number of days in the selected month
    num_days = monthrange(year, month)[1]
    start_date = datetime(year, month, 1).date()
    end_date = datetime(year, month, num_days).date()
    
    # Initialize counters
    working_days = 0
    present_days = 0
    late_days = 0
    half_days = 0
    absent_days = 0
    total_breaks = 0
    total_worked = timedelta()
    total_regular = timedelta()
    total_overtime = timedelta()
    daily_records = []
    half_day_counted = set()

    # Get all attendance records for the month in one query
    attendance_records = AttendanceRecord.objects.filter(
        user=user,
        date__range=(start_date, end_date)
    ).order_by('date').select_related('user')
    
    # Get all leave records for the month in one query
    if hasattr(user, 'employee'):
        leave_records = LeaveReportEmployee.objects.filter(
            employee=user.employee,
            status=1,
            start_date__lte=end_date,
            end_date__gte=start_date
        )
    elif hasattr(user, 'manager'):
        leave_records = LeaveReportManager.objects.filter(
            manager=user.manager,
            status=1,
            start_date__lte=end_date,
            end_date__gte=start_date
        )
    else:
        leave_records = []
    
    # Create a dictionary to track leave days
    leave_days = defaultdict(Decimal)
    for leave in leave_records:
        current_date = max(leave.start_date, start_date)
        end_date_leave = min(leave.end_date, end_date)
        while current_date <= end_date_leave:
            if leave.leave_type == "Full-Day":
                leave_days[current_date] += Decimal('1.0')
            elif leave.leave_type == "Half-Day":
                leave_days[current_date] += Decimal('0.5')
            current_date += timedelta(days=1)

    # Prefetch break records for all attendance records
    attendance_ids = [ar.id for ar in attendance_records]
    break_records = Break.objects.filter(
        attendance_record_id__in=attendance_ids
    )
    # Create a mapping of attendance ID to break records
    breaks_map = defaultdict(list)
    for br in break_records:
        breaks_map[br.attendance_record_id].append(br)

    # Process each day of the month
    for day in range(1, num_days + 1):
        current_date = datetime(year, month, day).date()
        weekday = current_date.weekday()
        is_sunday = weekday == 6
        is_saturday = weekday == 5
        week_of_month = (day - 1) // 7
        is_weekend = is_sunday or (is_saturday and week_of_month in [1, 3])
        
        # Initialize day_status with default values
        day_status = {
            'date': current_date,
            'is_weekend': is_weekend,
            'attendance': None,
            'leave': 0.0,
            'breaks_taken': 0,
            'total_break_time': timedelta(),
            'status': None
        }

        if not is_weekend:
            working_days += 1
            
            # Find attendance for this day
            attendance = next(
                (ar for ar in attendance_records if ar.date == current_date), 
                None
            )
            leave_hours = leave_days.get(current_date, Decimal('0.0'))
            
            if attendance:
                day_status['attendance'] = attendance
                day_status['status'] = attendance.status

                # increase present for any status (present , late , half_day)
                present_days += 1
                
                # Process breaks
                for br in breaks_map.get(attendance.id, []):
                    if br.break_end:
                        break_duration = br.duration if br.duration else (br.break_end - br.break_start)
                        day_status['total_break_time'] += break_duration
                        day_status['breaks_taken'] += 1
                
                # total breaks
                total_breaks += day_status['breaks_taken']

                # # Handle attendance status
                # if attendance.status == 'present':
                #     present_days += 1
                if attendance.status == 'late':
                    late_days += 1
                elif attendance.status == 'half_day':
                    if current_date not in half_day_counted:
                        half_days += 1
                        half_day_counted.add(current_date)

                # Handle half-day leave with attendance
                if leave_hours == Decimal('0.5'):
                    day_status['status'] = 'half_day'
                    day_status['leave'] = 0.5
                    if current_date not in half_day_counted:
                        half_days += 1
                        half_day_counted.add(current_date)

                    # reduce present day by 0.5
                    present_days -= 0.5

                # Add working hours
                if attendance.total_worked:
                    total_worked += attendance.total_worked
                if attendance.regular_hours:
                    total_regular += attendance.regular_hours
                if attendance.overtime_hours:
                    total_overtime += attendance.overtime_hours
            
            # Handle leave without attendance
            elif leave_hours > 0:
                day_status['leave'] = float(leave_hours)
                if leave_hours == Decimal('0.5'):
                    day_status['status'] = 'half_day'
                    if current_date not in half_day_counted:
                        half_days += 1
                        half_day_counted.add(current_date)

                    # Count half-day leave as presence
                    present_days += 0.5  
                else:
                    day_status['status'] = 'leave'
                    absent_days += 1
            
            # No attendance and no leave
            else:
                day_status['status'] = 'absent'
                absent_days += 1

        daily_records.append(day_status)

    # Convert timedelta to hours
    total_worked_hours = total_worked.total_seconds() / 3600
    total_regular_hours = total_regular.total_seconds() / 3600
    total_overtime_hours = total_overtime.total_seconds() / 3600
    
    # Determine if this is an employee or manager
    if hasattr(user, 'employee'):
        person = user.employee
    elif hasattr(user, 'manager'):
        person = user.manager
    else:
        person = None
    
    return {
        'employee': person,  
        'user': user,
        'month': month,
        'month_name': datetime(year, month, 1).strftime('%B'),
        'year': year,
        'daily_records': daily_records,
        'present_days': present_days,
        'half_days': half_days,
        'late_days': late_days,
        'absent_days': absent_days,
        'total_breaks': total_breaks, 
        'total_worked_hours': round(total_worked_hours, 2),
        'total_regular_hours': round(total_regular_hours, 2),
        'total_overtime_hours': round(total_overtime_hours, 2),
        'total_working_days': working_days,
    }




@login_required
def admin_todays_attendance(request):
    if not request.user.is_superuser:
        return redirect('admin_home')
    
    today = timezone.now().date()  # Use .date() to match DateField
    
    # Get attendance records for employees only (user_type="3")
    today_attendances = AttendanceRecord.objects.filter(
        date=today,
        user__user_type="3"  # Only include employees
    ).select_related('user__employee__department').order_by('-clock_in')
    
    # Debug: Print all attendance records for today
    all_attendances = AttendanceRecord.objects.filter(date=today)
    
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
    return render(request, 'ceo_template/todays_attendance.html', context)




@login_required
def admin_asset_issue_history(request):
    search_query = request.GET.get('search', '')
    page = request.GET.get('page', 1)
    
    resolved_issues = AssetIssue.objects.filter(status='resolved').order_by('-resolved_date')
    
    if search_query:
        resolved_issues = resolved_issues.filter(
            Q(asset__asset_name__icontains=search_query) |
            Q(asset__asset_serial_number__icontains=search_query) |
            Q(issue_type__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(resolution_method__icontains=search_query) 
        )
    
    paginator = Paginator(resolved_issues, 10)  # 10 issues per page
    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'total_resolved_count': resolved_issues.count(),
        'recurring_count': resolved_issues.filter(is_recurring=True).count(),
    }
    
    # Handle AJAX pagination
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string('ceo_template/admin_view_asset_issue_history.html', context, request=request)
        return JsonResponse({'html': html})
    
    return render(request, 'ceo_template/admin_view_asset_issue_history.html', context)


@login_required
@csrf_exempt
def delete_asset_history_issues(request):
    try:
        data = json.loads(request.body)
        issue_ids = data.get('issue_ids', [])
        delete_all = data.get('delete_all', False)
        # Check if user has permission to delete
        if not request.user.is_superuser:
            return JsonResponse({
                'success': False,
                'error': 'Permission denied'
            }, status=403)

        if delete_all:
            # Delete all resolved issues
            deleted_count, _ = AssetIssue.objects.filter(status='resolved').delete()
            return JsonResponse({
                'success': True,
                'message': f'Successfully deleted {deleted_count} issues'
            })
        elif issue_ids:
            # Validate issue IDs
            try:
                issue_ids = [int(id) for id in issue_ids]
            except (ValueError, TypeError):
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid issue IDs provided'
                }, status=400)
            
            # Delete selected issues
            deleted_count, _ = AssetIssue.objects.filter(
                id__in=issue_ids, 
                status='resolved'
            ).delete()
            
            return JsonResponse({
                'success': True,
                'message': f'Successfully deleted {deleted_count} issues'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'No issues selected for deletion'
            }, status=400)

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Server error: {str(e)}'
        }, status=500)





@login_required
@csrf_exempt
def save_holidays(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body.decode('utf-8'))
            holidays_data = data.get('holidays', [])
            saved_holidays = []
            errors = []
            
            # First validate all holidays before saving any
            for holiday_data in holidays_data:
                date_str = holiday_data.get('date')
                name = holiday_data.get('name')
                holiday_id = holiday_data.get('id')
                
                if not date_str or not name:
                    errors.append(f"Missing date or name for holiday")
                    continue
                    
                try:
                    date = datetime.strptime(date_str, '%Y-%m-%d').date()
                    
                    # Check if this date already exists (for new holidays)
                    if not holiday_id:
                        if Holiday.objects.filter(date=date).exists():
                            errors.append(f"A holiday already exists for {date_str}")
                            continue
                    
                except ValueError:
                    errors.append(f"Invalid date format for {date_str}")
                    continue
            
            if errors:
                return JsonResponse({
                    'success': False,
                    'error': "Validation errors",
                    'details': errors
                }, status=400)
            
            # Now save all holidays if validation passed
            for holiday_data in holidays_data:
                date_str = holiday_data.get('date')
                name = holiday_data.get('name')
                holiday_id = holiday_data.get('id')
                
                date = datetime.strptime(date_str, '%Y-%m-%d').date()
                
                if holiday_id:
                    # Update existing holiday
                    try:
                        holiday = Holiday.objects.get(id=holiday_id)
                        holiday.date = date
                        holiday.name = name
                        holiday.save()
                    except Holiday.DoesNotExist:
                        continue
                else:
                    # Create new holiday
                    holiday = Holiday.objects.create(
                        date=date,
                        name=name
                    )
                
                saved_holidays.append({
                    'id': holiday.id,
                    'date': holiday.date.strftime('%Y-%m-%d'),
                    'name': holiday.name
                })
            
            return JsonResponse({
                'success': True,
                'holidays': saved_holidays
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)
    
    return JsonResponse({
        'success': False,
        'error': 'Invalid request method'
    }, status=400)


@login_required
@csrf_exempt
def delete_holiday(request):
    if request.method == 'POST':
        try:
            holiday_id = request.POST.get('id')
            
            if not holiday_id:
                return JsonResponse({
                    'success': False,
                    'error': 'Missing holiday ID'
                }, status=400)
                
            holiday = Holiday.objects.get(id=holiday_id)
            holiday.delete()
            
            # Return updated holidays list
            holidays = Holiday.objects.all().order_by('date')
            holidays_data = [{
                'id': h.id,
                'date': h.date.strftime('%Y-%m-%d'),
                'name': h.name,
                'type': h.type
            } for h in holidays]
            
            return JsonResponse({
                'success': True,
                'holidays': holidays_data
            })
            
        except Holiday.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Holiday not found'
            }, status=404)
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)
    
    return JsonResponse({
        'success': False,
        'error': 'Invalid request method'
    }, status=405)
    


@login_required
@csrf_exempt
def get_holidays(request):
    if request.method == 'GET':
        holidays = Holiday.objects.all().order_by('date')
        holidays_data = [
            {
                'id': holiday.id,
                'date': holiday.date.strftime('%Y-%m-%d'),
                'name': holiday.name
            }
            for holiday in holidays
        ]
        
        return JsonResponse({
            'success': True,
            'holidays': holidays_data
        })
    
    return JsonResponse({
        'success': False,
        'error': 'Invalid request method'
    }, status=400)
    
    
@login_required   
def admin_view_notification(request):
    pending_leave_requests = LeaveReportManager.objects.filter(
        status=0
    ).order_by('-created_at')

    notification_ids = Notification.objects.filter(
        user=request.user,
        is_read=False,
        role="ceo",
    ).values_list('leave_or_notification_id', flat=True)

    leave_history = LeaveReportManager.objects.filter(
        status__in=[1, 2]
    ).order_by('-updated_at')

    # Pagination for each section
    page_number = request.GET.get('page')
    leave_paginator = Paginator(leave_history, 3)
    leave_page_obj = leave_paginator.get_page(page_number)

    context = {
        'pending_leave_requests': pending_leave_requests,
        'leave_page_obj': leave_page_obj,
        'manager_unread_ids': list(notification_ids),
        'LOCATION_CHOICES': LOCATION_CHOICES,
        'page_title': "View Notifications",
    }

    return render(request, "ceo_template/admin_view_notification.html", context)
 
@login_required   
def approve_admin_leave_request(request, leave_id):
    if request.method == 'POST':
        leave_request = get_object_or_404(LeaveReportManager, id=leave_id)
        msg = "Please check the Leave Request"
        if leave_request.status == 0:
            if not leave_request.end_date:
                leave_request.end_date = leave_request.start_date
                leave_request.save()

            leave_request.status = 1
            leave_request.save()

            if leave_request.leave_type == 'Half-Day':
                messages.success(request, "Half-Day leave approved.")
            else:
                messages.success(request, "Full-Day leave approved.")
            msg = "Leave request approved."

            # Update exixsting notification for manager to mark as read
            Notification.objects.filter(
                user = request.user,
                notification_type = 'leave-notification',
                leave_or_notification_id = leave_request.id,
                role = 'ceo'
            ).update(is_read = True)

            # send notification to manager
            Notification.objects.create(
                user = leave_request.manager.admin,
                message = msg,
                notification_type = 'manager-leave-notification',
                leave_or_notification_id = leave_request.id,
                role = 'manager'
            )
        else:
            messages.info(request, "This leave request has already been processed.")

    return redirect('admin_view_notification')

@login_required   
def reject_admin_leave_request(request, leave_id):
    if request.method == 'POST':
        msg = "Please check the Leave Request"
        leave_request = get_object_or_404(LeaveReportManager, id=leave_id)
        if leave_request.status == 0:
            leave_request.status = 2
            leave_request.save()
            msg = "Leave request rejected."
            messages.warning(request, "Leave request rejected.")

            # update exiting notification for manager:
            Notification.objects.filter(
                user = request.user,
                role = 'ceo',
                leave_or_notification_id = leave_request.id,
                notification_type = 'leave-notification'
            ).update(is_read = True)

            # create notifciation for manager
            Notification.objects.create(
                user = leave_request.manager.admin,
                message = msg,
                role = 'manager',
                leave_or_notification_id = leave_request.id,
                notification_type = 'manager-leave-notification'
            )
        else:
            messages.info(request, "This leave request has already been processed.")

    return redirect('admin_view_notification')

@login_required
def admin_view_attendance(request):
    current_date = datetime.now()
    current_year = current_date.year
    current_month = current_date.month

    years = [current_year + i for i in range(5)]
    months = [
        (f"{i:02}", datetime(current_year, i, 1).strftime('%B'))
        for i in range(1, 13)
    ]

    # Determine user access
    if hasattr(request.user, 'manager'):
        manager = request.user.manager
        departments = Department.objects.filter(division=manager.division)
        employees = Employee.objects.filter(department__in=departments).select_related('department')
        managers = Manager.objects.filter(department__in=departments).select_related('department')
    else:
        departments = Department.objects.all()
        employees = Employee.objects.all().select_related('department')
        managers = Manager.objects.all().select_related('department')

    context = {
        'departments': departments,
        'employees': employees,
        'managers': managers,
        'page_title': 'View Attendance',
        'months': months,
        'years': years,
        'current_year': current_year,
        'current_month': current_month
    }
    return render(request, 'ceo_template/admin_view_attendance.html', context)







logger = logging.getLogger(__name__)

User = get_user_model() 

@login_required
@csrf_exempt
def get_manager_and_employee_attendance(request):
    if request.method == 'POST':
        try:
            # Retrieve POST parameters
            employee_id = request.POST.get('employee_id')
            department_id = request.POST.get('department_id')
            manager_id = request.POST.get('manager_id')
            month = request.POST.get('month')
            year = request.POST.get('year')
            week = request.POST.get('week')
            from_date = request.POST.get('from_date')
            to_date = request.POST.get('to_date')
            page = int(request.POST.get('page', 1))
            per_page = request.POST.get('per_page', 5)
            try:
                per_page = int(per_page)
                per_page = min(per_page, 10000)  # Cap per_page
            except ValueError:
                per_page = 5

            # Validate required date inputs
            if not year and not (from_date and to_date):
                return JsonResponse({"error": "Year or date range is required"}, status=400)

            # Base queryset with related models
            queryset = AttendanceRecord.objects.select_related(
                'user__employee',
                'user__manager',
                'user__employee__department',
                'user__manager__department'
            ).prefetch_related('breaks').all()

            # Apply filters
            if employee_id and employee_id != 'all':
                try:
                    employee = Employee.objects.get(employee_id=employee_id)
                    queryset = queryset.filter(user__employee=employee)
                except Employee.DoesNotExist:
                    return JsonResponse({"error": "Employee not found"}, status=400)

            if department_id and department_id != 'all':
                queryset = queryset.filter(
                    Q(user__employee__department_id=department_id) |
                    Q(user__manager__department_id=department_id)
                )

            if manager_id and manager_id != 'all':
                try:
                    manager = None
                    # Adjust Manager lookup based on your model
                    if hasattr(Manager, 'manager_id'):
                        manager = Manager.objects.filter(manager_id=manager_id).first()
                    if not manager and hasattr(Manager, 'admin_id'):
                        manager = Manager.objects.filter(admin_id=manager_id).first()
                    if not manager:
                        manager = Manager.objects.filter(id=manager_id).first()

                    if not manager:
                        return JsonResponse({"error": "Manager not found"}, status=400)

                    queryset = queryset.filter(
                        Q(user__manager=manager) |
                        Q(user__employee__department=manager.department)
                    )
                except Exception as e:
                    logger.error(f"Manager lookup error: {str(e)}")
                    return JsonResponse({"error": f"Manager lookup error: {str(e)}"}, status=400)

            # Date filtering
            holiday_dates = set()
            filtered_dates = None
            start_date = None
            end_date = None
            today = datetime.now().date()
            current_year = today.year
            current_month = today.month

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

                for saturday in saturdays:
                    if saturday not in existing_holidays:
                        Holiday.objects.get_or_create(
                            date=saturday,
                            defaults={'name': f'Saturday - {saturday.strftime("%B %d, %Y")}'}
                        )

            set_automatic_holidays(current_year, current_month)

            # Calculate total working days and holiday count
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
                                end_date = today
                            queryset = queryset.filter(date__month=month, date__year=year)
                            holiday_dates = set(Holiday.objects.filter(
                                date__year=year,
                                date__month=month
                            ).values_list('date', flat=True))
                            filtered_dates = (start_date, end_date)
                            if year == current_year:
                                set_automatic_holidays(year, month)
                        except ValueError:
                            return JsonResponse({"error": "Invalid month number"}, status=400)

            if end_date > today:
                end_date = today

            queryset = queryset.order_by('-date')

            # Initialize attendance statistics
            present_days = 0
            late_days = 0
            half_days = 0
            absent_days = 0

            if start_date and end_date:
                employee = Employee.objects.get(employee_id=employee_id) if employee_id and employee_id != 'all' else None

                user_stats = {}
                if employee:
                    joining_date = employee.date_of_joining
                    first_clock_in = AttendanceRecord.objects.filter(
                        user=employee.admin,
                        status__in=['present', 'late', 'half_day']
                    ).order_by('date').first()
                    first_clock_in_date = first_clock_in.date if first_clock_in else None
                    user_stats[employee.admin.id] = {
                        'joining_date': joining_date,
                        'first_clock_in_date': first_clock_in_date,
                        'present_days': 0,
                        'late_days': 0,
                        'half_days': 0,
                        'absent_days': 0,
                    }
                else:
                    users = set(queryset.values_list('user', flat=True))
                    for user_id in users:
                        user = User.objects.get(id=user_id)
                        employee_for_user = Employee.objects.filter(admin=user).first()
                        if employee_for_user:
                            joining_date = employee_for_user.date_of_joining
                            first_clock_in = AttendanceRecord.objects.filter(
                                user=user,
                                status__in=['present', 'late', 'half_day']
                            ).order_by('date').first()
                            first_clock_in_date = first_clock_in.date if first_clock_in else None
                            user_stats[user_id] = {
                                'joining_date': joining_date,
                                'first_clock_in_date': first_clock_in_date,
                                'present_days': 0,
                                'late_days': 0,
                                'half_days': 0,
                                'absent_days': 0,
                            }

                date_status_map = {}
                for record in queryset:
                    user_id = record.user.id
                    if user_id not in date_status_map:
                        date_status_map[user_id] = {}
                    date_status_map[user_id][record.date] = record.status

                leave_dates_map = {}
                half_day_leave_dates_map = {}
                for user_id, stats in user_stats.items():
                    employee_for_user = Employee.objects.filter(admin_id=user_id).first()
                    if not employee_for_user:
                        continue
                    leaves = LeaveReportEmployee.objects.filter(
                        employee=employee_for_user,
                        status=1,
                        start_date__lte=end_date,
                        end_date__gte=start_date
                    )
                    leave_dates = set()
                    half_day_leave_dates = set()
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
                    leave_dates_map[user_id] = leave_dates
                    half_day_leave_dates_map[user_id] = half_day_leave_dates

                for user_id, stats in user_stats.items():
                    joining_date = stats['joining_date']
                    first_clock_in_date = stats['first_clock_in_date']
                    current_date = start_date

                    if not first_clock_in_date or today < first_clock_in_date:
                        continue

                    while current_date <= end_date:
                        if current_date < joining_date:
                            current_date += timedelta(days=1)
                            continue

                        weekday = current_date.weekday()
                        is_sunday = weekday == 6
                        is_saturday = weekday == 5
                        is_2nd_or_4th_saturday = is_saturday and ((current_date.day - 1) // 7) in [1, 3]
                        is_holiday = current_date in holiday_dates

                        if not (is_sunday or is_2nd_or_4th_saturday or is_holiday):
                            user_date_status = date_status_map.get(user_id, {}).get(current_date)
                            if current_date in half_day_leave_dates_map.get(user_id, set()):
                                stats['present_days'] += 1
                                stats['half_days'] += 1
                                stats['late_days'] += 1
                                stats['absent_days'] += 0.5
                            elif current_date in leave_dates_map.get(user_id, set()):
                                stats['present_days'] += 1
                            elif user_date_status == 'present':
                                stats['present_days'] += 1
                            elif user_date_status == 'late':
                                stats['present_days'] += 1
                                stats['late_days'] += 1
                            elif user_date_status == 'half_day':
                                stats['present_days'] += 1
                                stats['half_days'] += 1
                                stats['absent_days'] += 0.5
                            elif current_date <= today:
                                if first_clock_in_date and current_date < first_clock_in_date:
                                    stats['absent_days'] += 1
                                elif not user_date_status and current_date not in leave_dates_map.get(user_id, set()) and current_date not in half_day_leave_dates_map.get(user_id, set()):
                                    stats['absent_days'] += 1

                        current_date += timedelta(days=1)

                for user_id, stats in user_stats.items():
                    present_days += stats['present_days']
                    late_days += stats['late_days']
                    half_days += stats['half_days']
                    absent_days += stats['absent_days']

            filtered_working_days = total_working_days if filtered_dates[1] == full_month_end else sum(
                1 for d in [start_date + timedelta(days=x) for x in range((end_date - start_date).days + 1)]
                if not (d.weekday() == 6 or (d.weekday() == 5 and ((d.day - 1) // 7) in [1, 3]) or d in holiday_dates)
            )
            attendance_percentage = (present_days / filtered_working_days) * 100 if filtered_working_days > 0 else 0
            attendance_percentage = round(attendance_percentage, 1)

            attendance_list = []
            attendance_dates = set(queryset.values_list('date', flat=True))

            for record in queryset:
                if hasattr(record.user, 'employee'):
                    user = record.user.employee
                    name = f"{user.admin.first_name} {user.admin.last_name}"
                    department = user.department.name if user.department else ""
                    user_type = "Employee"
                    user_id = user.employee_id
                elif hasattr(record.user, 'manager'):
                    user = record.user.manager
                    name = f"{user.admin.first_name} {user.admin.last_name}"
                    department = user.department.name if user.department else ""
                    user_type = "Manager"
                    user_id = getattr(user, 'manager_id', None) or getattr(user, 'admin_id', None) or str(user.id)
                else:
                    continue

                weekday = record.date.weekday()
                is_sunday = weekday == 6
                is_saturday = weekday == 5
                is_2nd_or_4th_saturday = is_saturday and ((record.date.day - 1) // 7) in [1, 3]
                is_holiday = record.date in holiday_dates

                status = "Holiday" if is_holiday or is_sunday or is_2nd_or_4th_saturday else record.status

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

            attendance_list = sorted(attendance_list, key=lambda x: x['date'], reverse=True)

            paginator = Paginator(attendance_list, per_page)
            try:
                page_obj = paginator.page(page)
            except:
                return JsonResponse({"error": "Invalid page number"}, status=400)

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
            logger.error(f"Server error: {str(e)}")
            return JsonResponse({"error": f"Server error: {str(e)}"}, status=500)
    return JsonResponse({"error": "Invalid request method"}, status=405)