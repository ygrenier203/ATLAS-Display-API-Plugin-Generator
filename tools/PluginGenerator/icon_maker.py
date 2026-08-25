import binascii
import struct
import zlib


ICON_SYMBOLS = (
    'graph', 'pulse', 'gauge', 'grid',
    'checkered-flag', 'steering-wheel', 'tyre', 'stopwatch', 'race-car',
    'helmet', 'trophy', 'pit-lane', 'track-map', 'brake-disc',
    'suspension', 'engine', 'fuel', 'gear', 'lap-delta',
)


def parse_hex_color(value):
    value = str(value or '').strip().lstrip('#')
    if len(value) == 6:
        value += 'FF'
    if len(value) != 8:
        raise ValueError('Color must use #RRGGBB or #RRGGBBAA.')
    try:
        return tuple(int(value[index:index + 2], 16) for index in range(0, 8, 2))
    except ValueError as error:
        raise ValueError('Color must contain hexadecimal digits.') from error


def _set_pixel(pixels, size, x, y, color):
    if 0 <= x < size and 0 <= y < size:
        offset = ((y * size) + x) * 4
        pixels[offset:offset + 4] = bytes(color)


def _line(pixels, size, start, end, color, thickness):
    x0, y0 = start
    x1, y1 = end
    dx = abs(x1 - x0)
    sx = 1 if x0 < x1 else -1
    dy = -abs(y1 - y0)
    sy = 1 if y0 < y1 else -1
    error = dx + dy
    radius = max(0, thickness // 2)
    while True:
        for oy in range(-radius, radius + 1):
            for ox in range(-radius, radius + 1):
                _set_pixel(pixels, size, x0 + ox, y0 + oy, color)
        if x0 == x1 and y0 == y1:
            break
        twice_error = 2 * error
        if twice_error >= dy:
            error += dy
            x0 += sx
        if twice_error <= dx:
            error += dx
            y0 += sy


def _circle(pixels, size, center, radius, color, filled=False, thickness=1):
    cx, cy = center
    outer = radius * radius
    inner_radius = max(0, radius - thickness)
    inner = inner_radius * inner_radius
    for y in range(cy - radius, cy + radius + 1):
        for x in range(cx - radius, cx + radius + 1):
            distance = ((x - cx) ** 2) + ((y - cy) ** 2)
            if distance <= outer and (filled or distance >= inner):
                _set_pixel(pixels, size, x, y, color)


def _rectangle(pixels, size, left, top, right, bottom, color):
    for y in range(top, bottom):
        for x in range(left, right):
            _set_pixel(pixels, size, x, y, color)


def render_icon_pixels(size, background, foreground, symbol):
    if not isinstance(size, int) or size < 16 or size > 1024:
        raise ValueError('Icon size must be between 16 and 1024 pixels.')
    if symbol not in ICON_SYMBOLS:
        raise ValueError(f'Unknown icon symbol: {symbol}')
    background = parse_hex_color(background) if isinstance(background, str) else tuple(background)
    foreground = parse_hex_color(foreground) if isinstance(foreground, str) else tuple(foreground)
    pixels = bytearray(bytes(background) * (size * size))
    margin = size // 5
    thickness = max(2, size // 24)
    middle = size // 2

    if symbol == 'graph':
        points = [
            (margin, size - margin),
            (size * 2 // 5, size * 3 // 5),
            (size * 3 // 5, size * 2 // 3),
            (size - margin, margin),
        ]
        for start, end in zip(points, points[1:]):
            _line(pixels, size, start, end, foreground, thickness)
        for point in points:
            _circle(pixels, size, point, thickness, foreground, filled=True)
    elif symbol == 'pulse':
        points = [
            (margin, middle), (size * 3 // 8, middle),
            (size * 7 // 16, margin), (size * 9 // 16, size - margin),
            (size * 5 // 8, middle), (size - margin, middle),
        ]
        for start, end in zip(points, points[1:]):
            _line(pixels, size, start, end, foreground, thickness)
    elif symbol == 'gauge':
        radius = (size // 2) - margin
        _circle(pixels, size, (middle, middle), radius, foreground, thickness=thickness)
        _line(pixels, size, (middle, middle), (size * 3 // 4, size // 3), foreground, thickness)
        _circle(pixels, size, (middle, middle), thickness * 2, foreground, filled=True)
    elif symbol == 'grid':
        cell = (size - (margin * 2)) // 2
        gap = max(2, thickness)
        for row in range(2):
            for column in range(2):
                left = margin + (column * cell) + gap
                top = margin + (row * cell) + gap
                right = margin + ((column + 1) * cell) - gap
                bottom = margin + ((row + 1) * cell) - gap
                _rectangle(pixels, size, left, top, right, bottom, foreground)
    elif symbol == 'checkered-flag':
        pole_x = margin
        _line(pixels, size, (pole_x, margin), (pole_x, size - margin), foreground, thickness)
        flag_width = size - (margin * 2)
        cell = max(2, flag_width // 4)
        for row in range(3):
            for column in range(4):
                if (row + column) % 2 == 0:
                    left = pole_x + thickness + (column * cell)
                    top = margin + (row * cell)
                    _rectangle(pixels, size, left, top, left + cell, top + cell, foreground)
    elif symbol == 'steering-wheel':
        radius = (size // 2) - margin
        _circle(pixels, size, (middle, middle), radius, foreground, thickness=thickness)
        _circle(pixels, size, (middle, middle), max(1, thickness), foreground, filled=True)
        for end in ((middle, margin), (margin, size - margin), (size - margin, size - margin)):
            _line(pixels, size, (middle, middle), end, foreground, thickness)
    elif symbol == 'tyre':
        radius = (size // 2) - margin
        _circle(pixels, size, (middle, middle), radius, foreground, thickness=max(thickness, size // 8))
        _circle(pixels, size, (middle, middle), max(1, radius // 3), foreground, thickness=1)
    elif symbol == 'stopwatch':
        radius = (size // 2) - margin
        center = (middle, middle + max(1, size // 16))
        _circle(pixels, size, center, radius, foreground, thickness=thickness)
        _rectangle(pixels, size, middle - thickness, margin - thickness, middle + thickness + 1, margin + thickness, foreground)
        _line(pixels, size, center, (middle, center[1] - (radius // 2)), foreground, thickness)
        _line(pixels, size, center, (middle + (radius // 2), center[1]), foreground, thickness)
    elif symbol == 'race-car':
        body_left = margin
        body_right = size - margin
        body_top = size * 2 // 5
        body_bottom = size * 3 // 4
        _rectangle(pixels, size, body_left, body_top, body_right, body_bottom, foreground)
        _rectangle(pixels, size, size * 2 // 5, margin, size * 3 // 5, body_top, foreground)
        wheel_radius = max(1, size // 10)
        _circle(pixels, size, (body_left, body_bottom), wheel_radius, foreground, filled=True)
        _circle(pixels, size, (body_right - 1, body_bottom), wheel_radius, foreground, filled=True)
    elif symbol == 'helmet':
        radius = (size // 2) - margin
        _circle(pixels, size, (middle, middle), radius, foreground, filled=True)
        _rectangle(pixels, size, middle, middle - thickness, size - margin, middle + thickness + 1, background)
        _rectangle(pixels, size, middle, middle + thickness, size - margin, size - margin, background)
    elif symbol == 'trophy':
        _rectangle(pixels, size, middle - thickness, middle, middle + thickness + 1, size - margin, foreground)
        _rectangle(pixels, size, size // 3, size - margin, size * 2 // 3, size - margin + thickness, foreground)
        _rectangle(pixels, size, size // 3, margin, size * 2 // 3, middle, foreground)
        _circle(pixels, size, (size // 3, size // 3), size // 6, foreground, thickness=thickness)
        _circle(pixels, size, (size * 2 // 3, size // 3), size // 6, foreground, thickness=thickness)
    elif symbol == 'pit-lane':
        _line(pixels, size, (margin, margin), (margin, size - margin), foreground, thickness)
        _line(pixels, size, (size - margin, margin), (size - margin, size - margin), foreground, thickness)
        for y in range(margin, size - margin, max(2, size // 5)):
            _line(pixels, size, (middle, y), (middle, min(size - margin, y + thickness)), foreground, thickness)
    elif symbol == 'track-map':
        points = ((margin, middle), (size // 3, margin), (size - margin, size // 3),
                  (size * 2 // 3, size - margin), (size // 3, size * 2 // 3), (margin, middle))
        for start, end in zip(points, points[1:]):
            _line(pixels, size, start, end, foreground, thickness)
    elif symbol == 'brake-disc':
        radius = (size // 2) - margin
        _circle(pixels, size, (middle, middle), radius, foreground, thickness=thickness)
        _circle(pixels, size, (middle, middle), max(1, radius // 3), foreground, filled=True)
        for point in ((middle, margin), (middle, size - margin), (margin, middle), (size - margin, middle)):
            _circle(pixels, size, point, max(1, thickness // 2), foreground, filled=True)
    elif symbol == 'suspension':
        step = max(2, (size - margin * 2) // 6)
        points = [(margin + index * step, margin if index % 2 == 0 else size - margin) for index in range(7)]
        for start, end in zip(points, points[1:]):
            _line(pixels, size, start, end, foreground, thickness)
    elif symbol == 'engine':
        _rectangle(pixels, size, margin, size // 3, size - margin, size * 2 // 3, foreground)
        _rectangle(pixels, size, size // 3, margin, size * 2 // 3, size // 3, foreground)
        _line(pixels, size, (margin, middle), (margin // 2, middle), foreground, thickness)
        _line(pixels, size, (size - margin, middle), (size - margin // 2, middle), foreground, thickness)
    elif symbol == 'fuel':
        _rectangle(pixels, size, margin, margin, size * 2 // 3, size - margin, foreground)
        _rectangle(pixels, size, margin + thickness, margin + thickness, size * 2 // 3 - thickness, middle, background)
        _line(pixels, size, (size * 2 // 3, size // 3), (size - margin, middle), foreground, thickness)
        _line(pixels, size, (size - margin, middle), (size - margin, size - margin), foreground, thickness)
    elif symbol == 'gear':
        radius = (size // 2) - margin
        _circle(pixels, size, (middle, middle), radius, foreground, thickness=max(thickness, size // 8))
        for start, end in (((middle, margin), (middle, margin // 2)), ((middle, size - margin), (middle, size - margin // 2)),
                           ((margin, middle), (margin // 2, middle)), ((size - margin, middle), (size - margin // 2, middle))):
            _line(pixels, size, start, end, foreground, thickness)
    else:  # lap-delta
        _line(pixels, size, (margin, middle), (size - margin, middle), foreground, thickness)
        _line(pixels, size, (middle, margin), (middle, size - margin), foreground, thickness)
        _line(pixels, size, (margin, size - margin), (size - margin, margin), foreground, thickness)
    return bytes(pixels)


def _png_chunk(chunk_type, data):
    body = chunk_type + data
    return struct.pack('>I', len(data)) + body + struct.pack('>I', binascii.crc32(body) & 0xFFFFFFFF)


def create_icon_png(path, size=16, background='#20242B', foreground='#27B5E8', symbol='graph'):
    pixels = render_icon_pixels(size, background, foreground, symbol)
    rows = b''.join(b'\x00' + pixels[offset:offset + (size * 4)] for offset in range(0, len(pixels), size * 4))
    png = (
        b'\x89PNG\r\n\x1a\n'
        + _png_chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
        + _png_chunk(b'IDAT', zlib.compress(rows, 9))
        + _png_chunk(b'IEND', b'')
    )
    with open(path, 'wb') as stream:
        stream.write(png)
    return path


def open_icon_maker(parent, initial_directory='', save_path=None, on_saved=None):
    import tkinter as tk
    from tkinter import colorchooser, filedialog, messagebox, ttk

    dialog = tk.Toplevel(parent)
    dialog.title('ATLAS Plugin Icon Maker')
    dialog.transient(parent)
    dialog.grab_set()
    dialog.resizable(False, False)

    background_var = tk.StringVar(value='#20242B')
    foreground_var = tk.StringVar(value='#27B5E8')
    symbol_var = tk.StringVar(value='graph')
    size_var = tk.StringVar(value='16')
    result = {}

    canvas = tk.Canvas(dialog, width=192, height=192, highlightthickness=1, highlightbackground='#777777')
    canvas.grid(row=0, column=0, rowspan=7, padx=12, pady=12)

    def redraw(*_args):
        canvas.delete('all')
        background = background_var.get()
        foreground = foreground_var.get()
        try:
            canvas.configure(background=background)
        except tk.TclError:
            return
        margin = 34
        middle = 96
        width = 7
        symbol = symbol_var.get()
        if symbol in ICON_SYMBOLS[9:]:
            try:
                preview_pixels = render_icon_pixels(16, background, foreground, symbol)
            except ValueError:
                return
            scale = 12
            for y in range(16):
                for x in range(16):
                    offset = ((y * 16) + x) * 4
                    red, green, blue, alpha = preview_pixels[offset:offset + 4]
                    if alpha:
                        color = f'#{red:02X}{green:02X}{blue:02X}'
                        canvas.create_rectangle(
                            x * scale, y * scale, (x + 1) * scale, (y + 1) * scale,
                            fill=color, outline=color,
                        )
        elif symbol == 'graph':
            points = (margin, 150, 76, 112, 116, 128, 158, margin)
            canvas.create_line(*points, fill=foreground, width=width, joinstyle='round')
            for index in range(0, len(points), 2):
                canvas.create_oval(points[index] - 5, points[index + 1] - 5,
                                   points[index] + 5, points[index + 1] + 5,
                                   fill=foreground, outline='')
        elif symbol == 'pulse':
            canvas.create_line(margin, middle, 72, middle, 86, margin, 108, 158,
                               122, middle, 158, middle, fill=foreground, width=width)
        elif symbol == 'gauge':
            canvas.create_oval(margin, margin, 158, 158, outline=foreground, width=width)
            canvas.create_line(middle, middle, 140, 65, fill=foreground, width=width)
            canvas.create_oval(88, 88, 104, 104, fill=foreground, outline='')
        elif symbol == 'grid':
            for left, top, right, bottom in ((40, 40, 88, 88), (104, 40, 152, 88),
                                              (40, 104, 88, 152), (104, 104, 152, 152)):
                canvas.create_rectangle(left, top, right, bottom, fill=foreground, outline='')
        elif symbol == 'checkered-flag':
            canvas.create_line(48, 35, 48, 158, fill=foreground, width=7)
            cell = 24
            for row in range(3):
                for column in range(4):
                    if (row + column) % 2 == 0:
                        left = 54 + (column * cell)
                        top = 38 + (row * cell)
                        canvas.create_rectangle(left, top, left + cell, top + cell, fill=foreground, outline='')
        elif symbol == 'steering-wheel':
            canvas.create_oval(34, 34, 158, 158, outline=foreground, width=7)
            canvas.create_oval(88, 88, 104, 104, fill=foreground, outline='')
            for end in ((96, 35), (42, 145), (150, 145)):
                canvas.create_line(96, 96, *end, fill=foreground, width=7)
        elif symbol == 'tyre':
            canvas.create_oval(38, 38, 154, 154, outline=foreground, width=18)
            canvas.create_oval(78, 78, 114, 114, outline=foreground, width=3)
        elif symbol == 'stopwatch':
            canvas.create_oval(38, 44, 154, 160, outline=foreground, width=7)
            canvas.create_rectangle(87, 25, 105, 45, fill=foreground, outline='')
            canvas.create_line(96, 102, 96, 66, fill=foreground, width=7)
            canvas.create_line(96, 102, 128, 102, fill=foreground, width=7)
        else:
            canvas.create_rectangle(38, 78, 154, 138, fill=foreground, outline='')
            canvas.create_rectangle(78, 42, 114, 78, fill=foreground, outline='')
            canvas.create_oval(28, 124, 52, 148, fill=foreground, outline='')
            canvas.create_oval(140, 124, 164, 148, fill=foreground, outline='')

    def choose_color(variable):
        color = colorchooser.askcolor(variable.get(), parent=dialog)[1]
        if color:
            variable.set(color.upper())
            redraw()

    tk.Label(dialog, text='Symbol:').grid(row=0, column=1, sticky='w', padx=8, pady=(14, 4))
    symbol_combo = ttk.Combobox(dialog, textvariable=symbol_var, values=ICON_SYMBOLS, state='readonly', width=18)
    symbol_combo.grid(row=0, column=2, sticky='ew', padx=8, pady=(14, 4))
    symbol_combo.bind('<<ComboboxSelected>>', redraw)

    tk.Label(dialog, text='Background:').grid(row=1, column=1, sticky='w', padx=8, pady=4)
    tk.Entry(dialog, textvariable=background_var, width=14).grid(row=1, column=2, sticky='w', padx=8)
    tk.Button(dialog, text='Choose...', command=lambda: choose_color(background_var)).grid(row=1, column=3, padx=8)

    tk.Label(dialog, text='Accent:').grid(row=2, column=1, sticky='w', padx=8, pady=4)
    tk.Entry(dialog, textvariable=foreground_var, width=14).grid(row=2, column=2, sticky='w', padx=8)
    tk.Button(dialog, text='Choose...', command=lambda: choose_color(foreground_var)).grid(row=2, column=3, padx=8)

    tk.Label(dialog, text='PNG size:').grid(row=3, column=1, sticky='w', padx=8, pady=4)
    ttk.Combobox(dialog, textvariable=size_var, values=('16', '24', '32', '64'), state='readonly', width=10).grid(
        row=3, column=2, sticky='w', padx=8
    )

    def save_and_use():
        try:
            parse_hex_color(background_var.get())
            parse_hex_color(foreground_var.get())
        except ValueError as error:
            messagebox.showerror('Invalid Color', str(error), parent=dialog)
            return
        path = save_path
        if not path:
            path = filedialog.asksaveasfilename(
                parent=dialog,
                title='Save Plugin Icon',
                initialdir=initial_directory or None,
                initialfile='icon.png',
                defaultextension='.png',
                filetypes=[('PNG image', '*.png')],
            )
        if not path:
            return
        create_icon_png(path, int(size_var.get()), background_var.get(), foreground_var.get(), symbol_var.get())
        result['path'] = path
        if on_saved:
            on_saved(path)
        dialog.destroy()

    buttons = tk.Frame(dialog)
    buttons.grid(row=5, column=1, columnspan=3, pady=14)
    tk.Button(buttons, text='Save and Use', command=save_and_use, width=14).pack(side=tk.LEFT, padx=4)
    tk.Button(buttons, text='Cancel', command=dialog.destroy, width=10).pack(side=tk.LEFT, padx=4)
    background_var.trace_add('write', lambda *_args: redraw())
    foreground_var.trace_add('write', lambda *_args: redraw())
    redraw()
    dialog.protocol('WM_DELETE_WINDOW', dialog.destroy)
    dialog.wait_window()
    return result.get('path')


def main():
    import os
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    try:
        open_icon_maker(root, os.getcwd())
    finally:
        root.destroy()


if __name__ == '__main__':
    main()
