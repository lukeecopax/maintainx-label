import streamlit as st
import requests
import json
# import base64
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, Frame
from reportlab.lib.styles import ParagraphStyle
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

def generate_pdf_and_preview_data(input_url):
    """
    Fetches data for either a Part or a Location,
    generates a 3"x1" PDF label with its name and QR code,
    renders a PNG preview, and returns (pdf_bytes, filename, preview_png_bytes).
    """
    pdf_buffer = io.BytesIO()
    qr_buffer = io.BytesIO()
    fitz_doc = None
    preview_bytes = None

    try:
        # --- Resource ID Extraction ---
        if not input_url or "/" not in input_url:
            raise ValueError("Invalid URL format.")
        resource_id = input_url.rstrip("/").split("/")[-1]
        if not resource_id.isdigit():
            raise ValueError("Could not extract numeric ID.")

        # --- Determine endpoint & JSON key ---
        if "/locations/" in input_url:
            endpoint = f"{BASE_URL}/locations/{resource_id}"
            json_key = "location"
            filename_prefix = "LOC"
        else:
            endpoint = f"{BASE_URL}/parts/{resource_id}"
            json_key = "part"
            filename_prefix = "QR"

        # --- API Call ---
        response = requests.get(endpoint, headers=HEADERS, timeout=15)
        response.raise_for_status()
        payload = response.json().get(json_key, {})

        # --- Data Processing ---
        name = payload.get("name", "N/A").strip() or "N/A"
        qr_data = payload.get("barcode", "") or resource_id

        # --- Generate QR Code Image ---
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=2,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(qr_buffer, format="PNG")
        qr_buffer.seek(0)

        # --- PDF Generation ---
        c = canvas.Canvas(pdf_buffer, pagesize=LABEL_SIZE)
        padding = 0.05 * inch
        qr_size = LABEL_HEIGHT_INCH * inch - 2 * padding

        # Draw QR code at left
        c.drawImage(
            ImageReader(qr_buffer),
            x=padding,
            y=padding,
            width=qr_size,
            height=qr_size,
            mask="auto"
        )

        # Text area to the right of QR
        text_x = padding + qr_size + padding
        text_y = padding
        text_width = LABEL_WIDTH_INCH * inch - text_x - padding
        text_height = LABEL_HEIGHT_INCH * inch - 2 * padding

        # Dynamic font sizing (18pt → 6pt)
        max_fs, min_fs = 18, 6
        fitted_fs = min_fs
        paragraph = None
        paragraph_height = 0

        for fs in range(max_fs, min_fs - 1, -1):
            style = ParagraphStyle(
                name=f"PS_{fs}",
                fontName="Helvetica-Bold",
                fontSize=fs,
                leading=fs * 1.2,
                alignment=TA_LEFT
            )
            p = Paragraph(name, style)
            w, h = p.wrapOn(c, text_width, text_height)
            if h <= text_height:
                fitted_fs = fs
                paragraph = p
                paragraph_height = h
                break
            paragraph = p
            paragraph_height = h

        # Fallback in the very unlikely event paragraph is None
        if not paragraph:
            style = ParagraphStyle(
                name="PS_min",
                fontName="Helvetica-Bold",
                fontSize=min_fs,
                leading=min_fs * 1.2,
                alignment=TA_LEFT
            )
            paragraph = Paragraph(name, style)
            paragraph_height, _ = paragraph.wrapOn(c, text_width, text_height)

        # Vertical centering
        vertical_space = max(text_height - paragraph_height, 0)
        pad = vertical_space / 2

        frame = Frame(
            text_x, text_y,
            text_width, text_height,
            leftPadding=0,
            bottomPadding=pad,
            rightPadding=0,
            topPadding=pad,
            showBoundary=0
        )
        frame.addFromList([paragraph], c)

        c.showPage()
        c.save()
        pdf_bytes = pdf_buffer.getvalue()

        # --- Generate Preview Image (PNG) ---
        if pdf_bytes:
            try:
                fitz_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                page = fitz_doc.load_page(0)
                pix = page.get_pixmap(dpi=PREVIEW_DPI)
                preview_bytes = pix.tobytes("png")
            except Exception as e:
                st.warning(f"Could not generate preview: {e}")

        # --- Filename ---
        safe = "".join(ch for ch in name if ch.isalnum() or ch in (" ", "_", "-"))
        safe = safe.rstrip().replace(" ", "_")
        pdf_filename = f"{filename_prefix}_{resource_id}_{safe}_fs{fitted_fs}.pdf"

        return pdf_bytes, pdf_filename, preview_bytes

    except Exception as e:
        st.error(f"An error occurred: {e}")
        st.error(traceback.format_exc())
        return None, None, None

    finally:
        pdf_buffer.close()
        qr_buffer.close()
        if fitz_doc:
            fitz_doc.close()


# --- Streamlit App Layout ---
st.set_page_config(page_title="MaintainX Label Generator", layout="centered")

st.title("📄 MaintainX Part & Location Label Generator")
st.markdown(
    "Enter the URL of a Part or a Location from MaintainX to generate a "
    "3\"×1\" PDF label with its name and a QR code."
)

with st.form("label_form"):
    resource_url = st.text_input(
        "MaintainX Part or Location URL:",
        placeholder="e.g., https://app.getmaintainx.com/parts/123456 or https://app.getmaintainx.com/locations/963",
        key="resource_url"
    )
    submitted = st.form_submit_button("Generate PDF Label")

if submitted:
    if not resource_url:
        st.warning("Please enter a MaintainX URL.")
    else:
        with st.spinner("Generating label and preview..."):
            pdf_data, pdf_filename, preview_data = generate_pdf_and_preview_data(input_url=resource_url)

        if pdf_data and pdf_filename:
            st.download_button(
                label="⬇️ Download PDF Label",
                data=pdf_data,
                file_name=pdf_filename,
                mime="application/pdf",
            )

            if preview_data:
                st.markdown("**Label Preview:**")
                st.image(preview_data, use_container_width=True)
                st.markdown("---")
            else:
                st.warning("Could not generate label preview image.")

        elif pdf_data is None and pdf_filename is None:
            # Errors already shown in helper
            pass
        else:
            st.error("An unknown error occurred during PDF generation.")
