# fix_all_errors.py - Run this to fix all syntax errors in main.py

def fix_main_py():
    print("🔧 Fixing all syntax errors in main.py...")
    
    try:
        # Read the current file
        with open('main.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Fix the specific line 1824 error
        # This line should just be the closing of the file
        if "main(), r'<h3 style=" in content:
            print("✅ Found corrupted main() line, fixing...")
            # Replace the corrupted line
            content = content.replace(
                "main(), r'<h3 style=\"margin: 25px 0 15px 0; font-size: 20px; color: #333;\">\\1</h3>', html, flags=re.MULTILINE)",
                "    main()"
            )
        
        # Also ensure the _convert_markdown_to_html method is correct
        # Find the method and replace it entirely
        method_start = content.find("def _convert_markdown_to_html(self, markdown: str) -> str:")
        if method_start != -1:
            # Find the end of the method (next def or class)
            method_end = content.find("\n    def ", method_start + 1)
            if method_end == -1:
                method_end = content.find("\nclass ", method_start + 1)
            if method_end == -1:
                method_end = content.find("\n\n# ", method_start + 1)
            
            if method_end != -1:
                print("✅ Replacing _convert_markdown_to_html method with correct version...")
                
                correct_method = '''    def _convert_markdown_to_html(self, markdown: str) -> str:
        """Convert markdown to HTML"""
        html = markdown
        
        # Headers
        html = re.sub(r'^### (.*?)$', r'<h3 style="margin: 25px 0 15px 0; font-size: 20px; color: #333;">\\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.*?)$', r'<h2 style="margin: 30px 0 20px 0; font-size: 24px; color: #000;">\\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^# (.*?)$', r'<h1 style="margin: 40px 0 30px 0; font-size: 32px; color: #000;">\\1</h1>', html, flags=re.MULTILINE)
        
        # Bold and italic
        html = re.sub(r'\\*\\*([^*]+)\\*\\*', r'<strong>\\1</strong>', html)
        html = re.sub(r'\\*([^*]+)\\*', r'<em>\\1</em>', html)
        
        # Links
        html = re.sub(r'\\[([^\\]]+)\\]\\(([^\\)]+)\\)', r'<a href="\\2" style="color: #0066CC;">\\1</a>', html)
        
        # Paragraphs
        paragraphs = html.split('\\n\\n')
        html = ''.join([f'<p style="margin: 0 0 20px 0;">{p}</p>' for p in paragraphs if p.strip()])
        
        return html
'''
                # Replace the method
                content = content[:method_start] + correct_method + content[method_end:]
        
        # Ensure the file ends properly
        if not content.strip().endswith('main()'):
            print("✅ Fixing file ending...")
            # Find where main() should be
            if "__name__ == \"__main__\":" in content:
                # Make sure it ends with proper main() call
                parts = content.split("if __name__ == \"__main__\":")
                if len(parts) == 2:
                    parts[1] = '\n    main()\n'
                    content = "if __name__ == \"__main__\":".join(parts)
        
        # Save the fixed file
        with open('main_fixed.py', 'w', encoding='utf-8') as f:
            f.write(content)
        
        print("\n✅ Fixed file saved as 'main_fixed.py'")
        print("📋 Please review the changes, then rename it to 'main.py'")
        print("\nTo use the fixed file:")
        print("1. Review main_fixed.py")
        print("2. If it looks good: ")
        print("   - Backup your current main.py: rename main.py main_backup.py")
        print("   - Rename main_fixed.py to main.py")
        print("3. Run: python main.py")
            
    except FileNotFoundError:
        print("❌ main.py not found in current directory!")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    fix_main_py()