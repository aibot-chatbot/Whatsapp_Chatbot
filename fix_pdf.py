import os

files_to_update = [
    r'app\routes\knowledge_routes.py',
    r'app\services\knowledge_service.py'
]

for file_path in files_to_update:
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        content = content.replace('get_active_pdf_knowledge_file', 'get_active_knowledge_file')
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated {file_path}")
    else:
        print(f"File not found: {file_path}")
