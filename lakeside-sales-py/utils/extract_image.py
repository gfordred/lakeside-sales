"""
Utility to extract the base64 site plan image from the original HTML
"""
import re
import base64
from pathlib import Path

def extract_site_plan_image():
    """Extract the embedded site plan image from index.html"""
    
    html_path = Path(__file__).parent.parent.parent / "lakeside-sales" / "index.html"
    
    # Try alternative path
    if not html_path.exists():
        html_path = Path(r"c:\Users\GordonFordred\OneDrive - PV01-MMAPP Ltd\Dev Repos\lakeside-sales\index.html")
    
    if not html_path.exists():
        print(f"HTML file not found at {html_path}")
        return
    
    print("Reading HTML file...")
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the base64 image data
    pattern = r'xlink:href="data:image/jpeg;base64,([^"]+)"'
    match = re.search(pattern, content)
    
    if not match:
        print("Could not find base64 image data")
        return
    
    print("Found base64 image data, decoding...")
    base64_data = match.group(1)
    
    # Decode base64
    image_data = base64.b64decode(base64_data)
    
    # Save to assets/images
    output_path = Path(__file__).parent.parent / "assets" / "images" / "site_plan.jpg"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Saving image to {output_path}...")
    with open(output_path, 'wb') as f:
        f.write(image_data)
    
    print(f"✓ Site plan image saved successfully ({len(image_data)} bytes)")
    print(f"  Location: {output_path}")

if __name__ == "__main__":
    extract_site_plan_image()
