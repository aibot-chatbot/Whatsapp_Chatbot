import logging
logging.basicConfig(level=logging.INFO)
from dotenv import load_dotenv
load_dotenv()
from app.services.ai_router import generate_welcome_menu_suggestions
import app.services.ai_router as air

orig = air.generate_system_response
def mock_req(*args, **kwargs):
    res = orig(*args, **kwargs)
    print('RAW_RESPONSE:', repr(res))
    return res

air.generate_system_response = mock_req
print('FINAL:', generate_welcome_menu_suggestions(46, 46))
