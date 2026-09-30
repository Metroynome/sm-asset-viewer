"""Native file-picker launcher for the local asset viewer."""
import json
import os
import queue
import re
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from extract_regions import identify

HERE = Path(__file__).resolve().parent
SETTINGS = HERE / 'output' / 'launcher.json'


def extraction_target(iso, destination):
    iso, destination = Path(iso).resolve(), Path(destination).resolve()
    if not iso.is_file():
        raise ValueError('Choose an existing Size Matters PS2 ISO.')
    region = identify(iso)
    if region['id'] == 'unknown':
        raise ValueError('This is not a supported Size Matters PS2 disc (NTSC-U, PAL or NTSC-J).')
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError('Choose a new or empty extraction folder. To reuse extracted assets, use Open existing extraction.')
    return iso, destination, region


def existing_root(folder):
    root = Path(folder).resolve()
    for name in ('manifest.json', 'audio/manifest.json', 'disc/SYSTEM.CNF'):
        if not (root / name).is_file():
            raise ValueError(f'This extraction is incomplete: missing {name}. Choose the folder containing disc, unpacked and audio.')
    manifest = json.loads((root / 'manifest.json').read_text())
    if manifest.get('errors'):
        raise ValueError('The extraction manifest reports errors. Complete extraction before opening it.')
    return root


class Launcher:
    def __init__(self, window):
        self.window = window
        self.events = queue.Queue()
        self.process = None
        self.busy = False
        self.url = None
        self.generation = 0
        self.iso = tk.StringVar()
        self.destination = tk.StringVar()
        self.status = tk.StringVar(value='Choose an ISO to extract, or open an existing extraction.')
        try:
            self.recent = json.loads(SETTINGS.read_text()).get('recent', [])[:10]
        except (OSError, ValueError, AttributeError):
            self.recent = []
        self.recent = [p for p in self.recent if isinstance(p, str)]
        window.title('Size Matters Asset Viewer')
        window.geometry('820x570')
        window.minsize(660, 470)
        frame = ttk.Frame(window, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Size Matters Asset Viewer', font=('', 18, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='Extract a PS2 ISO once, then browse levels, mobys, textures and audio.').pack(anchor='w', pady=(6, 18))
        self.controls = []
        for title, variable, action in [('ISO', self.iso, self.choose_iso), ('Extraction folder', self.destination, self.choose_destination)]:
            row = ttk.Frame(frame)
            row.pack(fill='x', pady=4)
            ttk.Label(row, text=title, width=19).pack(side='left')
            entry = ttk.Entry(row, textvariable=variable)
            entry.pack(side='left', fill='x', expand=True, padx=(0, 8))
            button = ttk.Button(row, text='Browse...', command=action)
            button.pack(side='right')
            self.controls.extend((entry, button))
        row = ttk.Frame(frame)
        row.pack(fill='x', pady=12)
        for label, action in [('Extract and open', self.extract), ('Open existing extraction...', self.choose_existing)]:
            button = ttk.Button(row, text=label, command=action)
            button.pack(side='left', padx=(0, 8))
            self.controls.append(button)
        self.browser = ttk.Button(row, text='Open browser', command=lambda: webbrowser.open(self.url), state='disabled')
        self.browser.pack(side='right')
        row = ttk.Frame(frame)
        row.pack(fill='x', pady=(0, 12))
        ttk.Label(row, text='Recent folders', width=19).pack(side='left')
        self.history = ttk.Combobox(row, values=self.recent, state='readonly')
        self.history.pack(side='left', fill='x', expand=True, padx=(0, 8))
        if self.recent:
            self.history.current(0)
        button = ttk.Button(row, text='Open', command=lambda: self.open_existing(self.history.get()))
        button.pack(side='right')
        self.controls.append(button)
        ttk.Label(frame, textvariable=self.status, wraplength=750).pack(anchor='w', pady=4)
        self.progress = ttk.Progressbar(frame, mode='indeterminate')
        self.progress.pack(fill='x', pady=6)
        self.log = ScrolledText(frame, height=12, state='disabled', wrap='word')
        self.log.pack(fill='both', expand=True)
        ttk.Label(frame, text='Keep this launcher open while using the viewer.').pack(anchor='w', pady=(8, 0))
        window.protocol('WM_DELETE_WINDOW', self.close)
        window.after(100, self.poll)

    def choose_iso(self):
        path = filedialog.askopenfilename(parent=self.window, title='Choose Size Matters PS2 ISO', filetypes=[('PS2 ISO', '*.iso'), ('All files', '*.*')])
        if path:
            self.iso.set(path)

    def choose_destination(self):
        path = filedialog.askdirectory(parent=self.window, title='Choose or create an empty extraction folder', mustexist=False)
        if path:
            self.destination.set(path)

    def choose_existing(self):
        path = filedialog.askdirectory(parent=self.window, title='Choose extracted game folder')
        if path:
            self.open_existing(path)

    def extract(self):
        try:
            if not self.iso.get().strip() or not self.destination.get().strip():
                raise ValueError('Choose both an ISO and an extraction folder.')
            iso, root, region = extraction_target(self.iso.get(), self.destination.get())
        except (OSError, ValueError) as exc:
            messagebox.showerror('Cannot extract', str(exc), parent=self.window)
            return
        commands = [([str(HERE / 'extract_sm.py'), str(iso), '--output', str(root)] + (['--resume'] if root.exists() else []), f'Extracting {region["label"]} disc and WADs...'),
                    ([str(HERE / 'index_assets.py'), str(root)], 'Extracting audio and indexing assets...')]
        self.start(root, commands)

    def open_existing(self, path):
        if not path:
            return
        try:
            root = existing_root(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror('Cannot open extraction', str(exc), parent=self.window)
            return
        self.start(root, [])

    def start(self, root, commands):
        if self.busy:
            return
        self.stop_server()
        self.busy = True
        self.url = None
        self.generation += 1
        for control in self.controls:
            control.configure(state='disabled')
        self.browser.configure(state='disabled')
        self.progress.start()
        self.status.set('Preparing assets...')
        threading.Thread(target=self.work, args=(root, commands, self.generation), daemon=True).start()

    def work(self, root, commands, generation):
        def emit(event, value):
            self.events.put((generation, event, value))
        try:
            for args, status in commands:
                emit('status', status)
                self.run(args, emit=emit)
            existing_root(root)
            emit('status', 'Preparing previews (first launch takes longer)...')
            self.run([str(HERE / 'browse.py'), '--root', str(root), '--out', str(root / '.viewer'), '--port', '0'], root, emit)
        except Exception as exc:
            emit('error', str(exc))
        finally:
            emit('done', None)

    def run(self, args, root=None, emit=None):
        process = subprocess.Popen([sys.executable, '-u', *args], cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                                   env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        self.process = process
        with process.stdout:
            for line in process.stdout:
                emit('log', line)
                match = re.match(r'Browse (http://127\.0\.0\.1:\d+)', line)
                if root is not None and match:
                    emit('ready', (root, match[1]))
        if process.wait():
            raise RuntimeError(f'{Path(args[0]).name} failed. See the log above. Extracted files have been retained.')

    def poll(self):
        for _ in range(200):
            try:
                generation, event, value = self.events.get_nowait()
            except queue.Empty:
                break
            if generation != self.generation:
                continue
            if event == 'log':
                self.log.configure(state='normal')
                self.log.insert('end', value)
                self.log.see('end')
                self.log.configure(state='disabled')
            elif event == 'status':
                self.status.set(value)
            elif event == 'ready':
                self.busy = False
                for control in self.controls:
                    control.configure(state='normal')
                root, self.url = value
                self.status.set(f'Ready: {root}')
                self.progress.stop()
                self.browser.configure(state='normal')
                self.recent = [str(root)] + [p for p in self.recent if p != str(root)]
                self.recent = self.recent[:10]
                self.history.configure(values=self.recent)
                self.history.current(0)
                try:
                    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
                    SETTINGS.write_text(json.dumps({'recent': self.recent}, indent=2))
                except OSError as exc:
                    self.events.put((self.generation, 'log', f'Could not save recent folders: {exc}\n'))
                webbrowser.open(self.url)
            elif event == 'error':
                self.status.set('Could not finish. See the log for details.')
                messagebox.showerror('Asset viewer', value, parent=self.window)
            elif event == 'done':
                self.busy = False
                self.progress.stop()
                for control in self.controls:
                    control.configure(state='normal')
                self.browser.configure(state='disabled')
        self.window.after(100, self.poll)

    def stop_server(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)

    def close(self):
        if self.busy and not self.url:
            if not messagebox.askyesno('Stop extraction?', 'Extraction is still running. Stop it and close? Partial files will remain.', parent=self.window):
                return
        self.stop_server()
        self.window.destroy()


def main():
    window = tk.Tk()
    Launcher(window)
    window.mainloop()


if __name__ == '__main__':
    main()
