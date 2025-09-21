#!/usr/bin/env python3
"""
Fix Logger Usage in main.py
Replaces all incorrect logger.app.xxx() and logger.xxx.xxx() calls with standard logger.xxx()
"""
import re

def fix_logger_usage():
    """Fix all logger usage in main.py"""
    
    file_path = "/home/cyberdude/Documents/Projects/voice/main.py"
    
    print("🔧 Fixing logger usage in main.py...")
    
    # Read the file
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Track replacements
    replacements = 0
    original_content = content
    
    # Fix logger.app.xxx() -> logger.xxx()
    patterns = [
        (r'logger\.app\.debug\(', 'logger.debug('),
        (r'logger\.app\.info\(', 'logger.info('),
        (r'logger\.app\.warning\(', 'logger.warning('),
        (r'logger\.app\.error\(', 'logger.error('),
        (r'logger\.app\.critical\(', 'logger.critical('),
        (r'logger\.app\.exception\(', 'logger.exception('),
        
        # Keep specialized loggers for their specific purposes
        # (We'll keep logger.database.xxx, logger.tts.xxx, etc. as they are)
    ]
    
    for pattern, replacement in patterns:
        content, count = re.subn(pattern, replacement, content)
        replacements += count
        if count > 0:
            print(f"  ✅ Replaced {count} instances of {pattern}")
    
    if replacements > 0:
        # Write back to file
        with open(file_path, 'w') as f:
            f.write(content)
        
        print(f"\n🎉 Fixed {replacements} logger usage issues in main.py")
        print("✅ All logger.app.xxx() calls converted to logger.xxx()")
    else:
        print("✅ No logger.app issues found to fix")
    
    return replacements

if __name__ == "__main__":
    fix_logger_usage()
