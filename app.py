from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from io import BytesIO
from pdf2image import convert_from_bytes
import tempfile
import os
import subprocess
from bs4 import BeautifulSoup

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

def is_valid_url(url):
    try:
        result = requests.utils.urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False
    
def get_content_type(url):
    try:
        response = requests.head(url)
        content_type = response.headers.get('Content-Type')
        return content_type
    except requests.RequestException as e:
        return str(e)

def search_510k_device(device_name, limit=10):
    base_url = 'https://api.fda.gov/device/510k.json'
    params = {
        'search': f'device_name:"{device_name}"',
        'limit': limit
    }

    response = requests.get(base_url, params=params)

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to fetch data: {response.status_code}")

def fetch_device_details(k_number):
    details_url = f'https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID={
        k_number}'
    response = requests.get(details_url)

    if response.status_code != 200:
        raise Exception(f"Failed to fetch device details: {
                        response.status_code}")

    soup = BeautifulSoup(response.content, 'html.parser')
    reg_number_tag = soup.find(string='Regulation Number').find_next('a')

    if reg_number_tag:
        reg_number = reg_number_tag.text.strip()
        return reg_number
    else:
        raise Exception(
            f"Regulation number not found for 510(k) Number: {k_number}")

def extract_text_from_image(image_bytes, api_key):
    url = "https://api.ocr.space/parse/image"
    payload = {
        "apikey": api_key,
        "language": "eng",
    }
    files = {"file": ("image.png", image_bytes, "image/png")}
    response = requests.post(url, files=files, data=payload)
    result = response.json()
    if "ParsedResults" in result and result["ParsedResults"]:
        extracted_text = result["ParsedResults"][0]["ParsedText"]
        return extracted_text
    else:
        return None
    
def extract_text_from_pdf_with_images(pdf_url, api_key):
    text = ""
    temp_pdf_path = None
    try:
        # Check if the input is a URL or a file path
        if is_valid_url(pdf_url):
            response = requests.get(pdf_url)
            response.raise_for_status()
            pdf_bytes = BytesIO(response.content)
        else:
            with open(pdf_url, 'rb') as f:
                pdf_bytes = BytesIO(f.read())
                # Save PDF to a temporary file
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_pdf:
                    temp_pdf.write(pdf_bytes.getbuffer())
                    temp_pdf_path = temp_pdf.name

        # Convert all pages of the PDF to images
        images = convert_from_bytes(pdf_bytes.getvalue())

        for idx, image in enumerate(images):
            image_bytes = BytesIO()
            image.save(image_bytes, format='PNG')
            image_bytes.seek(0)
            extracted_image_text = extract_text_from_image(
                image_bytes, api_key)
            if extracted_image_text:
                text += f"Page {idx + 1}:\n{extracted_image_text}\n"
            else:
                text += f"Page {idx +
                                1}:\nText extraction failed for this image\n"
    except Exception as e:
        print(f"An error occurred while extracting text from PDF: {e}")
    finally:
        # Clean up the temporary PDF file
        if temp_pdf_path and os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)

    return text

def extract_text_from_docx_with_images(docx_url, api_key):
    text = ""
    try:
        response = requests.get(docx_url)
        response.raise_for_status()
        docx_bytes = BytesIO(response.content)

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as temp_docx:
            temp_docx.write(docx_bytes.read())
            temp_docx_path = temp_docx.name

        temp_pdf_path = temp_docx_path.replace('.docx', '.pdf')
        subprocess.run(['libreoffice', '--headless', '--convert-to', 'pdf', '--outdir',
                       os.path.dirname(temp_docx_path), temp_docx_path], stderr=subprocess.DEVNULL)

        # return temp_pdf_path
        text = extract_text_from_pdf_with_images(temp_pdf_path, api_key)
    except Exception as e:
        print(f"An error occurred while extracting text from DOCX: {e}")

    return text


@app.route('/upload', methods=['POST'])
def upload_file():
    file_urls = request.json.get('fileURLs')
    if not file_urls:
        return jsonify({'error': 'No file URLs provided'}), 400

    all_extracted_texts = []

    try:
        api_key = "K83551900988957"
        # gemini_api_key = "AIzaSyDvdKaAqQsbJim30noP8mfkHNAl0Y8pwhM"

        for url in file_urls:
            content_type = get_content_type(url)
            if 'pdf' in content_type:
                print("this is a pdf file")
                extracted_text = extract_text_from_pdf_with_images(
                    url, api_key)
            elif 'word' in content_type:
                print("The file is a DOCX.")
                extracted_text = extract_text_from_docx_with_images(
                    url, api_key)
            else:
                extracted_text = "Unsupported file type"
            all_extracted_texts.append(extracted_text)
        print(all_extracted_texts)

        return jsonify({
            'message': 'Files uploaded successfully',
            'extracted_texts': all_extracted_texts
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route("/ToSearchPreMarketDB", methods=["POST"])
def SearchDB():
    device_name = request.json.get('SearchKeyword')

    all_K_Number = []
    all_RegulatoryNumber = []

    try:
        # Step 1: Search for the device
        data = search_510k_device(device_name)

        if 'results' in data and len(data['results']) > 0:
            for entry in data['results']:
                print(f"Device Name: {entry['device_name']}")
                print(f"510(k) Number: {entry['k_number']}")
                all_K_Number.append(entry['k_number'])

                # Step 2: Fetch the regulation number
                regulation_number = fetch_device_details(entry['k_number'])
                print(f"Regulation Number: {regulation_number}")
                all_RegulatoryNumber.append(regulation_number)
        else:
            print(f"No results found for device name: {device_name}")

        return jsonify({
            'message': 'Search Successfull',
            'K_Number': all_K_Number,
            'RegulatoryNumber': all_RegulatoryNumber
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)
