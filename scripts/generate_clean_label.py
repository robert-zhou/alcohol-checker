from PIL import Image, ImageDraw, ImageFont
import os
import json

out_dir = os.path.join('sample_cases', 'clean_ocr_case')
os.makedirs(out_dir, exist_ok=True)

w, h = 1800, 2400
img = Image.new('RGB', (w, h), 'white')
d = ImageDraw.Draw(img)

text_blocks = [
    ('SUNRISE VODKA', 80, 140, 84),
    ('PREMIUM DISTILLED SPIRITS', 80, 250, 42),
    ('40% ALC./VOL.', 80, 420, 72),
    ('750 mL', 80, 520, 62),
    ('DISTILLED BY', 80, 660, 30),
    ('SUNRISE DISTILLERY', 80, 705, 46),
    ('SACRAMENTO, USA', 80, 770, 38),
    ('GOVERNMENT WARNING', 80, 980, 54),
    ('According to the Surgeon General, women should not drink', 80, 1075, 34),
    ('alcoholic beverages during pregnancy because of the risk of', 80, 1125, 34),
    ('birth defects.', 80, 1175, 34),
    ('Consumption of alcoholic beverages impairs your ability to', 80, 1245, 34),
    ('drive a car or operate machinery, and may cause health problems.', 80, 1295, 34),
]

for text, x, y, size in text_blocks:
    try:
        font = ImageFont.truetype('arial.ttf', size)
    except Exception:
        font = ImageFont.load_default()
    d.text((x, y), text, fill='black', font=font)

box = (100, 100, 1700, 1500)
d.rounded_rectangle(box, radius=20, outline='black', width=4)
for y in range(300, 1700, 140):
    d.line((100, y, 1700, y), fill='black', width=2)

img.save(os.path.join(out_dir, 'label.png'))

app_json = {
    'brand': 'Sunrise Vodka',
    'class': 'Vodka',
    'abv': '40%',
    'net_contents': '750 mL',
    'government_warning_present': True,
    'producer_name': 'Sunrise Distillery',
    'country_of_origin': 'USA'
}

with open(os.path.join(out_dir, 'application.json'), 'w', encoding='utf-8') as f:
    json.dump(app_json, f, indent=2)

print(f'Created {out_dir}')
print('label exists:', os.path.exists(os.path.join(out_dir, 'label.png')))
print('application exists:', os.path.exists(os.path.join(out_dir, 'application.json')))
