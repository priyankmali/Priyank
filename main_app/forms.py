from django import forms
from django.forms.widgets import DateInput
from datetime import date
from .models import *

class FormSettings(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.visible_fields():
            field.field.widget.attrs['class'] = 'form-control'

class CustomUserForm(FormSettings):
    email = forms.EmailField(required=True)
    gender = forms.ChoiceField(choices=[('M', 'Male'), ('F', 'Female')])
    first_name = forms.CharField(required=True)
    last_name = forms.CharField(required=True)
    address = forms.CharField(widget=forms.Textarea)
    password = forms.CharField(widget=forms.PasswordInput, required=False)
    profile_pic = forms.ImageField(required=False, widget=forms.FileInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['password'].widget.attrs['placeholder'] = "Fill this only if you wish to update password"
            user = self.instance.admin
            self.fields['first_name'].initial = user.first_name
            self.fields['last_name'].initial = user.last_name
            self.fields['email'].initial = user.email
            self.fields['address'].initial = user.address
            self.fields['gender'].initial = user.gender
            self.fields['profile_pic'].initial = user.profile_pic

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        if self.instance.pk:
            if CustomUser.objects.exclude(id=self.instance.admin.id).filter(email=email).exists():
                raise forms.ValidationError("This email is already registered.")
        else:
            if CustomUser.objects.filter(email=email).exists():
                raise forms.ValidationError("This email is already registered.")
        return email

    class Meta:
        model = CustomUser
        fields = ['first_name', 'last_name', 'email', 'gender', 'password', 'profile_pic', 'address']

class AdminForm(CustomUserForm):
    class Meta(CustomUserForm.Meta):
        model = Admin
        fields = CustomUserForm.Meta.fields



class EmployeeForm(CustomUserForm):
    emergency_name = forms.CharField(label="Emergency Contact Name", required=False)
    emergency_relationship = forms.CharField(label="Emergency Contact Relationship", required=False)
    emergency_phone = forms.CharField(label="Emergency Contact Phone", max_length=10, required=False)
    emergency_address = forms.CharField(label="Emergency Contact Address", required=False, widget=forms.Textarea)
    date_of_joining = forms.DateField(
        label="Date of Joining",
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=True
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Initialize emergency contact fields
        if self.instance and self.instance.emergency_contact:
            ec = self.instance.emergency_contact
            self.fields['emergency_name'].initial = ec.get('name', '')
            self.fields['emergency_relationship'].initial = ec.get('relationship', '')
            self.fields['emergency_phone'].initial = ec.get('phone', '')
            self.fields['emergency_address'].initial = ec.get('address', '')

        # Initialize date_of_joining field
        if self.instance and self.instance.pk and self.instance.date_of_joining:
            self.fields['date_of_joining'].initial = self.instance.date_of_joining

    def clean_date_of_joining(self):
        date_of_joining = self.cleaned_data.get('date_of_joining')
        if not date_of_joining:
            raise ValidationError("Date of Joining is required.")
        return date_of_joining

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Save emergency contact details
        instance.emergency_contact = {
            'name': self.cleaned_data.get('emergency_name'),
            'relationship': self.cleaned_data.get('emergency_relationship'),
            'phone': self.cleaned_data.get('emergency_phone'),
            'address': self.cleaned_data.get('emergency_address'),
        }

        # Save date_of_joining
        date_of_joining = self.cleaned_data.get('date_of_joining')
        if date_of_joining:
            instance.date_of_joining = date_of_joining
        else:
            print("Error: date_of_joining is missing in cleaned_data")  # Debugging

        if commit:
            try:
                instance.save()
                if hasattr(instance, 'admin'):
                    instance.admin.save()
                print(f"Saved Employee: {instance}, date_of_joining: {instance.date_of_joining}")  # Debugging
            except Exception as e:
                print(f"Error saving employee: {e}")  # Debugging
        return instance

    class Meta(CustomUserForm.Meta):
        model = Employee
        fields = CustomUserForm.Meta.fields + [
            'division', 'department', 'designation', 'team_lead', 'phone_number', 'date_of_joining'
        ]

class ManagerForm(CustomUserForm):
    emergency_name = forms.CharField(label="Emergency Contact Name", required=False)
    emergency_relationship = forms.CharField(label="Emergency Contact Relationship", required=False)
    emergency_phone = forms.CharField(label="Emergency Contact Phone", max_length=10, required=False)
    emergency_address = forms.CharField(label="Emergency Contact Address", required=False, widget=forms.Textarea)
    date_of_joining = forms.DateField(
        label="Date of Joining",
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=True
    )

    def __init__(self, *args, **kwargs):
        super(ManagerForm, self).__init__(*args, **kwargs)
        # Only set initial values if the instance exists and has an associated admin
        if self.instance and self.instance.pk and hasattr(self.instance, 'admin'):
            self.fields['email'].initial = self.instance.admin.email
            self.fields['password'].required = False  # Password is optional for updates

        if self.instance and self.instance.emergency_contact:
            ec = self.instance.emergency_contact
            self.fields['emergency_name'].initial = ec.get('name', '')
            self.fields['emergency_relationship'].initial = ec.get('relationship', '')
            self.fields['emergency_phone'].initial = ec.get('phone', '')
            self.fields['emergency_address'].initial = ec.get('address', '')

        if self.instance and hasattr(self.instance, 'date_of_joining'):
            self.fields['date_of_joining'].initial = self.instance.date_of_joining

    def save(self, commit=True):
        instance = super().save(commit=False)
        # Update or create the admin user
        if hasattr(instance, 'admin'):
            admin = instance.admin
        else:
            # Create a new CustomUser if no admin exists (new manager)
            admin = CustomUser(
                email=self.cleaned_data.get('email'),
                first_name=self.cleaned_data.get('first_name'),
                last_name=self.cleaned_data.get('last_name'),
                user_type=2,  # Manager
            )
            if self.cleaned_data.get('password') and self.cleaned_data.get('password').strip():
                admin.set_password(self.cleaned_data.get('password'))
            admin.save()
            instance.admin = admin

        admin.first_name = self.cleaned_data.get('first_name')
        admin.last_name = self.cleaned_data.get('last_name')
        admin.email = self.cleaned_data.get('email')
        if self.cleaned_data.get('password') and self.cleaned_data.get('password').strip():
            admin.set_password(self.cleaned_data.get('password'))
        admin.save()

        instance.emergency_contact = {
            'name': self.cleaned_data.get('emergency_name'),
            'relationship': self.cleaned_data.get('emergency_relationship'),
            'phone': self.cleaned_data.get('emergency_phone'),
            'address': self.cleaned_data.get('emergency_address'),
        }
        instance.date_of_joining = self.cleaned_data.get('date_of_joining')

        if commit:
            instance.save()
        return instance

    class Meta(CustomUserForm.Meta):
        model = Manager
        fields = CustomUserForm.Meta.fields + ['division', 'department', 'date_of_joining']




class DivisionForm(FormSettings):
    def __init__(self, *args, **kwargs):
        super(DivisionForm, self).__init__(*args, **kwargs)

    class Meta:
        fields = ['name']
        model = Division


class DepartmentForm(FormSettings):

    def __init__(self, *args, **kwargs):
        super(DepartmentForm, self).__init__(*args, **kwargs)

    class Meta:
        model = Department
        fields = ['name', 'division']


class LeaveReportManagerForm(FormSettings):
    def __init__(self, *args, **kwargs):
        super(LeaveReportManagerForm, self).__init__(*args, **kwargs)

    class Meta:
        model = LeaveReportManager
        fields = ['date', 'message']
        widgets = {
            'date': forms.DateInput(
                attrs={
                    'type': 'date',
                    'class': 'form-control',   # Ensures proper Bootstrap styling
                    'placeholder': 'Select a date',
                }
            ),
            'message': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Enter your message',
                    'rows': 3
                }
            )
        }


class FeedbackManagerForm(FormSettings):

    def __init__(self, *args, **kwargs):
        super(FeedbackManagerForm, self).__init__(*args, **kwargs)

    class Meta:
        model = FeedbackManager
        fields = ['feedback']


class LeaveReportEmployeeForm(FormSettings):
    def __init__(self, *args, **kwargs):
        super(LeaveReportEmployeeForm, self).__init__(*args, **kwargs)
        today = date.today().isoformat()
        self.fields['start_date'].widget.attrs['min'] = today
        self.fields['end_date'].widget.attrs['min'] = today

    class Meta:
        model = LeaveReportEmployee
        fields = [ 'leave_type','start_date', 'end_date', 'message']
        widgets = {
            'start_date': DateInput(attrs={'type': 'date'},),
            'end_date': DateInput(attrs={'type': 'date'}),
        }


class FeedbackEmployeeForm(FormSettings):

    def __init__(self, *args, **kwargs):
        super(FeedbackEmployeeForm, self).__init__(*args, **kwargs)

    class Meta:
        model = FeedbackEmployee
        fields = ['feedback']


class EmployeeEditForm(CustomUserForm):
    def __init__(self, *args, **kwargs):
        super(EmployeeEditForm, self).__init__(*args, **kwargs)

    class Meta(CustomUserForm.Meta):
        model = Employee
        fields = CustomUserForm.Meta.fields 



class ManagerEditForm(CustomUserForm):
    def __init__(self, *args, **kwargs):
        super(ManagerEditForm, self).__init__(*args, **kwargs)
        # Ensure email field is properly initialized from admin user
        if self.instance and self.instance.admin:
            self.fields['email'].initial = self.instance.admin.email
            self.fields['password'].required = False  # Password is optional for updates

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            # Update the admin user fields
            admin = instance.admin
            admin.first_name = self.cleaned_data.get('first_name')
            admin.last_name = self.cleaned_data.get('last_name')
            admin.email = self.cleaned_data.get('email')
            if self.cleaned_data.get('password') and self.cleaned_data.get('password').strip():
                admin.set_password(self.cleaned_data.get('password'))
            admin.save()
            instance.save()
        return instance

    class Meta(CustomUserForm.Meta):
        model = Manager
        fields = CustomUserForm.Meta.fields


class EditSalaryForm(FormSettings):
    def __init__(self, *args, **kwargs):
        super(EditSalaryForm, self).__init__(*args, **kwargs)

    class Meta:
        model = EmployeeSalary
        fields = ['department', 'employee', 'base', 'ctc']


# class ScheduleForm(forms.ModelForm):
#     class Meta:
#         model = Schedule
#         fields = ['project', 'task_description', 'status', 'employee']
#         widgets = {
#             # 'employee' : forms.TextInput(attrs={'class' : 'form-control'})
#             'project': forms.TextInput(attrs={'class': 'form-control','placeholder': 'Project name (optional)'}),
#             'task_description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control','placeholder': 'Describe your tasks for today...'}),
#             'status': forms.Select(attrs={'class': 'form-control'}),
#         }

# class ScheduleUpdateForm(forms.ModelForm):
#     class Meta:
#         model = ScheduleUpdate
#         fields = ['update_description', 'status']
#         widgets = {
#             'update_description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control','placeholder': 'What progress have you made?'}),
#             'status': forms.Select(attrs={'class': 'form-control'}),
#         }

#     def clean_update_description(self):
#         description = self.cleaned_data['update_description']
#         if not description.strip():
#             raise forms.ValidationError("Update description cannot be empty.")
#         return description