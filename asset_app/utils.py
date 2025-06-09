import qrcode
from io import BytesIO
from django.core.files.uploadedfile import InMemoryUploadedFile


def generate_qrcode(asset_id):
    asset_url = f'https://koliinfotech.company/koli-ems/asset-app/asset/{asset_id}/detail/'
    
    # Generate the QR code
    qr = qrcode.make(asset_url)
    
    # Convert the QR code to an in-memory image
    barcode_io = BytesIO()
    qr.save(barcode_io, 'PNG')
    barcode_io.seek(0)
 
    # Return the image as an InMemoryUploadedFile
    return InMemoryUploadedFile(
        barcode_io, None, f'{asset_id}_barcode.png', 'image/png', barcode_io.getbuffer().nbytes, None
    )