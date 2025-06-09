# forms.py
from django import forms
from .models import Assets, AssetCategory
from django_filters import FilterSet


class AssetCategoryForm(forms.ModelForm):
    class Meta:
        model = AssetCategory
        fields = ['category','has_os' ,'has_ip']
        labels = {
            'category': 'Category Name',
            'has_os': 'Does Category Has Operating system ?',
            'has_ip': 'Does Category Has IP address ?',
        }


class AssetForm(forms.ModelForm):
    class Meta:
        model = Assets
        fields = ['asset_category', 'asset_name', 'asset_brand', 'asset_condition','asset_image', 'os_version', 'ip_address', 'processor', 'ram', 'storage']
    
    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get('asset_category')

        if category:
            if category.has_os:
                if not cleaned_data.get('os_version'):
                    self.add_error('os_version', "OS Version is required for this category.")
                if not cleaned_data.get('processor'):
                    self.add_error('processor', "Processor is required for this category.")
                if not cleaned_data.get('ram'):
                    self.add_error('ram', "RAM is required for this category.")
                if not cleaned_data.get('storage'):
                    self.add_error('storage', "Storage is required for this category.")

            if category.has_ip:
                if not cleaned_data.get('ip_address'):
                    self.add_error('ip_address', "IP Address is required for this category.")

class AssetsFilter(FilterSet):
    class Meta:
        model = Assets
        fields = {
            'asset_name': ['icontains'],
        }
        