#!/usr/bin/env python3
"""
Extract text from PDF and save to GraphRAG input directory
"""

import PyPDF2
import os
import sys

def extract_pdf_text(pdf_path, output_path):
    try:
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            text = ''
            
            print(f"Processing {len(pdf_reader.pages)} pages...")
            
            for i, page in enumerate(pdf_reader.pages):
                page_text = page.extract_text()
                text += page_text + '\n\n'
                print(f"Processed page {i+1}/{len(pdf_reader.pages)}")
            
            # Clean up the text a bit
            text = text.strip()
            
            print(f"\nExtracted {len(text)} characters total")
            
            # Save to output file
            with open(output_path, 'w', encoding='utf-8') as outfile:
                outfile.write(text)
            
            print(f"Saved to: {output_path}")
            
            # Show first 1000 characters as preview
            print("\nFirst 1000 characters:")
            print("-" * 50)
            print(text[:1000])
            print("-" * 50)
            
            return text
            
    except Exception as e:
        print(f"Error extracting PDF: {e}")
        return None

if __name__ == "__main__":
    pdf_file = "/Users/heymitra/Downloads/docs/real2b-english.pdf"
    output_file = "input/real2b_english.txt"
    
    # Remove old legal case file if it exists
    old_files = ["input/sample.txt", "input/legal_case.txt"]
    for old_file in old_files:
        if os.path.exists(old_file):
            os.remove(old_file)
            print(f"Removed old file: {old_file}")
    
    # Extract the PDF
    text = extract_pdf_text(pdf_file, output_file)
    
    if text:
        print(f"\nSuccessfully extracted text from PDF!")
        print(f"Output saved to: {output_file}")
    else:
        print("Failed to extract text from PDF")