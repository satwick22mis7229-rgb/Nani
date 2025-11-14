from twilio.rest import Client
import os
from dotenv import load_dotenv

load_dotenv()

sid = os.getenv("TWILIO_ACCOUNT_SID")
token = os.getenv("TWILIO_AUTH_TOKEN")
verify_sid = os.getenv("TWILIO_VERIFY_SERVICE_SID")
print("Loaded Verify SID:", TWILIO_VERIFY_SERVICE_SID)

client = Client(sid, token)

try:
    service = client.verify.v2.services(verify_sid).fetch()
    print("SUCCESS: Verify Service Found ->", service.sid)
except Exception as e:
    print("ERROR:", e)
