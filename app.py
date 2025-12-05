from flask import Flask, request, jsonify, send_file, render_template
from werkzeug.utils import secure_filename
from flask_cors import CORS
import os
import PyPDF2
import fitz
import zipfile
import tempfile
import shutil
import traceback
import math
from PIL import Image
import io

app = Flask(__name__)
CORS(app)

app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['PROCESSED_FOLDER'] = 'processed'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['PROCESSED_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def cleanup_folder(folder_path):
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        try:
            if os.path.isfile(file_path):
                os.unlink(file_path)
        except Exception as e:
            print(f"Error deleting {file_path}: {e}")

class PDFProcessor:
    @staticmethod
    def merge_pdfs(pdf_files, output_path):
        merger = PyPDF2.PdfMerger()
        for pdf_file in pdf_files:
            merger.append(pdf_file)
        merger.write(output_path)
        merger.close()

    @staticmethod
    def split_pdf(input_path, output_folder, pages=None):
        doc = fitz.open(input_path)
        if pages == "all" or pages is None or pages == "":
            for page_num in range(len(doc)):
                output_pdf = fitz.open()
                output_pdf.insert_pdf(doc, from_page=page_num, to_page=page_num)
                output_path = os.path.join(output_folder, f"page_{page_num + 1}.pdf")
                output_pdf.save(output_path)
                output_pdf.close()
        else:
            page_ranges = pages.split(',')
            for page_range in page_ranges:
                if '-' in page_range:
                    start, end = map(int, page_range.split('-'))
                    output_pdf = fitz.open()
                    output_pdf.insert_pdf(doc, from_page=start-1, to_page=end-1)
                    output_path = os.path.join(output_folder, f"pages_{page_range}.pdf")
                    output_pdf.save(output_path)
                    output_pdf.close()
                else:
                    page_num = int(page_range) - 1
                    output_pdf = fitz.open()
                    output_pdf.insert_pdf(doc, from_page=page_num, to_page=page_num)
                    output_path = os.path.join(output_folder, f"page_{page_range}.pdf")
                    output_pdf.save(output_path)
                    output_pdf.close()
        doc.close()

    @staticmethod
    def remove_pages(input_path, output_path, pages_to_remove):
        """Remove specific pages from PDF"""
        doc = fitz.open(input_path)
        total_pages = len(doc)
        
        pages_to_remove_set = set()
        for page_str in pages_to_remove.split(','):
            if '-' in page_str:
                start, end = map(int, page_str.split('-'))
                for page in range(start, end + 1):
                    if 1 <= page <= total_pages:
                        pages_to_remove_set.add(page - 1)
            else:
                page_num = int(page_str)
                if 1 <= page_num <= total_pages:
                    pages_to_remove_set.add(page_num - 1)
        
        output_doc = fitz.open()
        for page_num in range(total_pages):
            if page_num not in pages_to_remove_set:
                output_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
        
        output_doc.save(output_path)
        output_doc.close()
        doc.close()
        
        return len(pages_to_remove_set)

    @staticmethod
    def organize_pages(input_path, output_path, page_order):
        """Reorganize pages according to specified order"""
        doc = fitz.open(input_path)
        total_pages = len(doc)
        
        page_sequence = []
        for item in page_order.split(','):
            if '-' in item:
                start, end = map(int, item.split('-'))
                for page in range(start, end + 1):
                    if 1 <= page <= total_pages:
                        page_sequence.append(page - 1)
            else:
                page_num = int(item)
                if 1 <= page_num <= total_pages:
                    page_sequence.append(page_num - 1)
        
        output_doc = fitz.open()
        for page_index in page_sequence:
            output_doc.insert_pdf(doc, from_page=page_index, to_page=page_index)
        
        output_doc.save(output_path)
        output_doc.close()
        doc.close()
        
        return len(page_sequence)

    @staticmethod
    def smart_compress_pdf(input_path, output_path, compression_level='medium'):
        """
        Smart compression that preserves text as vector data
        Only compresses images, keeps text crisp and clear
        """
        doc = fitz.open(input_path)
        
        # Compression profiles
        profiles = {
            'low': {
                'image_quality': 0.9,
                'image_dpi': 200,
                'jpeg_quality': 90,
                'compress_text': True,
                'compress_fonts': True
            },
            'medium': {
                'image_quality': 0.7,
                'image_dpi': 150,
                'jpeg_quality': 80,
                'compress_text': True,
                'compress_fonts': True
            },
            'high': {
                'image_quality': 0.5,
                'image_dpi': 100,
                'jpeg_quality': 70,
                'compress_text': True,
                'compress_fonts': True
            },
            'extreme': {
                'image_quality': 0.3,
                'image_dpi': 72,
                'jpeg_quality': 60,
                'compress_text': True,
                'compress_fonts': True
            }
        }
        
        profile = profiles.get(compression_level, profiles['medium'])
        
        # Create output PDF
        output_doc = fitz.open()
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            
            # Get the page as a PDF to preserve vector text
            output_page = output_doc.new_page(width=page.rect.width, height=page.rect.height)
            
            # First, add the original page content to preserve text
            output_page.show_pdf_page(
                output_page.rect,
                doc,
                page_num
            )
            
            # Now compress images on the page
            image_list = page.get_images()
            
            for img_index, img in enumerate(image_list):
                try:
                    xref = img[0]
                    pix = fitz.Pixmap(doc, xref)
                    
                    if pix.n - pix.alpha < 4:  # if not CMYK
                        # Compress the image
                        if profile['image_quality'] < 1.0:
                            # Scale down image if needed
                            if pix.width > 1000 or pix.height > 1000:
                                scale = profile['image_quality']
                                new_width = int(pix.width * scale)
                                new_height = int(pix.height * scale)
                                
                                # Convert to PIL for better resizing
                                img_data = pix.tobytes("ppm")
                                pil_img = Image.open(io.BytesIO(img_data))
                                pil_img = pil_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                                
                                # Convert back to bytes
                                img_byte_arr = io.BytesIO()
                                pil_img.save(img_byte_arr, format='JPEG', quality=profile['jpeg_quality'])
                                compressed_data = img_byte_arr.getvalue()
                                
                                # Replace the image in PDF
                                output_doc._updateObject(xref, compressed_data)
                        
                except Exception as e:
                    print(f"Error compressing image {img_index} on page {page_num}: {e}")
                    continue
                finally:
                    if 'pix' in locals():
                        pix = None  # Free memory
        
        # Save with optimization options
        save_options = {
            'garbage': 4,           # Remove unused objects
            'deflate': True,        # Compress the PDF structure
            'clean': True,          # Clean the PDF
            'deflate_images': True, # Compress images
            'deflate_fonts': True,  # Compress fonts
            'pretty': False         # Don't pretty-print (saves space)
        }
        
        output_doc.save(output_path, **save_options)
        output_doc.close()
        doc.close()

    @staticmethod
    def compress_pdf_to_size_smart(input_path, output_path, target_size_mb, max_iterations=6):
        """
        Smart size-based compression that preserves text quality
        """
        original_size = os.path.getsize(input_path) / (1024 * 1024)
        target_size_bytes = target_size_mb * 1024 * 1024
        
        print(f"Smart compression - Original: {original_size:.2f} MB, Target: {target_size_mb} MB")
        
        if original_size <= target_size_mb:
            # Just optimize without compression
            PDFProcessor.optimize_pdf(input_path, output_path)
            return original_size
        
        # Try different compression levels
        compression_levels = ['low', 'medium', 'high', 'extreme']
        best_size = original_size
        best_output = None
        
        for level in compression_levels:
            temp_output = tempfile.mktemp(suffix='.pdf')
            PDFProcessor.smart_compress_pdf(input_path, temp_output, level)
            
            current_size = os.path.getsize(temp_output) / (1024 * 1024)
            print(f"Compression level '{level}': {current_size:.2f} MB")
            
            if current_size <= target_size_mb:
                if best_output and os.path.exists(best_output):
                    os.remove(best_output)
                shutil.copy2(temp_output, output_path)
                os.remove(temp_output)
                print(f"Found suitable compression: {level} -> {current_size:.2f} MB")
                return current_size
            
            if current_size < best_size:
                best_size = current_size
                if best_output and os.path.exists(best_output):
                    os.remove(best_output)
                best_output = temp_output
            else:
                os.remove(temp_output)
        
        # If we didn't reach target, use the best we found
        if best_output and os.path.exists(best_output):
            shutil.copy2(best_output, output_path)
            os.remove(best_output)
        
        print(f"Best achieved: {best_size:.2f} MB")
        return best_size

    @staticmethod
    def optimize_pdf(input_path, output_path):
        """
        Optimize PDF without quality loss - just remove bloat
        """
        doc = fitz.open(input_path)
        
        save_options = {
            'garbage': 4,
            'deflate': True,
            'clean': True,
            'deflate_images': True,
            'deflate_fonts': True,
            'pretty': False
        }
        
        doc.save(output_path, **save_options)
        doc.close()

    @staticmethod
    def pdf_to_images(input_path, output_folder, format='png', dpi=150):
        doc = fitz.open(input_path)
        image_paths = []
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            mat = fitz.Matrix(dpi/72, dpi/72)
            pix = page.get_pixmap(matrix=mat)
            if format.lower() == 'jpg':
                img_path = os.path.join(output_folder, f"page_{page_num + 1}.jpg")
                pix.save(img_path, "JPEG", quality=90)
            else:
                img_path = os.path.join(output_folder, f"page_{page_num + 1}.png")
                pix.save(img_path, "PNG")
            image_paths.append(img_path)
        doc.close()
        return image_paths

    @staticmethod
    def protect_pdf(input_path, output_path, password):
        doc = fitz.open(input_path)
        doc.save(output_path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=password)
        doc.close()

    @staticmethod
    def unlock_pdf(input_path, output_path, password):
        """Remove password protection from PDF"""
        try:
            doc = fitz.open(input_path)
            if doc.authenticate(password):
                doc.save(output_path)
                doc.close()
                return True
            doc.close()
            return False
        except Exception as e:
            print(f"Unlock error: {e}")
            return False

@app.route('/')
def home():
    return '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>PDF Toolkit</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh; color: #333; padding: 20px;
            }
            .container { max-width: 1200px; margin: 0 auto; }
            header { text-align: center; margin-bottom: 40px; color: white; }
            header h1 { font-size: 3rem; margin-bottom: 10px; text-shadow: 2px 2px 4px rgba(0,0,0,0.3); }
            header p { font-size: 1.2rem; opacity: 0.9; }
            .tool-grid { 
                display: grid; 
                grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); 
                gap: 20px; 
                margin-bottom: 40px; 
            }
            .tool-card {
                background: white; border-radius: 15px; padding: 25px; text-align: center;
                box-shadow: 0 10px 30px rgba(0,0,0,0.2); transition: transform 0.3s ease;
                cursor: pointer;
            }
            .tool-card:hover { transform: translateY(-5px); }
            .tool-icon { font-size: 2.5rem; margin-bottom: 15px; color: #667eea; }
            .upload-area {
                background: white; border-radius: 15px; padding: 40px; text-align: center;
                box-shadow: 0 10px 30px rgba(0,0,0,0.2); margin-bottom: 20px;
            }
            .drop-zone {
                border: 3px dashed #667eea; border-radius: 10px; padding: 60px 20px;
                margin: 20px 0; transition: all 0.3s ease; background: #f8f9fa;
            }
            .drop-zone.active { border-color: #764ba2; background: #e9ecef; }
            .btn {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white; border: none; padding: 15px 30px; border-radius: 25px;
                font-size: 1rem; cursor: pointer; transition: all 0.3s ease;
                text-decoration: none; display: inline-block; margin: 10px;
            }
            .btn:hover { transform: scale(1.05); }
            .btn:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
            .file-list { margin: 20px 0; }
            .file-item {
                background: #f8f9fa; padding: 15px; border-radius: 8px;
                margin: 10px 0; display: flex; justify-content: space-between;
                align-items: center;
            }
            .file-info { 
                background: #e9ecef; padding: 10px; border-radius: 5px; 
                margin: 10px 0; text-align: left; font-size: 0.9em;
            }
            .quality-info {
                background: #d4edda; padding: 15px; border-radius: 8px;
                margin: 15px 0; text-align: center;
            }
            .page-preview {
                background: #d1ecf1; padding: 15px; border-radius: 8px;
                margin: 10px 0; text-align: center;
            }
            .progress-bar { 
                width: 100%; height: 10px; background: #e9ecef; 
                border-radius: 5px; margin: 20px 0; overflow: hidden; 
            }
            .progress { 
                height: 100%; 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                width: 0%; transition: width 0.3s ease;
            }
            .hidden { display: none; }
            .options-panel {
                background: #f8f9fa; padding: 20px; border-radius: 10px;
                margin: 20px 0; text-align: left;
            }
            .option-group { margin-bottom: 15px; }
            .option-group label { display: block; margin-bottom: 5px; font-weight: bold; }
            .option-group select, .option-group input, .option-group textarea {
                width: 100%; padding: 10px; border: 2px solid #ddd;
                border-radius: 5px; font-size: 1rem;
            }
            .size-preview { 
                background: #d4edda; padding: 10px; border-radius: 5px; 
                margin: 10px 0; text-align: center; font-weight: bold;
            }
            .compression-method { 
                display: flex; gap: 10px; margin-bottom: 15px;
            }
            .method-btn {
                flex: 1; padding: 10px; border: 2px solid #667eea; 
                border-radius: 5px; background: white; cursor: pointer;
                text-align: center; transition: all 0.3s ease;
            }
            .method-btn.active {
                background: #667eea; color: white;
            }
            .page-numbers { 
                background: #fff3cd; padding: 10px; border-radius: 5px;
                margin: 10px 0; font-size: 0.9em;
            }
            .feature-list {
                background: #e7f3ff; padding: 15px; border-radius: 8px;
                margin: 15px 0; text-align: left;
            }
            .feature-list ul {
                margin: 10px 0; padding-left: 20px;
            }
            .feature-list li {
                margin: 5px 0;
            }
            footer { text-align: center; color: white; margin-top: 40px; opacity: 0.8; }
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>PDF Toolkit</h1>
                <p>Your all-in-one online PDF solution</p>
            </header>

            <div class="tool-grid">
                <div class="tool-card" onclick="showTool('merge')">
                    <div class="tool-icon">📄</div>
                    <h3>Merge PDF</h3>
                    <p>Combine multiple PDF files into one</p>
                </div>
                <div class="tool-card" onclick="showTool('split')">
                    <div class="tool-icon">✂️</div>
                    <h3>Split PDF</h3>
                    <p>Split PDF into multiple files</p>
                </div>
                <div class="tool-card" onclick="showTool('compress')">
                    <div class="tool-icon">🗜️</div>
                    <h3>Compress PDF</h3>
                    <p>Smart compression with text preservation</p>
                </div>
                <div class="tool-card" onclick="showTool('remove-pages')">
                    <div class="tool-icon">❌</div>
                    <h3>Remove Pages</h3>
                    <p>Delete specific pages from PDF</p>
                </div>
                <div class="tool-card" onclick="showTool('organize')">
                    <div class="tool-icon">📑</div>
                    <h3>Organize PDF</h3>
                    <p>Reorder pages in PDF</p>
                </div>
                <div class="tool-card" onclick="showTool('pdf-to-images')">
                    <div class="tool-icon">🖼️</div>
                    <h3>PDF to Images</h3>
                    <p>Convert PDF pages to images</p>
                </div>
                <div class="tool-card" onclick="showTool('protect')">
                    <div class="tool-icon">🔒</div>
                    <h3>Protect PDF</h3>
                    <p>Add password protection</p>
                </div>
                <div class="tool-card" onclick="showTool('unlock')">
                    <div class="tool-icon">🔓</div>
                    <h3>Unlock PDF</h3>
                    <p>Remove password protection</p>
                </div>
            </div>

            <div id="tool-interface">
                <div class="upload-area">
                    <h2 id="tool-title">Select a Tool</h2>
                    <p id="tool-description">Choose a tool from above to get started</p>

                    <div id="upload-section">
                        <div class="drop-zone" id="dropZone">
                            <i>📁</i>
                            <h3>Drop your files here</h3>
                            <p>or click to browse</p>
                            <input type="file" id="fileInput" multiple accept=".pdf,.jpg,.jpeg,.png" class="hidden">
                        </div>

                        <div id="file-info" class="file-info hidden"></div>
                        <div id="page-preview" class="page-preview hidden"></div>
                        <div id="quality-info" class="quality-info hidden">
                            <h4>🎯 Smart Compression Active</h4>
                            <p>Text is preserved as crisp vector data - only images are compressed</p>
                        </div>

                        <div id="file-list" class="file-list"></div>

                        <div id="options-panel" class="options-panel hidden"></div>

                        <div class="progress-bar hidden" id="progressBar">
                            <div class="progress" id="progress"></div>
                        </div>

                        <button id="process-btn" class="btn" disabled>Process Files</button>
                    </div>
                </div>
            </div>
        </div>

        <footer>
            <p>&copy; 2024 PDF Toolkit. All rights reserved.</p>
        </footer>

        <script>
            let currentTool = '';
            let uploadedFiles = [];
            let originalFileSize = 0;
            let totalPages = 0;

            function showTool(tool) {
                currentTool = tool;
                const toolConfigs = {
                    'merge': { title: 'Merge PDF Files', description: 'Combine multiple PDF files into one document', multiple: true, accept: '.pdf' },
                    'split': { title: 'Split PDF File', description: 'Split a PDF into multiple files or extract specific pages', multiple: false, accept: '.pdf' },
                    'compress': { title: 'Compress PDF', description: 'Smart compression that preserves text quality', multiple: false, accept: '.pdf' },
                    'remove-pages': { title: 'Remove PDF Pages', description: 'Delete specific pages from your PDF', multiple: false, accept: '.pdf' },
                    'organize': { title: 'Organize PDF Pages', description: 'Reorder pages in your PDF', multiple: false, accept: '.pdf' },
                    'pdf-to-images': { title: 'PDF to Images', description: 'Convert PDF pages to image files (PNG, JPG)', multiple: false, accept: '.pdf' },
                    'protect': { title: 'Protect PDF', description: 'Add password protection to your PDF', multiple: false, accept: '.pdf' },
                    'unlock': { title: 'Unlock PDF', description: 'Remove password protection from PDF', multiple: false, accept: '.pdf' }
                };

                const config = toolConfigs[tool];
                document.getElementById('tool-title').textContent = config.title;
                document.getElementById('tool-description').textContent = config.description;
                document.getElementById('fileInput').multiple = config.multiple;
                document.getElementById('fileInput').accept = config.accept;
                showOptions(tool);
                resetUploadArea();
            }

            function showOptions(tool) {
                const optionsPanel = document.getElementById('options-panel');
                const optionTemplates = {
                    'split': `
                        <div class="option-group">
                            <label for="pages">Pages to Split:</label>
                            <input type="text" id="pages" placeholder="e.g., 1-3, 5, 7-9 or leave empty for all pages">
                            <small>Separate pages/ranges with commas</small>
                        </div>
                    `,
                    'compress': `
                        <div class="feature-list">
                            <h4>✨ Smart Compression Features:</h4>
                            <ul>
                                <li>✅ Text preserved as crisp vector data</li>
                                <li>✅ Only images are compressed</li>
                                <li>✅ Professional quality like ilovepdf.com</li>
                                <li>✅ Perfect for documents with text</li>
                            </ul>
                        </div>
                        <div class="compression-method">
                            <div class="method-btn active" onclick="selectCompressionMethod('quality')">Quality Preset</div>
                            <div class="method-btn" onclick="selectCompressionMethod('size')">Exact Size</div>
                        </div>
                        <div id="quality-options">
                            <div class="option-group">
                                <label for="quality">Compression Level:</label>
                                <select id="quality">
                                    <option value="low">Low Compression (Best Quality)</option>
                                    <option value="medium" selected>Medium Compression (Recommended)</option>
                                    <option value="high">High Compression (Good Balance)</option>
                                    <option value="extreme">Extreme Compression (Smallest Size)</option>
                                </select>
                                <small>Higher compression = smaller file but lower image quality</small>
                            </div>
                        </div>
                        <div id="size-options" class="hidden">
                            <div class="option-group">
                                <label for="target-size">Target File Size (MB):</label>
                                <input type="number" id="target-size" min="0.1" max="50" step="0.1" value="2.0">
                                <small>Smart algorithm will find the best balance</small>
                            </div>
                            <div id="size-preview" class="size-preview hidden">
                                Current: <span id="current-size">0</span> MB → Target: <span id="target-preview">0</span> MB
                            </div>
                        </div>
                    `,
                    'remove-pages': `
                        <div class="option-group">
                            <label for="pages-to-remove">Pages to Remove:</label>
                            <input type="text" id="pages-to-remove" placeholder="e.g., 1, 3, 5-8">
                            <small>Separate pages/ranges with commas. Total pages: <span id="total-pages">0</span></small>
                        </div>
                        <div class="page-numbers">
                            <strong>Examples:</strong><br>
                            Remove single pages: 1, 3, 5<br>
                            Remove page ranges: 2-5, 8-10<br>
                            Mixed: 1, 3-5, 7
                        </div>
                    `,
                    'organize': `
                        <div class="option-group">
                            <label for="page-order">New Page Order:</label>
                            <input type="text" id="page-order" placeholder="e.g., 3, 1, 2 or 5-8, 1-4">
                            <small>Specify the new order of pages. Total pages: <span id="total-pages-organize">0</span></small>
                        </div>
                        <div class="page-numbers">
                            <strong>Examples:</strong><br>
                            Reverse order: 3, 2, 1<br>
                            Move pages: 5, 1, 2, 3, 4<br>
                            Use ranges: 5-8, 1-4
                        </div>
                    `,
                    'pdf-to-images': `
                        <div class="option-group">
                            <label for="format">Output Format:</label>
                            <select id="format">
                                <option value="png">PNG (Best Quality)</option>
                                <option value="jpg">JPG (Smaller Size)</option>
                            </select>
                        </div>
                    `,
                    'protect': `
                        <div class="option-group">
                            <label for="password">Password:</label>
                            <input type="password" id="password" placeholder="Enter password" required>
                        </div>
                    `,
                    'unlock': `
                        <div class="option-group">
                            <label for="unlock-password">PDF Password:</label>
                            <input type="password" id="unlock-password" placeholder="Enter PDF password" required>
                        </div>
                    `
                };

                if (optionTemplates[tool]) {
                    optionsPanel.innerHTML = optionTemplates[tool];
                    optionsPanel.classList.remove('hidden');
                    
                    // Show quality info for compression
                    if (tool === 'compress') {
                        document.getElementById('quality-info').classList.remove('hidden');
                    } else {
                        document.getElementById('quality-info').classList.add('hidden');
                    }
                } else {
                    optionsPanel.classList.add('hidden');
                    document.getElementById('quality-info').classList.add('hidden');
                }
            }

            function selectCompressionMethod(method) {
                document.querySelectorAll('.method-btn').forEach(btn => btn.classList.remove('active'));
                event.target.classList.add('active');
                
                if (method === 'quality') {
                    document.getElementById('quality-options').classList.remove('hidden');
                    document.getElementById('size-options').classList.add('hidden');
                } else {
                    document.getElementById('quality-options').classList.add('hidden');
                    document.getElementById('size-options').classList.remove('hidden');
                    updateSizePreview();
                }
            }

            function updateSizePreview() {
                if (originalFileSize > 0) {
                    const targetSize = document.getElementById('target-size').value;
                    document.getElementById('current-size').textContent = originalFileSize.toFixed(2);
                    document.getElementById('target-preview').textContent = targetSize;
                    document.getElementById('size-preview').classList.remove('hidden');
                }
            }

            function updatePagePreview(pages) {
                totalPages = pages;
                document.getElementById('total-pages').textContent = pages;
                document.getElementById('total-pages-organize').textContent = pages;
                
                const pagePreview = document.getElementById('page-preview');
                pagePreview.innerHTML = `Total pages in document: <strong>${pages}</strong>`;
                pagePreview.classList.remove('hidden');
            }

            const dropZone = document.getElementById('dropZone');
            const fileInput = document.getElementById('fileInput');
            const fileList = document.getElementById('file-list');
            const fileInfo = document.getElementById('file-info');
            const processBtn = document.getElementById('process-btn');

            dropZone.addEventListener('click', () => fileInput.click());
            dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('active'); });
            dropZone.addEventListener('dragleave', () => { dropZone.classList.remove('active'); });
            dropZone.addEventListener('drop', (e) => { e.preventDefault(); dropZone.classList.remove('active'); handleFiles(e.dataTransfer.files); });

            fileInput.addEventListener('change', (e) => { handleFiles(e.target.files); });

            async function handleFiles(files) {
                uploadedFiles = Array.from(files);
                updateFileList();
                updateProcessButton();
                
                // Show file info for compression
                if (currentTool === 'compress' && uploadedFiles.length > 0) {
                    originalFileSize = uploadedFiles[0].size / (1024 * 1024);
                    fileInfo.innerHTML = `Original file size: <strong>${originalFileSize.toFixed(2)} MB</strong>`;
                    fileInfo.classList.remove('hidden');
                    updateSizePreview();
                } else {
                    fileInfo.classList.add('hidden');
                }

                // Get page count for page-related tools
                if ((currentTool === 'remove-pages' || currentTool === 'organize' || currentTool === 'split') && uploadedFiles.length > 0) {
                    try {
                        const pageCount = await getPageCount(uploadedFiles[0]);
                        updatePagePreview(pageCount);
                    } catch (error) {
                        console.error('Error getting page count:', error);
                    }
                }
            }

            async function getPageCount(file) {
                return new Promise((resolve, reject) => {
                    const formData = new FormData();
                    formData.append('file', file);
                    
                    fetch('/api/get-page-count', {
                        method: 'POST',
                        body: formData
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.page_count) {
                            resolve(data.page_count);
                        } else {
                            reject(new Error('Could not get page count'));
                        }
                    })
                    .catch(reject);
                });
            }

            function updateFileList() {
                fileList.innerHTML = '';
                uploadedFiles.forEach((file, index) => {
                    const fileItem = document.createElement('div');
                    fileItem.className = 'file-item';
                    fileItem.innerHTML = `<span>${file.name} (${formatFileSize(file.size)})</span><button onclick="removeFile(${index})">❌</button>`;
                    fileList.appendChild(fileItem);
                });
            }

            function removeFile(index) {
                uploadedFiles.splice(index, 1);
                updateFileList();
                updateProcessButton();
                fileInfo.classList.add('hidden');
                document.getElementById('page-preview').classList.add('hidden');
            }

            function updateProcessButton() {
                const minFiles = currentTool === 'merge' ? 2 : 1;
                processBtn.disabled = uploadedFiles.length < minFiles;
            }

            function formatFileSize(bytes) {
                if (bytes === 0) return '0 Bytes';
                const k = 1024;
                const sizes = ['Bytes', 'KB', 'MB', 'GB'];
                const i = Math.floor(Math.log(bytes) / Math.log(k));
                return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
            }

            function resetUploadArea() {
                uploadedFiles = [];
                fileList.innerHTML = '';
                fileInfo.classList.add('hidden');
                document.getElementById('page-preview').classList.add('hidden');
                document.getElementById('quality-info').classList.add('hidden');
                processBtn.disabled = true;
                document.getElementById('progressBar').classList.add('hidden');
                document.getElementById('progress').style.width = '0%';
                originalFileSize = 0;
                totalPages = 0;
            }

            processBtn.addEventListener('click', processFiles);

            async function processFiles() {
                const progressBar = document.getElementById('progressBar');
                const progress = document.getElementById('progress');
                progressBar.classList.remove('hidden');
                processBtn.disabled = true;

                try {
                    progress.style.width = '30%';
                    const formData = new FormData();
                    
                    if (currentTool === 'merge') {
                        uploadedFiles.forEach(file => { formData.append('files', file); });
                    } else {
                        if (uploadedFiles.length > 0) {
                            formData.append('file', uploadedFiles[0]);
                        } else {
                            throw new Error('No files uploaded');
                        }
                    }

                    const options = getToolOptions();
                    for (const [key, value] of Object.entries(options)) {
                        if (value) formData.append(key, value);
                    }

                    progress.style.width = '60%';
                    const endpoint = getEndpoint();
                    console.log('Sending to:', endpoint);
                    
                    const response = await fetch(endpoint, { method: 'POST', body: formData });
                    progress.style.width = '90%';

                    if (!response.ok) {
                        const errorText = await response.text();
                        throw new Error(`Server error: ${response.status}`);
                    }

                    const blob = await response.blob();
                    if (blob.size === 0) throw new Error('Received empty file');

                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = getDownloadFilename();
                    document.body.appendChild(a);
                    a.click();
                    setTimeout(() => {
                        window.URL.revokeObjectURL(url);
                        document.body.removeChild(a);
                    }, 100);

                    progress.style.width = '100%';
                    setTimeout(() => {
                        resetUploadArea();
                        progressBar.classList.add('hidden');
                    }, 2000);
                    
                } catch (error) {
                    console.error('Error:', error);
                    alert('Error processing files: ' + error.message);
                    progressBar.classList.add('hidden');
                    processBtn.disabled = false;
                }
            }

            function getToolOptions() {
                const options = {};
                switch(currentTool) {
                    case 'split': 
                        options.pages = document.getElementById('pages')?.value || 'all'; 
                        break;
                    case 'compress': 
                        const method = document.querySelector('.method-btn.active').textContent.includes('Quality') ? 'quality' : 'size';
                        if (method === 'quality') {
                            options.method = 'quality';
                            options.quality = document.getElementById('quality')?.value || 'medium';
                        } else {
                            options.method = 'size';
                            options.target_size = document.getElementById('target-size')?.value || '2.0';
                        }
                        break;
                    case 'remove-pages':
                        options.pages_to_remove = document.getElementById('pages-to-remove')?.value;
                        if (!options.pages_to_remove) {
                            alert('Please specify which pages to remove');
                            throw new Error('Pages to remove not specified');
                        }
                        break;
                    case 'organize':
                        options.page_order = document.getElementById('page-order')?.value;
                        if (!options.page_order) {
                            alert('Please specify the new page order');
                            throw new Error('Page order not specified');
                        }
                        break;
                    case 'pdf-to-images': 
                        options.format = document.getElementById('format')?.value || 'png'; 
                        break;
                    case 'protect': 
                        options.password = document.getElementById('password')?.value; 
                        break;
                    case 'unlock':
                        options.password = document.getElementById('unlock-password')?.value;
                        break;
                }
                return options;
            }

            function getEndpoint() {
                const endpoints = {
                    'merge': '/api/merge',
                    'split': '/api/split', 
                    'compress': '/api/compress',
                    'remove-pages': '/api/remove-pages',
                    'organize': '/api/organize',
                    'pdf-to-images': '/api/pdf-to-images',
                    'protect': '/api/protect',
                    'unlock': '/api/unlock'
                };
                return endpoints[currentTool];
            }

            function getDownloadFilename() {
                const filenames = {
                    'merge': 'merged.pdf',
                    'split': 'split_pages.zip',
                    'compress': 'compressed.pdf', 
                    'remove-pages': 'removed_pages.pdf',
                    'organize': 'reorganized.pdf',
                    'pdf-to-images': 'converted_images.zip',
                    'protect': 'protected.pdf',
                    'unlock': 'unlocked.pdf'
                };
                return filenames[currentTool];
            }

            // Add event listeners
            document.addEventListener('input', function(e) {
                if (e.target.id === 'target-size') {
                    updateSizePreview();
                }
            });
        </script>
    </body>
    </html>
    '''

# ... (keep all the existing API routes the same as before, but update the compress route)

@app.route('/api/compress', methods=['POST'])
def api_compress():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No files uploaded'}), 400
        
        file = request.files['file']
        method = request.form.get('method', 'quality')
        
        if not file or not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type'}), 400
        
        filename = secure_filename(file.filename)
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(input_path)
        
        output_path = os.path.join(app.config['PROCESSED_FOLDER'], 'compressed.pdf')
        
        if method == 'quality':
            quality = request.form.get('quality', 'medium')
            PDFProcessor.smart_compress_pdf(input_path, output_path, quality)
            print(f"Used smart compression with quality: {quality}")
        else:
            target_size = float(request.form.get('target_size', '2.0'))
            achieved_size = PDFProcessor.compress_pdf_to_size_smart(input_path, output_path, target_size)
            print(f"Smart size compression - Target: {target_size} MB, Achieved: {achieved_size:.2f} MB")
        
        if os.path.exists(input_path):
            os.remove(input_path)
        
        return send_file(output_path, as_attachment=True, download_name='compressed.pdf')
    
    except Exception as e:
        print(f"Compression error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': f'Compression failed: {str(e)}'}), 500

# ... (keep all other API routes exactly the same as in the previous version)

if __name__ == '__main__':
    cleanup_folder(app.config['UPLOAD_FOLDER'])
    cleanup_folder(app.config['PROCESSED_FOLDER'])
    print("PDF Toolkit starting on http://localhost:5000")
    print("✨ NEW: Smart compression that preserves text quality!")
    print("✅ Text remains as crisp vector data")
    print("✅ Only images are compressed") 
    print("✅ Professional results like ilovepdf.com")
    app.run(debug=True, host='0.0.0.0', port=5000)