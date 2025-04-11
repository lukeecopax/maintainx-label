import streamlit as st
import requests
import json
import base64
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, Frame
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import inch
from reportlab.lib.enums import TA_CENTER
from barcode import Code128
from barcode.writer import ImageWriter
import os
import io # Required for in-memory file handling

# --- Configuration & Constants ---
BASE_URL = "https://api.getmaintainx.com/v1"
# IMPORTANT: Replace these with st.secrets for production/sharing
# For local testing, you can leave them here or use environment variables
# BEARER_TOKEN = "YOUR_BEARER_TOKEN" # Replace with your actual token
# API_KEY = "YOUR_API_KEY"         # Replace with your actual API key

# Using the token/key from the original script for demonstration
# !! WARNING: Do not commit sensitive keys directly into code !!
# !! Use Streamlit Secrets (st.secrets) for deployment !!
# Near the top of app.py, replace the hardcoded credentials with:
try:
    BEARER_TOKEN = st.secrets["MX_BEARER_TOKEN"]
    API_KEY = st.secrets["MX_API_KEY"]
except KeyError:
    st.error("ERROR: MaintainX API credentials not found in Streamlit Secrets.")
    st.stop() # Stop execution if secrets are missing

HEADERS = {
    "Authorization": f"Bearer {BEARER_TOKEN}",
    "Content-Type": "application/json",
    "X-Api-Key": API_KEY
}

# --- Helper Function: Generate PDF ---
def generate_pdf_label_data(input_url):
    """
    Fetches part data, generates a barcode image, creates a PDF label in memory,
    and returns the PDF bytes and suggested filename.
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
            # Decide if you want to proceed without a barcode or stop
            # For now, let's try generating a barcode from the part_id as a fallback
            barcode_value = part_id
            st.info(f"Using Part ID '{part_id}' as fallback barcode value.")
            # return None, None # uncomment this if you want to stop if no barcode exists

        # Decode the barcode from Base64 if necessary (unlikely for standard barcodes)
        # The original code had this, keeping it just in case, but usually not needed for EAN/UPC/Code128
        try:
            # Attempt Base64 decoding ONLY if it looks like Base64
            if len(barcode_value) % 4 == 0 and all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/' for c in barcode_value):
                 decoded_barcode = base64.b64decode(barcode_value).decode('utf-8')
            else:
                 decoded_barcode = barcode_value # Use as-is
        except (base64.binascii.Error, UnicodeDecodeError):
            decoded_barcode = barcode_value # Use as-is if decoding fails

        if not decoded_barcode:
             st.error("Barcode value is empty after processing.")
             return None, None

        # --- Barcode Image Generation ---
        barcode_filename_base = 'temp_barcode'
        barcode_image_path = None
        try:
            # Generate Code-128 barcode image without text below it
            options = dict(write_text=False, module_height=5.0) # Adjust module_height for barcode thickness
            barcode_obj = Code128(decoded_barcode, writer=ImageWriter())
            # Save barcode image temporarily
            barcode_image_path = barcode_obj.save(barcode_filename_base, options) # Returns the full path with extension (.png)

            # --- PDF Generation ---
            pdf_buffer = io.BytesIO()
            c = canvas.Canvas(pdf_buffer, pagesize=(3 * inch, 1 * inch))

            # Barcode placement
            barcode_width = 2.5 * inch
            barcode_height = 0.30 * inch # Increased height slightly
            barcode_x = (3 * inch - barcode_width) / 2 # Centered horizontally
            barcode_y = 0.60 * inch # Positioned higher

            c.drawImage(barcode_image_path, x=barcode_x, y=barcode_y, width=barcode_width, height=barcode_height, preserveAspectRatio=True, anchor='n')

            # Text (Part Name) placement
            # Dynamic font size based on name length
            max_len_large_font = 25
            max_len_medium_font = 40
            if len(name) <= max_len_large_font:
                font_size = 14
            elif len(name) <= max_len_medium_font:
                font_size = 12
            else:
                font_size = 10 # Smaller font for very long names

            style = ParagraphStyle(
                name='CenteredStyle',
                fontName='Helvetica-Bold',
                fontSize=font_size,
                leading=font_size + 2, # Adjust line spacing slightly more than font size
                alignment=TA_CENTER,
                wordWrap='CJK', # Handles wrapping better for mixed characters
            )
            paragraph = Paragraph(name, style)

            # Frame for text - place below barcode
            frame_width = 2.8 * inch
            frame_height = barcode_y - (0.1 * inch) # Max height is space below barcode minus margin
            frame_x = (3 * inch - frame_width) / 2
            frame_y = 0.05 * inch # Bottom margin

            frame = Frame(frame_x, frame_y, frame_width, frame_height, leftPadding=0, bottomPadding=0, rightPadding=0, topPadding=0, showBoundary=0) # Set padding to 0

            # Draw the paragraph within the frame
            # This handles text wrapping automatically
            para_width, para_height = paragraph.wrapOn(c, frame_width, frame_height)
            if para_height <= frame_height: # Only draw if it fits
                frame.addFromList([paragraph], c)
            else:
                 # Handle text overflow - maybe truncate or just warn
                 st.warning(f"Part name '{name}' is too long to fit completely on the label at the smallest font size. It may be truncated.")
                 # Draw truncated text if needed (more complex) or just draw what fits
                 frame.addFromList([paragraph], c) # Draw whatever fits


            # Save PDF to buffer
            c.showPage()
            c.save()

            # --- Prepare return values ---
            pdf_bytes = pdf_buffer.getvalue()
            pdf_buffer.close()

            # Sanitize name for filename
            safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).rstrip()
            pdf_filename = f'MX_Label_{part_id}_{safe_name}.pdf'

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
        import traceback
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

st.markdown("---")
st.caption("Note: Ensure the API Token and Key used have the necessary permissions to read part data.")
st.caption("⚠️ Security Warning: The API credentials in this script are hardcoded for demonstration. Use Streamlit Secrets (`st.secrets`) for production or shared apps.")
