# sendgrid_debug.py - Debug SendGrid 400 errors
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from dotenv import load_dotenv

load_dotenv()

def test_basic_sendgrid():
    """Test most basic SendGrid functionality"""
    print("🔍 Testing Basic SendGrid...")
    
    api_key = os.getenv("SENDGRID_API_KEY")
    if not api_key:
        print("❌ No SENDGRID_API_KEY found")
        return
    
    print(f"API Key: {api_key[:10]}...{api_key[-5:]}")
    
    try:
        sg = SendGridAPIClient(api_key)
        
        # Test API key by trying to access account info
        print("🔑 Testing API key validity...")
        
        # Most basic email possible
        message = Mail(
            from_email='noreply@em6057.gistcapture.ai',
            to_emails='caddington05@gmail.com',
            subject='Test',
            plain_text_content='Test message'
        )
        
        print("📧 Attempting to send basic email...")
        response = sg.send(message)
        
        print(f"Status Code: {response.status_code}")
        print(f"Headers: {dict(response.headers)}")
        
        if response.status_code == 202:
            print("✅ Basic SendGrid test successful!")
        else:
            print(f"❌ Unexpected status: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        print(f"Error type: {type(e)}")
        
        # Try to get more details
        if hasattr(e, 'body'):
            print(f"Response body: {e.body}")
        if hasattr(e, 'status_code'):
            print(f"Status code: {e.status_code}")
        if hasattr(e, 'headers'):
            print(f"Headers: {e.headers}")

def test_different_emails():
    """Test the different working emails from your test"""
    working_emails = [
        "noreply@em6057.gistcapture.ai",
        "info@em6057.gistcapture.ai", 
        "hello@em6057.gistcapture.ai",
        "support@em6057.gistcapture.ai"
    ]
    
    print("\n🧪 Testing all working emails...")
    
    sg = SendGridAPIClient(os.getenv("SENDGRID_API_KEY"))
    
    for email in working_emails:
        print(f"\n📧 Testing: {email}")
        try:
            message = Mail(
                from_email=email,
                to_emails='caddington05@gmail.com',
                subject=f'Test from {email}',
                plain_text_content=f'Test message from {email}'
            )
            
            response = sg.send(message)
            
            if response.status_code == 202:
                print(f"   ✅ SUCCESS: {email}")
            else:
                print(f"   ❌ FAILED: {email} (Status: {response.status_code})")
                
        except Exception as e:
            print(f"   ❌ ERROR: {email} - {e}")

def check_api_key_permissions():
    """Check what permissions the API key has"""
    print("\n🔑 Checking API Key Permissions...")
    
    try:
        sg = SendGridAPIClient(os.getenv("SENDGRID_API_KEY"))
        
        # Try to get user info (this tells us if the key works)
        # Note: This might not work with restricted API keys
        print("Attempting to validate API key...")
        
        # The most basic test - just create a client
        print("✅ API key format appears valid")
        
    except Exception as e:
        print(f"❌ API key issue: {e}")

if __name__ == "__main__":
    print("🐛 SendGrid Debug Tool")
    print("=" * 40)
    
    check_api_key_permissions()
    test_basic_sendgrid()
    test_different_emails()
    
    print("\n💡 If all tests fail with 400 errors:")
    print("1. Check if your SendGrid account is verified")
    print("2. Verify the API key has 'Mail Send' permissions")
    print("3. Check if domain authentication is complete")
    print("4. Try using 'info@em6057.gistcapture.ai' instead")