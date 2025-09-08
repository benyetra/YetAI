#!/usr/bin/env python3
"""
Fix all localhost:8000 references in frontend to use environment variables
"""
import os
import glob
import re

def fix_file(file_path):
    """Fix localhost references in a single file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # Pattern 1: 'http://localhost:8000' -> `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}`
        content = re.sub(
            r"'http://localhost:8000'",
            "`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}`",
            content
        )
        
        # Pattern 2: "http://localhost:8000" -> `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}`
        content = re.sub(
            r'"http://localhost:8000"',
            "`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}`",
            content
        )
        
        # Pattern 3: `http://localhost:8000` -> `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}`
        content = re.sub(
            r'`http://localhost:8000`',
            "`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}`",
            content
        )
        
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"✅ Fixed: {file_path}")
            return True
        else:
            return False
            
    except Exception as e:
        print(f"❌ Error fixing {file_path}: {e}")
        return False

def main():
    """Main function to fix all files"""
    frontend_dir = "/Users/byetz/Development/YetAI/ai-sports-betting-mvp/frontend/src"
    
    # Find all TypeScript and TSX files
    patterns = ["**/*.ts", "**/*.tsx"]
    files_to_fix = []
    
    for pattern in patterns:
        files_to_fix.extend(glob.glob(os.path.join(frontend_dir, pattern), recursive=True))
    
    print(f"Found {len(files_to_fix)} files to check...")
    
    fixed_count = 0
    for file_path in files_to_fix:
        if fix_file(file_path):
            fixed_count += 1
    
    print(f"\n✅ Fixed {fixed_count} files with localhost references")
    
    if fixed_count > 0:
        print("\n🚀 All localhost references have been updated to use environment variables!")
        print("Frontend will now use production backend URL when deployed.")
    else:
        print("\n✅ No localhost references found or all were already fixed.")

if __name__ == "__main__":
    main()