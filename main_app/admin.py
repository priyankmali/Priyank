from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _
from .models import *
from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm

class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ('email',)

class CustomUserChangeForm(UserChangeForm):
    class Meta:
        model = CustomUser
        fields = ('email',)

class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = CustomUser

    # Include 'id' and other relevant fields in list_display
    list_display = ('id', 'email', 'is_staff', 'is_active', 'is_superuser')
    list_filter = ('is_staff', 'is_active', 'is_superuser')

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (_('Permissions'), {'fields': ('is_staff', 'is_active', 'is_superuser', 'groups', 'user_permissions')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2', 'is_staff', 'is_active', 'is_superuser')}),
    )

    # Show the email in search results
    search_fields = ('email',)
    ordering = ('email',)

    # Optionally, add a method to return the full list of fields, if you want to display them in admin
    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        # Get the fields dynamically based on the model's fields
        all_fields = [field.name for field in CustomUser._meta.fields]
        return fieldsets + ((_('All Fields'), {'fields': all_fields}),)

admin.site.register(CustomUser, CustomUserAdmin)


# Register other models
admin.site.register(Admin)
admin.site.register(Division)
admin.site.register(Department)
admin.site.register(Manager)
admin.site.register(Employee)
admin.site.register(LeaveReportEmployee)
admin.site.register(LeaveReportManager)
admin.site.register(FeedbackEmployee)
admin.site.register(FeedbackManager)
admin.site.register(NotificationManager)
admin.site.register(NotificationEmployee)
admin.site.register(Notification)
admin.site.register(EmployeeSalary)
admin.site.register(AttendanceRecord)
admin.site.register(Break)
admin.site.register(ActivityFeed)
admin.site.register(DailySchedule)
admin.site.register(DailyUpdate)
admin.site.register(EarylyClockOutRequest)
admin.site.register(LeaveBalance)