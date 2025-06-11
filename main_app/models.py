from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import UserManager
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.core.exceptions import ValidationError
from datetime import timedelta
import pytz
from datetime import datetime, time,date
from calendar import monthrange
from django.db import transaction
import logging

class CustomUserManager(UserManager):
    def _create_user(self, email, password, **extra_fields):
        email = self.normalize_email(email)
        user = CustomUser(email=email, **extra_fields)
        user.password = make_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        assert extra_fields["is_staff"]
        assert extra_fields["is_superuser"]
        return self._create_user(email, password, **extra_fields)


class CustomUser(AbstractUser):
    USER_TYPE = ((1, "CEO"), (2, "Manager"), (3, "Employee"))
    GENDER = [("M", "Male"), ("F", "Female")]
    
    
    username = None  # Removed username, using email instead
    email = models.EmailField(unique=True)
    user_type = models.CharField(default=1, choices=USER_TYPE, max_length=1)
    gender = models.CharField(max_length=1, choices=GENDER)
    profile_pic = models.ImageField(blank=True)
    address = models.TextField()
    fcm_token = models.TextField(default="")  # For firebase notifications
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = CustomUserManager()

    def __str__(self):
        return self.first_name + " " + self.last_name


class Admin(models.Model):
    admin = models.OneToOneField(CustomUser, on_delete=models.CASCADE,related_name='admin')
    def __str__(self):
        return self.admin.first_name+ " " + self.admin.last_name


class Division(models.Model):
    name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name



class Department(models.Model):
    name = models.CharField(max_length=120)
    division = models.ForeignKey(Division, on_delete=models.CASCADE)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class Manager(models.Model):
    division = models.ForeignKey(Division, on_delete=models.DO_NOTHING, null=True, blank=False)
    department = models.ForeignKey(Department, on_delete=models.DO_NOTHING, null=True, blank=False)
    emergency_contact = models.JSONField(blank=True, null=True)
    phone_number = models.CharField(max_length=10, blank=True, null=True)
    designation = models.CharField(max_length=50, blank=True, null=True)
    admin = models.OneToOneField(CustomUser, on_delete=models.CASCADE,related_name='manager')
    date_of_joining = models.DateField(blank=True, null=True)
    
    def __str__(self):
        return self.admin.last_name + " " + self.admin.first_name



logger = logging.getLogger(__name__)

class Employee(models.Model):
    admin = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='employee')
    division = models.ForeignKey(Division, on_delete=models.DO_NOTHING, null=True, blank=False)
    department = models.ForeignKey(Department, on_delete=models.DO_NOTHING, null=True, blank=False)
    employee_id = models.CharField(max_length=10, unique=True, null=True, blank=True)
    designation = models.CharField(max_length=50)
    team_lead = models.ForeignKey(Manager, on_delete=models.CASCADE, related_name='team_members', null=True, blank=True)
    phone_number = models.CharField(max_length=10)
    emergency_contact = models.JSONField(blank=True, null=True)
    date_of_joining = models.DateField(blank=True, null=True)

    def save(self, *args, **kwargs):
        # Check if this is an update (not a new instance)
        is_update = self.pk is not None
        old_date_of_joining = None

        if is_update:
            # Fetch the old date_of_joining before saving
            try:
                old_instance = Employee.objects.get(pk=self.pk)
                old_date_of_joining = old_instance.date_of_joining
            except Employee.DoesNotExist:
                old_date_of_joining = None

        # Generate employee_id if not set
        if not self.employee_id:
            last_id = Employee.objects.all().order_by('-id').first()
            if last_id and last_id.employee_id:
                emp_num = int(last_id.employee_id.replace('EMP', '')) + 1
            else:
                emp_num = 1
            self.employee_id = f"EMP{emp_num:03d}"

        # Save the Employee instance
        with transaction.atomic():
            super().save(*args, **kwargs)

            # Check if date_of_joining has changed
            if is_update and self.date_of_joining != old_date_of_joining:
                logger.info(f"Date of joining changed for {self.employee_id}: {old_date_of_joining} -> {self.date_of_joining}")
                # Recalculate LeaveBalance records
                self._recalculate_leave_balances()

    def _recalculate_leave_balances(self):
        """
        Recalculate all LeaveBalance records for this employee after date_of_joining changes.
        Preserves used_leaves values.
        """
        if not self.date_of_joining:
            logger.warning(f"No date_of_joining set for {self.employee_id}, skipping LeaveBalance recalculation")
            return

        # Store existing used_leaves values
        leave_balances = LeaveBalance.objects.filter(employee=self).order_by('year', 'month')
        used_leaves_data = {
            (balance.year, balance.month): balance.used_leaves
            for balance in leave_balances
        }
        logger.debug(f"Stored used_leaves data: {used_leaves_data}")

        # Delete existing LeaveBalance records
        leave_balances.delete()
        logger.info(f"Deleted existing LeaveBalance records for {self.employee_id}")

        # Reinitialize LeaveBalance records
        today = date.today()
        LeaveBalance.initialize_balances(self, today)
        logger.info(f"Reinitialized LeaveBalance records for {self.employee_id} from {self.date_of_joining} to {today}")

        # Restore used_leaves values
        for (year, month), used_leaves in used_leaves_data.items():
            balance = LeaveBalance.get_balance(self, year, month)
            if balance:
                balance.used_leaves = used_leaves
                balance.save()
                logger.debug(f"Restored used_leaves={used_leaves} for {self.employee_id} in {year}-{month}")

    def __str__(self):
        return self.admin.first_name + " " + self.admin.last_name



class LeaveBalance(models.Model):
    employee = models.ForeignKey('Employee', on_delete=models.CASCADE, related_name='leave_balances')
    year = models.PositiveIntegerField()
    month = models.PositiveIntegerField()
    allocated_leaves = models.FloatField(default=0.0)
    carried_forward = models.FloatField(default=0.0)
    used_leaves = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['employee', 'year', 'month']]
        indexes = [
            models.Index(fields=['employee', 'year', 'month']),
        ]

    def clean(self):
        if self.month < 1 or self.month > 12:
            raise ValidationError("Month must be between 1 and 12.")
        if self.allocated_leaves < 0 or self.used_leaves < 0 or self.carried_forward < 0:
            raise ValidationError("Leave counts cannot be negative.")
        if self.year < 2000 or self.year > 9999:
            raise ValidationError("Year must be a valid four-digit year.")

    def total_available_leaves(self):
        return max(0, self.allocated_leaves + self.carried_forward - self.used_leaves)

    def save(self, *args, **kwargs):
        self.clean()

        if not self.employee.date_of_joining:
            raise ValidationError("Employee must have a valid date_of_joining to calculate leave balances.")
        
        joining_date = self.employee.date_of_joining
        joining_year = joining_date.year
        joining_month = joining_date.month

        # Reset at the beginning of the year
        if self.month == 1:
            self.carried_forward = 0.0
            if not self.pk:  # Only reset used_leaves for new records
                self.used_leaves = 0.0

        # Calculate allocated leaves
        if self.year == joining_year and self.month == joining_month:
            self.allocated_leaves = 1.0
        elif self.year >= joining_year and (self.year > joining_year or self.month >= joining_month):
            self.allocated_leaves = 1.0
        else:
            self.allocated_leaves = 0.0

        # Calculate carry forward from previous month (if not January)
        if self.month > 1:
            prev_month = self.month - 1
            prev_year = self.year
        else:
            prev_month = 12
            prev_year = self.year - 1

        if self.month != 1 and prev_year >= joining_year and (prev_year > joining_year or prev_month >= joining_month):
            prev_balance = LeaveBalance.objects.filter(
                employee=self.employee,
                year=prev_year,
                month=prev_month
            ).first()
            if prev_balance and prev_balance.total_available_leaves() > 0:
                self.carried_forward = prev_balance.total_available_leaves()

        super().save(*args, **kwargs)

    @classmethod
    def get_balance(cls, employee, year_or_date, month=None):
        if isinstance(year_or_date, date):
            year = year_or_date.year
            month = year_or_date.month
        else:
            year = year_or_date

        return cls.objects.filter(employee=employee, year=year, month=month).first()

    @classmethod
    def create_balance(cls, employee, year, month):
        balance, created = cls.objects.get_or_create(
            employee=employee,
            year=year,
            month=month,
            defaults={'allocated_leaves': 0.0, 'used_leaves': 0.0, 'carried_forward': 0.0}
        )
        if created or not balance.allocated_leaves:
            balance.save()  # This will trigger the save method to set allocated_leaves and carried_forward
        return balance

    @classmethod
    def initialize_balances(cls, employee, end_date):
        joining_date = employee.date_of_joining
        current_date = joining_date
        end_year = end_date.year
        end_month = end_date.month

        while current_date.year < end_year or (current_date.year == end_year and current_date.month <= end_month):
            cls.create_balance(employee, current_date.year, current_date.month)
            if current_date.month == 12:
                current_date = current_date.replace(year=current_date.year + 1, month=1, day=1)
            else:
                current_date = current_date.replace(month=current_date.month + 1, day=1)

    @classmethod
    def deduct_leave(cls, employee, date, leave_type):
        balance = cls.get_balance(employee, date.year, date.month)
        if not balance:
            cls.initialize_balances(employee, date)
            balance = cls.get_balance(employee, date.year, date.month)

        leave_amount = 0.5 if leave_type == 'Half-Day' else 1.0
        available_leaves = balance.total_available_leaves()

        # Always allow the deduction, even if insufficient
        balance.used_leaves += leave_amount
        balance.save()
        new_available = balance.total_available_leaves()  # Could be negative, but total_available_leaves clamps to 0
        return True, available_leaves - leave_amount  # Return the actual change for tracking

    
class LeaveReportEmployee(models.Model):
    LEAVE_TYPE = (
        ('Half-Day', 'Half-Day'),
        ('Full-Day', 'Full-Day')
    )
    HALF_DAY_CHOICES = (
        ('First Half', 'First Half'),
        ('Second Half', 'Second Half')
    )

    employee = models.ForeignKey('Employee', on_delete=models.CASCADE)
    leave_type = models.CharField(max_length=100, choices=LEAVE_TYPE, default="Full-Day")
    half_day_type = models.CharField(max_length=100, choices=HALF_DAY_CHOICES, blank=True, null=True)
    start_date = models.DateField()
    end_date = models.DateField()
    message = models.TextField()
    status = models.SmallIntegerField(default=0)  # 0: Pending, 1: Approved, 2: Rejected
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        if self.leave_type == 'Half-Day' and not self.half_day_type:
            raise ValidationError("Please specify whether it's First Half or Second Half for Half-Day leaves.")
        if self.leave_type == 'Full-Day' and self.half_day_type:
            self.half_day_type = None
        if self.end_date < self.start_date:
            raise ValidationError("End date cannot be before start date.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

class AttendanceRecord(models.Model):
    STATUS_CHOICES = [
        ('present', 'Present'),
        ('late', 'Late'),
        ('half_day', 'Half Day'),
        ('absent', 'Absent'),
        ('leave', 'Leave'),
    ]

    user = models.ForeignKey('CustomUser', on_delete=models.CASCADE, related_name='attendance_records')
    date = models.DateField()
    clock_in = models.DateTimeField(null=True, blank=True)
    clock_out = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='present')
    department = models.ForeignKey('Department', on_delete=models.SET_NULL, null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    location = models.CharField(max_length=255, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    total_worked = models.DurationField(null=True, blank=True)
    regular_hours = models.DurationField(null=True, blank=True)
    overtime_hours = models.DurationField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['user', 'date']]
        indexes = [
            models.Index(fields=['user', 'date']),
            models.Index(fields=['date', 'department']),
            models.Index(fields=['status']),
        ]

    def clean(self):
        if self.clock_out and self.clock_in and self.clock_out < self.clock_in:
            raise ValidationError("Clock out time cannot be before clock in time.")
        if self.clock_in and self.clock_in.date() != self.date:
            raise ValidationError("Clock in time must be on the same date as the attendance record.")
        if self.clock_out and self.clock_out.date() != self.date:
            raise ValidationError("Clock out time must be on the same date as the attendance record.")

    def save(self, *args, **kwargs):
        # ist = pytz.timezone('Asia/Kolkata')
        if self.clock_in:
            # ist_time = self.clock_in.astimezone(ist)
            late_time = datetime.combine(self.clock_in.date(), time(9, 15))
            half_day_time = datetime.combine(self.clock_in.date(), time(13, 0))
            after_3pm_time = datetime.combine(self.clock_in.date(), time(15, 0))

            if self.status not in ['leave', 'absent']:
                if self.clock_in > after_3pm_time:
                    self.status = 'present'
                elif self.clock_in > half_day_time:
                    self.status = 'half_day'
                elif self.clock_in > late_time:
                    self.status = 'late'
                else:
                    self.status = 'present'

        if self.clock_out:
            self.total_worked = self.clock_out - self.clock_in
            regular_hours_limit = timedelta(hours=8)
            self.regular_hours = min(self.total_worked, regular_hours_limit)
            self.overtime_hours = max(timedelta(), self.total_worked - regular_hours_limit)

        super().save(*args, **kwargs)


        



class LeaveReportManager(models.Model):
    LEAVE_TYPE = (
        ('Half-Day','Half-Day'),
        ('Full-Day','Full-Day')
    )
    HALF_DAY_CHOICES = (
        ('First Half', 'First Half'),
        ('Second Half', 'Second Half')
    )
    manager = models.ForeignKey(Manager, on_delete=models.CASCADE)
    leave_type = models.CharField(max_length=100,choices=LEAVE_TYPE,blank=True,default="Full-Day")
    half_day_type = models.CharField(max_length=100, choices=HALF_DAY_CHOICES, blank=True, null=True)
    start_date = models.DateField(blank=True, null=True, default=None)
    end_date = models.DateField(blank=True,null=True)
    date = models.CharField(max_length=60)
    message = models.TextField()
    status = models.SmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class FeedbackEmployee(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    feedback = models.TextField()
    reply = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class FeedbackManager(models.Model):
    manager = models.ForeignKey(Manager, on_delete=models.CASCADE)
    feedback = models.TextField()
    reply = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class NotificationManager(models.Model):
    manager = models.ForeignKey(Manager, on_delete=models.CASCADE)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class NotificationEmployee(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(CustomUser, null=True, blank=True, on_delete=models.SET_NULL)

class EmployeeSalary(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    department = models.ForeignKey(Department, on_delete=models.CASCADE)
    base = models.FloatField(default=0)
    ctc = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Notification(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    role = models.CharField(max_length=56)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    notification_type = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    leave_or_notification_id = models.IntegerField()
    def __str__(self):
        return f"Notification for {self.user} - {self.notification_type} - {self.role}"
    


# class AttendanceRecord(models.Model):
#     STATUS_CHOICES = [
#         ('present', 'Present'),
#         ('late', 'Late'),
#         ('half_day', 'Half Day'),
#     ]
    
#     user = models.ForeignKey('CustomUser', on_delete=models.CASCADE, related_name='attendance_records')
#     date = models.DateField(auto_now_add=False)
#     clock_in = models.DateTimeField()
#     clock_out = models.DateTimeField(null=True, blank=True)
#     status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='present')
#     department = models.ForeignKey('Department', on_delete=models.SET_NULL, null=True, blank=True)
#     ip_address = models.GenericIPAddressField(null=True, blank=True)
#     location = models.CharField(max_length=255, null=True, blank=True)
#     notes = models.TextField(null=True, blank=True)
    
#     # Time calculations
#     total_worked = models.DurationField(null=True, blank=True)
#     regular_hours = models.DurationField(null=True, blank=True)
#     overtime_hours = models.DurationField(null=True, blank=True)
    
#     # Flags
#     is_primary_record = models.BooleanField(default=False)
#     requires_verification = models.BooleanField(default=False)
    
#     # Verification
#     is_verified = models.BooleanField(default=False)
#     verified_by = models.ForeignKey('CustomUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_attendances')
#     verification_time = models.DateTimeField(null=True, blank=True)
    
#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)

#     class Meta:
#         ordering = ['-date', 'user__email']
#         indexes = [
#             models.Index(fields=['user', 'date']),
#             models.Index(fields=['date', 'department']),
#             models.Index(fields=['status']),
#         ]
#         unique_together = [['user', 'date', 'clock_in']]  # Prevent duplicate clock-ins
    
#     def clean(self):
#         if self.clock_out and self.clock_in and self.clock_out < self.clock_in:
#             raise ValidationError("Clock out time cannot be before clock in time.")
        
#         # Ensure clock-in is on the same date
#         if self.clock_in.date() != self.date:
#             raise ValidationError("Clock in time must be on the same date as the attendance record.")
        
#         if self.clock_out and self.clock_out.date() != self.date:
#             raise ValidationError("Clock out time must be on the same date as the attendance record.")

#         if self.clock_out and self.user.user_type == "3":
#             try:
#                 employee = Employee.objects.get(admin=self.user)
#                 schedule = DailySchedule.objects.get(employee=employee, date=self.date)
#                 if not schedule.updates.exists():
#                     raise ValidationError("Cannot clock out until a daily update is submitted for today's schedule.")
#             except (Employee.DoesNotExist, DailySchedule.DoesNotExist):
#                 raise ValidationError("Cannot clock out without a valid schedule for today.")
    
#     def save(self, *args, **kwargs):
#         ist = pytz.timezone('Asia/Kolkata')
        
#         # Auto-close previous days' open records
#         if not self.pk:
#             open_records = AttendanceRecord.objects.filter(
#                 user=self.user,
#                 clock_out__isnull=True,
#                 date__lt=self.date
#             )
#             for record in open_records:
#                 record.clock_out = record.clock_in + timedelta(hours=10)
#                 record.notes = (
#                     f"{record.notes}\n" if record.notes else ""
#                 ) + f"Auto-logged out on {timezone.now()} due to new record creation"
#                 record.total_worked = record.clock_out - record.clock_in
#                 regular_hours_limit = timedelta(hours=8)
#                 if record.total_worked > regular_hours_limit:
#                     record.regular_hours = regular_hours_limit
#                     record.overtime_hours = record.total_worked - regular_hours_limit
#                 else:
#                     record.regular_hours = record.total_worked
#                     record.overtime_hours = timedelta()
#                 record.save()

#         # Check if early clock-out request is approved
#         early_clock_out_approved = False
#         if self.clock_out and not self.pk:
#             early_clock_out_approved = EarylyClockOutRequest.objects.filter(
#                 attendance_record=self,
#                 status='approved'
#             ).exists()

#         # Automatic status determination based on clock-in time
#         if self.clock_in:
#             ist_time = self.clock_in.astimezone(ist)
#             late_time = datetime.combine(ist_time.date(), time(9, 15)).replace(tzinfo=ist)
#             half_day_time = datetime.combine(ist_time.date(), time(13, 0)).replace(tzinfo=ist)
#             after_3pm_time = datetime.combine(ist_time.date(), time(15, 0)).replace(tzinfo=ist)

#             if ist_time > after_3pm_time:
#                 self.status = 'present'  # After 3:00 PM, count as present
#             elif ist_time > half_day_time:
#                 self.status = 'half_day'  # Between 1:00 PM and 3:00 PM
#             elif ist_time > late_time:
#                 self.status = 'late'  # After 9:15 AM but before 1:00 PM
#             else:
#                 self.status = 'present'  # Before 9:15 AM

#         # Calculate time durations if clock_out exists
#         if self.clock_out:
#             self.total_worked = self.clock_out - self.clock_in
#             regular_hours_limit = timedelta(hours=9)
#             if self.total_worked > regular_hours_limit:
#                 self.regular_hours = regular_hours_limit
#                 self.overtime_hours = self.total_worked - regular_hours_limit
#             else:
#                 self.regular_hours = self.total_worked
#                 self.overtime_hours = timedelta()
        
#         # Check if this is the first record of the day
#         if not self.pk:
#             existing_records = AttendanceRecord.objects.filter(
#                 user=self.user, 
#                 date=self.date
#             ).exists()
#             self.is_primary_record = not existing_records
        
#         super().save(*args, **kwargs)
    
#     def __str__(self):
#         return f"{self.user} - {self.date} ({self.status}) {self.clock_in.time()} to {self.clock_out.time() if self.clock_out else ''}"

        
class Break(models.Model):
    BREAK_TYPE_CHOICES = [
        ('lunch', 'Lunch Break'),
        ('short', 'Short Break'),
    ]
    
    attendance_record = models.ForeignKey(AttendanceRecord, on_delete=models.CASCADE, related_name='breaks')
    break_type = models.CharField(max_length=20, choices=BREAK_TYPE_CHOICES, default='lunch')
    break_start = models.DateTimeField()
    break_end = models.DateTimeField(null=True, blank=True)
    is_paid = models.BooleanField(default=True)
    reason = models.CharField(max_length=255, null=True, blank=True)
    duration = models.DurationField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.attendance_record}'

    class Meta:
        ordering = ['break_start']
    
    def clean(self):
        if self.break_end and self.break_start and self.break_end < self.break_start:
            raise ValidationError("Break end time cannot be before break start time.")
        
        if self.attendance_record.clock_in and self.break_start < self.attendance_record.clock_in:
            raise ValidationError("Break cannot start before clock in time.")
            
        if self.attendance_record.clock_out and self.break_end and self.break_end > self.attendance_record.clock_out:
            raise ValidationError("Break cannot end after clock out time.")
    
    def save(self, *args, **kwargs):
        if self.break_end:
            self.duration = self.break_end - self.break_start
        super().save(*args, **kwargs)
        
        # Update the parent attendance record
        if self.attendance_record:
            self.attendance_record.save()
    
    def __str__(self):
        return f"{self.get_break_type_display()} for {self.attendance_record.user} ({self.duration})"

class ActivityFeed(models.Model):
    ACTIVITY_TYPES = [
        ('clock_in', 'Clock In'),
        ('clock_out', 'Clock Out'),
        ('break_start', 'Break Start'),
        ('break_end', 'Break End'),
        ('status_change', 'Status Change'),
        ('correction', 'Time Correction'),
        ('verification', 'Verification'),
    ]
    
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    activity_type = models.CharField(max_length=50, choices=ACTIVITY_TYPES)
    timestamp = models.DateTimeField(auto_now_add=True)
    related_record = models.ForeignKey(AttendanceRecord, on_delete=models.SET_NULL, null=True, blank=True)
    details = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['activity_type']),
        ]
    
    def __str__(self):
        return f"{self.user} {self.get_activity_type_display()} at {self.timestamp}"

class AttendanceSummary(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='attendance_summaries')
    month = models.PositiveSmallIntegerField()
    year = models.PositiveSmallIntegerField()
    
    total_days = models.PositiveSmallIntegerField()
    present_days = models.PositiveSmallIntegerField()
    absent_days = models.PositiveSmallIntegerField()
    late_days = models.PositiveSmallIntegerField()
    half_days = models.PositiveSmallIntegerField()
    leave_days = models.PositiveSmallIntegerField()
    
    total_worked = models.DurationField()
    regular_hours = models.DurationField()
    overtime_hours = models.DurationField()
    total_breaks = models.DurationField()
    
    class Meta:
        unique_together = ('user', 'month', 'year')
        verbose_name_plural = 'Attendance Summaries'
    
    def __str__(self):
        return f"{self.user} - {self.month}/{self.year} Summary"
    
class Holiday(models.Model):
    HOLIDAY_TYPES = [
        ('public', 'Public Holiday'),
        ('company', 'Company Holiday'),
        ('observance', 'Observance'),
        ('seasonal', 'Seasonal'),
    ]
    
    date = models.DateField()
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=20, choices=HOLIDAY_TYPES, default='public')
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date']
        verbose_name_plural = 'Holidays'

    def __str__(self):
        return f"{self.name} ({self.date})"


def get_ist_date():
    return datetime.now().date()

class DailySchedule(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='schedules')
    attendance_record = models.ForeignKey('AttendanceRecord', on_delete=models.SET_NULL, 
                                        related_name='schedules', null=True, blank=True)
    date = models.DateField()
    task_description = models.TextField()
    project = models.CharField(max_length=100, blank=True)
    justification = models.TextField(blank=True)  # New field for justification
    total_hours = models.FloatField(default=0.0)  # New field for total scheduled hours
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('employee', 'date')
        ordering = ['-date', 'employee__admin__first_name']

    def __str__(self):
        return f"{self.employee} - {self.task_description} on {self.date}"
    
    def save(self, *args, **kwargs):
        # Calculate total_hours before saving
        self.total_hours = self.calculate_total_hours()
        super().save(*args, **kwargs)
    
    def calculate_total_hours(self):
        """Calculate total scheduled hours from task descriptions"""
        total_minutes = 0
        for task in self.tasks:
            time_part = task['time'].strip().lower()
            if 'h' in time_part:
                total_minutes += float(time_part.replace('h', '')) * 60
            elif 'm' in time_part:
                total_minutes += float(time_part.replace('m', ''))
            elif 's' in time_part:
                total_minutes += float(time_part.replace('s', '')) / 60
            elif time_part:  # assume minutes if no unit specified
                total_minutes += float(time_part)
        return total_minutes / 60
    
    def duration(self):
        """Calculate actual work duration from attendance record"""
        if self.attendance_record and self.attendance_record.clock_out:
            duration = self.attendance_record.clock_out - self.attendance_record.clock_in
            return duration.total_seconds() / 3600  # converts to hours
        return 0
    
    @property
    def tasks(self):
        """Parse task descriptions into structured data"""
        tasks = []
        for line in self.task_description.split('\n'):
            parts = line.split('|', 1)
            if len(parts) == 2:
                desc, time = parts
                tasks.append({'description': desc.strip(), 'time': time.strip()})
            else:
                tasks.append({'description': line.strip(), 'time': ''})
        return tasks
    
    @property
    def task_description_lines(self):
        """Get non-empty task description lines"""
        return [line for line in self.task_description.split("\n") if line.strip()]



class DailyUpdate(models.Model):
    schedule = models.ForeignKey(DailySchedule, on_delete=models.CASCADE, related_name='updates')
    update_description = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)
    justification = models.TextField(blank=True, default='')  # Add justification field

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"Update for {self.schedule} at {self.updated_at}"

    def clean(self):
        if not self.update_description.strip():
            raise ValidationError("Update description cannot be empty.")
    
    @property
    def updates(self):
        updates = []
        for line in self.update_description.split('\n'):
            parts = line.split('|', 1)
            if len(parts) == 2:
                desc, time = parts
                updates.append({'description': desc.strip(), 'time': time.strip()})
            else:
                updates.append({'description': line.strip(), 'time': ''})
        return updates

    @property
    def update_description_lines(self):
        return [line for line in self.update_description.split('\n') if line.strip()]

    @property
    def total_time_spent(self):
        """Calculate total time spent in minutes from update_description."""
        total_minutes = 0
        for update in self.updates:
            time_str = update['time'].lower()
            try:
                if 'h' in time_str:
                    total_minutes += float(time_str.replace('h', '')) * 60
                elif 'm' in time_str:
                    total_minutes += float(time_str.replace('m', ''))
                elif 's' in time_str:
                    total_minutes += float(time_str.replace('s', '')) / 60
            except (ValueError, IndexError):
                continue
        return total_minutes

    @property
    def total_time_spent_formatted(self):
        """Return total time spent in 'Xh Ym' format."""
        total_minutes = self.total_time_spent
        hours = int(total_minutes // 60)
        minutes = int(total_minutes % 60)
        return f"{hours}h {minutes}m"





class EarylyClockOutRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('denied', 'Denied'),
    ]
    attendance_record = models.ForeignKey(
        'AttendanceRecord',
        on_delete=models.CASCADE,
        related_name='early_clock_out_requests'
    )
    user = models.ForeignKey(
        'CustomUser',
        on_delete=models.CASCADE,
        related_name='early_clock_out_requests'
    )
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(
        'CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_early_clock_out_requests'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['user', 'submitted_at']),
            models.Index(fields=['status']),
            models.Index(fields=['attendance_record']),
        ]

    def __str__(self):
        return f"Early Clock-Out Request by {self.user} for {self.attendance_record} ({self.status})"

    def clean(self):
        if self.status == 'approved' and not self.reviewed_by:
            raise ValidationError("Approved requests must have a reviewer.")
        if self.reviewed_at and not self.reviewed_by:
            raise ValidationError("Reviewed requests must have a reviewer.")
        if self.reviewed_by and not self.reviewed_at:
            raise ValidationError("Reviewer must have a review timestamp.")

    def save(self, *args, **kwargs):
        is_new = not self.pk
        super().save(*args, **kwargs)
        if is_new:
            # Create NotificationManager for the manager
            from .models import NotificationManager, Manager
            manager = Manager.objects.filter(department=self.attendance_record.department).first()
            if manager:
                NotificationManager.objects.create(
                    manager=manager,
                    message=f"Early clock-out request from {self.user.get_full_name()} for {self.attendance_record.date}: {self.reason[:100]}",
                    created_at=timezone.now()
                )
        if self.status in ['approved', 'denied'] and not self.reviewed_at:
            self.reviewed_at = timezone.now()
            super().save(update_fields=['reviewed_at'])
