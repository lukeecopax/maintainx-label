import streamlit as st
import requests
import json
import base64
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, Frame
from reportlab.lib.styles import ParagraphStyle # Removed getSampleStyleSheet as it wasn't used
from reportlab.lib.pagesizes import inch
from reportlab.lib.enums import TA_CENTER
from barcode import Code128
from barcode.writer import ImageWriter
import os
import io # Required for in-memory file handling
import traceback # For detailed error logging

# --- Configuration & Constants ---
BASE_URL = "https://api.getmaintainx.com/v1"

# --- Load Secrets ---
# Using Streamlit Secrets for API Credentials
try:
    BEARER_TOKEN = st.secrets["MX_BEARER_TOKEN"]
    API_KEY = st.secrets["MX_API_KEY"]
except KeyError:
    # Fallback to hardcoded credentials ONLY if secrets are not found
         st.error("ERROR: MaintainX API credentials are missing.")
         st.stop()


HEADERS = {
    "Authorization": f"Bearer {BEARER_TOKEN}",
    "Content-Type": "application/json",
    "X-Api-Key": API_KEY
}

# --- Helper Function: Generate PDF ---
def generate_pdf_label_data(input_url):
    """
    Fetches part data, generates a barcode image, creates a PDF label in memory
    matching the original Colab script's layout, and returns the PDF bytes
    and suggested filename.
    """
    try:
        # Extract part ID from the URL
        if not input_url or '/' not in input_url:
             raise ValueError("Invalid URL format. Expected a full MaintainX part URL.")
        part_id = input_url.rstrip('/').split('/')[-1]
        if not part_id.isdigit():
             raise ValueError("Could not extract a valid numeric Part ID from the URL.")

    except Exception as e:
        st.error(f"Error parsing URL: {e}")
        return None, None

    # Construct the endpoint URL
    endpoint = f"{BASE_URL}/parts/{part_id}"

    # --- API Call ---
    try:
        response = requests.get(endpoint, headers=HEADERS, timeout=15) # Added timeout
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

    except requests.exceptions.RequestException as e:
        st.error(f"API Request Failed: {e}")
        # Attempt to parse error details from MaintainX response if available
        try:
            error_details = response.json()
            st.error(f"API Error Details: {error_details.get('message', response.text)}")
        except (json.JSONDecodeError, AttributeError):
             st.error(f"Raw Response Content: {response.text}") # Show raw text if not JSON
        return None, None

    # --- Data Processing ---
    try:
        data = response.json()
        part = data.get('part', {})
        name = part.get('name', 'N/A').strip()
        barcode_value = part.get('barcode', '') # Raw barcode value from API

        if not barcode_value:
            st.warning("Part found, but it does not have a barcode value assigned in MaintainX.")
            # Fallback behaviour: Use part_id if barcode is missing
            barcode_value = part_id
            st.info(f"Using Part ID '{part_id}' as fallback barcode value.")

        # Decode the barcode from Base64 if necessary (Unlikely, but kept from original)
        try:
            # Basic check if it *might* be Base64 before attempting decode
            if len(barcode_value) % 4 == 0 and len(barcode_value) > 4 and all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=' for c in barcode_value):
                 decoded_barcode = base64.b64decode(barcode_value).decode('utf-8')
            else:
                 decoded_barcode = barcode_value # Use as-is
        except (base64.binascii.Error, UnicodeDecodeError):
            st.warning(f"Value '{barcode_value}' in barcode field couldn't be Base64 decoded, using raw value.")
            decoded_barcode = barcode_value # Use as-is if decoding fails

        if not decoded_barcode:
             st.error("Barcode value is empty after processing.")
             return None, None

        # --- Barcode Image Generation ---
        barcode_filename_base = 'temp_barcode'
        barcode_image_path = None
        try:
            # Generate Code-128 barcode image without text below it
            # Reverted options to match original Colab script
            options = dict(write_text=False)
            barcode_obj = Code128(decoded_barcode, writer=ImageWriter())
            # Save barcode image temporarily
            barcode_image_path = barcode_obj.save(barcode_filename_base, options) # Returns the full path with extension (.png)

            # --- PDF Generation (Layout matching original Colab script) ---
            pdf_buffer = io.BytesIO()
            c = canvas.Canvas(pdf_buffer, pagesize=(3 * inch, 1 * inch))

            # Barcode placement - Reverted to original parameters
            barcode_width = 2.5 * inch
            barcode_height = 0.22 * inch # Original height
            barcode_x = (3 * inch - barcode_width) / 2 # Centered horizontally
            barcode_y = 0.75 * inch # Original Y position (higher)

            # Draw the barcode image - Reverted to original simple drawImage call
            c.drawImage(barcode_image_path, x=barcode_x, y=barcode_y, width=barcode_width, height=barcode_height)

            # Text (Part Name) placement - Reverted to original parameters
            # Original dynamic font size logic
            font_size = 16 if len(name) <= 30 else 14

            # Original style setup
            style = ParagraphStyle(
                name='CenteredStyle',
                fontName='Helvetica-Bold',
                fontSize=font_size,
                leading=font_size, # Original leading
                alignment=TA_CENTER
            )
            paragraph = Paragraph(name, style)

            # Original Frame definition
            frame_width = 2.9 * inch # Original width
            frame_height = 0.78 * inch # Original height (fixed)
            frame_x = (3 * inch - frame_width) / 2 # Centered horizontally
            frame_y = 0.02 * inch # Original Y position (lower)

            frame = Frame(frame_x, frame_y, frame_width, frame_height, showBoundary=0) # Original Frame

            # Original method to add Paragraph to the Frame
            # ReportLab's Frame handles text wrapping and clipping automatically based on dimensions
            frame.addFromList([paragraph], c)

            # Save PDF to buffer
            c.showPage()
            c.save()

            # --- Prepare return values ---
            pdf_bytes = pdf_buffer.getvalue()
            pdf_buffer.close()

            # Sanitize name for filename
            safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).rstrip().replace(' ', '_')
            pdf_filename = f'barcode_{part_id}_{safe_name}.pdf'

            return pdf_bytes, pdf_filename

        finally:
            # --- Cleanup ---
            # Ensure the temporary barcode image is deleted
            if barcode_image_path and os.path.exists(barcode_image_path):
                try:
                    os.remove(barcode_image_path)
                except OSError as e:
                    st.warning(f"Could not delete temporary barcode file {barcode_image_path}: {e}")

    except Exception as e:
        st.error(f"An error occurred during label generation: {e}")
        st.error(traceback.format_exc()) # More detailed error for debugging
        return None, None


# --- Streamlit App Layout ---
st.set_page_config(page_title="MaintainX Label Generator", layout="centered")

st.title("📄 MaintainX Part Label Generator")
st.markdown("Enter the URL of a Part from MaintainX to generate a 3\"x1\" PDF label with its name and barcode.")

# Use a form to prevent rerunning the whole script on text input change
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
        with st.spinner("Generating label... Fetching data and creating PDF..."):
            # Call the function which now uses the original layout parameters
            pdf_data, pdf_filename = generate_pdf_label_data(part_url_input)

        if pdf_data and pdf_filename:
            st.success(f"✅ PDF Label '{pdf_filename}' generated successfully!")

            st.download_button(
                label="⬇️ Download PDF Label",
                data=pdf_data,
                file_name=pdf_filename,
                mime="application/pdf",
            )
        elif pdf_data is None and pdf_filename is None:
            # Error message was already shown in the function
            pass # Error handled, do nothing more here
        else:
             st.error("An unknown error occurred during PDF generation.")
