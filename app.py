import streamlit as st
import requests
import json
# import base64
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, Frame
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import inch
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.utils import ImageReader
import qrcode
# from PIL import Image
import io
import traceback
import fitz  # PyMuPDF

# --- Configuration & Constants ---
BASE_URL = "https://api.getmaintainx.com/v1"
LABEL_WIDTH_INCH = 3
LABEL_HEIGHT_INCH = 1
LABEL_SIZE = (LABEL_WIDTH_INCH * inch, LABEL_HEIGHT_INCH * inch)
PREVIEW_DPI = 150

# --- Load Secrets ---
try:
    BEARER_TOKEN = st.secrets["MX_BEARER_TOKEN"]
    API_KEY = st.secrets["MX_API_KEY"]
except KeyError as e:
    st.error(f"ERROR: MaintainX API credential '{e.args[0]}' is missing in Streamlit secrets.")
    st.stop()

HEADERS = {
    "Authorization": f"Bearer {BEARER_TOKEN}",
    "Content-Type": "application/json",
    "X-Api-Key": API_KEY
}

# --- Helper Function: Generate PDF and Preview Image ---
def generate_pdf_and_preview_data(input_url):
    """
    Fetches part data, generates QR/text PDF (text vertically centered),
    creates a PNG preview image, and returns PDF bytes, filename, and PNG bytes.
    """
    pdf_buffer = io.BytesIO()
    qr_image_buffer = io.BytesIO()
    fitz_doc = None
    preview_image_bytes = None

    try:
        # --- Part ID Extraction ---
        if not input_url or '/' not in input_url: raise ValueError("Invalid URL format.")
        part_id = input_url.rstrip('/').split('/')[-1]
        if not part_id.isdigit(): raise ValueError("Could not extract numeric Part ID.")

        # --- API Call ---
        endpoint = f"{BASE_URL}/parts/{part_id}"
        try:
            response = requests.get(endpoint, headers=HEADERS, timeout=15)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            st.error(f"API Request Failed: {e}")
            try: error_details = response.json(); st.error(f"API Error Details: {error_details.get('message', response.text)}")
            except: st.error(f"Raw Response Content: {response.text}")
            return None, None, None

        # --- Data Processing ---
        data = response.json()
        part = data.get('part', {})
        name = part.get('name', 'N/A').strip()
        qr_data_value = part.get('barcode', '')
        if not qr_data_value:
            st.warning("Using Part ID as fallback QR data.")
            qr_data_value = part_id
        processed_qr_data = qr_data_value
        if not processed_qr_data: st.error("QR Code data is empty."); return None, None, None
        if not name: st.warning("Part name is empty."); name = "N/A"

        # --- QR Code Image Generation ---
        qr = qrcode.QRCode( version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=2,)
        qr.add_data(processed_qr_data); qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(qr_image_buffer, format='PNG'); qr_image_buffer.seek(0)

        # --- PDF Generation ---
        c = canvas.Canvas(pdf_buffer, pagesize=LABEL_SIZE)
        padding = 0.05 * inch
        qr_size = LABEL_HEIGHT_INCH * inch - (2 * padding)
        qr_x = padding; qr_y = padding
        text_x = qr_x + qr_size + padding
        text_y = padding # Frame starts near bottom
        text_width = LABEL_WIDTH_INCH * inch - text_x - padding
        text_height = LABEL_HEIGHT_INCH * inch - (2 * padding) # Total available vertical space for text frame

        # --- Draw QR Code ---
        qr_img_reader = ImageReader(qr_image_buffer)
        c.drawImage( qr_img_reader, x=qr_x, y=qr_y, width=qr_size, height=qr_size, mask='auto')

        # --- Text Placement (Dynamic Size, Bold, Full Inclusion, Vertical Centering) ---
        max_font_size = 18; min_font_size = 6
        fitted_font_size = min_font_size
        paragraph = None
        paragraph_actual_height = 0 # Store the actual height of the fitted paragraph

        for current_font_size in range(max_font_size, min_font_size - 1, -1):
            style = ParagraphStyle( name=f'TextStyle_{current_font_size}', fontName='Helvetica-Bold', fontSize=current_font_size, leading=current_font_size * 1.2, alignment=TA_LEFT,)
            current_paragraph = Paragraph(name, style)
            actual_width, actual_height = current_paragraph.wrapOn(c, text_width, text_height)
            if actual_height <= text_height:
                fitted_font_size = current_font_size
                paragraph = current_paragraph
                paragraph_actual_height = actual_height # Store the height that fits
                break
            else:
                 paragraph = current_paragraph # Keep track of the last attempted (smallest)
                 paragraph_actual_height = actual_height # Store its height too

        if paragraph is None: # Handle empty name case
             style = ParagraphStyle(name='TextStyle_min', fontName='Helvetica-Bold', fontSize=min_font_size, leading=min_font_size*1.2, alignment=TA_LEFT)
             paragraph = Paragraph(name, style)
             paragraph_actual_height, _ = paragraph.wrapOn(c, text_width, text_height)

        # --- Calculate Vertical Padding for Centering ---
        vertical_space = text_height - paragraph_actual_height
        if vertical_space < 0: vertical_space = 0 # Safety check
        # Distribute the space above and below the text content
        calculated_top_padding = vertical_space / 2.0
        calculated_bottom_padding = vertical_space / 2.0

        # --- Define the Text Frame with Calculated Padding ---
        text_frame = Frame(
            text_x, text_y, # Frame still positioned near bottom-left of its area
            text_width, text_height, # Frame still occupies the full available height
            leftPadding=0,
            bottomPadding=calculated_bottom_padding, # Apply calculated padding
            rightPadding=0,
            topPadding=calculated_top_padding,      # Apply calculated padding
            showBoundary=0 # Set to 1 for debugging
        )

        # Add the dynamically sized Paragraph to the Frame (padding handles centering)
        text_frame.addFromList([paragraph], c)
        c.showPage(); c.save()
        # --- PDF Generated ---

        # --- Generate Preview Image ---
        pdf_bytes = pdf_buffer.getvalue()
        if pdf_bytes:
            try:
                fitz_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                if fitz_doc.page_count > 0:
                    page = fitz_doc.load_page(0)
                    pix = page.get_pixmap(dpi=PREVIEW_DPI)
                    preview_image_bytes = pix.tobytes("png")
            except Exception as img_err:
                 st.warning(f"Could not generate image preview from PDF: {img_err}")
                 preview_image_bytes = None
            # fitz_doc closing handled in finally

        # --- Prepare Return Values ---
        safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).rstrip().replace(' ', '_')
        pdf_filename = f'QR_{part_id}_{safe_name}_fs{fitted_font_size}.pdf'
        return pdf_bytes, pdf_filename, preview_image_bytes

    except Exception as e:
        st.error(f"An error occurred: {e}")
        st.error(traceback.format_exc())
        return None, None, None

    finally:
        if not pdf_buffer.closed: pdf_buffer.close()
        if not qr_image_buffer.closed: qr_image_buffer.close()
        if fitz_doc: fitz_doc.close()


# --- Streamlit App Layout ---
st.set_page_config(page_title="MaintainX QR Label Generator", layout="centered")
st.title(" G MaintainX Part QR Code Label Generator")
st.markdown("Enter the URL of a Part from MaintainX to generate a 3\"x1\" PDF label with its name and a QR code.")

with st.form("label_form"):
    part_url_input = st.text_input(
        "MaintainX Part URL:",
        placeholder="e.g., https://app.getmaintainx.com/parts/123456",
        key="part_url"
    )
    submitted = st.form_submit_button("Generate PDF Label")

if submitted:
    if not part_url_input:
        st.warning("Please enter a MaintainX Part URL.")
    else:
        with st.spinner("Generating label and preview..."):
            pdf_data, pdf_filename, preview_data = generate_pdf_and_preview_data(input_url=part_url_input) # Pass input correctly

        if pdf_data and pdf_filename:
            # st.success(f"✅ PDF Label '{pdf_filename}' generated successfully!")

            # --- Display Download Button ---
            st.download_button(
                label="⬇️ Download PDF Label",
                data=pdf_data,
                file_name=pdf_filename,
                mime="application/pdf",
            )

            # --- Display Preview Image ---
            if preview_data:
                st.markdown("**Label Preview:**")
                # Use use_container_width instead of use_column_width
                st.image(preview_data, use_container_width=True)
                st.markdown("---")
            else:
                st.warning("Could not generate label preview image.")


        elif pdf_data is None and pdf_filename is None:
            pass # Error handled in function
        else:
             st.error("An unknown error occurred during PDF generation.")
