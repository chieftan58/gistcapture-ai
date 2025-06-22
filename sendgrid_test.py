import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

def test_current_verified_setup():
    """Test with your current verified domains"""
    api_key = os.getenv("SENDGRID_API_KEY")
    sg = SendGridAPIClient(api_key)
    
    # Test only professional gistcapture.ai subdomain emails
    test_from_emails = [
        "noreply@em6057.gistcapture.ai",  # Using verified subdomain
        "info@em6057.gistcapture.ai",     # Using verified subdomain
        "hello@em6057.gistcapture.ai",    # Using verified subdomain
        "support@em6057.gistcapture.ai",  # Using verified subdomain
    ]
    
    print("🧪 Testing your current verified SendGrid setup...")
    print("=" * 60)
    
    working_emails = []
    
    for from_email in test_from_emails:
        print(f"\n📧 Testing: {from_email} → caddington05@gmail.com")
        
        try:
            message = Mail(
                from_email=from_email,
                to_emails="caddington05@gmail.com",
                subject=f"✅ Test from {from_email} - {datetime.now().strftime('%H:%M:%S')}",
                html_content=f"""
                <html>
                <body style="font-family: Arial, sans-serif; padding: 20px;">
                    <h2 style="color: #28a745;">✅ SendGrid Test Success!</h2>
                    <p><strong>From:</strong> {from_email}</p>
                    <p><strong>To:</strong> caddington05@gmail.com</p>
                    <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                    <p><strong>Status:</strong> This email address is working with your current SendGrid setup!</p>
                    
                    <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
                        <h3>Domain Status from Your Dashboard:</h3>
                        <ul>
                            <li>✅ em6057.gistcapture.ai - VERIFIED</li>
                            <li>✅ click.gistcapture.ai - VERIFIED</li>
                            <li>✅ caddington05@gmail.com - VERIFIED</li>
                            <li>❌ gistcapture.ai root domain - NEEDS SETUP</li>
                        </ul>
                    </div>
                    
                    <p style="background-color: #e9ecef; padding: 10px; border-radius: 5px;">
                        <strong>Recommendation:</strong> Use this working email address in your GistCapture AI script!
                    </p>
                </body>
                </html>
                """,
                plain_text_content=f"Test email from {from_email} at {datetime.now()}"
            )
            
            response = sg.send(message)
            
            if response.status_code == 202:
                print(f"   ✅ SUCCESS! {from_email} is working")
                working_emails.append(from_email)
                message_id = response.headers.get('X-Message-Id', 'N/A')
                print(f"   📋 Message ID: {message_id}")
            else:
                print(f"   ❌ Failed with status: {response.status_code}")
                
        except Exception as e:
            print(f"   ❌ Error: {e}")
    
    print("\n" + "="*60)
    print("📊 RESULTS:")
    
    if working_emails:
        print(f"✅ {len(working_emails)} working email address(es):")
        for email in working_emails:
            print(f"   • {email}")
        
        print(f"\n🎯 RECOMMENDED: Use {working_emails[0]} in your main script")
        print("📧 Check caddington05@gmail.com for test emails!")
        
        # Show how to update main script
        print(f"\n📝 UPDATE YOUR MAIN SCRIPT:")
        print(f"Change this line in main.py:")
        print(f'EMAIL_FROM = "{working_emails[0]}"')
        
    else:
        print("❌ No working email addresses found")
        print("💡 You may need to set up the root domain gistcapture.ai")
    
    return working_emails

def setup_root_domain_instructions():
    """Show how to set up root domain gistcapture.ai"""
    print("\n" + "="*70)
    print("🔧 TO SET UP ROOT DOMAIN gistcapture.ai (OPTIONAL):")
    print("="*70)
    print("1. In your SendGrid dashboard, click 'Authenticate Your Domain'")
    print("2. Enter: gistcapture.ai (NOT em6057.gistcapture.ai)")
    print("3. Follow the DNS setup instructions")
    print("4. This will let you use: info@gistcapture.ai, noreply@gistcapture.ai, etc.")
    print("\n💡 BUT you can use your current working emails immediately!")

if __name__ == "__main__":
    print("🚀 Quick Fix Test - Using Your Current Verified Setup")
    
    working_emails = test_current_verified_setup()
    
    if working_emails:
        print(f"\n🎉 QUICK FIX READY!")
        print(f"✅ Use: {working_emails[0]}")
        print("✅ Your GistCapture AI can start working immediately!")
    else:
        setup_root_domain_instructions()