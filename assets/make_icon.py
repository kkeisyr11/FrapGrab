import os
from PIL import Image, ImageDraw

def generate_app_icon():
    assets_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    os.makedirs(assets_dir, exist_ok=True)
    icon_path = os.path.join(assets_dir, "icon.ico")
    png_path = os.path.join(assets_dir, "icon.png")
    
    # Create 256x256 icon
    size = (256, 256)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Outer dark hexagon / circle background
    draw.ellipse((8, 8, 248, 248), fill="#141824", outline="#00e5ff", width=6)
    
    # Inner gaming tactical ring
    draw.ellipse((35, 35, 221, 221), outline="#202b42", width=4)
    
    # Crosshair lines (Tactical shooter theme)
    draw.line((128, 18, 128, 65), fill="#00e5ff", width=5)
    draw.line((128, 191, 128, 238), fill="#00e5ff", width=5)
    draw.line((18, 128, 65, 128), fill="#00e5ff", width=5)
    draw.line((191, 128, 238, 128), fill="#00e5ff", width=5)
    
    # Red Record dot / camera aperture in center
    draw.ellipse((85, 85, 171, 171), fill="#e53e3e", outline="#ff6b6b", width=5)
    
    # White play triangle inside red circle
    draw.polygon([(115, 105), (115, 151), (155, 128)], fill="#ffffff")
    
    img.save(png_path, "PNG")
    img.save(icon_path, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print(f"Icon generated at {icon_path}")
    return icon_path

if __name__ == "__main__":
    generate_app_icon()
