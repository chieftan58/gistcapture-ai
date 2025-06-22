# test_email.py - Quick email test
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from dotenv import load_dotenv

load_dotenv()

def test_email():
    SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
    EMAIL_FROM = os.getenv("EMAIL_FROM")
    EMAIL_TO = os.getenv("EMAIL_TO")
    
    print(f"Testing email from: {EMAIL_FROM}")
    print(f"Testing email to: {EMAIL_TO}")
    print(f"SendGrid API Key exists: {'Yes' if SENDGRID_API_KEY else 'No'}")
    
    try:
        message = Mail(
            from_email=EMAIL_FROM,
            to_emails=EMAIL_TO,
            subject="GistCapture AI - Test Email",
            plain_text_content="This is a test email from your GistCapture AI system. If you receive this, email is working correctly!",
            html_content="<p>This is a test email from your <strong>GistCapture AI</strong> system.</p><p>If you receive this, email is working correctly!</p>"
        )
        
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        
        print(f"✅ Test email sent!")
        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        
        if response.status_code == 202:
            print("✅ Email accepted by SendGrid. Check your inbox (and spam folder)!")
        else:
            print(f"⚠️ Unexpected status code: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Email test failed: {e}")
        print("\nTroubleshooting tips:")
        print("1. Verify your SENDGRID_API_KEY is correct")
        print("2. Verify your EMAIL_FROM is verified in SendGrid")
        print("3. Check SendGrid dashboard for any issues")

if __name__ == "__main__":
    test_email()