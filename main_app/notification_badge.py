
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from main_app.models import Notification
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction

def send_notification(user, message,notification_type,id,role):
    Notification.objects.create(
        user=user,
        message=message,
        notification_type = notification_type,
        leave_or_notification_id = id,
        role = role
    )

def employee_view_notification(request):
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')

    # Mark all as read when viewed
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)

    return render(request, 'employee/notifications.html', {
        'notifications': notifications
    })


@csrf_exempt
def mark_notification_read(request):
    if request.method != 'POST' or request.headers.get('x-requested-with') != 'XMLHttpRequest':
        return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)
    
    notification_id = request.POST.get('notification_id')  
    notification_type = request.POST.get('notification_type')

    try:
        with transaction.atomic():
            if notification_type == 'general-notification':
                notification = get_object_or_404(
                    Notification,
                    user=request.user,
                    role='manager',
                    notification_type=notification_type,
                    leave_or_notification_id=notification_id
                )

                if not notification.is_read:
                    notification.is_read = True
                    notification.save()
                    return JsonResponse({'status': 'success', 'message': 'Notification marked as read'})
                return JsonResponse({'status': 'success', 'message': 'Notification already read'})
            
            elif notification_type in ['notification-from-manager' , 'notification-from-admin' , 'leave-notification' , 'clockout-notification' , 'manager-leave-notification' , 'asset-notification']:
                
                notifications = Notification.objects.filter(
                    user=request.user,
                    role__in=['employee' , 'ceo' , 'manager'],
                    notification_type=notification_type,
                    leave_or_notification_id=notification_id,
                    is_read = False
                )
                
                updated_count = notifications.update(is_read = True)
                
                if updated_count > 0:
                    return JsonResponse({'status': 'success', 'message': 'Notification marked as read'})
                return JsonResponse({'status': 'success', 'message': 'Notification already read'})
            else:
                return JsonResponse({'status': 'error', 'message': 'Invalid notification type'}, status=400)

    except Notification.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Notification not found'}, status=404)

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
    # if request.method == 'POST':
    #     if type == "leave":
    #         notification = Notification.objects.filter(leave_or_notification_id=notification_id, user=request.user,role = role).first()
    #         if notification:
    #             notification.is_read = True
    #             notification.save()
    #             return JsonResponse({'success': True})
    # else:
    #     notification = Notification.objects.filter(user=request.user, notification_type='notification',role = role)
    #     updated_count = notification.update(is_read=True)
    #     if updated_count > 0:
    #         return JsonResponse({'success': True})
    #     else:
    #         return JsonResponse({'success': False}, status=404)
    # return JsonResponse({'success': False}, status=400)
