from django.utils.deprecation import MiddlewareMixin
from django.urls import reverse,resolve
from django.shortcuts import redirect
from django.shortcuts import render


class LoginCheckMiddleWare(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        modulename = view_func.__module__
        user = request.user # Who is the current user ?
        if user.is_authenticated:
            if user.user_type == '1': # Is it the CEO/Admin
                if modulename == 'main_app.employee_views':
                    return redirect(reverse('admin_home'))
            elif user.user_type == '2': #  Manager :-/ ?
                if modulename == 'main_app.employee_views' or modulename == 'main_app.ceo_views':
                    return redirect(reverse('manager_home'))
            elif user.user_type == '3': # ... or Employee ?
                if modulename == 'main_app.ceo_views' or modulename == 'main_app.manager_views':
                    return redirect(reverse('employee_home'))
            else: # None of the aforementioned ? Please take the user to login page
                return redirect(reverse('login_page'))
        else:
            if request.path == reverse('clock_in_out_api') or request.path == reverse('login_page') or modulename == 'django.contrib.auth.views' or request.path == reverse('user_login') : # If the path is login or has anything to do with authentication, pass
                pass
            else:
                return redirect(reverse('login_page'))


class RoleBasedAccessMiddleware:
    def __init__(self,get_response):
        self.get_response = get_response

        self.asset_urls = {
            'asset_app:assets-list' : ['1','2'],
            'asset_app:assetscategory-create': ['1','2'],
            'asset_app:assets-detail' : ['1','2','3'],
            'asset_app:assets-create' : ['1','2'],
            'asset_app:asset-assign' : ['1','2'],
            'asset_app:asset-claim' : ['1','2','3'],
            'asset_app:approve-notification' : ['1','2'],
            'asset_app:get_category_config' : ['1','2'],
            'asset_app:asset-unclaim' : ['1','2'],
            'asset_app:asset-update' : ['1','2'],
            'asset_app:asset-delete' : ['1','2'],
            'asset_app:assetcategory-update' : ['1','2'],
            'asset_app:not-assign-asset-list' : ['1','2','3'],
            'asset_app:my-assets' : ['1','2','3'],
            'asset_app:print_all_barcode' : ['1','2'],
            'asset_app:assetcategory-delete' : ['1','2'],
        }

    def __call__(self,request):
        path = request.path
        user = request.user

        try:
            resolved = resolve(request.path_info)
            current_usrl_name = resolved.view_name
        except Exception:
            return self.get_response(request)
        
        if current_usrl_name in self.asset_urls:
            allowed_user_type = self.asset_urls[current_usrl_name]
            if str(user.user_type) not in allowed_user_type:
                return render(request,'main_app/403.html',status=403)

        return self.get_response(request)

