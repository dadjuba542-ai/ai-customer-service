import os
import uuid
from dataclasses import dataclass
from io import BytesIO
from typing import BinaryIO

from PIL import Image, ImageOps, UnidentifiedImageError


ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
DEFAULT_MAIN_MAX_SIZE = 1200
DEFAULT_THUMB_MAX_SIZE = 480
DEFAULT_MAIN_QUALITY = 80
DEFAULT_THUMB_QUALITY = 76


@dataclass
class ProcessedImage:
    url: str
    thumb_url: str
    width: int
    height: int
    thumb_width: int
    thumb_height: int
    size: int
    thumb_size: int


def is_allowed_image_filename(filename: str) -> bool:
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else 'jpg'
    return ext in ALLOWED_IMAGE_EXTENSIONS


def thumb_url_for(url: str) -> str:
    if not url or not url.startswith('/uploads/'):
        return url
    path, suffix = _split_url_suffix(url)
    root, ext = os.path.splitext(path)
    if root.endswith('_thumb'):
        return url
    return f'{root}_thumb{ext or ".jpg"}{suffix}'


def process_uploaded_image(
    file_obj: BinaryIO,
    upload_dir: str,
    *,
    filename_stem: str = '',
    main_max_size: int = DEFAULT_MAIN_MAX_SIZE,
    thumb_max_size: int = DEFAULT_THUMB_MAX_SIZE,
    main_quality: int = DEFAULT_MAIN_QUALITY,
    thumb_quality: int = DEFAULT_THUMB_QUALITY,
) -> ProcessedImage:
    image = _open_image(file_obj)
    stem = filename_stem or uuid.uuid4().hex
    filename = f'{stem}.jpg'
    thumb_filename = f'{stem}_thumb.jpg'

    main_image = _resize_image(image, main_max_size)
    thumb_image = _resize_image(image, thumb_max_size)

    os.makedirs(upload_dir, exist_ok=True)
    main_path = os.path.join(upload_dir, filename)
    thumb_path = os.path.join(upload_dir, thumb_filename)

    main_size = _save_jpeg(main_image, main_path, main_quality)
    thumb_size = _save_jpeg(thumb_image, thumb_path, thumb_quality)

    return ProcessedImage(
        url=f'/uploads/{filename}',
        thumb_url=f'/uploads/{thumb_filename}',
        width=main_image.size[0],
        height=main_image.size[1],
        thumb_width=thumb_image.size[0],
        thumb_height=thumb_image.size[1],
        size=main_size,
        thumb_size=thumb_size,
    )


def optimize_image_file(
    source_path: str,
    dest_path: str,
    thumb_path: str,
    *,
    main_max_size: int = DEFAULT_MAIN_MAX_SIZE,
    thumb_max_size: int = DEFAULT_THUMB_MAX_SIZE,
    main_quality: int = DEFAULT_MAIN_QUALITY,
    thumb_quality: int = DEFAULT_THUMB_QUALITY,
) -> ProcessedImage:
    with open(source_path, 'rb') as fh:
        image = _open_image(fh)
    main_image = _resize_image(image, main_max_size)
    thumb_image = _resize_image(image, thumb_max_size)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    main_size = _save_jpeg(main_image, dest_path, main_quality)
    thumb_size = _save_jpeg(thumb_image, thumb_path, thumb_quality)
    return ProcessedImage(
        url='',
        thumb_url='',
        width=main_image.size[0],
        height=main_image.size[1],
        thumb_width=thumb_image.size[0],
        thumb_height=thumb_image.size[1],
        size=main_size,
        thumb_size=thumb_size,
    )


def _open_image(file_obj: BinaryIO) -> Image.Image:
    try:
        image = Image.open(file_obj)
        image.load()
    except UnidentifiedImageError as exc:
        raise ValueError('无法识别图片文件') from exc
    image = ImageOps.exif_transpose(image)
    if getattr(image, 'is_animated', False):
        image.seek(0)
    if image.mode in ('RGBA', 'LA', 'P'):
        background = Image.new('RGB', image.size, (255, 255, 255))
        image = image.convert('RGBA')
        background.paste(image, mask=image.split()[-1])
        return background
    if image.mode != 'RGB':
        return image.convert('RGB')
    return image


def _resize_image(image: Image.Image, max_size: int) -> Image.Image:
    output = image.copy()
    if max(output.size) > max_size:
        output.thumbnail((max_size, max_size), Image.LANCZOS)
    return output


def _save_jpeg(image: Image.Image, path: str, quality: int) -> int:
    buffer = BytesIO()
    image.save(buffer, format='JPEG', quality=quality, optimize=True, progressive=True)
    data = buffer.getvalue()
    with open(path, 'wb') as fh:
        fh.write(data)
    return len(data)


def _split_url_suffix(url: str) -> tuple[str, str]:
    for marker in ('?', '#'):
        if marker in url:
            base, rest = url.split(marker, 1)
            return base, marker + rest
    return url, ''
