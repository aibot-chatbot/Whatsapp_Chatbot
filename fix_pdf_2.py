import os

file_path = r'app\database\knowledge_file_repository.py'
if os.path.exists(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    content = content.replace("def get_active_pdf_knowledge_file(", "def get_active_knowledge_file(")
    content = content.replace(".eq(\"file_type\", \"pdf\")", "")
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
        
html_path = r'frontend\flow_builder.html'
if os.path.exists(html_path):
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()
    
    html = html.replace('Extract PDF Info', 'Extract Document Info')
    html = html.replace('from PDF', 'from Document')
    html = html.replace('extractPdfInfo', 'extractDocInfo')
    
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
