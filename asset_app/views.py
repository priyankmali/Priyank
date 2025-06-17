from django.shortcuts import render, redirect, get_object_or_404,HttpResponse
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views import View
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from main_app.notification_badge import send_notification
from .models import Assets,Notify_Manager,Notify_Employee,AssetsIssuance, AssetCategory, AssetAssignmentHistory,AssetIssue
from .forms import AssetForm,AssetCategoryForm
from .filters import AssetsFilter
from django.urls import reverse
from django.contrib.auth.mixins import LoginRequiredMixin
import requests,json
from django.templatetags.static import static
from django.contrib import messages
from main_app.models import CustomUser
from django.http import HttpResponseForbidden
from django.db.models import Q
from django.utils import timezone
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import ProtectedError
from django.template.loader import render_to_string
from django.db import IntegrityError
from django import forms

LOCATION_CHOICES = (
    ("Main Room" , "Main Room"),
    ("Meeting Room", "Meeting Room"),
    ("Main Office", "Main Office"),
)


class AssetsListView(ListView):
    model = Assets
    template_name = 'asset_app/home.html'
    context_object_name = 'assets'
    paginate_by = 5

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        # Employee
        if user.user_type == '3': 
            issued_assets = AssetsIssuance.objects.filter(
                asset_assignee=user
            ).values_list('asset_id', flat=True)
            queryset = queryset.filter(id__in=issued_assets)
        
        # Apply search filter
        search = self.request.GET.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(asset_name__icontains=search) |
                Q(asset_serial_number__icontains=search) |
                Q(asset_brand__icontains=search)
            )
        
        # Apply status filter
        status = self.request.GET.get('status')
        if status == 'issued':
            queryset = queryset.filter(is_asset_issued=True)
        elif status == 'available':
            queryset = queryset.filter(is_asset_issued=False)
        
        # Apply category filter
        category = self.request.GET.get('category')
        if category:
            queryset = queryset.filter(asset_category_id=category)
        
        queryset = queryset.select_related(
            'asset_category',
            'manager'
        ).prefetch_related(
            'assetsissuance_set',
            'assetsissuance_set__asset_assignee'
        ).order_by('-updated_date')
        
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['asset_categories'] = AssetCategory.objects.all()
        context['is_employee'] = self.request.user.user_type == '3'
        
        # Add current filter values to context
        context['current_filters'] = {
            'search': self.request.GET.get('search', ''),
            'status': self.request.GET.get('status', ''),
            'category': self.request.GET.get('category', '')
        }
        
        return context

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        context = self.get_context_data()

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            html = render_to_string(self.template_name , context , request=request)
            return HttpResponse(html)
        
        return self.render_to_response(context)

class AssetsDetailView(DetailView):
    model = Assets
    template_name = 'asset_app/asset_detail.html'
    context_object_name = 'asset'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        asset = self.object

        current_issuance = AssetsIssuance.objects.filter(
            asset=asset,
        ).select_related('asset_assignee').first()
        
        # Get historical issuances (inactive)
        historical_issuances = AssetAssignmentHistory.objects.filter(
            asset=asset,
        ).order_by('-date_assigned')

        # Add issue history
        issue_history = AssetIssue.objects.filter(
            asset=asset
        ).order_by('-reported_date').select_related('reported_by', 'resolved_by')

        context.update({
            'current_issuance': current_issuance,
            'historical_issuances': historical_issuances,
            'issue_history': issue_history,
            'recurring_count': issue_history.filter(is_recurring=True).count(),
            'issue_count': issue_history.count(),
            'now': timezone.now() 
        })
        return context


class AssetCategoryCreateView(LoginRequiredMixin, CreateView):
    model = AssetCategory
    form_class = AssetCategoryForm
    template_name = 'asset_app/assetcategory_form.html'
    success_url = reverse_lazy('asset_app:assetscategory-create')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['current_user'] = self.request.user
        context['page_title'] = "Asset Categories"
        
        categories = AssetCategory.objects.all()
        
        search_query = self.request.GET.get('search')
        if search_query:
            categories = categories.filter(category__icontains=search_query)
        
        # Add pagination
        page = self.request.GET.get('page', 1)
        paginator = Paginator(categories, 5)
        try:
            categories = paginator.page(page)
        except PageNotAnInteger:
            categories = paginator.page(1)
        except EmptyPage:
            categories = paginator.page(paginator.num_pages)
        
        context['categories'] = categories
        context['search'] = search_query or ''  # Pass search query to context
        return context

    def get(self, request, *args, **kwargs):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            context = self.get_context_data()
            html = render_to_string(
                self.template_name,
                context,
                request=request
            )
            return HttpResponse(html)
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.category = form.instance.category.lower()
        try:
            # Attempt to save the form
            response = super().form_valid(form)
            messages.success(self.request, "Asset category created successfully!")
            return response
        except IntegrityError:
            # Handle duplicate category error
            form.add_error('category', 'This category already exists.')
            return self.form_invalid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'This category already present')
        return super().form_invalid(form)
    
    
class AssetCategoryUpdateView(LoginRequiredMixin, UpdateView):
    model = AssetCategory
    fields = ['category','has_os' ,'has_ip']
    template_name = 'asset_app/assetcategory_form.html'
    success_url = reverse_lazy('asset_app:assetscategory-create')

    def form_valid(self, form):
        form.instance.category = form.instance.category.lower().strip()
        messages.success(
            self.request,
            f'Category "{form.instance.category}" updated successfully'
        )
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['current_user'] = self.request.user
        context['page_title'] = "Update Asset Category"
        context['categories'] = AssetCategory.objects.all().order_by('category') 
        return context


class AssetCategoryDeleteView(LoginRequiredMixin, DeleteView):
    model = AssetCategory
    template_name = 'asset_app/assetcategory_form.html'
    success_url = reverse_lazy('asset_app:assetscategory-create')

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        try:
            self.object.delete()
            messages.success(request, f"Category '{self.object.category}' deleted successfully.")
            return redirect(self.success_url)
        except ProtectedError as e:
            protected_objects = list(e.protected_objects)
            error_message = (
                f"Cannot delete category '{self.object.category}' because it's being used by: "
                f"{', '.join(str(obj) for obj in protected_objects[:3])}"
                f"{' and more...' if len(protected_objects) > 3 else ''}"
            )
            messages.error(request, error_message)
            return redirect('asset_app:assetscategory-create')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['current_user'] = self.request.user
        return context


def get_category_config(request):
    category_id = request.GET.get('category_id')
    try:
        category = AssetCategory.objects.get(id=category_id)
        return JsonResponse({
            'has_os': category.has_os,
            'has_ip': category.has_ip
        })
    except AssetCategory.DoesNotExist:
        return JsonResponse({'error': 'Invalid category'}, status=400)

class AssetsCreateView(LoginRequiredMixin, CreateView):
    model = Assets
    form_class = AssetForm
    template_name = 'asset_app/assets_form.html'
    success_url = reverse_lazy('asset_app:assets-list')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Add quantity field to the form
        form.fields['quantity'] = forms.IntegerField(
            min_value=1,
            initial=1,
            required=True,
            help_text="Number of identical assets to create"
        )
        return form

    def form_valid(self, form):
        # Get quantity from form data
        quantity = form.cleaned_data.pop('quantity', 1)

        asset = form.save(commit=False)

        # if user is type 2 (Manager)
        if self.request.user.user_type in ["1","2"]:
            asset.manager = self.request.user

        # Save with quantity
        if quantity == 1:
            asset.save()
            messages.success(self.request, "Asset created successfully!")
        else:
            created_assets = asset.save(quantity=quantity)
            messages.success(self.request, f"Successfully created {quantity} assets!")

        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # Pass all managers only if admin or superuser
        if user.user_type == "1" or user.is_superuser:
            context['allManager'] = CustomUser.objects.filter(user_type="2")
        
        context['current_user'] = user
        return context
    
    

class AssetUpdateView(LoginRequiredMixin, UpdateView):
    model = Assets
    form_class = AssetForm
    template_name = 'asset_app/asset_update.html'
    context_object_name = 'asset'

    def get_success_url(self):
        return reverse('asset_app:asset-update',kwargs={'pk' : self.object.pk})
    
    def form_valid(self, form):
        messages.success(self.request,'Asset Update Successfully!')
        return super().form_valid(form)
    
    def form_invalid(self, form):
        messages.error(self.request,'There was an error Updating Asset.Please Check Form Fields!!')
        return super().form_invalid(form)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        asset = self.get_object()
        context['show_all_fields'] = bool(asset.ip_address or asset.os_version)
        context['basic_fields'] = ['asset_category', 'asset_name', 'asset_brand', 'asset_condition', 'asset_image']
        return context


class AssetDeleteView(View):
    def get(self, request, pk):
        asset = get_object_or_404(Assets, pk=pk)
        try:
            asset.delete()
            messages.success(request, "Asset deleted successfully.")
        except ProtectedError:
            messages.error(request, "Cannot delete this asset because it is currently issued.")
        return redirect('asset_app:assets-list')
    


class AssetAssignView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = Assets
    fields = ['asset_assignee']
    template_name = 'asset_app/asset_assign.html'

    def test_func(self):
        return str(self.request.user.user_type) in ['2', '3']

    def get_success_url(self):
        return reverse('asset_app:assets-detail', kwargs={'pk': self.object.pk})



class MyAssetView(LoginRequiredMixin, ListView):
    template_name = 'asset_app/asset_assign.html'
    context_object_name = 'asset_issuances'
    paginate_by = 5

    def get_queryset(self):
        user = self.request.user
        
        if user.user_type == '3':
            return AssetsIssuance.objects.filter(asset_assignee=user).select_related('asset').order_by('-date_issued')
        
        elif user.user_type == '2':
            return AssetsIssuance.objects.filter(
                assigned_by=user
            ).select_related('asset', 'asset_assignee').order_by('-date_issued')
        
        else:
            return AssetsIssuance.objects.all().order_by('-date_issued')
        
   
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['issue_types'] = AssetIssue.ISSUE_TYPES
        # context['status_choices'] = AssetIssue.STATUS_CHOICES

        if user.user_type == '3':  
            context['total_assets'] = self.get_queryset().count()
            context['active_assets'] = self.get_queryset().filter(asset__is_asset_issued=True).count()
        
        return context
    
    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        context = self.get_context_data()

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            html = render_to_string(self.template_name, context, request=request)
            return HttpResponse(html)

        return self.render_to_response(context)

    def post(self,request,*args,**kwargs):
        if request.method == "POST":
            asset_id_ = request.POST.get("asset_id")
            issue_type_ = request.POST.get("issue_type")
            description_ = request.POST.get("description")
            is_recurring_ = request.POST.get("is_recurring", False) 
            recurrence_notes_ = request.POST.get("recurrence_notes")

            if asset_id_ and issue_type_ and description_:
                asset = Assets.objects.filter(id=asset_id_).first()

                existing_unresolved_issue = AssetIssue.objects.filter(
                    asset=asset,
                    reported_by=self.request.user,
                    issue_type = issue_type_,
                    status__in=['pending', 'in_progress']
                ).exists()

                if existing_unresolved_issue:
                    messages.warning(request, "An unresolved issue of this type already exists for this asset!")
                    return redirect('asset_app:my-assets')
                
                is_recurring_bool = is_recurring_ == 'on'
                
                new_asset = AssetIssue.objects.create(
                    asset=asset,
                    reported_by=self.request.user,
                    issue_type=issue_type_,
                    description=description_,
                    is_recurring = is_recurring_bool,
                    recurrence_notes= recurrence_notes_ if recurrence_notes_ else "",
                )
                new_asset.save()
                messages.success(request, "Issue Reported Successfully")
                send_notification(asset.manager, "Issue Reported Successfully","asset-notification",new_asset.id,"manager")
                return redirect('asset_app:my-assets')
                
            else:
                messages.error(request,"Something Wrong!!!")
                return redirect('asset_app:my-assets')

        return redirect('asset_app:my-assets')


class AssetNotAssignListView(LoginRequiredMixin, View):
    login_url = reverse_lazy("login_page")
    template_name = 'asset_app/not_assigned_asset_list.html'
    paginate_by = 10
    
    def handle_no_permission(self):
        messages.warning(self.request, "Please log in to access this page.")
        return redirect(self.login_url)
    
    def get(self, request):
        user = request.user
        not_assign_assets = Assets.objects.filter(is_asset_issued=False)

        # get all categories:
        categories = AssetCategory.objects.all()

        # search functionality
        search_ = request.GET.get('search')
        if search_:
            not_assign_assets = not_assign_assets.filter(
                Q(asset_name__icontains=search_) |
                Q(asset_serial_number__icontains=search_) |
                Q(asset_brand__icontains=search_) |
                Q(asset_category__category__icontains=search_)
            )

        # sorting
        sort_by = request.GET.get('sort')
        if sort_by:
            not_assign_assets = not_assign_assets.order_by(sort_by)
        else:
            # Default sorting
            not_assign_assets = not_assign_assets.order_by('-asset_added_date')

        # Category filter
        category_id = request.GET.get('category')
        if category_id:
            not_assign_assets = not_assign_assets.filter(asset_category_id=category_id)

        # pagination
        paginator = Paginator(not_assign_assets, self.paginate_by)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)

        if user.user_type in ['1','2']:
            return render(request, self.template_name, {
                'assets': page_obj,
                'page_obj': page_obj,
                'categories': categories,
                'page_title': 'Not Assigned Asset List',
            })
        else:
            pending_requests = Notify_Manager.objects.filter(
                asset__in=not_assign_assets,
                manager__isnull=False,
                approved__isnull=True
            ).values_list('asset_id', flat=True)

            context = {
                'assets': page_obj,
                'page_obj': page_obj,
                'categories': categories,
                'pending_requests': list(pending_requests),
                'page_title': 'Not Assigned Asset List',
            }

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            html = render_to_string(self.template_name, context, request=request)
            return HttpResponse(html)

        return render(request, self.template_name, context)
        

class AssetClaimView(LoginRequiredMixin, View):
    login_url = reverse_lazy("login_page")
    
    def handle_no_permission(self):
        messages.warning(self.request, "Please log in to access this page.")
        return redirect(self.login_url)

    def get(self, request):
        user = request.user
        # Manager View
        if user.user_type == '2':  
            template_name = 'manager_template/manager_claim.html'
            unclaimed_assets = Assets.objects.filter(is_asset_issued=False)

            pending_requests = Notify_Manager.objects.filter(
                asset__in=unclaimed_assets,
                manager__isnull=False,
                approved__isnull=True  
            ).values_list('asset_id', flat=True)

            return render(request, template_name, {
                'assets': unclaimed_assets,
                'page_title': 'Claim Asset',
            })
        
         # employee view
        else:
            return redirect(reverse('asset_app:not-assign-asset-list'))
        

    def post(self, request, *args, **kwargs):
        user = request.user

        asset_id = request.POST.get('asset_id')
        asset = get_object_or_404(Assets, id=asset_id)

        if asset.is_asset_issued:
            messages.warning(request, "This asset has already been claimed.")
            return redirect('asset_app:asset-claim')

        try:
            manager_message = request.POST.get('message', 'Requesting asset approval.')
            manager = asset.manager

            new_req = Notify_Manager.objects.create(
                manager=manager,
                employee=user,
                asset=asset,
                message=manager_message,
                approved = None
            )
            new_req.save()

            send_notification(get_object_or_404(CustomUser , id=new_req.manager.id), manager_message,"asset-notification",new_req.id,"manager")
            messages.success(request, "Your asset request has been sent for approval.")

        except Exception as e:
            print(f"Notification error: {e}")
            messages.error(request, "Failed to send asset request.")

        return redirect('asset_app:asset-claim')

   
  

class AssetUnclaimView(LoginRequiredMixin, View):
    def post(self, request, asset_id):
        asset = get_object_or_404(Assets, id=asset_id, asset_assignee=request.user)
        asset.asset_assignee = None
        asset.asset_issued = False
        asset.save()
        messages.success(request, f"You have unclaimed the asset: {asset.asset_name}")
        return redirect('asset_app:asset-claim')



def print_all_barcode(request):
    assets = Assets.objects.all().order_by('asset_serial_number')
    assets_to_print = []
    show_print_view = False
    error_message = None
    
    if request.method == 'POST':
        show_print_view = True
        if 'print_all' in request.POST:
            assets_to_print = assets
        elif 'print_selected' in request.POST:
            selected_ids = request.POST.getlist('selected_assets')
            if not selected_ids:
                error_message = 'Please select at least one asset to print'
                show_print_view = False
            else:
                assets_to_print = assets.filter(id__in=selected_ids)
    
        search_query = request.POST.get('search', '')
        if search_query:
            assets = assets.filter(
                asset_serial_number__icontains=search_query
            ) | assets.filter(
                asset_category__category__icontains=search_query
            )
    
    # Pagination
    paginator = Paginator(assets, 5)  # 5 assets per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'assets': page_obj,
        'assets_to_print': assets_to_print,
        'show_print_view': show_print_view,
        'error_message': error_message,
        'search_query': request.POST.get('search', '')
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string(
            'asset_app/print_assets_barcode.html',
            context,
            request=request
        )
        return HttpResponse(html)

    return render(request, 'asset_app/print_assets_barcode.html', context)