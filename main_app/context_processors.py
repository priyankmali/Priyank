from .models import CustomUser, AttendanceRecord, Notification, EarylyClockOutRequest
from django.utils import timezone
from django.contrib.auth.models import AnonymousUser
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta

from django.utils import timezone
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from calendar import monthrange
import logging
from .models import CustomUser, AttendanceRecord, EarylyClockOutRequest, Employee, LeaveBalance

logger = logging.getLogger(__name__)



from django.utils import timezone
from django.contrib.auth.models import AnonymousUser
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from .models import AttendanceRecord, CustomUser, EarylyClockOutRequest
import logging

logger = logging.getLogger(__name__)

def clock_times(request):
    context = {
        "latest_entry": None,
        "current_record": None,
        "can_clock_out": False,
        "complete_8Hours": False,
        "work_duration": None,
        "remaining_time": None,
    }

    user = request.user
    if isinstance(user, AnonymousUser) or not user.is_authenticated:
        return context

    try:
        custom_user = CustomUser.objects.get(id=user.id)
        today = timezone.now().astimezone(ZoneInfo('Asia/Kolkata')).date()
        
        # Get the latest attendance record
        latest_entry = AttendanceRecord.objects.filter(user=custom_user).order_by("-clock_in").first()
        
        # Get current active clock-in record
        current_record = AttendanceRecord.objects.filter(
            user=custom_user,
            clock_out__isnull=True,
            date=today,
            status__in=['present', 'late', 'half_day']
        ).first()

        if latest_entry and latest_entry.clock_in:
            try:
                clock_in_time = latest_entry.clock_in.astimezone(ZoneInfo('Asia/Kolkata'))
                current_time = datetime.now(ZoneInfo('Asia/Kolkata'))
                work_duration = current_time - clock_in_time
                
                # determine worked duration based on the status
                if latest_entry.status == 'half_day':
                    fixed_time = timedelta(hours=4 , minutes=30)
                else:
                    fixed_time = timedelta(hours=8 , minutes=30)

                if work_duration >= fixed_time:
                    context["complete_8Hours"] = True
                    context['work_duration'] = work_duration
                    context['can_clock_out'] = True
                else:
                    context['remaining_time'] = int((fixed_time - work_duration).total_seconds())
            except AttributeError as e:
                logger.error(f"Error processing clock_in for latest_entry {latest_entry.id if latest_entry else 'None'}: {str(e)}")
                context['latest_entry'] = None

        if current_record:
            early_request = EarylyClockOutRequest.objects.filter(
                attendance_record=current_record,
                status='approved'
            ).exists()
            if early_request:
                context['can_clock_out'] = True

        context["latest_entry"] = latest_entry
        context["current_record"] = current_record

    except CustomUser.DoesNotExist:
        logger.warning(f"CustomUser not found for user ID {user.id}")
    except Exception as e:
        logger.error(f"Error in clock_times for user {user.id}: {str(e)}")

    return context

def unread_notification_count(request):
    employee_leave_request_to_manager_count = 0
    manager_general_count = 0
    employee_clockout_request_to_manager_count = 0
    employee_notification_from_manager_count = 0
    employee_leave_approved_or_rejected_notification_count = 0
    employee_asset_request = 0
    total_asset_unread_notifications = 0
    total_unread_notifications = 0

    if request.user.is_authenticated:
        if request.user.user_type == '2':
            manager_general_count = Notification.objects.filter(
                user=request.user,
                is_read=False,
                notification_type='general-notification',
                role="manager"
            ).count()

            employee_asset_request_count = Notification.objects.filter(
                is_read = False , 
                notification_type = 'asset-notification',
                role = 'manager'
            ).count()

            employee_leave_request_to_manager_count = Notification.objects.filter(
                user=request.user,
                is_read=False,
                notification_type='leave-notification',
                role="manager"
            ).count()

            manager_leave_request_from_ceo_count = Notification.objects.filter(
                user=request.user,
                is_read=False,
                notification_type='manager-leave-notification',
                role="manager"
            ).count()

            employee_clockout_request_to_manager_count = Notification.objects.filter(
                user=request.user,
                is_read=False,
                notification_type='clockout-notification',
                role="manager"
            ).count()

            employee_asset_claim_request_to_manager_count = Notification.objects.filter(
                is_read=False,
                notification_type='asset-notification',
                role="manager"
            ).count()

            total_unread_notifications = (
                manager_general_count +
                employee_leave_request_to_manager_count +
                employee_clockout_request_to_manager_count +
                employee_asset_request_count + manager_leave_request_from_ceo_count
            )

            total_unread_notifications_gen_leave_clockout = (
                manager_general_count +
                employee_leave_request_to_manager_count +
                employee_clockout_request_to_manager_count 
            )

            total_asset_unread_notifications = (
                employee_asset_request_count
            )

            return {
                'total_unread_notifications': total_unread_notifications,
                'manager_general_count': manager_general_count,
                'employee_leave_request_to_manager_count': employee_leave_request_to_manager_count,
                'employee_clockout_request_to_manager_count': employee_clockout_request_to_manager_count,
                'manager_leave_request_from_ceo_count' : manager_leave_request_from_ceo_count,
                'total_unread_notifications_gen_leave_clockout' : total_unread_notifications_gen_leave_clockout,

                'employee_asset_request_count' : employee_asset_request_count,
                'total_asset_unread_notifications': total_asset_unread_notifications,
                
            }
        
        elif request.user.user_type == '1':
            ceo_notification_from_manager_leave_request = Notification.objects.filter(
                user = request.user,
                is_read = False,
                notification_type__in = ['manager-leave-notification'],
                role = 'ceo'
            ).count()
            
            ceo_notification_from_employee_leave_request = Notification.objects.filter(
                user = request.user,
                is_read = False,
                notification_type__in = ['employee-leave-notification'],
                role = 'ceo'
            ).count()

            total_unread_notifications = (ceo_notification_from_manager_leave_request + ceo_notification_from_employee_leave_request)

            return {
                'total_unread_notifications': total_unread_notifications,
                'ceo_notification_from_manager_leave_request' : ceo_notification_from_manager_leave_request,
                'ceo_notification_from_employee_leave_request' : ceo_notification_from_employee_leave_request
            }

        else:
            employee_notification_from_manager_count = Notification.objects.filter(
                user=request.user,
                is_read=False,
                notification_type__in=['notification-from-manager', 'notification-from-admin'],
                role="employee"
            ).count()

            employee_leave_approved_or_rejected_notification_count = Notification.objects.filter(
                user=request.user,
                is_read=False,
                notification_type='leave-notification',
                role="employee"
            ).count()

            employee_clockout_request_to_manager_count = Notification.objects.filter(
                user=request.user,
                is_read=False,
                notification_type='clockout-notification',
                role="employee"
            ).count()

            employee_asset_request = Notification.objects.filter(
                user = request.user , 
                is_read = False , 
                notification_type = 'asset-notification',
                role = 'employee' 
            ).count()

            total_unread_notifications = (
                employee_notification_from_manager_count +
                employee_leave_approved_or_rejected_notification_count +
                employee_clockout_request_to_manager_count + employee_asset_request
            )

            total_general_unread_notification = (
                employee_notification_from_manager_count 
            )

            return {
                'total_unread_notifications': total_unread_notifications,
                'total_general_unread_notification' : total_general_unread_notification,
                'employee_notification_from_manager_count': employee_notification_from_manager_count,
                'employee_leave_approved_or_rejected_notification_count': employee_leave_approved_or_rejected_notification_count,
                'employee_clockout_request_to_manager_count': employee_clockout_request_to_manager_count,
                'employee_asset_request' : employee_asset_request,
            }
    
    # Add a default return dictionary if the user is not authenticated
    return {
        'total_unread_notifications': 0,
        'manager_general_count': 0,
        'employee_leave_request_to_manager_count': 0,
        'employee_clockout_request_to_manager_count': 0,
        'total_asset_unread_notifications': 0,
        'employee_notification_from_manager_count': 0,
        'employee_leave_approved_or_rejected_notification_count': 0,
        'employee_clockout_request_to_manager_count': 0,
        'ceo_notification_from_manager_leave_request' : 0,
        'ceo_notification_from_employee_leave_request' : 0,
        'manager_leave_request_from_ceo_count' : 0,
        'total_unread_notifications_gen_leave_clockout' : 0,
        'total_general_unread_notification' : 0,
        'employee_asset_request' : 0,
        'total_asset_notification' : 0,
                
    }
       



def leave_balance_context(request):
    if not request.user.is_authenticated:
        return {
            'yearly_leave_data': [],
            'total_available_leaves': 0.0,
            'employee_name': '',
            'department': '',
        }

    employee = getattr(request.user, 'employee', None)
    if not employee:
        return {
            'yearly_leave_data': [],
            'total_available_leaves': 0.0,
            'employee_name': request.user.get_full_name(),
            'department': 'N/A',
        }

    current_year = timezone.now().year
    current_month = timezone.now().month
    yearly_leave_data = []
    total_available_leaves = 0.0

    # Check for the first clock-in to determine if LeaveBalance records exist
    first_clock_in = AttendanceRecord.objects.filter(
        user=request.user,
        status__in=['present', 'late', 'half_day']
    ).order_by('date').first()

    if first_clock_in:
        # If there's a clock-in, ensure LeaveBalance records are initialized
        LeaveBalance.initialize_balances(employee, timezone.now().date())

        # Fetch leave balances for the current year
        leave_balances = LeaveBalance.objects.filter(
            employee=employee,
            year=current_year
        ).order_by('month')

        for month in range(1, 13):
            balance = leave_balances.filter(month=month).first()
            if balance:
                yearly_leave_data.append({
                    'month': month,
                    'allocated_leaves': balance.allocated_leaves,
                    'carried_forward': balance.carried_forward,
                    'used_leaves': balance.used_leaves,
                    'available_leaves': balance.total_available_leaves(),
                })
            else:
                # For future months, show default values
                yearly_leave_data.append({
                    'month': month,
                    'allocated_leaves': 0.0,
                    'carried_forward': 0.0,
                    'used_leaves': 0.0,
                    'available_leaves': 0.0,
                })

        # Get the current month's balance to compute total available leaves
        current_balance = LeaveBalance.get_balance(employee, current_year, current_month)
        if current_balance:
            total_available_leaves = current_balance.total_available_leaves()

    else:
        # No clock-in yet, so no LeaveBalance records should exist
        for month in range(1, 13):
            yearly_leave_data.append({
                'month': month,
                'allocated_leaves': 0.0,
                'carried_forward': 0.0,
                'used_leaves': 0.0,
                'available_leaves': 0.0,
            })

    return {
        'yearly_leave_data': yearly_leave_data,
        'total_available_leaves': total_available_leaves,
        'employee_name': employee.admin.get_full_name(),
        'department': employee.department.name if employee.department else 'N/A',
    }



# def unread_notification_count(request):
#     if request.user.is_authenticated:
#         employee_general_count = Notification.objects.filter(user=request.user, is_read=False, notification_type='notification',role = "employee").count()
#         manager_general_count = Notification.objects.filter(user=request.user, is_read=False, notification_type='notification',role = "manager").count()
#         admin_general_count = Notification.objects.filter(user=request.user, is_read=False, notification_type='notification',role = "admin").count()
#         admin_employee_feedback_count = Notification.objects.filter(user=request.user, is_read=False, notification_type='employee feedback',role = "admin").count()
#         employee_leave_count = Notification.objects.filter(user=request.user, is_read=False, notification_type='leave',role = "employee").count()
#         manager_leave_count = Notification.objects.filter(user=request.user, is_read=False, notification_type='leave',role = "manager").count()
#         admin_leave_count = Notification.objects.filter(user=request.user, is_read=False, notification_type='leave',role = "admin").count()
#         print("general_countgeneral_count>>",employee_general_count,"manager_general_count>>>",manager_general_count,"admin_general_count>>>>>>",admin_general_count,request.user)
#         print("employee_leave_count>>>",employee_leave_count,"manager_leave_count>>>",manager_leave_count,"admin_leave_count>>>>>",admin_leave_count,request.user)
#         print("admin_employee_feedback_count>>",admin_employee_feedback_count)
#     else:
#         general_count = 0
#         leave_count = 0
#         employee_general_count = 0
#         manager_general_count = 0
#         admin_general_count = 0
#         admin_employee_feedback_count = 0
#         employee_leave_count = 0
#         manager_leave_count= 0
#         admin_leave_count= 0

#     return {
#         # 'unread_general_notification_count': general_count,
#         'unread_employee_general_notification_count': employee_general_count,
#         'unread_manager_general_notification_count': manager_general_count,
#         'admin_employee_feedback_count':admin_employee_feedback_count,
#         'admin_general_count':admin_general_count,
#         # 'unread_leave_notification_count': leave_count,
#         'unread_employee_leave_notification_count': employee_leave_count,
#         'unread_manager_leave_notification_count': manager_leave_count,
#         'admin_leave_count':admin_leave_count
#     }

from .models import Notification

def admin_notification_count(request):
    context = {
        'unread_admin_manager_leave_count': 0,
        'unread_admin_general_count': 0,
        'total_admin_notifications': 0,
    }
    
    if request.user.is_authenticated and request.user.is_superuser:
        # Count of unread manager leave applications for admin
        context['unread_admin_manager_leave_count'] = Notification.objects.filter(
            is_read=False,
            notification_type='leave',
            role='manager'  # notifications from managers
        ).count()
        
        # Count of general notifications for admin
        context['unread_admin_general_count'] = Notification.objects.filter(
            is_read=False,
            notification_type='notification',
            role='admin'  # notifications meant for admin
        ).count()
        
        # Total admin notifications count
        context['total_admin_notifications'] = (
            context['unread_admin_manager_leave_count'] + 
            context['unread_admin_general_count']
        )
    
    return context
    
# def unread_notification_count(request):
#     if not request.user.is_authenticated:
#         return {
#             'unread_employee_general_notification_count': 0,
#             'unread_manager_general_notification_count': 0,
#             'admin_employee_feedback_count': 0,
#             'admin_general_count': 0,
#             'unread_employee_leave_notification_count': 0,
#             'unread_manager_leave_notification_count': 0,
#             'admin_leave_count': 0
#         }
    
#     context = {
#         'unread_employee_general_notification_count': 0,
#         'unread_manager_general_notification_count': 0,
#         'admin_employee_feedback_count': 0,
#         'admin_general_count': 0,
#         'unread_employee_leave_notification_count': 0,
#         'unread_manager_leave_notification_count': 0,
#         'admin_leave_count': 0
#     }

#     try:
      
#         general_notifications = Notification.objects.filter(
#             user=request.user,
#             is_read=False
#         ).exclude(
#             notification_type__in=['asset_request', 'asset_issue']
#         )

#         # Employee counts
#         if hasattr(request.user, 'employee'):
#             context.update({
#                 'unread_employee_general_notification_count': general_notifications.filter(
#                     role="employee",
#                     notification_type="notification"
#                 ).count(),
#                 'unread_employee_leave_notification_count': general_notifications.filter(
#                     role="employee",
#                     notification_type="leave"
#                 ).count()
#             })

#         # Manager counts
#         elif hasattr(request.user, 'manager'):
#             context.update({
#                 'unread_manager_general_notification_count': general_notifications.filter(
#                     role="manager",
#                     notification_type="notification"
#                 ).count(),
#                 'unread_manager_leave_notification_count': general_notifications.filter(
#                     role="manager",
#                     notification_type="leave"
#                 ).count()
#             })

#         # Admin counts
#         elif hasattr(request.user, 'admin'):
#             context.update({
#                 'admin_general_count': general_notifications.filter(
#                     role="admin",
#                     notification_type="notification"
#                 ).count(),
#                 'admin_employee_feedback_count': general_notifications.filter(
#                     role="admin",
#                     notification_type="employee feedback"
#                 ).count(),
#                 'admin_leave_count': general_notifications.filter(
#                     role="admin",
#                     notification_type="leave"
#                 ).count()
#             })

#     except Exception as e:
#         # Log error but don't break the site
#         import logging
#         logging.error(f"Error in unread_notification_count context processor: {str(e)}")
    
#     return context



def asset_notification_count(request):
    if not request.user.is_authenticated:
        return {
            'unread_asset_notification_count': 0,
            'unread_asset_request_count': 0,
            'unread_asset_issue_count': 0
        }

    context = {
        'unread_asset_notification_count': 0,
        'unread_asset_request_count': 0,
        'unread_asset_issue_count': 0
    }

    try:
        # For Managers (Asset Requests)
        if hasattr(request.user, 'manager'):
            # Count pending asset requests (manager-specific)
            asset_request_count = Notification.objects.filter(
                user=request.user,
                is_read=False,
                notification_type='asset_request',
                role="manager"
            ).count()
            
            # Count pending asset issues (global, but manager can see)
            asset_issue_count = Notification.objects.filter(
                is_read=False,
                notification_type='asset_issue',
                role="manager"
            ).count()
            
            context.update({
                'unread_asset_notification_count': asset_request_count + asset_issue_count,
                'unread_asset_request_count': asset_request_count,
                'unread_asset_issue_count': asset_issue_count
            })

        # For Employees (if they can have asset notifications)
        elif hasattr(request.user, 'employee'):
            asset_issue_count = Notification.objects.filter(
                user=request.user,
                is_read=False,
                notification_type='asset_issue',
                role="employee"
            ).count()
            
            context.update({
                'unread_asset_notification_count': asset_issue_count,
                'unread_asset_issue_count': asset_issue_count
            })

        # For Admins (if they need to see all asset notifications)
        elif hasattr(request.user, 'admin'):
            asset_request_count = Notification.objects.filter(
                is_read=False,
                notification_type='asset_request'
            ).count()
            
            asset_issue_count = Notification.objects.filter(
                is_read=False,
                notification_type='asset_issue'
            ).count()
            
            context.update({
                'unread_asset_notification_count': asset_request_count + asset_issue_count,
                'unread_asset_request_count': asset_request_count,
                'unread_asset_issue_count': asset_issue_count
            })

    except Exception as e:
        # Log error but don't break the site
        import logging
        logging.error(f"Error in asset_notification_count context processor: {str(e)}")
    
    return context

