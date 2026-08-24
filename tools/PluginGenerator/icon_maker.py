import binascii
import struct
import zlib


ICON_SYMBOLS = ('graph', 'pulse', 'gauge', 'grid')


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
    else:
        cell = (size - (margin * 2)) // 2
        gap = max(2, thickness)
        for row in range(2):
            for column in range(2):
                left = margin + (column * cell) + gap
                top = margin + (row * cell) + gap
                right = margin + ((column + 1) * cell) - gap
                bottom = margin + ((row + 1) * cell) - gap
                for y in range(top, bottom):
                    for x in range(left, right):
                        _set_pixel(pixels, size, x, y, foreground)
    return bytes(pixels)


def _png_chunk(chunk_type, data):
    body = chunk_type + data
    return struct.pack('>I', len(data)) + body + struct.pack('>I', binascii.crc32(body) & 0xFFFFFFFF)


def create_icon_png(path, size=256, background='#20242B', foreground='#27B5E8', symbol='graph'):
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


def open_icon_maker(parent, initial_directory=''):
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
    size_var = tk.StringVar(value='256')
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
        if symbol == 'graph':
            points = (margin, 150, 76, 112, 116, 128, 158, margin)
            canvas.create_line(*points, fill=foreground, width=width, joint='curve')
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
        else:
            for left, top, right, bottom in ((40, 40, 88, 88), (104, 40, 152, 88),
                                              (40, 104, 88, 152), (104, 104, 152, 152)):
                canvas.create_rectangle(left, top, right, bottom, fill=foreground, outline='')

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
    ttk.Combobox(dialog, textvariable=size_var, values=('64', '128', '256', '512'), state='readonly', width=10).grid(
        row=3, column=2, sticky='w', padx=8
    )

    def save_and_use():
        try:
            parse_hex_color(background_var.get())
            parse_hex_color(foreground_var.get())
        except ValueError as error:
            messagebox.showerror('Invalid Color', str(error), parent=dialog)
            return
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
