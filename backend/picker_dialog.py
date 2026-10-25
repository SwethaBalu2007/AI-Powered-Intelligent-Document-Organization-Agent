"""
Standalone Native Folder Picker Process.
Runs on the main GUI thread in its own process to guarantee that the native OS
Folder Selection dialog always opens on top of all windows without blocking asyncio.
"""

import sys
import os

def main():
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        # Force the dialog to pop in the foreground
        root.wm_attributes('-topmost', 1)
        root.update()

        folder_selected = filedialog.askdirectory(
            title="Select Folder to Organize — AI Document Agent"
        )
        root.destroy()
        if folder_selected:
            # Print to stdout for caller to read
            print(os.path.normpath(folder_selected))
        else:
            print("")
    except Exception as e:
        sys.stderr.write(f"Dialog error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
