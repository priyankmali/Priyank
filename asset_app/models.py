from django.db import models
from django.utils import timezone
from django.conf import settings
from django.urls import reverse
from io import BytesIO
from django.core.files import File
import qrcode
from .utils import generate_qrcode


LOCATION_CHOICES = (
    ("Main Room" , "Main Room"),
    ("Meeting Room", "Meeting Room"),
    ("Main Office", "Main Office"),
)

ASSET_CONDITION_CHOICES = [
    ('new', 'New'),
    ('used', 'Used'),
]

DEPARTMENT_CHOICE = [
    ('hr', 'HR'),
    ('python', 'Python'),
    ('admin', 'Admin'),
    ('javascript','JavaScript')
]


class AssetCategory(models.Model):
    category = models.CharField(max_length=100,unique=True)
    has_os = models.BooleanField(default=False)
    has_ip = models.BooleanField(default=False)

    def save(self,*args,**kwargs):
        self.category = self.category.lower()
        super().save(*args,**kwargs)

    def __str__(self):
        return self.category

class Assets(models.Model):
    PREFIX = "KOLI"
    asset_category = models.ForeignKey(AssetCategory, on_delete=models.CASCADE)
    asset_name = models.CharField(max_length=100,blank=True,null=True)
    asset_serial_number = models.CharField(max_length=100,unique=True,blank=True)
    asset_brand = models.CharField(max_length=100)
    asset_image = models.ImageField(upload_to='images/', blank=True, null=True)
    manager = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='managed_assets')
    
    is_asset_issued = models.BooleanField(default=False)
    asset_added_date = models.DateTimeField(default=timezone.now)
    updated_date = models.DateTimeField(auto_now=True)
    return_date = models.DateTimeField(null=True, blank=True)

    asset_condition = models.CharField(max_length=100, choices=ASSET_CONDITION_CHOICES, blank=True, null=True)
    os_version = models.CharField(max_length=100, blank=True, null=True,default=None)
    ip_address = models.GenericIPAddressField(blank=True, null=True,default=None)
    processor = models.CharField(max_length=100, blank=True, null=True)  
    ram = models.CharField(max_length=50, blank=True, null=True)  
    storage = models.CharField(max_length=50, blank=True, null=True)
    
    barcode = models.ImageField(upload_to='barcodes/', blank=True, null=True)


    def save(self, *args, **kwargs):
        if not self.pk:
            last_asset = Assets.objects.filter(asset_category__category=self.asset_category.category).order_by("-asset_added_date").first()
            if last_asset:
                last_numeric_number = int(last_asset.asset_serial_number[len(last_asset.PREFIX)+len(last_asset.asset_category.category[:4]):])
                new_numeric_value = last_numeric_number + 1
                new_serial_number = f"{self.PREFIX}{last_asset.asset_category.category[:4].upper()}{str(new_numeric_value).zfill(4)}"
                print(new_serial_number)
            else:
                new_serial_number = f"{self.PREFIX}{self.asset_category.category[:4].upper()}0001"
            
            self.asset_serial_number = new_serial_number
            super().save(*args, **kwargs)

        if not self.barcode:
            qrcode_file = generate_qrcode(self.id)
            self.barcode.save(qrcode_file.name, qrcode_file, save=False)

        
        super().save(*args, **kwargs)

    @property
    def status(self):
       return "Active" if self.is_asset_issued else "Not Active"
    

    def __str__(self):
        return f"{self.asset_name} ({self.asset_serial_number})"

    def get_absolute_url(self):
        return reverse('assets-detail', kwargs={'pk': self.pk})


class Assetssearch(models.Model):
    name = models.CharField(max_length=255)
    location = models.CharField(max_length=255)
    description = models.TextField()

    def __str__(self):
        return self.name


class AssetsIssuance(models.Model):
    asset = models.ForeignKey(Assets, on_delete=models.PROTECT)
    asset_location = models.CharField(max_length=100, choices=LOCATION_CHOICES)
    date_issued = models.DateTimeField(default=timezone.now)
    asset_assignee = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.asset.asset_name} issued to {self.asset_assignee}"

    def get_absolute_url(self):
        return reverse('assets-detail', kwargs={'pk': self.pk})

class AssetAssignmentHistory(models.Model):
    asset = models.ForeignKey(Assets, on_delete=models.CASCADE)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='managed_assignments')
    date_assigned = models.DateTimeField()
    date_returned = models.DateTimeField()
    location = models.CharField(max_length=100, choices=LOCATION_CHOICES)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-date_returned']
        verbose_name_plural = 'Assignment Histories'

    def __str__(self):
        return f"{self.asset} assignment history"

class AssetIssue(models.Model):
    ISSUE_TYPES = (
        ('hardware', 'Hardware Problem'),
        ('software', 'Software Problem'),
        ('performance', 'Performance Issue'),
        ('other', 'Other'),
    )

    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
    )
    
    asset = models.ForeignKey(Assets, on_delete=models.CASCADE, related_name='asset_issue_notifications',null=True)
    reported_by =models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='asset_issue_requests',null=True)
    reported_date = models.DateTimeField(auto_now_add=True)
    issue_type = models.CharField(max_length=20, choices=ISSUE_TYPES)
    description = models.TextField()
    notes = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='resolved_issues',null=True, blank=True)
    resolved_date = models.DateTimeField(null=True, blank=True)

    resolution_method = models.TextField(blank=True, null=True, help_text="How the issue was resolved")
    time_taken = models.DurationField(null=True, blank=True, help_text="Time taken to resolve the issue")
    is_recurring = models.BooleanField(default=False, help_text="Does this issue occur frequently?")
    recurrence_notes = models.TextField(blank=True, null=True, help_text="Notes about recurring issues")

    @property
    def is_resolved(self):
        return self.status == 'resolved'
    
    @property
    def days_to_resolve(self):
        if self.resolved_date and self.reported_date:
            return (self.resolved_date - self.reported_date).days
        return None
    
    def save(self, *args, **kwargs):
        if self.status == 'resolved':
            self.resolved_date = timezone.now()
            if self.reported_date:
                self.time_taken = self.resolved_date - self.reported_date
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.asset}-{self.get_issue_type_display()} - {self.get_status_display()}"


class Notify_Manager(models.Model):
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='manager_notifications')
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='asset_requests',null=True)
    asset = models.ForeignKey(Assets, on_delete=models.CASCADE, related_name='manager_notifications',null=True)  # <-- ADD THIS
    message = models.TextField()
    approved = models.BooleanField(null=True,default=None)
    timestamp = models.DateTimeField(default=timezone.now)
    is_read = models.BooleanField(default=False)

    def __str__(self):
        return f"Notification to {self.manager.first_name} {self.manager.last_name} at {self.timestamp}"

    @property
    def status(self):
        if self.approved is True:
            return "Approved"
        elif self.approved is False:
            return "Rejected"
        return "Pending"

class Notify_Employee(models.Model):
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='employee_notifications')
    message = models.TextField()
    timestamp = models.DateTimeField(default=timezone.now)
    is_read = models.BooleanField(default=False)

    def __str__(self):
        return f"Notification to {self.employee.first_name} {self.employee.last_name} at {self.timestamp}"

    class Meta:
        verbose_name = "Employee Notification"
        verbose_name_plural = "Employee Notifications"
        ordering = ['-timestamp'] 
