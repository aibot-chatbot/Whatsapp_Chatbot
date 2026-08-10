import sys
sys.path.append('.')
from app.database.db import supabase
import json

response = supabase.table('flows').select('*').eq('id', 9).execute()
if response.data:
    print(json.dumps(response.data[0]['flow_data'], indent=2))
else:
    print('Not found')
